#! /usr/bin/env python

from optparse import OptionParser
import threading, pprint, sys, os
data_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(data_dir, 'lib'))

from common import *
import common
import taker as takermodule
from irc import IRCMessageChannel, random_nick
import bitcoin as btc
import sendpayment

#thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class PaymentThread(threading.Thread):
	def __init__(self, taker):
		threading.Thread.__init__(self)
		self.daemon = True
		self.taker = taker
		self.ignored_makers = []

	def create_tx(self):
		crow = self.taker.db.execute('SELECT COUNT(DISTINCT counterparty) FROM orderbook;').fetchone()
		counterparty_count = crow['COUNT(DISTINCT counterparty)']
		counterparty_count -= len(self.ignored_makers)
		if counterparty_count < self.taker.options.makercount:
			print 'not enough counterparties to fill order, ending'
			self.taker.msgchan.shutdown()
			return

		utxos = self.taker.utxo_data
		orders = None
		cjamount = 0
		change_addr = None
		choose_orders_recover = None
		if self.taker.cjamount == 0:
			total_value = sum([va['value'] for va in utxos.values()])
			orders, cjamount = choose_sweep_orders(self.taker.db, total_value,
				self.taker.options.txfee, self.taker.options.makercount,
				self.taker.chooseOrdersFunc, self.ignored_makers)
			if not self.taker.options.answeryes:
				total_cj_fee = total_value - cjamount - self.taker.options.txfee
				debug('total cj fee = ' + str(total_cj_fee))
				total_fee_pc = 1.0*total_cj_fee / cjamount
				debug('total coinjoin fee = ' + str(float('%.3g' % (100.0 * total_fee_pc))) + '%')
				sendpayment.check_high_fee(total_fee_pc)
				if raw_input('send with these orders? (y/n):')[0] != 'y':
					self.finishcallback(None)
					return
		else:
			orders, total_cj_fee = self.sendpayment_choose_orders(
				self.taker.cjamount, self.taker.options.makercount)
			if not orders:
				debug('ERROR not enough liquidity in the orderbook, exiting')
				return
			total_amount = self.taker.cjamount + total_cj_fee + self.taker.options.txfee
			print 'total amount spent = ' + str(total_amount)
			cjamount = self.taker.cjamount
			change_addr = self.taker.changeaddr
			choose_orders_recover = self.sendpayment_choose_orders

		auth_addr = self.taker.utxo_data[self.taker.auth_utxo]['address']
		self.taker.start_cj(self.taker.wallet, cjamount, orders, utxos,
			self.taker.destaddr, change_addr, self.taker.options.txfee,
			self.finishcallback, choose_orders_recover, auth_addr)

	def finishcallback(self, coinjointx):
		if coinjointx.all_responded:
			#now sign it ourselves
			tx = btc.serialize(coinjointx.latest_tx)
			for index, ins in enumerate(coinjointx.latest_tx['ins']):
				utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
				if utxo != self.taker.auth_utxo:
					continue
				addr = coinjointx.input_utxos[utxo]['address']
				tx = btc.sign(tx, index, coinjointx.wallet.get_key_from_addr(addr))
			print 'unsigned tx = \n\n' + tx + '\n'
			debug('created unsigned tx, ending')
			self.taker.msgchan.shutdown()
			return
		self.ignored_makers += coinjointx.nonrespondants
		debug('recreating the tx, ignored_makers=' + str(self.ignored_makers))
		self.create_tx()

	def sendpayment_choose_orders(self, cj_amount, makercount, nonrespondants=[], active_nicks=[]):
		self.ignored_makers += nonrespondants
		orders, total_cj_fee = choose_orders(self.taker.db, cj_amount, makercount,
			self.taker.chooseOrdersFunc, self.ignored_makers + active_nicks)
		if not orders:
			return None, 0
		print 'chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(total_cj_fee)
		if not self.taker.options.answeryes:
			if len(self.ignored_makers) > 0:
				noun = 'total'
			else:
				noun = 'additional'
			total_fee_pc = 1.0*total_cj_fee / cj_amount
			debug(noun + ' coinjoin fee = ' + str(float('%.3g' % (100.0 * total_fee_pc))) + '%')
			sendpayment.check_high_fee(total_fee_pc)
			if raw_input('send with these orders? (y/n):')[0] != 'y':
				debug('ending')
				self.taker.msgchan.shutdown()
				return None, -1
		return orders, total_cj_fee

	def run(self):
		print 'waiting for all orders to certainly arrive'
		time.sleep(self.taker.options.waittime)
		self.create_tx()

class CreateUnsignedTx(takermodule.Taker):
	def __init__(self, msgchan, wallet, auth_utxo, cjamount, destaddr, changeaddr,
			utxo_data, options, chooseOrdersFunc):
		takermodule.Taker.__init__(self, msgchan)
		self.wallet = wallet
		self.auth_utxo = auth_utxo
		self.cjamount = cjamount
		self.destaddr = destaddr
		self.changeaddr = changeaddr
		self.utxo_data = utxo_data
		self.options = options
		self.chooseOrdersFunc = chooseOrdersFunc

	def on_welcome(self):
		takermodule.Taker.on_welcome(self)
		PaymentThread(self).start()

def main():
	parser = OptionParser(usage='usage: %prog [options] [auth utxo] [cjamount] [cjaddr] [changeaddr] [utxos..]',
		description='Creates an unsigned coinjoin transaction. Outputs a partially signed transaction ' +
			'hex string. The user must sign their inputs independently and broadcast them. The JoinMarket' +
			' protocol requires the taker to have a single p2pk UTXO input to use to authenticate the ' +
			' encrypted messages. For this reason you must pass auth utxo and the corresponding private key')
	#for cjamount=0 do a sweep, and ignore change address
	parser.add_option('-f', '--txfee', action='store', type='int', dest='txfee',
		default=10000, help='total miner fee in satoshis, default=10000')
	parser.add_option('-w', '--wait-time', action='store', type='float', dest='waittime',
		help='wait time in seconds to allow orders to arrive, default=5', default=5)
	parser.add_option('-N', '--makercount', action='store', type='int', dest='makercount',
		help='how many makers to coinjoin with, default=2', default=2)
	parser.add_option('-C','--choose-cheapest', action='store_true', dest='choosecheapest', default=False,
		help='override weightened offers picking and choose cheapest')
	parser.add_option('-P','--pick-orders', action='store_true', dest='pickorders', default=False,
		help='manually pick which orders to take. doesn\'t work while sweeping.')
	parser.add_option('--yes', action='store_true', dest='answeryes', default=False,
		help='answer yes to everything')
	#TODO implement
	#parser.add_option('-n', '--no-network', action='store_true', dest='nonetwork', default=False,
	#	help='dont query the blockchain interface, instead user must supply value of UTXOs on ' +
	#		' command line in the format txid:output/value-in-satoshi')
	(options, args) = parser.parse_args()

	if len(args) < 3:
		parser.error('Needs a wallet, amount and destination address')
		sys.exit(0)
	auth_utxo = args[0]
	cjamount = int(args[1])
	destaddr = args[2]
	changeaddr = args[3]
	cold_utxos = args[4:]

	common.load_program_config()
	addr_valid1, errormsg1 = validate_address(destaddr)
	#if amount = 0 dont bother checking changeaddr so user can write any junk
	if cjamount != 0:
		addr_valid2, errormsg2 = validate_address(changeaddr)
	else:
		addr_valid2 = True
	if not addr_valid1 or not addr_valid2:
		if not addr_valid1:
			print 'ERROR: Address invalid. ' + errormsg1
		else:
			print 'ERROR: Address invalid. ' + errormsg2
		return

	all_utxos = [auth_utxo] + cold_utxos
	query_result = common.bc_interface.query_utxo_set(all_utxos)
	if None in query_result:
		print query_result
	utxo_data = {}
	for utxo, data in zip(all_utxos, query_result):
		utxo_data[utxo] = {'address': data['address'], 'value': data['value']}
	auth_privkey = raw_input('input private key for ' + utxo_data[auth_utxo]['address'] + ' :')
	if utxo_data[auth_utxo]['address'] != btc.privtoaddr(auth_privkey, magicbyte=common.get_p2pk_vbyte()):
		print 'ERROR: privkey does not match auth utxo'
		return

	chooseOrdersFunc = None
	if options.pickorders and amount != 0: #cant use for sweeping
		chooseOrdersFunc = pick_order
	elif options.choosecheapest:
		chooseOrdersFunc = cheapest_order_choose
	else: #choose randomly (weighted)
		chooseOrdersFunc = weighted_order_choose
	
	common.nickname = random_nick()
	debug('starting sendpayment')

	class UnsignedTXWallet(common.AbstractWallet):
		def get_key_from_addr(self, addr):
			debug('getting privkey of ' + addr)
			if btc.privtoaddr(auth_privkey, magicbyte=common.get_p2pk_vbyte()) != addr:
				raise RuntimeError('privkey doesnt match given address')
			return auth_privkey

	wallet = UnsignedTXWallet()
	irc = IRCMessageChannel(common.nickname)
	taker = CreateUnsignedTx(irc, wallet, auth_utxo, cjamount, destaddr,
		changeaddr, utxo_data, options, chooseOrdersFunc)
	try:
		debug('starting irc')
		irc.run()
	except:
		debug('CRASHING, DUMPING EVERYTHING')
		debug_dump_object(wallet, ['addr_cache', 'keys', 'wallet_name', 'seed'])
		debug_dump_object(taker)
		import traceback
		debug(traceback.format_exc())

if __name__ == "__main__":
	main()
	print('done')

