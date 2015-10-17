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

def check_high_fee(total_fee_pc):
	WARNING_THRESHOLD = 0.02 # 2%
	if total_fee_pc > WARNING_THRESHOLD:
		print '\n'.join(['='* 60]*3)
		print 'WARNING   ' * 6
		print '\n'.join(['='* 60]*1)
		print 'OFFERED COINJOIN FEE IS UNUSUALLY HIGH. DOUBLE/TRIPLE CHECK.'
		print '\n'.join(['='* 60]*1)
		print 'WARNING   ' * 6
		print '\n'.join(['='* 60]*3)

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
		if counterparty_count < self.taker.makercount:
			print 'not enough counterparties to fill order, ending'
			self.taker.msgchan.shutdown()
			return

		utxos = None
		orders = None
		cjamount = 0
		change_addr = None
		choose_orders_recover = None
		if self.taker.amount == 0:
			utxos = self.taker.wallet.get_utxos_by_mixdepth()[self.taker.mixdepth]
			total_value = sum([va['value'] for va in utxos.values()])
			orders, cjamount = choose_sweep_orders(self.taker.db, total_value,
				self.taker.txfee, self.taker.makercount,
				self.taker.chooseOrdersFunc, self.ignored_makers)
			if not self.taker.answeryes:
				total_cj_fee = total_value - cjamount - self.taker.txfee
				debug('total cj fee = ' + str(total_cj_fee))
				total_fee_pc = 1.0*total_cj_fee / cjamount
				debug('total coinjoin fee = ' + str(float('%.3g' % (100.0 * total_fee_pc))) + '%')
				check_high_fee(total_fee_pc)
				if raw_input('send with these orders? (y/n):')[0] != 'y':
					self.taker.msgchan.shutdown()
					return
		else:
			orders, total_cj_fee = self.sendpayment_choose_orders(self.taker.amount,
				self.taker.makercount)
			if not orders:
				debug('ERROR not enough liquidity in the orderbook, exiting')
				return
			total_amount = self.taker.amount + total_cj_fee + self.taker.txfee
			print 'total amount spent = ' + str(total_amount)
			utxos = self.taker.wallet.select_utxos(self.taker.mixdepth, total_amount)
			cjamount = self.taker.amount
			change_addr = self.taker.wallet.get_change_addr(self.taker.mixdepth)
			choose_orders_recover = self.sendpayment_choose_orders

		self.taker.start_cj(self.taker.wallet, cjamount, orders, utxos,
			self.taker.destaddr, change_addr, self.taker.txfee,
			self.finishcallback, choose_orders_recover)

	def finishcallback(self, coinjointx):
		if coinjointx.all_responded:
			coinjointx.self_sign_and_push()
			debug('created fully signed tx, ending')
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
		if not self.taker.answeryes:
			if len(self.ignored_makers) > 0:
				noun = 'total'
			else:
				noun = 'additional'
			total_fee_pc = 1.0*total_cj_fee / cj_amount
			debug(noun + ' coinjoin fee = ' + str(float('%.3g' % (100.0 * total_fee_pc))) + '%')
			check_high_fee(total_fee_pc)
			if raw_input('send with these orders? (y/n):')[0] != 'y':
				debug('ending')
				self.taker.msgchan.shutdown()
				return None, -1
		return orders, total_cj_fee

	def run(self):
		print 'waiting for all orders to certainly arrive'
		time.sleep(self.taker.waittime)
		self.create_tx()


class SendPayment(takermodule.Taker):
	def __init__(self, msgchan, wallet, destaddr, amount, makercount, txfee, waittime, mixdepth, answeryes, chooseOrdersFunc):
		takermodule.Taker.__init__(self, msgchan)
		self.wallet = wallet
		self.destaddr = destaddr
		self.amount = amount
		self.makercount = makercount
		self.txfee = txfee
		self.waittime = waittime
		self.mixdepth = mixdepth
		self.answeryes = answeryes
		self.chooseOrdersFunc = chooseOrdersFunc

	def on_welcome(self):
		takermodule.Taker.on_welcome(self)
		PaymentThread(self).start()

def main():
	parser = OptionParser(usage='usage: %prog [options] [wallet file / fromaccount] [amount] [destaddr]',
		description='Sends a single payment from a given mixing depth of your ' +
			'wallet to an given address using coinjoin and then switches off. Also sends from bitcoinqt. ' +
			'Setting amount to zero will do a sweep, where the entire mix depth is emptied')
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
	parser.add_option('-m', '--mixdepth', action='store', type='int', dest='mixdepth',
		help='mixing depth to spend from, default=0', default=0)
	parser.add_option('--yes', action='store_true', dest='answeryes', default=False,
		help='answer yes to everything')
	parser.add_option('--rpcwallet', action='store_true', dest='userpcwallet', default=False,
		help='Use the Bitcoin Core wallet through json rpc, instead of the internal joinmarket ' +
			'wallet. Requires blockchain_source=json-rpc')
	(options, args) = parser.parse_args()

	if len(args) < 3:
		parser.error('Needs a wallet, amount and destination address')
		sys.exit(0)
	wallet_name = args[0]
	amount = int(args[1])
	destaddr = args[2]
	
	load_program_config()
	addr_valid, errormsg = validate_address(destaddr)
	if not addr_valid:
		print 'ERROR: Address invalid. ' + errormsg
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

	if not options.userpcwallet:
		wallet = Wallet(wallet_name, options.mixdepth + 1)
	else:
		wallet = BitcoinCoreWallet(fromaccount = wallet_name)
	common.bc_interface.sync_wallet(wallet)

	irc = IRCMessageChannel(common.nickname)
	taker = SendPayment(irc, wallet, destaddr, amount, options.makercount, options.txfee,
		options.waittime, options.mixdepth, options.answeryes, chooseOrdersFunc)
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

