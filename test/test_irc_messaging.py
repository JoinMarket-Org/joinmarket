#! /usr/bin/env python
from __future__ import absolute_import
'''Tests of joinmarket bots end-to-end (including IRC and bitcoin) '''

import subprocess
import signal
import os
import pytest
import time
import threading
from commontest import local_command, make_wallets
from joinmarket.message_channel import CJPeerError
import joinmarket.irc
from joinmarket import load_program_config, IRCMessageChannel

python_cmd = "python2"
yg_cmd = "yield-generator-basic.py"
yg_name = None

class DummyMC(IRCMessageChannel):
    def __init__(self, nick):
        super(DummyMC, self).__init__(nick)

def on_order_seen(counterparty, oid, ordertype, minsize,
                                           maxsize, txfee, cjfee):
    global yg_name
    yg_name = counterparty

def on_pubkey(pubkey):
    print "received pubkey: " + pubkey

class RawIRCThread(threading.Thread):

    def __init__(self, ircmsgchan):
        threading.Thread.__init__(self, name='RawIRCThread')
        self.daemon = True
        self.ircmsgchan = ircmsgchan
    
    def run(self):
        self.ircmsgchan.run()

def test_junk_messages(setup_messaging):
    #start a yg bot just to receive messages
    wallets = make_wallets(1,
                           wallet_structures=[[1,0,0,0,0]],
                           mean_amt=1)
    wallet = wallets[0]['wallet']
    ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[0]['seed'])], bg=True)
    
    #time.sleep(90)
    #start a raw IRCMessageChannel instance in a thread;
    #then call send_* on it with various errant messages
    mc = DummyMC("irc_ping_test")
    mc.register_orderbookwatch_callbacks(on_order_seen=on_order_seen)
    mc.register_taker_callbacks(on_pubkey=on_pubkey)    
    RawIRCThread(mc).start()
    time.sleep(1)
    mc.request_orderbook()
    time.sleep(1)
    #now try directly
    mc.pubmsg("!orderbook")
    time.sleep(1)
    #should be ignored; can we check?
    mc.pubmsg("!orderbook!orderbook")
    time.sleep(1)
    #assuming MAX_PRIVMSG_LEN is not something crazy
    #big like 550, this should fail
    with pytest.raises(AssertionError) as e_info:
        mc.pubmsg("junk and crap"*40)
    time.sleep(1)
    #assuming MAX_PRIVMSG_LEN is not something crazy
    #small like 180, this should succeed
    mc.pubmsg("junk and crap"*15)
    time.sleep(2)
    #try a long order announcement in public
    #because we don't want to build a real orderbook,
    #call the underlying IRC announce function.
    #TODO: how to test that the sent format was correct?
    mc._announce_orders(["!abc def gh 0001"]*30, None)
    time.sleep(5)
    #send a fill with an invalid pubkey to the existing yg;
    #this should trigger a NaclError but should NOT kill it.
    mc._IRCMessageChannel__privmsg(yg_name, "fill", "0 10000000 abcdef")
    time.sleep(1)
    #try:
    with pytest.raises(CJPeerError) as e_info:
        mc.send_error(yg_name, "fly you fools!")
    #except CJPeerError:
    #    print "CJPeerError raised"
    #    pass
    time.sleep(5)
    mc.shutdown()
    ygp.send_signal(signal.SIGINT)
    ygp.wait()

@pytest.fixture(scope="module")
def setup_messaging():
    #Trigger PING LAG sending artificially
    joinmarket.irc.PING_INTERVAL = 3    
    load_program_config()




