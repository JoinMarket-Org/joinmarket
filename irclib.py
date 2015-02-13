
from common import *
from message_channel import MessageChannel

import socket, threading, time
import base64, os
import enc_wrapper

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
	#def run(self): pass
	#def shutdown(self): pass
	def request_orderbook(self): pass
	def fill_order(self, nick, oid, cj_amount, taker_pubkey): pass
	def send_auth(self, nick, pubkey, sig): pass
	def send_tx(self, nick, txhex): pass
	def announce_orders(self, orderlist, nick=None): pass #nick=None means announce publicly
	def cancel_orders(self, oid_list): pass
	def send_error(self, nick, errormsg): pass
	def send_pubkey(self, nick, pubkey): pass
	def send_ioauth(self, nick, utxo_list, cj_pubkey, change_addr, sig): pass
	def send_sigs(self, nick, sig_list): pass

	def register_channel_callbacks(self, on_welcome=None, on_set_topic=None,
		on_connect=None, on_disconnect=None, on_nick_leave=None, on_nick_change=None):
	def register_orderbookwatch_callbacks(self, on_orders_seen=None,
		on_orders_cancel=None):
	def register_taker_callbacks(self, on_error=None, on_pubkey=None, on_ioauth=None,
		on_sigs=None):
	def register_maker_callbacks(self, on_orderbook_requested=None, on_order_filled=None,
		on_seen_auth=None, on_seen_tx=None):

	def on_privmsg(self, nick, message): pass
	def on_pubmsg(self, nick, message): pass
	def on_welcome(self): pass
	def on_set_topic(self, newtopic): pass
	def on_leave(self, nick): pass
	def on_disconnect(self): pass
	def on_connect(self): pass
	#TODO implement on_nick_change
	
	def encrypting(self, cmd, nick, sending=False):
		'''Establish whether the message is to be
		encrypted/decrypted based on the command string.
		If so, retrieve the appropriate crypto_box object
		and return. Sending/receiving flag enables us
		to check which command strings correspond to which
		type of object (maker/taker).'''

		if cmd in plaintext_commands:
			return None
		elif cmd not in encrypted_commands:
			raise Exception("Invalid command type: " + cmd)
		
		maker_strings = ['tx','auth'] if not sending else ['ioauth','sig']
		taker_strings = ['ioauth','sig'] if not sending else ['tx','auth']
		
		if cmd in maker_strings:
			return self.active_orders[nick].crypto_box
		elif cmd in taker_strings:
			return self.cjtx.crypto_boxes[nick][1]		
		else:
			raise Exception("Invalid command type: " + cmd)
	
	#close implies it will attempt to reconnect			
	def close(self):
		try:
			self.send_raw("QUIT")
		except IOError as e:
			debug('errored while trying to quit: ' + repr(e))

	def shutdown(self):
		self.close()
		self.give_up = True

	def pubmsg(self, message):
		debug('>>pubmsg ' + message)
		self.send_raw("PRIVMSG " + self.channel + " :" + message)

	def privmsg(self, nick, cmd, message):
		debug('>>privmsg ' + 'nick=' + nick + ' cmd=' + cmd + ' msg=' + message)
		#should we encrypt?
		box = self.encrypting(cmd, nick, sending=True)
		#encrypt before chunking
		if box:
			message = enc_wrapper.encrypt_encode(message, box)
		
		if len(message) > 350:
			message_chunks = chunks(message, 350)
		else: 
			message_chunks = [message]
			
		for m in message_chunks:
			trailer = ' ~' if m==message_chunks[-1] else ' ;'
			header = "PRIVMSG " + nick + " :"
			if m==message_chunks[0]: header += '!'+cmd + ' '
			self.send_raw(header + m + trailer)

	def send_raw(self, line):
		#if not line.startswith('PING LAG'):
		#	debug('sendraw ' + line)
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
			if nick not in self.built_privmsg:
				#new message starting
				cmd_string = ''.join(message.split(' ')[0][1:])
				self.built_privmsg[nick] = [cmd_string, message[:-2]]
			else:
				self.built_privmsg[nick][1] += message[:-2]
			box = self.encrypting(self.built_privmsg[nick][0], nick)						
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
				self.on_privmsg(nick, parsed)
			else:
				raise Exception("message formatting error")			
		else:
			debug("<<pubmsg nick=%s message=%s" % (nick, message))
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
		elif chunks[1] == '376': #end of motd
			if self.on_connect:
				self.on_connect()
			self.send_raw('JOIN ' + self.channel)
		elif chunks[1] == '433': #nick in use
			self.nick += '_'
			self.send_raw('NICK ' + self.nick)
		elif chunks[1] == '366': #end of names list
			self.connect_attempts = 0
			if self.on_welcome:
				self.on_welcome()
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
			if self.on_nick_leave:
				self.on_nick_leave(nick)
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

	def __init__(self, server, port, nick, channel, username='username', realname='realname'):
		self.serverport = (server, port)
		self.nick = nick
		self.channel = channel
		self.userrealname = (username, realname)

	def run(self):
		self.connect_attempts = 0
		self.waiting = {}
		self.built_privmsg = {}
		self.give_up = False
		self.ping_reply = True
		self.lockcond = threading.Condition()
		PingThread(self).start()

		while self.connect_attempts < 10 and not self.give_up:
			try:
				debug('connecting')
				self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				self.sock.connect(self.serverport)
				self.fd = self.sock.makefile()
				self.send_raw('USER %s b c :%s' % userrealname)
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
			if self.on_disconnect:
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

