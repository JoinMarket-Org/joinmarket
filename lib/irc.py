
from common import *
from message_channel import MessageChannel
from message_channel import CJPeerError

import socket, threading, time, ssl, socks
import base64, os, urllib2, re
import enc_wrapper

MAX_PRIVMSG_LEN = 400
COMMAND_PREFIX = '!'
PING_INTERVAL = 40
PING_TIMEOUT = 10
encrypted_commands = ["auth", "ioauth", "tx", "sig"]
plaintext_commands = ["fill", "error", "pubkey", "orderbook", "relorder", "absorder", "push"]

def random_nick():
	random_article_url = 'http://en.wikipedia.org/wiki/Special:Random'
	page = urllib2.urlopen(random_article_url).read()
	page_title = page[page.index('<title>') + 7 : page.index('</title>')]
	title = page_title[:page_title.index(' - Wikipedia')]
	ircnick = ''.join([s.capitalize() for s in re.split('\\W+', title)])
	if re.match('\\d', ircnick[0]):
		ircnick = '_' + ircnick
	ircnick = ircnick[:9]
	return ircnick

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
					try: self.irc.close()
					except IOError: pass
					try: self.irc.fd.close()
					except IOError: pass
					try: 
						self.irc.sock.shutdown(socket.SHUT_RDWR)
						self.irc.sock.close()
					except IOError: pass
			except IOError as e:
				debug('ping thread: ' + repr(e))
		debug('ended ping thread')

#handle one channel at a time
class IRCMessageChannel(MessageChannel):

	#close implies it will attempt to reconnect			
	def close(self):
		try:
			self.send_raw("QUIT")
		except IOError as e:
			debug('errored while trying to quit: ' + repr(e))

	def shutdown(self):
		self.close()
		self.give_up = True

	def send_error(self, nick, errormsg):
		debug('error<%s> : %s' % (nick, errormsg))
		self.__privmsg(nick, 'error', errormsg)
		raise CJPeerError()

	#OrderbookWatch callback
	def request_orderbook(self):
		self.__pubmsg(COMMAND_PREFIX + 'orderbook')

	#Taker callbacks
	def fill_orders(self, nickoid_dict, cj_amount, taker_pubkey):
		for c, oid in nickoid_dict.iteritems():
			msg = str(oid) + ' ' + str(cj_amount) + ' ' + taker_pubkey
			self.__privmsg(c, 'fill', msg)

	def send_auth(self, nick, pubkey, sig):
		message = pubkey + ' ' + sig
		self.__privmsg(nick, 'auth', message)	

	def send_tx(self, nick_list, txhex):
		txb64 = base64.b64encode(txhex.decode('hex'))
		for nick in nick_list:
			self.__privmsg(nick, 'tx', txb64)
			time.sleep(1) #HACK! really there should be rate limiting, see issue#31

	def push_tx(self, nick, txhex):
		txb64 = base64.b64encode(txhex.decode('hex'))
		self.__privmsg(nick, 'push', txb64)

	#Maker callbacks
	def announce_orders(self, orderlist, nick=None):
		#nick=None means announce publicly
		order_keys = ['oid', 'minsize', 'maxsize', 'txfee', 'cjfee']
		header = 'PRIVMSG ' + (nick if nick else self.channel) + ' :'
		orderlines = []
		for i, order in enumerate(orderlist):
			orderparams = COMMAND_PREFIX + order['ordertype'] +\
				' ' + ' '.join([str(order[k]) for k in order_keys])
			orderlines.append(orderparams)
			line = header + ''.join(orderlines) + ' ~'
			if len(line) > MAX_PRIVMSG_LEN or i == len(orderlist)-1:
				if i < len(orderlist)-1:
					line = header + ''.join(orderlines[:-1]) + ' ~'
				self.send_raw(line)
				orderlines = [orderlines[-1]]

	def cancel_orders(self, oid_list):
		clines = [COMMAND_PREFIX + 'cancel ' + str(oid) for oid in oid_list]
		self.__pubmsg(''.join(clines))

	def send_pubkey(self, nick, pubkey):
		self.__privmsg(nick, 'pubkey', pubkey)

	def send_ioauth(self, nick, utxo_list, cj_pubkey, change_addr, sig):
		authmsg = (str(','.join(utxo_list)) + ' ' + 
	                cj_pubkey + ' ' + change_addr + ' ' + sig)
		self.__privmsg(nick, 'ioauth', authmsg)

	def send_sigs(self, nick, sig_list):
		#TODO make it send the sigs on one line if there's space
		for s in sig_list:
			self.__privmsg(nick, 'sig', s)
			time.sleep(0.5) #HACK! really there should be rate limiting, see issue#31

	def __pubmsg(self, message):
		debug('>>pubmsg ' + message)
		self.send_raw("PRIVMSG " + self.channel + " :" + message)

	def __privmsg(self, nick, cmd, message):
		debug('>>privmsg ' + 'nick=' + nick + ' cmd=' + cmd + ' msg=' + message)
		#should we encrypt?
		box = self.__get_encryption_box(cmd, nick)
		#encrypt before chunking
		if box:
			message = enc_wrapper.encrypt_encode(message, box)

		header = "PRIVMSG " + nick + " :"
		max_chunk_len = MAX_PRIVMSG_LEN - len(header) - len(cmd) - 4
		#1 for command prefix 1 for space 2 for trailer
		if len(message) > max_chunk_len:
			message_chunks = chunks(message, max_chunk_len)
		else: 
			message_chunks = [message]
		for m in message_chunks:
			trailer = ' ~' if m==message_chunks[-1] else ' ;'
			if m==message_chunks[0]:
				m = COMMAND_PREFIX + cmd + ' ' + m
			self.send_raw(header + m + trailer)

	def send_raw(self, line):
		#if not line.startswith('PING LAG'):
		#	debug('sendraw ' + line)
		self.sock.sendall(line + '\r\n')

	def check_for_orders(self, nick, chunks):
		if chunks[0] in ordername_list:
			try:
				counterparty = nick
				oid = chunks[1]
				ordertype = chunks[0]
				minsize = chunks[2]
				maxsize = chunks[3]
				txfee = chunks[4]
				cjfee = chunks[5]
				if self.on_order_seen:
					self.on_order_seen(counterparty, oid,
						ordertype, minsize, maxsize, txfee, cjfee)
			except IndexError as e:
				debug('index error parsing chunks')
				#TODO what now? just ignore iirc
			finally:
				return True
		return False

	def __on_privmsg(self, nick, message):
		'''handles the case when a private message is received'''
		if message[0] != COMMAND_PREFIX:
			return
		for command in message[1:].split(COMMAND_PREFIX):
			chunks = command.split(" ")
			#looks like a very similar pattern for all of these
			# check for a command name, parse arguments, call a function
			# maybe we need some eval() trickery to do it better

			try:
				#orderbook watch commands
				if self.check_for_orders(nick, chunks):
					pass

				#taker commands
				elif chunks[0] == 'pubkey':
					maker_pk = chunks[1]
					if self.on_pubkey:
						self.on_pubkey(nick, maker_pk)
				elif chunks[0] == 'ioauth':
					utxo_list = chunks[1].split(',')
					cj_pub = chunks[2]
					change_addr = chunks[3]
					btc_sig = chunks[4]
					if self.on_ioauth:
						self.on_ioauth(nick, utxo_list, cj_pub, change_addr, btc_sig)
				elif chunks[0] == 'sig':
					sig = chunks[1]
					if self.on_sig:
						self.on_sig(nick, sig)

				#maker commands
				if chunks[0] == 'fill':
					try:
						oid = int(chunks[1])
						amount = int(chunks[2])
						taker_pk = chunks[3]
					except (ValueError, IndexError) as e:
						self.send_error(nick, str(e))
					if self.on_order_fill:
						self.on_order_fill(nick, oid, amount, taker_pk)
				elif chunks[0] == 'auth':
					try:
						i_utxo_pubkey = chunks[1]
						btc_sig = chunks[2]
					except (ValueError, IndexError) as e:
						self.send_error(nick, str(e))
					if self.on_seen_auth:
						self.on_seen_auth(nick, i_utxo_pubkey, btc_sig)
				elif chunks[0] == 'tx':
					b64tx = chunks[1]
					try:
						txhex = base64.b64decode(b64tx).encode('hex')
					except TypeError as e:
						self.send_error(nick, 'bad base64 tx. ' + repr(e))
					if self.on_seen_tx:
						self.on_seen_tx(nick, txhex)
				elif chunks[0] == 'push':
					b64tx = chunks[1]
					try:
						txhex = base64.b64decode(b64tx).encode('hex')
					except TypeError as e:
						self.send_error(nick, 'bad base64 tx. ' + repr(e))
					if self.on_push_tx:
						self.on_push_tx(nick, txhex)
			except CJPeerError:
				#TODO proper error handling
				debug('cj peer error TODO handle')
				continue

	def __on_pubmsg(self, nick, message):
		if message[0] != COMMAND_PREFIX:
			return
		for command in message[1:].split(COMMAND_PREFIX):
			chunks = command.split(" ")
			if self.check_for_orders(nick, chunks):
				pass
			elif chunks[0] == 'cancel':
				#!cancel [oid]
				try:
					oid = int(chunks[1])
					if self.on_order_cancel:
						self.on_order_cancel(nick, oid)
				except ValueError as e:
					debug("!cancel " + repr(e))
					return
			elif chunks[0] == 'orderbook':
				if self.on_orderbook_requested:
					self.on_orderbook_requested(nick)
			else:
				#TODO this is for testing/debugging, should be removed, see taker.py
				if hasattr(self, 'debug_on_pubmsg_cmd'):
					self.debug_on_pubmsg_cmd(nick, chunks)

	def __get_encryption_box(self, cmd, nick):
		'''Establish whether the message is to be
		encrypted/decrypted based on the command string.
		If so, retrieve the appropriate crypto_box object
		and return. Sending/receiving flag enables us
		to check which command strings correspond to which
		type of object (maker/taker).''' #old doc, dont trust
		if cmd in plaintext_commands:
			return None
		else:
			return self.cjpeer.get_crypto_box_from_nick(nick)

	def __handle_privmsg(self, source, target, message):
		nick = get_irc_nick(source)
		if target == self.nick:
			if message[0] == '\x01':
				endindex = message[1:].find('\x01')
				if endindex == -1:
					return
				ctcp = message[1:endindex + 1]
				if ctcp.upper() == 'VERSION':
					self.send_raw('PRIVMSG ' + nick + ' :\x01VERSION xchat 2.8.8 Ubuntu\x01')
					return

			if nick not in self.built_privmsg:
				if message[0] != COMMAND_PREFIX:
					debug('message not a cmd')
					return
				#new message starting
				cmd_string = message[1:].split(' ')[0]
				if cmd_string not in plaintext_commands + encrypted_commands:
					debug('cmd not in cmd_list, line="' + message + '"')
					return
				self.built_privmsg[nick] = [cmd_string, message[:-2]]
			else:
				self.built_privmsg[nick][1] += message[:-2]
			box = self.__get_encryption_box(self.built_privmsg[nick][0], nick)
			if message[-1]==';':
				self.waiting[nick]=True
			elif message[-1]=='~':
				self.waiting[nick]=False
				if box:
					#need to decrypt everything after the command string
					to_decrypt = ''.join(self.built_privmsg[nick][1].split(' ')[1])
					decrypted = enc_wrapper.decode_decrypt(to_decrypt, box)
					parsed = self.built_privmsg[nick][1].split(' ')[0] + ' ' + decrypted
				else:
					parsed = self.built_privmsg[nick][1]
				#wipe the message buffer waiting for the next one
				del self.built_privmsg[nick]
				debug("<<privmsg nick=%s message=%s" % (nick, parsed))
				self.__on_privmsg(nick, parsed)
			else:
				#drop the bad nick
				del self.built_privmsg[nick]
		elif target == self.channel:
			debug("<<pubmsg nick=%s message=%s" % (nick, message))
			self.__on_pubmsg(nick, message)
		else:
			debug('what is this? privmsg src=%s target=%s message=%s;' % (source, target, message))
		
	def __handle_line(self, line):
		line = line.rstrip()
		#print('<< ' + line)
		if line.startswith('PING '):
			self.send_raw(line.replace('PING', 'PONG'))
			return

		chunks = line.split(' ')
		if self.password:
			if chunks[1] == 'CAP':
				if chunks[3] != 'ACK':
					debug('server does not support SASL, quitting')
					self.shutdown()
				self.send_raw('AUTHENTICATE PLAIN')
			elif chunks[0] == 'AUTHENTICATE':
				self.send_raw('AUTHENTICATE ' + base64.b64encode(self.nick + '\x00' + self.nick + '\x00' + self.password))
			elif chunks[1] == '903':
				debug('Successfully authenticated')
				self.password = None
				self.send_raw('CAP END')
			elif chunks[1] == '904':
				debug('Failed authentication, wrong password')
				self.shutdown()
			return

		if chunks[1] == 'PRIVMSG':
			self.__handle_privmsg(chunks[0], chunks[2], get_irc_text(line))
		if chunks[1] == 'PONG':
			self.ping_reply = True
			self.lockcond.acquire()
			self.lockcond.notify()
			self.lockcond.release()
		elif chunks[1] == '376': #end of motd
			if self.on_connect:
				self.on_connect()
			self.send_raw('JOIN ' + self.channel)
		elif chunks[1] == '433': #nick in use
			#self.nick = random_nick()
			self.nick += '_' #helps keep identity constant if just _ added
			self.send_raw('NICK ' + self.nick)
		elif chunks[1] == '366': #end of names list
			self.connect_attempts = 0
			if self.on_welcome:
				self.on_welcome()
			debug('Connected to IRC and joined channel')
		elif chunks[1] == '332' or chunks[1] == 'TOPIC': #channel topic
			topic = get_irc_text(line)
			self.on_set_topic(topic)
		elif chunks[1] == 'QUIT':
			nick = get_irc_nick(chunks[0])
			if nick == self.nick:
				raise IOError('we quit')
			else:
				if self.on_nick_leave:
					self.on_nick_leave(nick)
		elif chunks[1] == 'KICK':
			target = chunks[3]
			nick = get_irc_nick(chunks[0])
			if target == self.nick:
				self.give_up = True
				raise IOError(get_irc_nick(chunks[0]) + ' has kicked us from the irc channel! Reason=' + get_irc_text(line))
			else:
				if self.on_nick_leave:
					self.on_nick_leave(target)
		elif chunks[1] == 'PART':
			nick = get_irc_nick(chunks[0])
			if self.on_nick_leave:
				self.on_nick_leave(nick)
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

	def __init__(self, given_nick, username='username', realname='realname', password=None):
		MessageChannel.__init__(self)
		self.cjpeer = None #subclasses have to set this to self
		self.given_nick = given_nick
		self.nick = given_nick
		self.serverport = (config.get("MESSAGING","host"), int(config.get("MESSAGING","port")))
		self.socks5_host = config.get("MESSAGING","socks5_host")
		self.socks5_port = int(config.get("MESSAGING","socks5_port"))
		self.channel = get_config_irc_channel()
		self.userrealname = (username, realname)
		if password and len(password) == 0:
			password = None
		self.password = password

	def run(self):
		self.connect_attempts = 0
		self.waiting = {}
		self.built_privmsg = {}
		self.give_up = False
		self.ping_reply = True
		self.lockcond = threading.Condition()
		#PingThread(self).start()

		while self.connect_attempts < 10 and not self.give_up:
			try:
				debug('connecting')
				if config.get("MESSAGING","socks5").lower() == 'true':
					debug("Using socks5 proxy %s:%d" % (self.socks5_host, self.socks5_port))
					socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, self.socks5_host, self.socks5_port, True)
					self.sock = socks.socksocket()	
				else:
					self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				if config.get("MESSAGING","usessl").lower() == 'true':
					self.sock = ssl.wrap_socket(self.sock)
				self.fd = self.sock.makefile()
				self.sock.connect(self.serverport)
				if self.password:
					self.send_raw('CAP REQ :sasl')
				self.send_raw('USER %s b c :%s' % self.userrealname)
				self.send_raw('NICK ' + self.given_nick)
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
				debug(repr(e))
			finally:
				try:
					self.fd.close()
					self.sock.close()
				except Exception as e:
					print repr(e)
			if self.on_disconnect:
				self.on_disconnect()
			debug('disconnected irc')
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

