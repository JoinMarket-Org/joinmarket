import socket, threading, time
from common import debug, chunks
import enc_wrapper
import base64, os

PING_INTERVAL = 40
PING_TIMEOUT = 10


def get_irc_text(line):
    return line[line[1:].find(':') + 2:]


def get_irc_nick(source):
    return source[1:source.find('!')]


class PingThread(threading.Thread):

    def __init__(self, irc):
        threading.Thread.__init__(self)
        self.daemon = True
        self.irc = irc

    def run(self):
        debug('starting ping thread')
        while not self.irc.give_up:
            time.sleep(PING_INTERVAL)
            try:
                self.irc.ping_reply = False
                #maybe use this to calculate the lag one day
                self.irc.lockcond.acquire()
                self.irc.send_raw('PING LAG' + str(int(time.time() * 1000)))
                self.irc.lockcond.wait(PING_TIMEOUT)
                self.irc.lockcond.release()
                if not self.irc.ping_reply:
                    debug('irc ping timed out')
                    try:
                        self.irc.close()
                    except IOError:
                        pass
                    try:
                        self.irc.fd.close()
                    except IOError:
                        pass
                    try:
                        self.irc.sock.shutdown(socket.SHUT_RDWR)
                        self.irc.sock.close()
                    except IOError:
                        pass
            except IOError as e:
                debug('ping thread: ' + repr(e))
        debug('ended ping thread')


#handle one channel at a time
class IRCClient(object):

    def on_privmsg(self, nick, message):
        pass

    def on_pubmsg(self, nick, message):
        pass

    def on_welcome(self):
        pass

    def on_set_topic(self, newtopic):
        pass

    def on_leave(self, nick):
        pass

    def on_disconnect(self):
        pass

    def on_connect(self):
        pass

    #TODO implement on_nick_change

    ###############################
    #Encryption code
    ###############################
    def init_encryption(self, fname):
        if not os.path.isfile(fname):
            self.enc_kp = enc_wrapper.init_keypair(fname)
        else:
            self.enc_kp = enc_wrapper.libnacl.utils.load_key(fname)

    def start_encryption(self, nick, c_pk_hex):
        '''sets encryption mode on
		for all succeeding messages
		until end_encryption is called.
		Public key of counterparty must be
		passed in in hex.'''
        if not self.enc_kp:
            raise Exception("Cannot initialise encryption without a keypair")
        self.cp_pubkeys[nick] = enc_wrapper.init_pubkey(c_pk_hex)
        self.enc_boxes[nick] = enc_wrapper.as_init_encryption(
            self.enc_kp, self.cp_pubkeys[nick])
        self.encrypting[nick] = True

    def end_encryption(self, nick):
        self.encrypting[nick] = False
        #for safety, blank out all data related
        #to the connection
        self.cp_pubkeys[nick] = None
        self.enc_boxes[nick] = None

    def encrypt_encode(self, msg, nick):
        if not (nick in self.encrypting.keys()) or not (
                nick in self.enc_boxes.keys()):
            raise Exception("Encryption is not switched on.")
        if not (self.encrypting[nick] and self.enc_boxes[nick]):
            raise Exception("Encryption is not switched on.")
        encrypted = self.enc_boxes[nick].encrypt(msg)
        return base64.b64encode(encrypted)

    def decode_decrypt(self, msg, nick):
        if not (nick in self.encrypting.keys()) or not (
                nick in self.enc_boxes.keys()):
            raise Exception("Encryption is not switched on.")
        if not (self.encrypting[nick] and self.enc_boxes[nick]):
            raise Exception("Encryption is not switched on.")
        decoded = base64.b64decode(msg)
        return self.enc_boxes[nick].decrypt(decoded)
    #############################
    #End encryption code
    #############################

    def close(self):
        try:
            self.send_raw("QUIT")
        except IOError as e:
            debug('errored while trying to quit: ' + repr(e))

    def shutdown(self):
        self.close()
        self.give_up = True

    def pubmsg(self, message):
        #debug('pubmsg ' + message)
        self.send_raw("PRIVMSG " + self.channel + " :" + message)

    def privmsg(self, nick, message):
        #debug('privmsg to ' + nick + ' ' + message)
        if nick in self.encrypting.keys() and self.encrypting[nick]:
            message = self.encrypt_encode(message, nick)
        if len(message) > 350:
            message_chunks = chunks(message, 350)
        else:
            message_chunks = [message]
        print "We are going to send these chunks: "
        print message_chunks
        for m in message_chunks:
            trailer = ' ~' if m == message_chunks[-1] else ' ;'
            self.send_raw("PRIVMSG " + nick + " :" + m + trailer)

    def send_raw(self, line):
        if not line.startswith('PING LAG'):
            debug('sendraw ' + line)
        self.sock.sendall(line + '\r\n')

    def __handle_privmsg(self, source, target, message):
        nick = get_irc_nick(source)
        if message[0] == '\x01':
            endindex = message[1:].find('\x01')
            if endindex == -1:
                return
            ctcp = message[1:endindex + 1]
            #self.send_raw('PRIVMSG ' + nick + ' :\x01VERSION 
            #TODO ctcp version here, since some servers dont let you get on without

        if target == self.nick:
            if nick not in self.built_privmsg or self.built_privmsg[nick] == '':
                self.built_privmsg[nick] = message[:-2]
            else:
                self.built_privmsg[nick] += message[:-2]
            if message[-1] == ';':
                self.waiting[nick] = True
            elif message[-1] == '~':
                self.waiting[nick] = False
                if nick in self.encrypting.keys() and self.encrypting[nick]:
                    parsed = self.decode_decrypt(self.built_privmsg[nick], nick)
                else:
                    parsed = self.built_privmsg[nick]
                #wipe the message buffer waiting for the next one
                self.built_privmsg[nick] = ''
                self.on_privmsg(nick, parsed)
            else:
                raise Exception("message formatting error")
        else:
            self.on_pubmsg(nick, message)

    def __handle_line(self, line):
        line = line.rstrip()
        #print('<< ' + line)
        if line.startswith('PING '):
            self.send_raw(line.replace('PING', 'PONG'))
            return

        chunks = line.split(' ')
        if chunks[1] == 'PRIVMSG':
            self.__handle_privmsg(chunks[0], chunks[2], get_irc_text(line))
        if chunks[1] == 'PONG':
            self.ping_reply = True
            self.lockcond.acquire()
            self.lockcond.notify()
            self.lockcond.release()
        elif chunks[1] == '376':  #end of motd
            self.on_connect()
            self.send_raw('JOIN ' + self.channel)
        elif chunks[1] == '433':  #nick in use
            self.nick += '_'
            self.send_raw('NICK ' + self.nick)
        elif chunks[1] == '366':  #end of names list
            self.connect_attempts = 0
            self.on_welcome()
        elif chunks[1] == '332' or chunks[1] == 'TOPIC':  #channel topic
            topic = get_irc_text(line)
            self.on_set_topic(topic)
        elif chunks[1] == 'QUIT':
            nick = get_irc_nick(chunks[0])
            if nick == self.nick:
                raise IOError('we quit')
            else:
                self.on_leave(nick)
        elif chunks[1] == 'KICK':
            target = chunks[3]
            nick = get_irc_nick(chunks[0])
            self.on_leave(nick)
        elif chunks[1] == 'PART':
            nick = get_irc_nick(chunks[0])
            self.on_leave(nick)
        elif chunks[1] == 'JOIN':
            channel = chunks[2][1:]
            nick = get_irc_nick(chunks[0])
        '''
		elif chunks[1] == '005':
			self.motd_fd = open("motd.txt", "w")
		elif chunks[1] == '372':
			self.motd_fd.write(get_irc_text(line) + "\n")
		elif chunks[1] == '251':
			self.motd_fd.close()
		'''

    def run(self,
            server,
            port,
            nick,
            channel,
            username='username',
            realname='realname'):
        self.nick = nick
        self.channel = channel
        self.connect_attempts = 0
        #set up encryption management variables
        self.cp_pubkeys = {}
        self.enc_boxes = {}
        self.encrypting = {}
        self.waiting = {}
        self.built_privmsg = {}
        self.give_up = False
        self.ping_reply = True
        self.lockcond = threading.Condition()
        PingThread(self).start()

        while self.connect_attempts < 10 and not self.give_up:
            try:
                print 'connecting'
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect((server, port))
                self.fd = self.sock.makefile()
                self.send_raw('USER %s b c :%s' % (username, realname))
                self.send_raw('NICK ' + nick)
                while 1:
                    try:
                        line = self.fd.readline()
                    except AttributeError as e:
                        raise IOError(repr(e))
                    if line == None:
                        debug('line returned null')
                        break
                    if len(line) == 0:
                        debug('line was zero length')
                        break
                    self.__handle_line(line)
            except IOError as e:
                print repr(e)
            finally:
                self.fd.close()
                self.sock.close()
            self.on_disconnect()
            print 'disconnected irc'
            time.sleep(10)
            self.connect_attempts += 1
        debug('ending irc')
        self.give_up = True


def irc_privmsg_size_throttle(irc, target, lines, prefix=''):
    line = ''
    for l in lines:
        line += l
        if len(line) > MAX_PRIVMSG_LEN:
            irc.privmsg(target, prefix + line)
            line = ''
    if len(line) > 0:
        irc.privmsg(target, prefix + line)
