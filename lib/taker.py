#! /usr/bin/env python

from common import *
import common
import enc_wrapper
import bitcoin as btc
import binascii
import sqlite3, base64, threading, time, random, pprint

class CoinJoinTX(object):
	#soon the taker argument will be removed and just be replaced by wallet or some other interface
	def __init__(self, msgchan, wallet, db, cj_amount, orders, input_utxos, my_cj_addr,
		my_change_addr, total_txfee, finishcallback, choose_orders_recover, auth_addr=None):
		'''
		if my_change is None then there wont be a change address
		thats used if you want to entirely coinjoin one utxo with no change left over
		orders is the orders you want to fill {'counterpartynick': oid, 'cp2': oid2}
		'''
		debug('starting cj to ' + str(my_cj_addr) + ' with change at ' + str(my_change_addr))
		#parameters
		self.msgchan = msgchan
		self.wallet = wallet
		self.db = db
		self.cj_amount = cj_amount
		self.active_orders = dict(orders)
		self.input_utxos = input_utxos
		self.finishcallback = finishcallback
		self.total_txfee = total_txfee
		self.my_cj_addr = my_cj_addr
		self.my_change_addr = my_change_addr
		self.choose_orders_recover = choose_orders_recover
		self.auth_addr = auth_addr
		self.timeout_lock = threading.Condition() #used to wait() and notify()
		#used to restrict access to certain variables across threads
		self.timeout_thread_lock = threading.Condition()
		self.end_timeout_thread = False
		CoinJoinTX.TimeoutThread(self).start()
		#state variables
		self.txid = None
		self.cjfee_total = 0
		self.maker_txfee_contributions = 0
		self.nonrespondants = list(self.active_orders.keys())
		self.all_responded = False
		self.latest_tx = None
		self.utxos = {None: self.input_utxos.keys()} #None means they belong to me
		self.outputs = []
		#create DH keypair on the fly for this Tx object
		self.kp = enc_wrapper.init_keypair()
		self.crypto_boxes = {}
		self.msgchan.fill_orders(self.active_orders, self.cj_amount, self.kp.hex_pk())

	def start_encryption(self, nick, maker_pk):
		if nick not in self.active_orders.keys():
			debug("Counterparty not part of this transaction. Ignoring")
			return
		self.crypto_boxes[nick] = [maker_pk, enc_wrapper.as_init_encryption(\
		                        self.kp, enc_wrapper.init_pubkey(maker_pk))]
		#send authorisation request
		if self.auth_addr:
			my_btc_addr = self.auth_addr
		else:
			my_btc_addr = self.input_utxos.itervalues().next()['address']
		my_btc_priv = self.wallet.get_key_from_addr(my_btc_addr)
		my_btc_pub = btc.privtopub(my_btc_priv, True)
		my_btc_sig = btc.ecdsa_sign(self.kp.hex_pk(), binascii.unhexlify(my_btc_priv))
		self.msgchan.send_auth(nick, my_btc_pub, my_btc_sig)
	
	def auth_counterparty(self, nick, btc_sig, cj_pub):
		'''Validate the counterpartys claim to own the btc
		address/pubkey that will be used for coinjoining 
		with an ecdsa verification.'''
		#crypto_boxes[nick][0] = maker_pubkey
		if not btc.ecdsa_verify(self.crypto_boxes[nick][0], btc_sig, binascii.unhexlify(cj_pub)):
			debug('signature didnt match pubkey and message')
			return False
		return True
	
	def recv_txio(self, nick, utxo_list, cj_pub, change_addr):	
		if nick not in self.nonrespondants:
			debug('recv_txio => nick=' + nick + ' not in nonrespondants ' + str(self.nonrespondants))
			return
		self.utxos[nick] = utxo_list
		order = self.db.execute('SELECT ordertype, txfee, cjfee FROM '
			'orderbook WHERE oid=? AND counterparty=?',
			(self.active_orders[nick], nick)).fetchone()
		utxo_data = common.bc_interface.query_utxo_set(self.utxos[nick])
		if None in utxo_data:
			common.debug('ERROR outputs unconfirmed or already spent. utxo_data='
				+ pprint.pformat(utxo_data))
			#when internal reviewing of makers is created, add it here to immediately quit
			return #ignore this message, eventually the timeout thread will recover
		total_input = sum([d['value'] for d in utxo_data])
		real_cjfee = calc_cj_fee(order['ordertype'], order['cjfee'], self.cj_amount)
		self.outputs.append({'address': change_addr, 'value':
			total_input - self.cj_amount - order['txfee'] + real_cjfee})
		debug('fee breakdown for %s totalin=%d cjamount=%d txfee=%d realcjfee=%d' % (nick,
			total_input, self.cj_amount, order['txfee'], real_cjfee))
		cj_addr = btc.pubtoaddr(cj_pub, get_p2pk_vbyte())
		self.outputs.append({'address': cj_addr, 'value': self.cj_amount})
		self.cjfee_total += real_cjfee
		self.maker_txfee_contributions += order['txfee']
		self.nonrespondants.remove(nick)
		if len(self.nonrespondants) > 0:
			debug('nonrespondants = ' + str(self.nonrespondants))
			return
		self.all_responded = True
		with self.timeout_lock:
			self.timeout_lock.notify()
		debug('got all parts, enough to build a tx')
		self.nonrespondants = list(self.active_orders.keys())

		my_total_in = sum([va['value'] for u, va in self.input_utxos.iteritems()])
		my_txfee = max(self.total_txfee - self.maker_txfee_contributions, 0)
		my_change_value = (my_total_in - self.cj_amount - self.cjfee_total - my_txfee)
		debug('fee breakdown for me totalin=%d my_txfee=%d makers_txfee=%d cjfee_total=%d => changevalue=%d' % (my_total_in, 
			my_txfee, self.maker_txfee_contributions, self.cjfee_total, my_change_value))
		if self.my_change_addr == None:
			if my_change_value != 0 and abs(my_change_value) != 1:
				#seems you wont always get exactly zero because of integer rounding
				# so 1 satoshi extra or fewer being spent as miner fees is acceptable
				debug('WARNING CHANGE NOT BEING USED\nCHANGEVALUE = ' + str(my_change_value))
		else:
			self.outputs.append({'address': self.my_change_addr, 'value': my_change_value})
		self.utxo_tx = [dict([('output', u)]) for u in sum(self.utxos.values(), [])]
		self.outputs.append({'address': self.coinjoin_address(), 'value': self.cj_amount})
		random.shuffle(self.utxo_tx)
		random.shuffle(self.outputs)
		tx = btc.mktx(self.utxo_tx, self.outputs)	
		debug('obtained tx\n' + pprint.pformat(btc.deserialize(tx)))
		self.msgchan.send_tx(self.active_orders.keys(), tx)

		self.latest_tx = btc.deserialize(tx)
		for index, ins in enumerate(self.latest_tx['ins']):
			utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			if utxo not in self.input_utxos.keys():
				continue
			#placeholders required
			ins['script'] = 'deadbeef'

	def add_signature(self, nick, sigb64):
		if nick not in self.nonrespondants:
			debug('add_signature => nick=' + nick + ' not in nonrespondants ' + str(self.nonrespondants))
			return
		sig = base64.b64decode(sigb64).encode('hex')
		inserted_sig = False
		txhex = btc.serialize(self.latest_tx)
		
		#batch retrieval of utxo data
		utxo = {}
		ctr = 0
		for index, ins in enumerate(self.latest_tx['ins']):
			utxo_for_checking = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			if ins['script'] != '' or  utxo_for_checking in self.input_utxos.keys():
				continue
			utxo[ctr] = [index, utxo_for_checking]
			ctr += 1
		utxo_data = common.bc_interface.query_utxo_set([x[1] for x in utxo.values()])
		#insert signatures
		for i,u in utxo.iteritems():
			if utxo_data[i] == None:
				continue
			sig_good = btc.verify_tx_input(txhex, u[0], utxo_data[i]['script'], *btc.deserialize_script(sig))
			if sig_good:
				debug('found good sig at index=%d' % (u[0]))
				self.latest_tx['ins'][u[0]]['script'] = sig
				inserted_sig = True
				#check if maker has sent everything possible
				self.utxos[nick].remove(u[1])
				if len(self.utxos[nick]) == 0:
					debug('nick = ' + nick + ' sent all sigs, removing from nonrespondant list')
					self.nonrespondants.remove(nick)
				break
		if not inserted_sig:
			debug('signature did not match anything in the tx')
			#TODO what if the signature doesnt match anything
			# nothing really to do except drop it, carry on and wonder why the
			# other guy sent a failed signature

		tx_signed = True
		for ins in self.latest_tx['ins']:
			if ins['script'] == '':
				tx_signed = False
		if not tx_signed:
			return
		self.end_timeout_thread = True
		self.all_responded = True
		with self.timeout_lock:
			self.timeout_lock.notify()
		debug('all makers have sent their signatures')
		for index, ins in enumerate(self.latest_tx['ins']):
			#remove placeholders
			if ins['script'] == 'deadbeef':
				ins['script'] = ''
		if self.finishcallback != None:
			self.finishcallback(self)

	def coinjoin_address(self):
		if self.my_cj_addr:
			return self.my_cj_addr
		else:
			return donation_address(self)

	def sign_tx(self, tx, i, priv):
		if self.my_cj_addr:
			return btc.sign(tx, i, priv)
		else:
			return sign_donation_tx(tx, i, priv)	

	def self_sign(self):
		#now sign it ourselves
		tx = btc.serialize(self.latest_tx)
		for index, ins in enumerate(self.latest_tx['ins']):
			utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			if utxo not in self.input_utxos.keys():
				continue
			addr = self.input_utxos[utxo]['address']
			tx = self.sign_tx(tx, index, self.wallet.get_key_from_addr(addr))
		self.latest_tx = btc.deserialize(tx)

	def push(self, txd):
		tx = btc.serialize(txd)
		debug('\n' + tx)
		debug('txid = ' + btc.txhash(tx))
		#TODO send to a random maker or push myself
		#TODO need to check whether the other party sent it
		#self.msgchan.push_tx(self.active_orders.keys()[0], txhex)	
		self.txid = common.bc_interface.pushtx(tx)
		if self.txid == None:
			debug('unable to pushtx')

	def self_sign_and_push(self):
		self.self_sign()
		self.push(self.latest_tx)

	def recover_from_nonrespondants(self):
		debug('nonresponding makers = ' + str(self.nonrespondants))
		#if there is no choose_orders_recover then end and call finishcallback
		# so the caller can handle it in their own way, notable for sweeping
		# where simply replacing the makers wont work
		if not self.choose_orders_recover:
			self.end_timeout_thread = True
			if self.finishcallback != None:
				self.finishcallback(self)
			return

		if self.latest_tx == None:
			#nonresponding to !fill, recover by finding another maker
			debug('nonresponse to !fill')
			for nr in self.nonrespondants:
				del self.active_orders[nr]
			new_orders, new_makers_fee = self.choose_orders_recover(self.cj_amount,
				len(self.nonrespondants), self.nonrespondants, self.active_orders.keys())
			for nick, order in new_orders.iteritems():
				self.active_orders[nick] = order
			self.nonrespondants = list(new_orders.keys())
			debug('new active_orders = ' + pprint.pformat(self.active_orders) +
				'\nnew nonrespondants = ' + pprint.pformat(self.nonrespondants))
			self.msgchan.fill_orders(new_orders, self.cj_amount, self.kp.hex_pk())
		else:
			debug('nonresponse to !sig')
			#nonresponding to !sig, have to restart tx from the beginning
			self.end_timeout_thread = True
			if self.finishcallback != None:
				self.finishcallback(self)
			#finishcallback will check if self.all_responded is True and will know it came from here

	class TimeoutThread(threading.Thread):
		def __init__(self, cjtx):
			threading.Thread.__init__(self)
			self.cjtx = cjtx

		def run(self):
			debug('started timeout thread for coinjoin of amount ' +
				str(self.cjtx.cj_amount) + ' to addr ' + str(self.cjtx.my_cj_addr))

			#how the threading to check for nonresponding makers works like this
			#there is a Condition object
			#in a loop, call cond.wait(timeout)
			# after it returns, check a boolean
			# to see if if the messages have arrived
			while not self.cjtx.end_timeout_thread:
				debug('waiting for all replies.. timeout=' + str(common.maker_timeout_sec))
				with self.cjtx.timeout_lock:
					self.cjtx.timeout_lock.wait(common.maker_timeout_sec)
				if self.cjtx.all_responded:
					debug('timeout thread woken by notify(), makers responded in time')
					self.cjtx.all_responded = False
				else:
					debug('timeout thread woken by timeout, makers didnt respond')
					with self.cjtx.timeout_thread_lock:
						self.cjtx.recover_from_nonrespondants()

class CoinJoinerPeer(object):
	def __init__(self, msgchan):
		self.msgchan = msgchan

	def get_crypto_box_from_nick(self, nick):
		raise Exception()

	def on_set_topic(self, newtopic):
		chunks = newtopic.split('|')
		for msg in chunks[1:]:
			try:
				msg = msg.strip()
				params = msg.split(' ')
				min_version = int(params[0])
				max_version = int(params[1])
				alert = msg[msg.index(params[1]) + len(params[1]):].strip()
			except ValueError, IndexError:
				continue
			if min_version < common.JM_VERSION and max_version > common.JM_VERSION:
				print '=' * 60
				print 'JOINMARKET ALERT'
				print alert
				print '=' * 60
				common.joinmarket_alert = alert


class OrderbookWatch(CoinJoinerPeer):
	def __init__(self, msgchan):
		CoinJoinerPeer.__init__(self, msgchan)
		self.msgchan.register_orderbookwatch_callbacks(self.on_order_seen,
			self.on_order_cancel)
		self.msgchan.register_channel_callbacks(self.on_welcome, self.on_set_topic,
			None, self.on_disconnect, self.on_nick_leave, None)

		con = sqlite3.connect(":memory:", check_same_thread=False)
		con.row_factory = sqlite3.Row
		self.db = con.cursor()
		self.db.execute("CREATE TABLE orderbook(counterparty TEXT, oid INTEGER, ordertype TEXT, "
			+ "minsize INTEGER, maxsize INTEGER, txfee INTEGER, cjfee TEXT);")

	def on_order_seen(self,	counterparty, oid, ordertype, minsize, maxsize, txfee, cjfee):
		try:
			if int(oid) < 0 or int(oid) > sys.maxint:
				debug("Got invalid order ID: " + oid + " from " + counterparty)
				return
			# delete orders eagerly, so in case a buggy maker sends an invalid offer,
			# we won't accidentally !fill based on the ghost of its previous message.
			self.db.execute("DELETE FROM orderbook WHERE counterparty=? AND oid=?;",
				(counterparty, oid))
			# now validate the remaining fields
			if int(minsize) < 0 or int(minsize) > 21*10**14:
				debug("Got invalid minsize: " + minsize + " from " + counterparty)
				return
			if int(maxsize) < 0 or int(maxsize) > 21*10**14:
				debug("Got invalid maxsize: " + maxsize + " from " + counterparty)
				return
			if int(txfee) < 0:
				debug("Got invalid txfee: " + txfee +  " from " + counterparty)
				return
			if int(minsize) > int(maxsize):
				debug("Got minsize bigger than maxsize: " + minsize +
				      " - " + maxsize + " from " + counterparty)
				return
			self.db.execute('INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);',
				(counterparty, oid, ordertype, minsize, maxsize, txfee,
				 str(Decimal(cjfee)))) # any parseable Decimal is a valid cjfee
		except InvalidOperation:
			debug("Got invalid cjfee: " + cjfee + " from " + counterparty)
		except:
			debug("Error parsing order " + oid + " from " + counterparty)

	def on_order_cancel(self, counterparty, oid):
		self.db.execute("DELETE FROM orderbook WHERE counterparty=? AND oid=?;",
			(counterparty, oid))

	def on_welcome(self):
		self.msgchan.request_orderbook()

	def on_nick_leave(self, nick):
		self.db.execute('DELETE FROM orderbook WHERE counterparty=?;', (nick,))

	def on_disconnect(self):
		self.db.execute('DELETE FROM orderbook;')

#assume this only has one open cj tx at a time
class Taker(OrderbookWatch):
	def __init__(self, msgchan):
		OrderbookWatch.__init__(self, msgchan)
		msgchan.register_taker_callbacks(self.on_error, self.on_pubkey,
			self.on_ioauth, self.on_sig)
		msgchan.cjpeer = self
		self.cjtx = None
		self.maker_pks = {}
		#TODO have a list of maker's nick we're coinjoining with, so
		# that some other guy doesnt send you confusing stuff

	def get_crypto_box_from_nick(self, nick):
		if nick in self.cjtx.crypto_boxes:
			return self.cjtx.crypto_boxes[nick][1] #libsodium encryption object
		else:
			debug('something wrong, no crypto object, nick=' + nick + ', message will be dropped')
			return None

	def start_cj(self, wallet, cj_amount, orders, input_utxos, my_cj_addr, my_change_addr,
			total_txfee, finishcallback=None, choose_orders_recover=None, auth_addr=None):
		self.cjtx = CoinJoinTX(self.msgchan, wallet, self.db, cj_amount, orders,
			input_utxos, my_cj_addr, my_change_addr, total_txfee, finishcallback,
			choose_orders_recover, auth_addr)

	def on_error(self):
		pass #TODO implement

	def on_pubkey(self, nick, maker_pubkey):
		self.cjtx.start_encryption(nick, maker_pubkey)

	def on_ioauth(self, nick, utxo_list, cj_pub, change_addr, btc_sig):
		if not self.cjtx.auth_counterparty(nick, btc_sig, cj_pub):
			debug('Authenticated encryption with counterparty: ' + nick + \
			' not established. TODO: send rejection message')
			return
		with self.cjtx.timeout_thread_lock:
			self.cjtx.recv_txio(nick, utxo_list, cj_pub, change_addr)

	def on_sig(self, nick, sig):
		with self.cjtx.timeout_thread_lock:
			self.cjtx.add_signature(nick, sig)


#this stuff copied and slightly modified from pybitcointools
def donation_address(cjtx):
	reusable_donation_pubkey = '02be838257fbfddabaea03afbb9f16e8529dfe2de921260a5c46036d97b5eacf2a'
	global sign_k
	sign_k = os.urandom(32)
	debug("Using the following nonce value: "+binascii.hexlify(sign_k))
	c = btc.sha256(btc.multiply(binascii.hexlify(sign_k), reusable_donation_pubkey, True))
	sender_pubkey = btc.add_pubkeys([reusable_donation_pubkey, btc.privtopub(c+'01', True)], True)
	sender_address = btc.pubtoaddr(sender_pubkey, get_p2pk_vbyte())
	debug('sending coins to ' + sender_address)
	return sender_address


def sign_donation_tx(tx, i, priv):
	return btc.sign(tx, i, priv, usenonce=sign_k)
