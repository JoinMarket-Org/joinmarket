#! /usr/bin/env python

from common import *
import irclib
import bitcoin as btc
import base64, pprint, threading
import enc_wrapper

class CoinJoinOrder(object):
	def __init__(self, maker, nick, oid, amount, taker_pk):
		self.maker = maker
		self.oid = oid
		self.cj_amount = amount
		#the btc pubkey of the utxo that the taker plans to use as input
		self.taker_pk = taker_pk
		#create DH keypair on the fly for this Order object
		self.kp = enc_wrapper.init_keypair()
		#the encryption channel crypto box for this Order object
		self.crypto_box = enc_wrapper.as_init_encryption(self.kp, enc_wrapper.init_pubkey(self.taker_pk))
		
		order_s = [o for o in maker.orderlist if o['oid'] == oid]
		if len(order_s) == 0:
			self.maker.send_error(nick, 'oid not found')
		order = order_s[0]
		if amount < order['minsize'] or amount > order['maxsize']:
			self.maker.send_error(nick, 'amount out of range')
		self.utxos, self.cj_addr, self.change_addr = maker.oid_to_order(oid, amount)
		self.ordertype = order['ordertype']
		self.txfee = order['txfee']
		self.cjfee = order['cjfee']
		debug('new cjorder nick=%s oid=%d amount=%d' % (nick, oid, amount))
		#always a new address even if the order ends up never being
		# furfilled, you dont want someone pretending to fill all your
		# orders to find out which addresses you use
		self.send_priv(nick, '!pubkey', self.kp.hex_pk(), False)
	
	def send_priv(self, nick, cmd, msg, enc=False):
		if enc:
			self.maker.privmsg(nick, cmd + ' ' + enc_wrapper.encrypt_encode(msg, self.crypto_box))
		else:
			self.maker.privmsg(nick, cmd + ' ' + msg)
		
	def auth_counterparty(self,nick,i_utxo_pubkey,btc_sig):
		#TODO: add check that the pubkey's address is part of the order.
		self.i_utxo_pubkey = i_utxo_pubkey
		
		if not btc.ecdsa_verify(self.taker_pk,btc_sig,self.i_utxo_pubkey):
			print 'signature didnt match pubkey and message'
			return False
		#authorisation of taker passed
		#send auth request to taker
		#TODO the next 2 lines are a little inefficient.
		btc_key = self.maker.wallet.get_key_from_addr(self.cj_addr)
		btc_pub = btc.privtopub(btc_key)
		btc_sig = btc.ecdsa_sign(self.kp.hex_pk(),btc_key)
		authmsg = str(','.join(self.utxos)) + ' ' + \
	                btc_pub + ' ' + self.change_addr + ' ' + btc_sig
		self.send_priv(nick, '!auth', authmsg, True)		
		return True
	
	def recv_tx(self, nick, b64tx):
		try:
			txhex = base64.b64decode(b64tx).encode('hex')
		except TypeError as e:
			self.maker.send_error(nick, 'bad base64 tx. ' + repr(e))
		try:
			self.tx = btc.deserialize(txhex)
		except IndexError as e:
			self.maker.send_error(nick, 'malformed txhex. ' + repr(e))
		debug('obtained tx\n' + pprint.pformat(self.tx))
		goodtx, errmsg = self.verify_unsigned_tx(self.tx)
		if not goodtx:
			debug('not a good tx, reason=' + errmsg)
			self.maker.send_error(nick, errmsg)
		#TODO: the above 3 errors should be encrypted, but it's a bit messy.
		debug('goodtx')
		sigs = []
		for index, ins in enumerate(self.tx['ins']):
			utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			if utxo not in self.maker.wallet.unspent:
				continue
			addr = self.maker.wallet.unspent[utxo]['address']
			txs = btc.sign(txhex, index, self.maker.wallet.get_key_from_addr(addr))
			sigs.append(base64.b64encode(btc.deserialize(txs)['ins'][index]['script'].decode('hex')))
		#len(sigs) > 0 guarenteed since i did verify_unsigned_tx()

		add_addr_notify(self.change_addr, self.unconfirm_callback, self.confirm_callback)
		debug('sending sigs ' + str(sigs))
		for s in sigs:
			self.send_priv(nick, '!sig', s, True)
		self.maker.active_orders[nick] = None

	def unconfirm_callback(self, balance):
		self.wallet_unspent_lock.acquire()
		try:
			removed_utxos = self.maker.wallet.remove_old_utxos(self.tx)
		finally:
			self.wallet_unspent_lock.release()
		debug('saw tx on network, removed_utxos=\n' + pprint.pformat(removed_utxos))
		to_cancel, to_announce = self.maker.on_tx_unconfirmed(self, balance, removed_utxos)
		self.maker.modify_orders(to_cancel, to_announce)

	def confirm_callback(self, confirmations, txid, balance):
		self.wallet_unspent_lock.acquire()
		try:
			added_utxos = self.maker.wallet.add_new_utxos(self.tx, txid)
		finally:
			self.wallet_unspent_lock.release()
		debug('tx in a block, added_utxos=\n' + pprint.pformat(added_utxos))
		to_cancel, to_announce = self.maker.on_tx_confirmed(self,
			confirmations, txid, balance, added_utxos)
		self.maker.modify_orders(to_cancel, to_announce)

	def verify_unsigned_tx(self, txd):
		tx_utxo_set = set([ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index']) for ins in txd['ins']])
		my_uxto_set = set(self.utxos)
		wallet_uxtos = set(self.wallet.unspent)
		if not tx_utxo_set.issuperset(my_utxo_set):
			return False, 'my utxos are not contained'
		if not wallet.utxos.issuperset(my_utxo_set):
			return False, 'my utxos already spent'
		my_total_in = 0
		for u in self.utxos:
			usvals = self.maker.wallet.unspent[u]
			my_total_in += usvals['value']

		real_cjfee = calc_cj_fee(self.ordertype, self.cjfee, self.cj_amount)
		expected_change_value = (my_total_in - self.cj_amount
			- self.txfee + real_cjfee)
		debug('earned = ' + str(real_cjfee - self.txfee))
		debug('mycjaddr, mychange = ' + self.cj_addr + ', ' + self.change_addr)

		times_seen_cj_addr = 0
		times_seen_change_addr = 0
		for outs in txd['outs']:
			addr = btc.script_to_address(outs['script'], get_addr_vbyte())
			if addr == self.cj_addr:
				times_seen_cj_addr += 1
				if outs['value'] != self.cj_amount:
					return False, 'Wrong cj_amount. I expect ' + str(cj_amount)
			if addr == self.change_addr:
				times_seen_change_addr += 1
				if outs['value'] != expected_change_value:
					return False, 'wrong change, i expect ' + str(expected_change_value)
		if times_seen_cj_addr != 1 or times_seen_change_addr != 1:
			return False, 'cj or change addr not in tx outputs exactly once'
		return True, None

class CJMakerOrderError(StandardError):
	pass

class Maker(irclib.IRCClient):
	def __init__(self, wallet):
		self.active_orders = {}
		self.wallet = wallet
		self.nextoid = -1
		self.orderlist = self.create_my_orders()
		self.wallet_unspent_lock = threading.Lock()

	def privmsg_all_orders(self, target, orderlist=None):
		if orderlist == None:
			orderlist = self.orderlist
		order_keys = ['ordertype', 'oid', 'minsize', 'maxsize', 'txfee', 'cjfee']
		orderline = ''
		for order in orderlist:
			elem_list = [str(order[k]) for k in order_keys]
			orderline += (command_prefix + ' '.join(elem_list))
			if len(orderline) > MAX_PRIVMSG_LEN:
				self.privmsg(target, orderline)
				orderline = ''
		if len(orderline) > 0:
			self.privmsg(target, orderline)
		
	def send_error(self, nick, errmsg):
		debug('error<%s> : %s' % (nick, errmsg))
		self.privmsg(nick, command_prefix + 'error ' + errmsg)
		raise CJMakerOrderError()

	def on_welcome(self):
		self.privmsg_all_orders(CHANNEL)
		
	def on_privmsg(self, nick, message):
		if message[0] != command_prefix:
			return
		command_lines = message.split(command_prefix)
		for command_line in command_lines:
			if len(command_line) == 0:
				continue
			chunks = command_line.split(" ")
			try:
				if len(chunks) < 2:
					self.send_error(nick, 'Not enough arguments')
					encmsg = enc_wrapper.decode_decrypt(chunks[1],self.active_orders[nick].crypto_box)
					encrypted_chunks = encmsg.split(" ")
						i_utxo_pubkey = encrypted_chunks[0]
						btc_sig = encrypted_chunks[1]
				if chunks[0] == 'fill':
					if nick in self.active_orders and self.active_orders[nick] != None:
						self.active_orders[nick] = None
						debug('had a partially filled order but starting over now')
					try:
						oid = int(chunks[1])
						amount = int(chunks[2])
						taker_pk = chunks[3]
					except (ValueError, IndexError) as e:
						self.send_error(nick, str(e))
					self.wallet_unspent_lock.acquire()
					try:
						self.active_orders[nick] = CoinJoinOrder(self, nick, oid, amount, taker_pk)
					finally:
						self.wallet_unspent_lock.release()
				elif chunks[0] == 'auth':
					if nick not in self.active_orders or self.active_orders[nick] == None:
						self.send_error(nick, 'No open order from this nick')
					cjorder = self.active_orders[nick]
					try:
						i_utxo_pubkey = chunks[1]
						btc_sig = chunks[2]
					except (ValueError,IndexError) as e:
						self.send_error(nick, str(e))
					self.active_orders[nick].auth_counterparty(nick, i_utxo_pubkey, btc_sig)
					
				elif chunks[0] == 'tx':
					if nick not in self.active_orders or self.active_orders[nick] == None:
						self.send_error(nick, 'No open order from this nick')
					encb64tx = chunks[1]
					self.wallet_unspent_lock.acquire()
					try:
						self.active_orders[nick].recv_tx(nick, enc_wrapper.decode_decrypt(encb64tx,self.active_orders[nick].crypto_box))
					finally:
						self.wallet_unspent_lock.release()
			except CJMakerOrderError:
				self.active_orders[nick] = None
				continue

	#each order has an id for referencing to and looking up
	# using the same id again overwrites it, they'll be plenty of times when an order
	# has to be modified and its better to just have !order rather than !cancelorder then !order
	def on_pubmsg(self, nick, message):
		if message[0] == command_prefix:
			chunks = message[1:].split(" ")
			if chunks[0] == 'orderbook':
				self.privmsg_all_orders(nick)
		
	def on_set_topic(self, newtopic):
		chunks = newtopic.split('|')
		if len(chunks) > 1:
			print '=' * 60
			print 'MESSAGE FROM BELCHER!'
			print chunks[1].strip()
			print '=' * 60

	def on_leave(self, nick):
		self.active_orders[nick] = None

	def modify_orders(self, to_cancel, to_announce):
		debug('modifying orders. to_cancel=' + str(to_cancel) + '\nto_announce=' + str(to_announce))
		for oid in to_cancel:
			order = [o for o in self.orderlist if o['oid'] == oid][0]
			self.orderlist.remove(order)
		if len(to_cancel) > 0:
			clines = [command_prefix + 'cancel ' + str(oid) for oid in to_cancel]
			self.pubmsg(''.join(clines))
		if len(to_announce) > 0:
			self.privmsg_all_orders(CHANNEL, to_announce)
			for ann in to_announce:
				oldorder_s = [order for order in self.orderlist if order['oid'] == ann['oid']]
				if len(oldorder_s) > 0:
					self.orderlist.remove(oldorder_s[0])
			self.orderlist += to_announce

	#these functions
	# create_my_orders()
	# oid_to_uxto()
	# on_tx_unconfirmed()
	# on_tx_confirmed()
	#define the sell-side pricing algorithm of this bot
	#still might be a bad way of doing things, we'll see
	def create_my_orders(self):

		'''
		#tells the highest value possible made by combining all utxos
		#fee is 0.2% of the cj amount
		total_value = 0
		for utxo, addrvalue in self.wallet.unspent.iteritems():
			total_value += addrvalue['value']

		order = {'oid': 0, 'ordertype': 'relorder', 'minsize': 0,
			'maxsize': total_value, 'txfee': 10000, 'cjfee': '0.002'}
		return [order]
		'''

		#each utxo is a single absolute-fee order
		orderlist = []
		for utxo, addrvalue in self.wallet.unspent.iteritems():
			order = {'oid': self.get_next_oid(), 'ordertype': 'absorder', 'minsize': 0,
				'maxsize': addrvalue['value'], 'txfee': 10000, 'cjfee': 100000,
				'utxo': utxo, 'mixdepth': self.wallet.addr_cache[addrvalue['address']][0]}
			orderlist.append(order)
		#yes you can add keys there that are never used by the rest of the Maker code
		# so im adding utxo and mixdepth here
		return orderlist
		

	#has to return a list of utxos and mixing depth the cj address will be in
	# the change address will be in mixing_depth-1
	def oid_to_order(self, oid, amount):
		'''
		unspent = []
		for utxo, addrvalue in self.wallet.unspent.iteritems():
			unspent.append({'value': addrvalue['value'], 'utxo': utxo})
		inputs = btc.select(unspent, amount)
		#TODO this raises an exception if you dont have enough money, id rather it just returned None
		mixing_depth = 1
		return [i['utxo'] for i in inputs], mixing_depth
		'''

		order = [o for o in self.orderlist if o['oid'] == oid][0]
		cj_addr = self.wallet.get_receive_addr(order['mixdepth'] + 1)
		change_addr = self.wallet.get_change_addr(order['mixdepth'])
		return [order['utxo']], cj_addr, change_addr
		
	def get_next_oid(self):
		self.nextoid += 1
		return self.nextoid

	#gets called when the tx is seen on the network
	#must return which orders to cancel or recreate
	def on_tx_unconfirmed(self, cjorder, balance, removed_utxos):
		return ([cjorder.oid], [])

	#gets called when the tx is included in a block
	#must return which orders to cancel or recreate
	# and i have to think about how that will work for both
	# the blockchain explorer api method and the bitcoid walletnotify
	def on_tx_confirmed(self, cjorder, confirmations, txid, balance, added_utxos):
		to_announce = []
		for i, out in enumerate(cjorder.tx['outs']):
			addr = btc.script_to_address(out['script'], get_addr_vbyte())
			if addr == cjorder.change_addr:
				neworder = {'oid': self.get_next_oid(), 'ordertype': 'absorder', 'minsize': 0,
					'maxsize': out['value'], 'txfee': 10000, 'cjfee': 100000,
					'utxo': txid + ':' + str(i)}
				to_announce.append(neworder)
			if addr == cjorder.cj_addr:
				neworder = {'oid': self.get_next_oid(), 'ordertype': 'absorder', 'minsize': 0,
					'maxsize': out['value'], 'txfee': 10000, 'cjfee': 100000,
					'utxo': txid + ':' + str(i)}
				to_announce.append(neworder)
		return ([], to_announce)


def main():
	from socket import gethostname
	nickname = 'cj-maker-' + btc.sha256(gethostname())[:6]
	import sys
	seed = sys.argv[1] #btc.sha256('dont use brainwallets except for holding testnet coins')

	wallet = Wallet(seed,max_mix_depth=5)
	wallet.sync_wallet()

	maker = Maker(wallet)
	print 'connecting to irc'
	try:
		maker.run(HOST, PORT, nickname, CHANNEL)
	finally:
		debug('CRASHING, DUMPING EVERYTHING')
		debug('wallet seed = ' + seed)
		debug_dump_object(wallet, ['addr_cache'])
		debug_dump_object(maker)

if __name__ == "__main__":
	main()
	print('done')
