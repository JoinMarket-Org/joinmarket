#! /usr/bin/env python

from common import *
import irclib
import bitcoin as btc
import sys
import sqlite3
import base64

from socket import gethostname
nickname = 'cj-maker-' + btc.sha256(gethostname())[:6]
seed = sys.argv[1] #btc.sha256('dont use brainwallets except for holding testnet coins')

class CoinJoinOrder(object):
	def __init__(self, maker, nick, oid, amount):
		self.maker = maker
		self.oid = oid
		self.cj_amount = amount
		order = [o for o in orderlist if o['oid'] == oid][0]
		if amount <= order['minsize'] or amount >= order['maxsize']:
			maker.privmsg(nick, command_prefix + 'error amount out of range')
		#TODO logic for this error causing the order to be removed from list of open orders
		self.utxos, self.mixing_depth = oid_to_order(maker.wallet, oid, amount)
		self.ordertype = order['ordertype']
		self.txfee = order['txfee']
		self.cjfee = order['cjfee']
		self.cj_addr = maker.wallet.get_receive_addr(self.mixing_depth)
		self.change_addr = maker.wallet.get_change_addr(self.mixing_depth - 1)
		self.b64txparts = []
		#even if the order ends up never being furfilled, you dont want someone
		# pretending to fill all your orders to find out which addresses you use
		maker.privmsg(nick, command_prefix + 'myparts ' + ','.join(self.utxos) + ' ' +
			self.cj_addr + ' ' + self.change_addr)
	def recv_tx_part(self, b64txpart):
		self.b64txparts.append(b64txpart)
		#TODO this is a dos opportunity, flood someone with !txpart
		#repeatedly to fill up their memory

	def recv_tx(self, nick, b64txpart):
		self.b64txparts.append(b64txpart)
		tx = base64.b64decode(''.join(self.b64txparts)).encode('hex')
		txd = btc.deserialize(tx)
		goodtx, errmsg = self.verify_unsigned_tx(txd)
		if not goodtx:
			self.maker.privmsg(nick, command_prefix + 'error ' + errmsg)
			return False
		sigs = []
		for index, ins in enumerate(txd['ins']):
			utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			if utxo not in self.maker.wallet.unspent:
				continue
			addr = self.maker.wallet.unspent[utxo]['address']
			txs = btc.sign(tx, index, self.maker.wallet.get_key_from_addr(addr))
			sigs.append(base64.b64encode(btc.deserialize(txs)['ins'][index]['script'].decode('hex')))
		if len(sigs) == 0:
			print 'ERROR no private keys found'

		#TODO make this a function in irclib.py
		sigline = ''
		for sig in sigs:
			prev_sigline = sigline
			sigline = sigline + command_prefix + 'sig ' + sig
			if len(sigline) > MAX_PRIVMSG_LEN:
				self.maker.privmsg(nick, prev_sigline)
				sigline = command_prefix + 'sig ' + sig
		if len(sigline) > 0:
			self.maker.privmsg(nick, sigline)
		return True

	def verify_unsigned_tx(self, txd):
		tx_utxos = set([ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index']) for ins in txd['ins']])
		if not tx_utxos.issuperset(set(self.utxos)):
			return False, 'my utxos are not contained'
		my_total_in = 0
		for u in self.utxos:
			usvals = self.maker.wallet.unspent[u]
			my_total_in += int(usvals['value'])

		real_cjfee = calc_cj_fee(self.ordertype, self.cjfee, self.cj_amount)
		expected_change_value = (my_total_in - self.cj_amount
			- self.txfee + real_cjfee)
		debug('earned fee = ' + str(real_cjfee))
		debug('mycjaddr, mychange = ' + self.cj_addr + ', ' + self.change_addr)

		times_seen_cj_addr = 0
		times_seen_change_addr = 0
		for outs in txd['outs']:
			addr = btc.script_to_address(outs['script'], get_vbyte())
			if addr == self.cj_addr:
				times_seen_cj_addr += 1
				if outs['value'] != self.cj_amount:
					return False, 'Wrong cj_amount. I expect ' + str(cj_amount)
			if addr == self.change_addr:
				times_seen_change_addr += 1
				if outs['value'] != expected_change_value:
					return False, 'wrong change, i expect ' + str(expected_change_address)
		if times_seen_cj_addr != 1 or times_seen_change_addr != 1:
			return False, 'cj or change addr not in tx outputs exactly once'
		return True, None

#these two functions create_my_orders() and oid_to_uxto() define the
# sell-side pricing algorithm of this bot
def create_my_orders(wallet):

	#tells the highest value possible made by combining all utxos
	#fee is 0.2% of the cj amount
	total_value = 0
	for utxo, addrvalue in wallet.unspent.iteritems():
		total_value += addrvalue['value']

	order = {'oid': 0, 'ordertype': 'relorder', 'minsize': 0,
		'maxsize': total_value, 'txfee': 10000, 'cjfee': '0.002'}
	global orderlist
	orderlist = [order]
	'''
        db.execute("CREATE TABLE myorders(oid INTEGER, ordertype TEXT, "
		+ "minsize INTEGER, maxsize INTEGER, txfee INTEGER, cjfee TEXT);")
	#simple algorithm where each utxo we have becomes an order
	oid = 0
	for un in db.execute('SELECT * FROM unspent;').fetchall():
		db.execute('INSERT INTO myorders VALUES(?, ?, ?, ?, ?, ?);',
			(oid, 'absorder', 0, un['value'], 10000, '100000'))
		oid += 1
	'''

def oid_to_order(wallet, oid, amount):
	unspent = []
	for utxo, addrvalue in wallet.unspent.iteritems():
		unspent.append({'value': addrvalue['value'], 'utxo': utxo})
	inputs = btc.select(unspent, amount)
	#TODO this raises an exception if you dont have enough money, id rather it just returned None
	mixing_depth = 1
	return [i['utxo'] for i in inputs], mixing_depth
	'''
	unspent = db.execute('SELECT * FROM unspent WHERE value > ?;', (amount,)).fetchone()
	return [unspent['utxo']]
	'''


class Maker(irclib.IRCClient):
	def __init__(self, wallet):
		self.active_orders = {}
		self.wallet = wallet

	def privmsg_all_orders(self, target):
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
			
	def on_welcome(self):
		self.privmsg_all_orders(CHANNEL)

	def on_privmsg(self, nick, message):
		#debug("privmsg nick=%s message=%s" % (nick, message))
		if message[0] != command_prefix:
			return
		command_lines = message.split(command_prefix)
		for command_line in command_lines:
			chunks = command_line.split(" ")
			if chunks[0] == 'fill':
				oid = int(chunks[1])
				amount = int(chunks[2])
				self.active_orders[nick] = CoinJoinOrder(self, nick, oid, amount)
			elif chunks[0] == 'txpart':
				b64txpart = chunks[1] #TODO check nick appears in active_orders
				self.active_orders[nick].recv_tx_part(b64txpart)
			elif chunks[0] == 'tx':
				b64txpart = chunks[1]
				self.active_orders[nick].recv_tx(nick, b64txpart)


	#each order has an id for referencing to and looking up
	# using the same id again overwrites it, they'll be plenty of times when an order
	# has to be modified and its better to just have !order rather than !cancelorder then !order
	def on_pubmsg(self, nick, message):
		#debug("pubmsg nick=%s message=%s" % (nick, message))
		if message[0] == command_prefix:
			chunks = message[1:].split(" ")
			if chunks[0] == '%quit' or chunks[0] == '%makerquit':
				self.shutdown()
			elif chunks[0] == '%say': #% is a way to remind me its a testing cmd
				self.pubmsg(message[6:])
			elif chunks[0] == '%rm':
				self.pubmsg('!cancel ' + chunks[1])
			elif chunks[0] == 'orderbook':
				self.privmsg_all_orders(nick)
		
	def on_set_topic(self, newtopic):
		chunks = newtopic.split('|')
		try:
			print chunks[1].strip()
			print chunks[3].strip()
		except IndexError:
			pass	

def main():
	#TODO using sqlite3 to store my own orders is overkill, just
	# use a python data structure

	wallet = Wallet(seed)
	wallet.download_wallet_history()
	wallet.find_unspent_addresses()
	print 'downloaded wallet history'

	create_my_orders(wallet)
	maker = Maker(wallet)
	maker.run(HOST, PORT, nickname, CHANNEL)

if __name__ == "__main__":
	main()
	print('done')
