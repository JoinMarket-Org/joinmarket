#! /usr/bin/env python

from common import *
import common
import enc_wrapper
import bitcoin as btc

import sqlite3, base64, threading, time, random, pprint

class CoinJoinTX(object):
	#soon the taker argument will be removed and just be replaced by wallet or some other interface
	def __init__(self, msgchan, wallet, db, cj_amount, orders, input_utxos, my_cj_addr,
		my_change_addr, my_txfee, finishcallback=None):
		'''
		if my_change is None then there wont be a change address
		thats used if you want to entirely coinjoin one utxo with no change left over
		orders is the orders you want to fill {'counterpartynick': oid, 'cp2': oid2}
		'''
		debug('starting cj to ' + my_cj_addr + ' with change at ' + str(my_change_addr))
		self.msgchan = msgchan
		self.wallet = wallet
		self.db = db
		self.cj_amount = cj_amount
		self.active_orders = dict(orders)
		self.nonrespondants = list(orders.keys())
		self.input_utxos = input_utxos
		self.utxos = {None: input_utxos.keys()} #None means they belong to me
		self.finishcallback = finishcallback
		self.my_txfee = my_txfee
		self.outputs = [{'address': my_cj_addr, 'value': self.cj_amount}]
		self.my_cj_addr = my_cj_addr
		self.my_change_addr = my_change_addr
		self.cjfee_total = 0
		self.latest_tx = None
		#create DH keypair on the fly for this Tx object
		self.kp = enc_wrapper.init_keypair()
		self.crypto_boxes = {}
		self.msgchan.fill_orders(orders, cj_amount, self.kp.hex_pk())

	def start_encryption(self, nick, maker_pk):
		if nick not in self.active_orders.keys():
			raise Exception("Counterparty not part of this transaction.")
		self.crypto_boxes[nick] = [maker_pk, enc_wrapper.as_init_encryption(\
		                        self.kp, enc_wrapper.init_pubkey(maker_pk))]
		#send authorisation request
		my_btc_addr = self.input_utxos.itervalues().next()['address']
		my_btc_priv = self.wallet.get_key_from_addr(my_btc_addr)
		my_btc_pub = btc.privtopub(my_btc_priv)
		my_btc_sig = btc.ecdsa_sign(self.kp.hex_pk(), my_btc_priv)
		self.msgchan.send_auth(nick, my_btc_pub, my_btc_sig)
	
	def auth_counterparty(self, nick, btc_sig, cj_pub):
		'''Validate the counterpartys claim to own the btc
		address/pubkey that will be used for coinjoining 
		with an ecdsa verification.'''
		if not btc.ecdsa_verify(self.crypto_boxes[nick][0], btc_sig, cj_pub):
			print 'signature didnt match pubkey and message'
			return False
		return True
	
	def recv_txio(self, nick, utxo_list, cj_pub, change_addr):	
		if nick not in self.nonrespondants:
			debug('nick(' + nick + ') not in nonrespondants ' + str(self.nonrespondants))
			return
		self.utxos[nick] = utxo_list
		order = self.db.execute('SELECT ordertype, txfee, cjfee FROM '
			'orderbook WHERE oid=? AND counterparty=?',
			(self.active_orders[nick], nick)).fetchone()
		utxo_data = common.bc_interface.query_utxo_set(self.utxos[nick])
		if None in utxo_data:
			common.debug('ERROR outputs unconfirmed or already spent. utxo_data='
				+ pprint.pformat(utxo_data))
			raise RuntimeError('killing taker, TODO handle this error')
		total_input = sum([d['value'] for d in utxo_data])
		real_cjfee = calc_cj_fee(order['ordertype'], order['cjfee'], self.cj_amount)
		self.outputs.append({'address': change_addr, 'value':
			total_input - self.cj_amount - order['txfee'] + real_cjfee})
		print 'fee breakdown for %s totalin=%d cjamount=%d txfee=%d realcjfee=%d' % (nick,
			total_input, self.cj_amount, order['txfee'], real_cjfee)
		cj_addr = btc.pubtoaddr(cj_pub, get_addr_vbyte())
		self.outputs.append({'address': cj_addr, 'value': self.cj_amount})
		self.cjfee_total += real_cjfee
		self.nonrespondants.remove(nick)
		if len(self.nonrespondants) > 0:
			debug('nonrespondants = ' + str(self.nonrespondants))
			return
		debug('got all parts, enough to build a tx cjfeetotal=' + str(self.cjfee_total))

		my_total_in = 0
		for u, va in self.input_utxos.iteritems():
			my_total_in += va['value']
		#my_total_in = sum([va['value'] for u, va in self.input_utxos.iteritems()])

		my_change_value = my_total_in - self.cj_amount - self.cjfee_total - self.my_txfee
		print 'fee breakdown for me totalin=%d txfee=%d cjfee_total=%d => changevalue=%d' % (my_total_in, 
			self.my_txfee, self.cjfee_total, my_change_value)
		if self.my_change_addr == None:
			if my_change_value != 0 and abs(my_change_value) != 1:
				#seems you wont always get exactly zero because of integer rounding
				# so 1 satoshi extra or fewer being spent as miner fees is acceptable
				print 'WARNING CHANGE NOT BEING USED\nCHANGEVALUE = ' + str(my_change_value)
		else:
			self.outputs.append({'address': self.my_change_addr, 'value': my_change_value})
		utxo_tx = [dict([('output', u)]) for u in sum(self.utxos.values(), [])]
		random.shuffle(self.outputs)
		tx = btc.mktx(utxo_tx, self.outputs)	
		debug('obtained tx\n' + pprint.pformat(btc.deserialize(tx)))
		self.msgchan.send_tx(self.active_orders.keys(), tx)

		#now sign it ourselves here
		for index, ins in enumerate(btc.deserialize(tx)['ins']):
			utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			if utxo not in self.input_utxos.keys():
				continue
			addr = self.input_utxos[utxo]['address']
			tx = btc.sign(tx, index, self.wallet.get_key_from_addr(addr))
		self.latest_tx = btc.deserialize(tx)

	def add_signature(self, sigb64):
		sig = base64.b64decode(sigb64).encode('hex')
		inserted_sig = False
		tx = btc.serialize(self.latest_tx)
		for index, ins in enumerate(self.latest_tx['ins']):
			if ins['script'] != '':
				continue
			utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			utxo_data = common.bc_interface.query_utxo_set(utxo)
			if utxo_data[0] == None:
				continue
			sig_good = btc.verify_tx_input(tx, index, utxo_data[0]['script'], *btc.deserialize_script(sig))
			if sig_good:
				debug('found good sig at index=%d' % (index))
				ins['script'] = sig
				inserted_sig = True
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
		debug('the entire tx is signed, ready to pushtx()')
		txhex = btc.serialize(self.latest_tx)
		debug('\n' + txhex)

		#TODO send to a random maker or push myself
		#self.msgchan.push_tx(self.active_orders.keys()[0], txhex)	
		self.txid = common.bc_interface.pushtx(txhex)
		debug('pushed tx ' + str(self.txid))
		if self.txid == None:
			debug('unable to pushtx')
		if self.finishcallback != None:
			self.finishcallback(self)

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
		self.db.execute("DELETE FROM orderbook WHERE counterparty=? AND oid=?;",
			(counterparty, oid))
		self.db.execute('INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);',
			(counterparty, oid, ordertype, minsize, maxsize, txfee, cjfee))

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
		#maybe a start_cj_tx() method is needed

	def get_crypto_box_from_nick(self, nick):
		return self.cjtx.crypto_boxes[nick][1]

	def start_cj(self, wallet, cj_amount, orders, input_utxos, my_cj_addr, my_change_addr,
			my_txfee, finishcallback=None):
		self.cjtx = CoinJoinTX(self.msgchan, wallet, self.db, cj_amount, orders,
			input_utxos, my_cj_addr, my_change_addr, my_txfee, finishcallback)

	def on_error(self):
		pass #TODO implement

	def on_pubkey(self, nick, maker_pubkey):
		self.cjtx.start_encryption(nick, maker_pubkey)

	def on_ioauth(self, nick, utxo_list, cj_pub, change_addr, btc_sig):
		if not self.cjtx.auth_counterparty(nick, btc_sig, cj_pub):
			print 'Authenticated encryption with counterparty: ' + nick + \
			' not established. TODO: send rejection message'
			return				
		self.cjtx.recv_txio(nick, utxo_list, cj_pub, change_addr)

	def on_sig(self, nick, sig):
		self.cjtx.add_signature(sig)

if __name__ == "__main__":
	main()
	print('done')
