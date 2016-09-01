from __future__ import absolute_import, print_function

import base64
import random
import socket
import ssl
import threading
import time
import Queue
import sys
import time
import json

from pprint import pformat
from matrix_client.client import MatrixClient
from matrix_client.api import MatrixRequestError
from requests.exceptions import MissingSchema

from getpass import getpass

from joinmarket.configure import jm_single, get_network
from joinmarket.message_channel import MessageChannel, CJPeerError, COMMAND_PREFIX
from joinmarket.support import get_log, chunks
from joinmarket.socks import socksocket, setdefaultproxy, PROXY_TYPE_SOCKS5

matrix_config_options = ["matrix_host", "matrix_port", "matrix_chan"]
log = get_log()

#hardcoded limit is 100s of kB, we set a reasonable, sane limit
MAX_MATRIX_LINE_LENGTH = 10000

def get_rand_name():
    import string
    return ''.join(random.choice(string.ascii_letters) for _ in range(10))    

class MatrixMessageChannel(MessageChannel):
    def __init__(self, username=None, realname='', password=''):
        MessageChannel.__init__(self)
        for opt in matrix_config_options:
            if not jm_single().config.has_option("MESSAGING", opt):
                raise Exception(
        "To use matrix, joinmarket.cfg must contain settings:" + ','.join(
            [matrix_config_options]))
        self.host = jm_single().config.get("MESSAGING", "matrix_host")
        self.hostport= jm_single().config.getint("MESSAGING", "matrix_port")
        self.fqhost = "https://"+self.host+":"+str(self.hostport)
        register_needed = False
        if realname:
            log.debug("Realname: " + realname + " is not currently being used.")
        if username is None:
            self.base_username = get_rand_name()
        else:
            self.base_username = username
        self.username = "@" + self.base_username + ":" + self.host
        if not password:
            password = get_rand_name()
            register_needed = True
        self.password = password
        self.matrix_client = MatrixClient(self.fqhost)
        #keep track of privmsg rooms
        self.private_rooms = {}
        pit_room_id = jm_single().config.get("MESSAGING", "matrix_chan")
        if get_network()=="testnet":
            pit_room_id += "-test"
        self.pit_room_id = "#" + pit_room_id + ":" + self.host
        self.add_listeners()
        self.finished = False
        self.logged_in = False
        self.nb = None

    def debug(self, msg):
        log.debug(" *" + self.base_username + "* " + msg)

    def get_nicks_in_pit(self):
        return self.pit_room.get_members()

    def join_room(self, room):
        rm = self.matrix_client.join_room(room_id_or_alias=room)
        frompoint = self.matrix_client.end
        response = self.matrix_client.api._send("GET",
                            "/rooms/"+rm.room_id+'/messages',
                            query_params={"from":frompoint,"dir":"b",
                                                            "limit":1})
        #don't reset the endpoint upwards
        #self.matrix_client.end = response["end"]
        return (rm, response)

    def run(self):
        #connect
        try:
            self.matrix_client.login_with_password(self.username, self.password)
        except MatrixRequestError as e:
            log.debug(e)
            if e.code == 403:
                self.debug(
                "Bad username or password (this is normal for a new connection).")
                register_needed = True
            else:
                self.debug("Check your sever details are correct.")
                exit(1)
        
        except MissingSchema as e:
            self.debug("Bad URL format, connection failure.")
            log.debug(e)
            exit(1)

        if register_needed:
            #for registration, don't provide full @name:server, just name
            try:
                self.matrix_client.register_with_password(self.base_username,
                                                          self.password)
            except MatrixRequestError as e:
                self.debug("New user registration failure: " + repr(e))

        #Will almost certainly need some exception handling TODO
        self.pit_room, resp = self.join_room(self.pit_room_id)
        if self.on_welcome:
            self.on_welcome()
        self.matrix_client.start_listener_thread()
        self.logged_in = True
        while True:
            if self.finished:
                break
            time.sleep(0.2)

    def shutdown(self):
        self.debug("Shutting down matrix connection")
        #TODO this is not yet in API documentation, not
        #sure it does much (was told it just expires a token)
        #NB This is not actually correct syntax yet.
        #self.matrix_client.api._send("POST", "/logout")
        self.finished = True

    def _announce_orders(self, orderlist, nick):
        dest = self.pit_room_id if nick is None else nick
        #Matrix has no meaningful line length limit but
        #to prevent DOS make a sanity check
        orderline = ''.join(orderlist)
        assert len(orderline) < MAX_MATRIX_LINE_LENGTH
        if nick is None:
            self.pubmsg(orderline)
        else:
            self._privmsg(nick, '', orderline)

    def add_listeners(self):
        self.matrix_client.add_listener(self.on_message_public)

    def send_privmsg_invite(self, recipient):
        try:
            start_time = time.time()
            room = self.matrix_client.create_room(is_public=False,
                        invitees=(recipient,))
            duration = time.time() - start_time
        except:
            self.debug("Failed to create private room for: " + recipient)
            raise
        self.debug("Create room took: " + str(duration))
        self.private_rooms[recipient] = room

    def _privmsg(self, recipient, cmd, msg):
        if recipient not in self.private_rooms:
            self.send_privmsg_invite(recipient)
            #This is an unpleasant hack to allow the other side to join
            #before we send our first message. TODO.
            time.sleep(2)
        if cmd:
            m = COMMAND_PREFIX + cmd + ' ' + msg
        else:
            #allow raw send; this is for _announce_orders currently
            m = msg
        self.private_rooms[recipient].send_text(m)

    def _pubmsg(self, msg):
        self.pit_room.send_text(msg)
    
    def process_jm_privmsg_invite(self, sender, roomid):
        #Include any logic to decide whether we want
        #to speak to this counterparty here TODO
        #artificial delay so we don't get the message in time
        start_time = time.time()
        room = self.matrix_client.join_room(roomid)
        duration = time.time() -start_time
        self.debug("Room join took: " + str(duration))
        self.private_rooms[sender] = room

    # This is the main message callback
    def on_message_public(self, event):
        if event['type']=="m.presence":
            return
        if "room_id" not in event.keys():
            self.debug(pformat(event))
            #self.debug("Received this non room event: ")
            #self.debug(event['type'])
            return
        if event['type'] != "m.room.member" and \
           event['room_id'] not in [self.pit_room.room_id] + \
           [x.room_id for x in self.private_rooms.values()]:
            self.debug("Received an event for a room we're not connected to: ",
                  event['room_id'], ", ignoring.")
            self.debug("We currently have these rooms: ")
            self.debug(pformat([self.pit_room.room_id] + \
                          [x.room_id for x in self.private_rooms.values()]))
            return
        if event['type'] == "m.room.member":
            sender = event['sender']
            #for now just printing any joins
            if event['membership'] == "invite":
                if not event['state_key'] == self.username:
                    #these are received when we send invites, ignore
                    return
                rm_id = event['room_id']
                self.process_jm_privmsg_invite(sender, rm_id)
        elif event['type'] == "m.room.message":
            #self.debug("RECEIVED")
            #self.debug(pformat(event))
            sender = event['sender']
            if sender==self.username:
                return
            if event['content']['msgtype'] == "m.text":
                #Here we proceed with the joinmarket messaging protocol
                if event['room_id'] in [x.room_id for x in self.private_rooms.values()]:
                    self.debug("Received a private message from " + sender)
                    self.on_privmsg(sender, event['content']['body'])
                else:
                    #if event['room_id'] != self.pit_room.room_id:
                    #    self.debug("Received a privmsg for a not-yet created room.")
                    #    self.on_privmsg(sender, event['content']['body'])
                    #else:
                    self.on_pubmsg(sender, event['content']['body'])
        else:
            self.debug("What is this? " + event['type'])