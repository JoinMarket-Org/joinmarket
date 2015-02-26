#! /usr/bin/env python

from common import *
import common
import taker as takermodule
from irc import IRCMessageChannel
import bitcoin as btc

from optparse import OptionParser
import threading

#thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class PaymentThread(threading.Thread):
	def __init__(self, taker):
		threading.Thread.__init__(self)
		self.daemon = True
		self.taker = taker

	def finishcallback(self):
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
			total_value = 0
			utxo_list = self.taker.wallet.get_utxo_list_by_mixdepth()[self.taker.mixdepth]
			for utxo in utxo_list:
				total_value += self.taker.wallet.unspent[utxo]['value']
			orders, cjamount = choose_sweep_order(self.taker.db, total_value, self.taker.txfee, self.taker.makercount)
			self.taker.cjtx = takermodule.CoinJoinTX(self.taker.msgchan, self.taker.wallet, self.taker.db, cjamount, orders, utxo_list,
				self.taker.destaddr, None, self.taker.txfee, self.finishcallback)
		else:
			orders, total_cj_fee = choose_order(self.taker.db, self.taker.amount, self.taker.makercount)
			print 'chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(total_cj_fee)
			total_amount = self.taker.amount + total_cj_fee + self.taker.txfee
			print 'total amount spent = ' + str(total_amount)

			utxos = self.taker.wallet.select_utxos(self.taker.mixdepth, total_amount)
			self.taker.cjtx = takermodule.CoinJoinTX(self.taker.msgchan, self.taker.wallet,
				self.taker.db, self.taker.amount, orders, utxos, self.taker.destaddr,
				self.taker.wallet.get_change_addr(self.taker.mixdepth), self.taker.txfee,
				self.finishcallback)

class SendPayment(takermodule.Taker):
	def __init__(self, msgchan, wallet, destaddr, amount, makercount, txfee, waittime, mixdepth):
		takermodule.Taker.__init__(self, msgchan)
		self.wallet = wallet
		self.destaddr = destaddr
		self.amount = amount
		self.makercount = makercount
		self.txfee = txfee
		self.waittime = waittime
		self.mixdepth = mixdepth

	def on_welcome(self):
		takermodule.Taker.on_welcome(self)
		PaymentThread(self).start()

def main():
	parser = OptionParser(usage='usage: %prog [options] [seed] [amount] [destaddr]',
		description='Sends a single payment from the zero mixing depth of your ' +
			'wallet to an given address using coinjoin and then switches off. ' +
			'Setting amount to zero will do a sweep, where the entire mix depth is emptied')
	parser.add_option('-f', '--txfee', action='store', type='int', dest='txfee',
		default=10000, help='miner fee contribution, in satoshis, default=10000')
	parser.add_option('-w', '--wait-time', action='store', type='float', dest='waittime',
		help='wait time in seconds to allow orders to arrive, default=5', default=5)
	parser.add_option('-N', '--makercount', action='store', type='int', dest='makercount',
		help='how many makers to coinjoin with, default=2', default=2)
	parser.add_option('-m', '--mixdepth', action='store', type='int', dest='mixdepth',
		help='mixing depth to spend from, default=0', default=0)
	(options, args) = parser.parse_args()

	if len(args) < 3:
		parser.error('Needs a seed, amount and destination address')
		sys.exit(0)
	seed = args[0]
	amount = int(args[1])
	destaddr = args[2]

	import binascii, os
	common.nickname = 'payer-' +binascii.hexlify(os.urandom(4))

	wallet = Wallet(seed, options.mixdepth + 1)
	wallet.sync_wallet()

	irc = IRCMessageChannel(common.nickname)
	taker = SendPayment(irc, wallet, destaddr, amount, options.makercount, options.txfee,
		options.waittime, options.mixdepth)
	try:
		debug('starting irc')
		irc.run()
	except:
		debug('CRASHING, DUMPING EVERYTHING')
		debug('wallet seed = ' + seed)
		debug_dump_object(wallet, ['addr_cache'])
		debug_dump_object(taker)
		import traceback
		debug(traceback.format_exc())

if __name__ == "__main__":
	main()
	print('done')
