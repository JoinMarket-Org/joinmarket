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


#thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class PaymentThread(threading.Thread):
	def __init__(self, taker):
		threading.Thread.__init__(self)
		self.daemon = True
		self.taker = taker

	def finishcallback(self, coinjointx):
		self.taker.msgchan.shutdown()

	def run(self):
		print 'waiting for all orders to certainly arrive'
		time.sleep(self.taker.waittime)

		crow = self.taker.db.execute('SELECT COUNT(DISTINCT counterparty) FROM orderbook;').fetchone()
		counterparty_count = crow['COUNT(DISTINCT counterparty)']
		if counterparty_count < self.taker.makercount:
			print 'not enough counterparties to fill order, ending'
			self.taker.msgchan.shutdown()
			return

		if self.taker.amount == 0:
			utxo_list = self.taker.wallet.get_utxos_by_mixdepth()[self.taker.mixdepth]
			total_value = sum([va['value'] for va in utxo_list.values()])
			if self.taker.choosecheapest: #choose cheapest
				chooseOrdersBy = cheapest_order_choose
			else: #choose randomly (weighted)
				chooseOrdersBy = weighted_order_choose
				
			orders, cjamount = choose_sweep_order(self.taker.db, total_value, self.taker.txfee, self.taker.makercount, chooseOrdersBy)
			if not self.taker.answeryes:
				if raw_input('send with these orders? (y/n):')[0] != 'y':
					self.finishcallback(None)
					return
			self.taker.start_cj(self.taker.wallet, cjamount, orders, utxo_list,
				self.taker.destaddr, None, self.taker.txfee, self.finishcallback)
		else:
			if self.taker.pickorders: #pick orders manually
				chooseOrdersBy = pick_order
			elif self.taker.choosecheapest: #choose cheapest
				chooseOrdersBy = cheapest_order_choose
			else: #choose randomly (weighted)
				chooseOrdersBy = weighted_order_choose
				
			orders, total_cj_fee = choose_order(self.taker.db, self.taker.amount, self.taker.makercount, chooseOrdersBy)
			if not orders:
				debug('ERROR not enough liquidity in the orderbook, exiting')
				return
			print 'chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(total_cj_fee)
			if not self.taker.answeryes:
				if raw_input('send with these orders? (y/n):')[0] != 'y':
					self.finishcallback(None)
					return
			total_amount = self.taker.amount + total_cj_fee + self.taker.txfee
			print 'total amount spent = ' + str(total_amount)

			utxos = self.taker.wallet.select_utxos(self.taker.mixdepth, total_amount)
			self.taker.start_cj(self.taker.wallet, self.taker.amount, orders, utxos, self.taker.destaddr,
				self.taker.wallet.get_change_addr(self.taker.mixdepth), self.taker.txfee,
				self.finishcallback)

class SendPayment(takermodule.Taker):
	def __init__(self, msgchan, wallet, destaddr, amount, makercount, txfee, waittime, mixdepth, answeryes, choosecheapest, pickorders):
		takermodule.Taker.__init__(self, msgchan)
		self.wallet = wallet
		self.destaddr = destaddr
		self.amount = amount
		self.makercount = makercount
		self.txfee = txfee
		self.waittime = waittime
		self.mixdepth = mixdepth
		self.answeryes = answeryes
		self.choosecheapest = choosecheapest
		self.pickorders = pickorders

	def on_welcome(self):
		takermodule.Taker.on_welcome(self)
		PaymentThread(self).start()

def main():
	parser = OptionParser(usage='usage: %prog [options] [wallet file / seed] [amount] [destaddr]',
		description='Sends a single payment from the zero mixing depth of your ' +
			'wallet to an given address using coinjoin and then switches off. ' +
			'Setting amount to zero will do a sweep, where the entire mix depth is emptied')
	parser.add_option('-f', '--txfee', action='store', type='int', dest='txfee',
		default=10000, help='miner fee contribution, in satoshis, default=10000')
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
	(options, args) = parser.parse_args()

	if len(args) < 3:
		parser.error('Needs a seed, amount and destination address')
		sys.exit(0)
	seed = args[0]
	amount = int(args[1])
	destaddr = args[2]
	
	load_program_config()
	addr_valid, errormsg = validate_address(destaddr)
	if not addr_valid:
		print 'ERROR: Address invalid. ' + errormsg
		return
	
	common.nickname = random_nick()
	debug('starting sendpayment')

	wallet = Wallet(seed, options.mixdepth + 1)
	common.bc_interface.sync_wallet(wallet)
	wallet.print_debug_wallet_info()

	irc = IRCMessageChannel(common.nickname)
	taker = SendPayment(irc, wallet, destaddr, amount, options.makercount, options.txfee,
		options.waittime, options.mixdepth, options.answeryes, options.choosecheapest, options.pickorders)
	try:
		debug('starting irc')
		irc.run()
	except:
		debug('CRASHING, DUMPING EVERYTHING')
		debug('wallet seed = ' + seed)
		debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
		debug_dump_object(taker)
		import traceback
		debug(traceback.format_exc())

if __name__ == "__main__":
	main()
	print('done')
