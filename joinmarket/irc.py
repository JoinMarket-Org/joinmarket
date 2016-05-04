from __future__ import absolute_import, print_function

import base64
import random
import socket
import ssl
import threading
import time
import Queue

from joinmarket.configure import jm_single, get_config_irc_channel
from joinmarket.message_channel import MessageChannel, CJPeerError
from joinmarket.enc_wrapper import encrypt_encode, decode_decrypt
from joinmarket.support import get_log, chunks
from joinmarket.socks import socksocket, setdefaultproxy, PROXY_TYPE_SOCKS5

MAX_PRIVMSG_LEN = 450
COMMAND_PREFIX = '!'
PING_INTERVAL = 300
PING_TIMEOUT = 60

#Throttling parameters; data from
#tests by @chris-belcher:
##worked (bytes per sec/bytes per sec interval / counterparties / max_privmsg_len)
#300/4 / 6 / 400
#600/4 / 6 / 400
#450/4 / 10 / 400
#450/4 / 10 / 450
#525/4 / 10 / 450
##didnt work
#600/4 / 10 / 450
#600/4 / 10 / 400
#2000/2 / 10 / 400
#450/4 / 10 / 475
MSG_INTERVAL = 0.001
B_PER_SEC = 450
B_PER_SEC_INTERVAL = 4.0

encrypted_commands = ["auth", "ioauth", "tx", "sig"]
plaintext_commands = ["fill", "error", "pubkey", "orderbook", "relorder",
                      "absorder", "push"]

log = get_log()


def random_nick(nick_len=9):
    vowels = "aeiou"
    consonants = ''.join([chr(
        c) for c in range(
            ord('a'), ord('z') + 1) if vowels.find(chr(c)) == -1])
    assert nick_len % 2 == 1
    N = (nick_len - 1) / 2
    rnd_consonants = [consonants[random.randrange(len(consonants))]
                      for _ in range(N + 1)]
    rnd_vowels = [vowels[random.randrange(len(vowels))]
                  for _ in range(N)] + ['']
    ircnick = ''.join([i for sl in zip(rnd_consonants, rnd_vowels) for i in sl])
    ircnick = ircnick.capitalize()
    # not using debug because it might not know the logfile name at this point
    print('Generated random nickname: ' + ircnick)
    return ircnick
    # Other ideas for random nickname generation:
    # - weight randomness by frequency of letter appearance
    # - u always follows q
    # - generate different length nicks
    # - append two or more of these words together
    # - randomly combine phonetic sounds instead consonants, which may be two consecutive consonants
    #  - e.g. th, dj, g, p, gr, ch, sh, kr,
    # - neutral network that generates nicks


def get_irc_text(line):
    return line[line[1:].find(':') + 2:]


def get_irc_nick(source):
    return source[1:source.find('!')]


class ThrottleThread(threading.Thread):

    def __init__(self, irc):
        threading.Thread.__init__(self, name='ThrottleThread')
        self.daemon = True
        self.irc = irc
        self.msg_buffer = []

    def run(self):
        log.debug("starting throttle thread")
        last_msg_time = 0
        print_throttle_msg = True
        while not self.irc.give_up:
            self.irc.lockthrottle.acquire()
            while not (self.irc.throttleQ.empty() and self.irc.obQ.empty()
                       and self.irc.pingQ.empty()):
                time.sleep(0.0001) #need to avoid cpu spinning if throttled
                try:
                    pingmsg = self.irc.pingQ.get(block=False)
                    #ping messages are not counted to throttling totals,
                    #so send immediately
                    self.irc.sock.sendall(pingmsg + '\r\n')
                    continue
                except Queue.Empty:
                    pass
                except:
                    log.debug("failed to send ping message on socket")
                    break
                #First throttling mechanism: no more than 1 line
                #per MSG_INTERVAL seconds.
                x = time.time() - last_msg_time
                if  x < MSG_INTERVAL:
                    continue
                #Second throttling mechanism: limited kB/s rate
                #over the most recent period.
                q = time.time() - B_PER_SEC_INTERVAL
                #clean out old messages
                self.msg_buffer = [_ for _ in self.msg_buffer if _[1] > q]
                bytes_recent = sum(len(i[0]) for i in self.msg_buffer)
                if bytes_recent > B_PER_SEC * B_PER_SEC_INTERVAL:
                    if print_throttle_msg:
                        log.debug("Throttling triggered, with: "+str(
                            bytes_recent)+ " bytes in the last "+str(
                                B_PER_SEC_INTERVAL)+" seconds.")
                    print_throttle_msg = False
                    continue
                print_throttle_msg = True
                try:
                    throttled_msg = self.irc.throttleQ.get(block=False)
                except Queue.Empty:
                    try:
                        throttled_msg = self.irc.obQ.get(block=False)
                    except Queue.Empty:
                        #this code *should* be unreachable.
                        continue
                try:
                    self.irc.sock.sendall(throttled_msg+'\r\n')
                    last_msg_time = time.time()
                    self.msg_buffer.append((throttled_msg, last_msg_time))
                except:
                    log.debug("failed to send on socket")
                    try:
                        self.irc.fd.close()
                    except: pass
                    break
            self.irc.lockthrottle.wait()
            self.irc.lockthrottle.release()

        log.debug("Ended throttling thread.")

class PingThread(threading.Thread):

    def __init__(self, irc):
        threading.Thread.__init__(self, name='PingThread')
        self.daemon = True
        self.irc = irc

    def run(self):
        log.debug('starting ping thread')
        while not self.irc.give_up:
            time.sleep(PING_INTERVAL)
            try:
                self.irc.ping_reply = False
                # maybe use this to calculate the lag one day
                self.irc.lockcond.acquire()
                self.irc.send_raw('PING LAG' + str(int(time.time() * 1000)))
                self.irc.lockcond.wait(PING_TIMEOUT)
                self.irc.lockcond.release()
                if not self.irc.ping_reply:
                    log.debug('irc ping timed out')
                    try:
                        self.irc.close()
                    except:
                        pass
                    try:
                        self.irc.fd.close()
                    except:
                        pass
                    try:
                        self.irc.sock.shutdown(socket.SHUT_RDWR)
                        self.irc.sock.close()
                    except:
                        pass
            except IOError as e:
                log.debug('ping thread: ' + repr(e))
        log.debug('ended ping thread')


# handle one channel at a time
class IRCMessageChannel(MessageChannel):
    # close implies it will attempt to reconnect
    def close(self):
        try:
            self.sock.sendall("QUIT\r\n")
        except IOError as e:
            log.debug('errored while trying to quit: ' + repr(e))

    def shutdown(self):
        self.close()
        self.give_up = True

    def send_error(self, nick, errormsg):
        log.debug('error<%s> : %s' % (nick, errormsg))
        self.__privmsg(nick, 'error', errormsg)
        raise CJPeerError()

    # OrderbookWatch callback
    def request_orderbook(self):
        self.__pubmsg(COMMAND_PREFIX + 'orderbook')

    # Taker callbacks
    def fill_orders(self, nick_order_dict, cj_amount, taker_pubkey):
        for c, order in nick_order_dict.iteritems():
            msg = str(order['oid']) + ' ' + str(cj_amount) + ' ' + taker_pubkey
            self.__privmsg(c, 'fill', msg)

    def send_auth(self, nick, pubkey, sig):
        message = pubkey + ' ' + sig
        self.__privmsg(nick, 'auth', message)

    def send_tx(self, nick_list, txhex):
        txb64 = base64.b64encode(txhex.decode('hex'))
        for nick in nick_list:
            self.__privmsg(nick, 'tx', txb64)

    def push_tx(self, nick, txhex):
        txb64 = base64.b64encode(txhex.decode('hex'))
        self.__privmsg(nick, 'push', txb64)

    # Maker callbacks
    def announce_orders(self, orderlist, nick=None):
        # nick=None means announce publicly
        order_keys = ['oid', 'minsize', 'maxsize', 'txfee', 'cjfee']
        header = 'PRIVMSG ' + (nick if nick else self.channel) + ' :'
        orderlines = []
        for i, order in enumerate(orderlist):
            orderparams = COMMAND_PREFIX + order['ordertype'] + \
                          ' ' + ' '.join([str(order[k]) for k in order_keys])
            orderlines.append(orderparams)
            line = header + ''.join(orderlines) + ' ~'
            if len(line) > MAX_PRIVMSG_LEN or i == len(orderlist) - 1:
                if i < len(orderlist) - 1:
                    line = header + ''.join(orderlines[:-1]) + ' ~'
                self.send_raw(line)
                orderlines = [orderlines[-1]]

    def cancel_orders(self, oid_list):
        clines = [COMMAND_PREFIX + 'cancel ' + str(oid) for oid in oid_list]
        self.__pubmsg(''.join(clines))

    def send_pubkey(self, nick, pubkey):
        self.__privmsg(nick, 'pubkey', pubkey)

    def send_ioauth(self, nick, utxo_list, cj_pubkey, change_addr, sig):
        authmsg = (str(','.join(utxo_list)) + ' ' + cj_pubkey + ' ' +
                   change_addr + ' ' + sig)
        self.__privmsg(nick, 'ioauth', authmsg)

    def send_sigs(self, nick, sig_list):
        # TODO make it send the sigs on one line if there's space
        for s in sig_list:
            self.__privmsg(nick, 'sig', s)

    def __pubmsg(self, message):
        log.debug('>>pubmsg ' + message)
        self.send_raw("PRIVMSG " + self.channel + " :" + message)

    def __privmsg(self, nick, cmd, message):
        log.debug('>>privmsg ' + 'nick=' + nick + ' cmd=' + cmd + ' msg=' +
                  message)
        # should we encrypt?
        box, encrypt = self.__get_encryption_box(cmd, nick)
        # encrypt before chunking
        if encrypt:
            if not box:
                log.debug('error, dont have encryption box object for ' + nick +
                          ', dropping message')
                return
            message = encrypt_encode(message, box)

        header = "PRIVMSG " + nick + " :"
        max_chunk_len = MAX_PRIVMSG_LEN - len(header) - len(cmd) - 4
        # 1 for command prefix 1 for space 2 for trailer
        if len(message) > max_chunk_len:
            message_chunks = chunks(message, max_chunk_len)
        else:
            message_chunks = [message]
        for m in message_chunks:
            trailer = ' ~' if m == message_chunks[-1] else ' ;'
            if m == message_chunks[0]:
                m = COMMAND_PREFIX + cmd + ' ' + m
            self.send_raw(header + m + trailer)

    def send_raw(self, line):
        # Messages are queued and prioritised.
        # This is an addressing of github #300
        if line.startswith("PING") or line.startswith("PONG"):
            self.pingQ.put(line)
        elif "relorder" in line or "absorder" in line:
                self.obQ.put(line)
        else:
            self.throttleQ.put(line)
        self.lockthrottle.acquire()
        self.lockthrottle.notify()
        self.lockthrottle.release()

    def check_for_orders(self, nick, _chunks):
        if _chunks[0] in jm_single().ordername_list:
            try:
                counterparty = nick
                oid = _chunks[1]
                ordertype = _chunks[0]
                minsize = _chunks[2]
                maxsize = _chunks[3]
                txfee = _chunks[4]
                cjfee = _chunks[5]
                if self.on_order_seen:
                    self.on_order_seen(counterparty, oid, ordertype, minsize,
                                       maxsize, txfee, cjfee)
            except IndexError as e:
                log.exception(e)
                log.debug('index error parsing chunks')
                # TODO what now? just ignore iirc
            finally:
                return True
        return False

    def __on_privmsg(self, nick, message):
        """handles the case when a private message is received"""
        if message[0] != COMMAND_PREFIX:
            return
        for command in message[1:].split(COMMAND_PREFIX):
            _chunks = command.split(" ")
            # looks like a very similar pattern for all of these
            # check for a command name, parse arguments, call a function
            # maybe we need some eval() trickery to do it better

            try:
                # orderbook watch commands
                if self.check_for_orders(nick, _chunks):
                    pass

                # taker commands
                elif _chunks[0] == 'pubkey':
                    maker_pk = _chunks[1]
                    if self.on_pubkey:
                        self.on_pubkey(nick, maker_pk)
                elif _chunks[0] == 'ioauth':
                    utxo_list = _chunks[1].split(',')
                    cj_pub = _chunks[2]
                    change_addr = _chunks[3]
                    btc_sig = _chunks[4]
                    if self.on_ioauth:
                        self.on_ioauth(nick, utxo_list, cj_pub, change_addr,
                                       btc_sig)
                elif _chunks[0] == 'sig':
                    sig = _chunks[1]
                    if self.on_sig:
                        self.on_sig(nick, sig)

                # maker commands
                if _chunks[0] == 'fill':
                    try:
                        oid = int(_chunks[1])
                        amount = int(_chunks[2])
                        taker_pk = _chunks[3]
                    except (ValueError, IndexError) as e:
                        self.send_error(nick, str(e))
                    if self.on_order_fill:
                        self.on_order_fill(nick, oid, amount, taker_pk)
                elif _chunks[0] == 'auth':
                    try:
                        i_utxo_pubkey = _chunks[1]
                        btc_sig = _chunks[2]
                    except (ValueError, IndexError) as e:
                        self.send_error(nick, str(e))
                    if self.on_seen_auth:
                        self.on_seen_auth(nick, i_utxo_pubkey, btc_sig)
                elif _chunks[0] == 'tx':
                    b64tx = _chunks[1]
                    try:
                        txhex = base64.b64decode(b64tx).encode('hex')
                    except TypeError as e:
                        self.send_error(nick, 'bad base64 tx. ' + repr(e))
                    if self.on_seen_tx:
                        self.on_seen_tx(nick, txhex)
                elif _chunks[0] == 'push':
                    b64tx = _chunks[1]
                    try:
                        txhex = base64.b64decode(b64tx).encode('hex')
                    except TypeError as e:
                        self.send_error(nick, 'bad base64 tx. ' + repr(e))
                    if self.on_push_tx:
                        self.on_push_tx(nick, txhex)
            except CJPeerError:
                # TODO proper error handling
                log.debug('cj peer error TODO handle')
                continue

    def __on_pubmsg(self, nick, message):
        if message[0] != COMMAND_PREFIX:
            return
        commands = message[1:].split(COMMAND_PREFIX)
        #DOS vector: repeated !orderbook requests, see #298.
        if commands.count('orderbook')>1:
            return
        for command in commands:
            _chunks = command.split(" ")
            if self.check_for_orders(nick, _chunks):
                pass
            elif _chunks[0] == 'cancel':
                # !cancel [oid]
                try:
                    oid = int(_chunks[1])
                    if self.on_order_cancel:
                        self.on_order_cancel(nick, oid)
                except (ValueError, IndexError) as e:
                    log.debug("!cancel " + repr(e))
                    return
            elif _chunks[0] == 'orderbook':
                if self.on_orderbook_requested:
                    self.on_orderbook_requested(nick)
            else:
                # TODO this is for testing/debugging, should be removed, see taker.py
                if hasattr(self, 'debug_on_pubmsg_cmd'):
                    self.debug_on_pubmsg_cmd(nick, _chunks)

    def __get_encryption_box(self, cmd, nick):
        """Establish whether the message is to be
        encrypted/decrypted based on the command string.
        If so, retrieve the appropriate crypto_box object
        and return. Sending/receiving flag enables us
        to check which command strings correspond to which
        type of object (maker/taker)."""  # old doc, dont trust
        if cmd in plaintext_commands:
            return None, False
        else:
            return self.cjpeer.get_crypto_box_from_nick(nick), True

    def __handle_privmsg(self, source, target, message):
        nick = get_irc_nick(source)
        if target == self.nick:
            if message[0] == '\x01':
                endindex = message[1:].find('\x01')
                if endindex == -1:
                    return
                ctcp = message[1:endindex + 1]
                if ctcp.upper() == 'VERSION':
                    self.send_raw('PRIVMSG ' + nick +
                                  ' :\x01VERSION xchat 2.8.8 Ubuntu\x01')
                    return

            if nick not in self.built_privmsg:
                if message[0] != COMMAND_PREFIX:
                    log.debug('message not a cmd')
                    return
                # new message starting
                cmd_string = message[1:].split(' ')[0]
                if cmd_string not in plaintext_commands + encrypted_commands:
                    log.debug('cmd not in cmd_list, line="' + message + '"')
                    return
                self.built_privmsg[nick] = [cmd_string, message[:-2]]
            else:
                self.built_privmsg[nick][1] += message[:-2]
            box, encrypt = self.__get_encryption_box(
                self.built_privmsg[nick][0], nick)
            if message[-1] == ';':
                self.waiting[nick] = True
            elif message[-1] == '~':
                self.waiting[nick] = False
                if encrypt:
                    if not box:
                        log.debug('error, dont have encryption box object for '
                                  + nick + ', dropping message')
                        return
                    # need to decrypt everything after the command string
                    to_decrypt = ''.join(self.built_privmsg[nick][1].split(' ')[
                        1])
                    try:
                        decrypted = decode_decrypt(to_decrypt, box)
                    except ValueError as e:
                        log.debug('valueerror when decrypting, skipping: ' +
                                  repr(e))
                        return
                    parsed = self.built_privmsg[nick][1].split(' ')[
                        0] + ' ' + decrypted
                else:
                    parsed = self.built_privmsg[nick][1]
                # wipe the message buffer waiting for the next one
                del self.built_privmsg[nick]
                log.debug("<<privmsg nick=%s message=%s" % (nick, parsed))
                self.__on_privmsg(nick, parsed)
            else:
                # drop the bad nick
                del self.built_privmsg[nick]
        elif target == self.channel:
            log.debug("<<pubmsg nick=%s message=%s" % (nick, message))
            self.__on_pubmsg(nick, message)
        else:
            log.debug('what is this? privmsg src=%s target=%s message=%s;' %
                      (source, target, message))

    def __handle_line(self, line):
        line = line.rstrip()
        # log.debug('<< ' + line)
        if line.startswith('PING '):
            self.send_raw(line.replace('PING', 'PONG'))
            return

        _chunks = line.split(' ')
        if _chunks[1] == 'QUIT':
            nick = get_irc_nick(_chunks[0])
            if nick == self.nick:
                raise IOError('we quit')
            else:
                if self.on_nick_leave:
                    self.on_nick_leave(nick)
        elif _chunks[1] == '433':  # nick in use
            # self.nick = random_nick()
            self.nick += '_'  # helps keep identity constant if just _ added
            self.send_raw('NICK ' + self.nick)
        if self.password:
            if _chunks[1] == 'CAP':
                if _chunks[3] != 'ACK':
                    log.debug('server does not support SASL, quitting')
                    self.shutdown()
                self.send_raw('AUTHENTICATE PLAIN')
            elif _chunks[0] == 'AUTHENTICATE':
                self.send_raw('AUTHENTICATE ' + base64.b64encode(
                    self.nick + '\x00' + self.nick + '\x00' + self.password))
            elif _chunks[1] == '903':
                log.debug('Successfully authenticated')
                self.password = None
                self.send_raw('CAP END')
            elif _chunks[1] == '904':
                log.debug('Failed authentication, wrong password')
                self.shutdown()
            return

        if _chunks[1] == 'PRIVMSG':
            self.__handle_privmsg(_chunks[0], _chunks[2], get_irc_text(line))
        if _chunks[1] == 'PONG':
            self.ping_reply = True
            self.lockcond.acquire()
            self.lockcond.notify()
            self.lockcond.release()
        elif _chunks[1] == '376':  # end of motd
            self.built_privmsg = {}
            if self.on_connect:
                self.on_connect()
            self.send_raw('JOIN ' + self.channel)
            self.send_raw(
                'MODE ' + self.nick + ' +B')  # marks as bots on unreal
            self.send_raw(
                'MODE ' + self.nick + ' -R')  # allows unreg'd private messages
        elif _chunks[1] == '366':  # end of names list
            log.debug('Connected to IRC and joined channel')
            if self.on_welcome:
                self.on_welcome()
        elif _chunks[1] == '332' or _chunks[1] == 'TOPIC':  # channel topic
            topic = get_irc_text(line)
            self.on_set_topic(topic)
        elif _chunks[1] == 'KICK':
            target = _chunks[3]
            if target == self.nick:
                self.give_up = True
                fmt = '{} has kicked us from the irc channel! Reason= {}'.format
                raise IOError(fmt(get_irc_nick(_chunks[0]), get_irc_text(line)))
            else:
                if self.on_nick_leave:
                    self.on_nick_leave(target)
        elif _chunks[1] == 'PART':
            nick = get_irc_nick(_chunks[0])
            if self.on_nick_leave:
                self.on_nick_leave(nick)

        # todo: cleanup
        # elif _chunks[1] == 'JOIN':
        #     channel = _chunks[2][1:]
        #     nick = get_irc_nick(_chunks[0])
        #
        # elif chunks[1] == '005':
        #     self.motd_fd = open("motd.txt", "w")
        # elif chunks[1] == '372':
        #     self.motd_fd.write(get_irc_text(line) + "\n")
        # elif chunks[1] == '251':
        #     self.motd_fd.close()

    def __init__(self,
                 given_nick,
                 username='username',
                 realname='realname',
                 password=None):
        MessageChannel.__init__(self)
        self.give_up = True
        self.cjpeer = None  # subclasses have to set this to self
        self.given_nick = given_nick
        self.nick = given_nick
        config = jm_single().config
        self.serverport = (config.get("MESSAGING", "host"),
                           int(config.get("MESSAGING", "port")))
        self.socks5_host = config.get("MESSAGING", "socks5_host")
        self.socks5_port = int(config.get("MESSAGING", "socks5_port"))
        self.channel = get_config_irc_channel()
        self.userrealname = (username, realname)
        if password and len(password) == 0:
            password = None
        self.given_password = password
        self.pingQ = Queue.Queue()
        self.throttleQ = Queue.Queue()
        self.obQ = Queue.Queue()

    def run(self):
        self.waiting = {}
        self.give_up = False
        self.ping_reply = True
        self.lockcond = threading.Condition()
        self.lockthrottle = threading.Condition()
        PingThread(self).start()
        ThrottleThread(self).start()

        while not self.give_up:
            try:
                config = jm_single().config
                log.debug('connecting')
                if config.get("MESSAGING", "socks5").lower() == 'true':
                    log.debug("Using socks5 proxy %s:%d" %
                              (self.socks5_host, self.socks5_port))
                    setdefaultproxy(PROXY_TYPE_SOCKS5,
                                          self.socks5_host, self.socks5_port,
                                          True)
                    self.sock = socksocket()
                else:
                    self.sock = socket.socket(socket.AF_INET,
                                              socket.SOCK_STREAM)
                self.sock.connect(self.serverport)
                if config.get("MESSAGING", "usessl").lower() == 'true':
                    self.sock = ssl.wrap_socket(self.sock)
                self.fd = self.sock.makefile()
                self.password = None
                if self.given_password:
                    self.password = self.given_password
                    self.send_raw('CAP REQ :sasl')
                self.send_raw('USER %s b c :%s' % self.userrealname)
                self.nick = self.given_nick
                self.send_raw('NICK ' + self.nick)
                while 1:
                    try:
                        line = self.fd.readline()
                    except AttributeError as e:
                        raise IOError(repr(e))
                    if line is None:
                        log.debug('line returned null')
                        break
                    if len(line) == 0:
                        log.debug('line was zero length')
                        break
                    self.__handle_line(line)
            except IOError as e:
                import traceback
                log.debug(traceback.format_exc())
            finally:
                try:
                    self.fd.close()
                    self.sock.close()
                except Exception as e:
                    print(repr(e))
            if self.on_disconnect:
                self.on_disconnect()
            log.debug('disconnected irc')
            if not self.give_up:
                time.sleep(30)
        log.debug('ending irc')
        self.give_up = True
