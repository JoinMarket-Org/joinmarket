
import datetime, threading, binascii, sys, os, copy
data_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(data_dir, 'lib'))

import taker as takermodule
import common
from common import *
from irc import IRCMessageChannel, random_nick

from optparse import OptionParser
from pprint import pprint

def lower_bounded_int(thelist, lowerbound):
	return [int(l) if int(l) >= lowerbound else lowerbound for l in thelist]

def generate_tumbler_tx(destaddrs, options):
	#sends the coins up through a few mixing depths
	#send to the destination addresses from different mixing depths

	#simple algo, move coins completely from one mixing depth to the next
	# until you get to the end, then send to destaddrs

	#txcounts for going completely from one mixdepth to the next
	# follows a normal distribution
	txcounts = rand_norm_array(options.txcountparams[0],
		options.txcountparams[1], options.mixdepthcount)
	txcounts = lower_bounded_int(txcounts, options.mintxcount)
	tx_list = []
	for m, txcount in enumerate(txcounts):
		#assume that the sizes of outputs will follow a power law
		amount_fractions = rand_pow_array(options.amountpower, txcount)
		amount_fractions = [1.0 - x for x in amount_fractions]
		amount_fractions = [x/sum(amount_fractions) for x in amount_fractions]
		#transaction times are uncorrelated
		#time between events in a poisson process followed exp
		waits = rand_exp_array(options.timelambda, txcount)
		#number of makers to use follows a normal distribution
		makercounts = rand_norm_array(options.makercountrange[0], options.makercountrange[1], txcount)
		makercounts = lower_bounded_int(makercounts, options.minmakercount)
		if m == options.mixdepthcount - options.addrcount and options.donateamount:
			tx_list.append({'amount_fraction': 0, 'wait': round(waits[0], 2),
				'srcmixdepth': m + options.mixdepthsrc, 'makercount': makercounts[0],
				'destination': 'internal'})
		for amount_fraction, wait, makercount in zip(amount_fractions, waits, makercounts):
			tx = {'amount_fraction': amount_fraction, 'wait': round(wait, 2),
				'srcmixdepth': m + options.mixdepthsrc, 'makercount': makercount, 'destination': 'internal'}
			tx_list.append(tx)

	addrask = options.addrcount - len(destaddrs)
	external_dest_addrs = ['addrask']*addrask + destaddrs
	for mix_offset in range(options.addrcount):
		srcmix = options.mixdepthsrc + options.mixdepthcount - mix_offset - 1
		for tx in reversed(tx_list):
			if tx['srcmixdepth'] == srcmix:
				tx['destination'] = external_dest_addrs[mix_offset]
				break
		if mix_offset == 0:
			#setting last mixdepth to send all to dest
			tx_list_remove = []
			for tx in tx_list:
				if tx['srcmixdepth'] == srcmix:
					if tx['destination'] == 'internal':
						tx_list_remove.append(tx)
					else:
						tx['amount_fraction'] = 1.0
			[tx_list.remove(t) for t in tx_list_remove]
	return tx_list

#thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class TumblerThread(threading.Thread):
	def __init__(self, taker):
		threading.Thread.__init__(self)
		self.daemon = True
		self.taker = taker
		self.ignored_makers = []
		self.sweeping = False

	def unconfirm_callback(self, txd, txid):
		debug('that was %d tx out of %d' % (self.current_tx+1, len(self.taker.tx_list)))

	def confirm_callback(self, txd, txid, confirmations):
		self.taker.wallet.add_new_utxos(txd, txid)
		self.lockcond.acquire()
		self.lockcond.notify()
		self.lockcond.release()

	def finishcallback(self, coinjointx):
		if coinjointx.all_responded:
			common.bc_interface.add_tx_notify(coinjointx.latest_tx,
				self.unconfirm_callback, self.confirm_callback, coinjointx.my_cj_addr)
			self.taker.wallet.remove_old_utxos(coinjointx.latest_tx)
			coinjointx.self_sign_and_push()
		else:
			self.ignored_makers += coinjointx.nonrespondants
			debug('recreating the tx, ignored_makers=' + str(self.ignored_makers))
			self.create_tx()

	def tumbler_choose_orders(self, cj_amount, makercount, nonrespondants=[], active_nicks=[]):
		self.ignored_makers += nonrespondants
		while True:
			orders, total_cj_fee = choose_orders(self.taker.db, cj_amount,
				makercount, weighted_order_choose, self.ignored_makers + active_nicks)
			abs_cj_fee = 1.0*total_cj_fee / makercount
			rel_cj_fee = abs_cj_fee / cj_amount
			debug('rel/abs average fee = ' + str(rel_cj_fee) + ' / ' + str(abs_cj_fee))

			if rel_cj_fee > self.taker.options.maxcjfee[0] and abs_cj_fee > self.taker.options.maxcjfee[1]:
				debug('cj fee higher than maxcjfee, waiting ' + str(self.taker.options.liquiditywait) + ' seconds')
				time.sleep(self.taker.options.liquiditywait)
				continue
			if orders == None:
				debug('waiting for liquidity ' + str(self.taker.options.liquiditywait) + 'secs, hopefully more orders should come in')
				time.sleep(self.taker.options.liquiditywait)
				continue
			break
		debug('chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(total_cj_fee))
		return orders, total_cj_fee

	def create_tx(self):
		utxos = None
		orders = None
		cj_amount = 0
		change_addr = None
		choose_orders_recover = None
		if self.sweep:
			debug('sweeping')
			utxos = self.taker.wallet.get_utxos_by_mixdepth()[self.tx['srcmixdepth']]
			total_value = sum([addrval['value'] for addrval in utxos.values()])
			while True:
				orders, cj_amount = choose_sweep_orders(self.taker.db, total_value,
					self.taker.options.txfee, self.tx['makercount'], weighted_order_choose,
					self.ignored_makers)
				if orders == None:
					debug('waiting for liquidity ' + str(self.taker.options.liquiditywait) + 'secs, hopefully more orders should come in')
					time.sleep(self.taker.options.liquiditywait)
					continue
				abs_cj_fee = 1.0*(total_value - cj_amount) / self.tx['makercount']
				rel_cj_fee = abs_cj_fee / cj_amount
				debug('rel/abs average fee = ' + str(rel_cj_fee) + ' / ' + str(abs_cj_fee))
				if rel_cj_fee > self.taker.options.maxcjfee[0] and abs_cj_fee > self.taker.options.maxcjfee[1]:
					debug('cj fee higher than maxcjfee, waiting ' + str(self.taker.options.liquiditywait) + ' seconds')
					time.sleep(self.taker.options.liquiditywait)
					continue
				break
		else:
			if self.tx['amount_fraction'] == 0:
				cj_amount = int(self.balance * self.taker.options.donateamount / 100.0)
				self.destaddr = None
			else:
				cj_amount = int(self.tx['amount_fraction'] * self.balance)
			if cj_amount < self.taker.options.mincjamount:
				debug('cj amount too low, bringing up')
				cj_amount = self.taker.options.mincjamount
			change_addr = self.taker.wallet.get_change_addr(self.tx['srcmixdepth'])
			debug('coinjoining ' + str(cj_amount) + ' satoshi')
			orders, total_cj_fee = self.tumbler_choose_orders(cj_amount, self.tx['makercount'])
			total_amount = cj_amount + total_cj_fee + self.taker.options.txfee
			debug('total amount spent = ' + str(total_amount))
			utxos = self.taker.wallet.select_utxos(self.tx['srcmixdepth'], total_amount)
			choose_orders_recover = self.tumbler_choose_orders

		self.taker.start_cj(self.taker.wallet, cj_amount, orders, utxos,
			self.destaddr, change_addr, self.taker.options.txfee,
			self.finishcallback, choose_orders_recover)

	def init_tx(self, tx, balance, sweep):
		destaddr = None
		if tx['destination'] == 'internal':
			destaddr = self.taker.wallet.get_receive_addr(tx['srcmixdepth'] + 1)
		elif tx['destination'] == 'addrask':
			common.debug_silence = True
			while True:
				destaddr = raw_input('insert new address: ')
				addr_valid, errormsg = validate_address(destaddr)
				if addr_valid:
					break
				print 'Address ' + destaddr + ' invalid. ' + errormsg + ' try again'
			common.debug_silence = False
		else:
			destaddr = tx['destination']
		self.sweep = sweep
		self.balance = balance
		self.tx = tx
		self.destaddr = destaddr
		self.create_tx()
		self.lockcond.acquire()
		self.lockcond.wait()
		self.lockcond.release()
		debug('tx confirmed, waiting for ' + str(tx['wait']) + ' minutes')
		time.sleep(tx['wait'] * 60)
		debug('woken')

	def run(self):
		debug('waiting for all orders to certainly arrive')
		time.sleep(self.taker.options.waittime)

		sqlorders = self.taker.db.execute('SELECT cjfee, ordertype FROM orderbook;').fetchall()
		orders = [o['cjfee'] for o in sqlorders if o['ordertype'] == 'relorder']
		orders = sorted(orders)
		if len(orders) == 0:
			debug('There are no orders at all in the orderbook! Is the bot connecting to the right server?')
			return
		relorder_fee = float(orders[0])
		debug('relorder fee = ' + str(relorder_fee))
		maker_count = sum([tx['makercount'] for tx in self.taker.tx_list])
		debug('uses ' + str(maker_count) + ' makers, at ' + str(relorder_fee*100) + '% per maker, estimated total cost '
			+ str(round((1 - (1 - relorder_fee)**maker_count) * 100, 3)) + '%')
		debug('starting')
		self.lockcond = threading.Condition()

		self.balance_by_mixdepth = {}
		for i, tx in enumerate(self.taker.tx_list):
			if tx['srcmixdepth'] not in self.balance_by_mixdepth:
				self.balance_by_mixdepth[tx['srcmixdepth']] = self.taker.wallet.get_balance_by_mixdepth()[tx['srcmixdepth']]
			sweep = True
			for later_tx in self.taker.tx_list[i + 1:]:
				if later_tx['srcmixdepth'] == tx['srcmixdepth']:
					sweep = False
			self.current_tx = i
			self.init_tx(tx, self.balance_by_mixdepth[tx['srcmixdepth']], sweep)

		debug('total finished')
		self.taker.msgchan.shutdown()

		'''
		crow = self.taker.db.execute('SELECT COUNT(DISTINCT counterparty) FROM orderbook;').fetchone()
		counterparty_count = crow['COUNT(DISTINCT counterparty)']
		if counterparty_count < self.taker.makercount:
			print 'not enough counterparties to fill order, ending'
			self.taker.msgchan.shutdown()
			return
		'''


class Tumbler(takermodule.Taker):
	def __init__(self, msgchan, wallet, tx_list, options):
		takermodule.Taker.__init__(self, msgchan)
		self.wallet = wallet
		self.tx_list = tx_list
		self.options = options
		self.tumbler_thread = None

	def on_welcome(self):
		takermodule.Taker.on_welcome(self)
		if not self.tumbler_thread:
			self.tumbler_thread = TumblerThread(self)
			self.tumbler_thread.start()

def main():
	parser = OptionParser(usage='usage: %prog [options] [wallet file] [destaddr(s)...]',
		description='Sends bitcoins to many different addresses using coinjoin in'
			' an attempt to break the link between them. Sending to multiple '
			' addresses is highly recommended for privacy. This tumbler can'
			' be configured to ask for more address mid-run, giving the user'
			' a chance to click `Generate New Deposit Address` on whatever service'
			' they are using.')
	parser.add_option('-m', '--mixdepthsource', type='int', dest='mixdepthsrc',
		help='Mixing depth to spend from. Useful if a previous tumbler run prematurely ended with '
		+ 'coins being left in higher mixing levels, this option can be used to resume without needing'
		+ ' to send to another address. default=0', default=0)
	parser.add_option('-f', '--txfee', type='int', dest='txfee',
		default=10000, help='total miner fee in satoshis, default=10000')
	parser.add_option('-a', '--addrcount', type='int', dest='addrcount',
		default=3, help='How many destination addresses in total should be used. If not enough are given'
			' as command line arguments, the script will ask for more. This parameter is required'
			' to stop amount correlation. default=3')
	parser.add_option('-x', '--maxcjfee', type='float', dest='maxcjfee', nargs=2,
		default=(0.01, 10000), help='maximum coinjoin fee and bitcoin value the tumbler is '
		'willing to pay to a single market maker. Both values need to be exceeded, so if '
		'the fee is 30% but only 500satoshi is paid the tx will go ahead. default=0.01, 10000 (1%, 10000satoshi)')
	parser.add_option('-N', '--makercountrange', type='float', nargs=2, action='store', dest='makercountrange',
		help='Input the mean and spread of number of makers to use. e.g. 3 1.5 will be a normal distribution '
		'with mean 3 and standard deveation 1.5 inclusive, default=3 1.5', default=(3, 1.5))
	parser.add_option('--minmakercount', type='int', dest='minmakercount', default=2,
		help='The minimum maker count in a transaction, random values below this are clamped at this number. default=2')
	parser.add_option('-M', '--mixdepthcount', type='int', dest='mixdepthcount',
		help='How many mixing depths to mix through', default=4)
	parser.add_option('-c', '--txcountparams', type='float', nargs=2, dest='txcountparams', default=(4, 1),
		help='The number of transactions to take coins from one mixing depth to the next, it is'
		' randomly chosen following a normal distribution. Should be similar to --addrask. '
		'This option controls the parameters of the normal distribution curve. (mean, standard deviation). default=(4, 1)')
	parser.add_option('--mintxcount', type='int', dest='mintxcount', default=1,
		help='The minimum transaction count per mixing level, default=1')
	parser.add_option('--donateamount', type='float', dest='donateamount', default=1.5,
		help='percent of funds to donate to joinmarket development, or zero to opt out')
	parser.add_option('--amountpower', type='float', dest='amountpower', default=100.0,
		help='The output amounts follow a power law distribution, this is the power, default=100.0')
	parser.add_option('-l', '--timelambda', type='float', dest='timelambda', default=30,
		help='Average the number of minutes to wait between transactions. Randomly chosen '
		' following an exponential distribution, which describes the time between uncorrelated'
		' events. default=30')
	parser.add_option('-w', '--wait-time', action='store', type='float', dest='waittime',
		help='wait time in seconds to allow orders to arrive, default=20', default=20)
	parser.add_option('-s', '--mincjamount', type='int', dest='mincjamount', default=100000,
		help='minimum coinjoin amount in transaction in satoshi, default 100k')
	parser.add_option('-q', '--liquiditywait', type='int', dest='liquiditywait', default=60,
		help='amount of seconds to wait after failing to choose suitable orders before trying again, default 60')
	(options, args) = parser.parse_args()

	if len(args) < 1:
		parser.error('Needs a wallet file')
		sys.exit(0)
	wallet_file = args[0]
	destaddrs = args[1:]
	print destaddrs
	
	common.load_program_config()
	for addr in destaddrs:
		addr_valid, errormsg = validate_address(addr)
		if not addr_valid:
			print 'ERROR: Address ' + addr + ' invalid. ' + errormsg
			return

	if len(destaddrs) > options.addrcount:
		options.addrcount = len(destaddrs)
	if options.addrcount+1 > options.mixdepthcount:
		print 'not enough mixing depths to pay to all destination addresses, increasing mixdepthcount'
		options.mixdepthcount = options.addrcount+1
	if options.donateamount > 10.0:
		#fat finger probably, or misunderstanding
		options.donateamount = 0.9

	print str(options)
	tx_list = generate_tumbler_tx(destaddrs, options)
	if not tx_list:
		return

	tx_list2 = copy.deepcopy(tx_list)
	tx_dict = {}
	for tx in tx_list2:
		srcmixdepth = tx['srcmixdepth']
		tx.pop('srcmixdepth')
		if srcmixdepth not in tx_dict:
			tx_dict[srcmixdepth] = []
		tx_dict[srcmixdepth].append(tx)
	dbg_tx_list = []
	for srcmixdepth, txlist in tx_dict.iteritems():
		dbg_tx_list.append({'srcmixdepth': srcmixdepth, 'tx': txlist})
	debug('tumbler transaction list')
	pprint(dbg_tx_list)

	total_wait = sum([tx['wait'] for tx in tx_list])
	print 'creates ' + str(len(tx_list)) + ' transactions in total'
	print 'waits in total for ' + str(len(tx_list)) + ' blocks and ' + str(total_wait) + ' minutes'
	total_block_and_wait = len(tx_list)*10 + total_wait
	print('estimated time taken ' + str(total_block_and_wait) +
		' minutes or ' + str(round(total_block_and_wait/60.0, 2)) + ' hours')
	if options.addrcount <= 1:
		print '='*50
		print 'WARNING: You are only using one destination address'
		print 'this is very bad for privacy'
		print '='*50

	ret = raw_input('tumble with these tx? (y/n):')
	if ret[0] != 'y':
		return

	#NOTE: possibly out of date documentation
	#a couple of modes
	#im-running-from-the-nsa, takes about 80 hours, costs a lot
	#python tumbler.py -a 10 -N 10 5 -c 10 5 -l 50 -M 10 wallet_file 1xxx
	#
	#quick and cheap, takes about 90 minutes
	#python tumbler.py -N 2 1 -c 3 0.001 -l 10 -M 3 -a 1 wallet_file 1xxx
	#
	#default, good enough for most, takes about 5 hours
	#python tumbler.py wallet_file 1xxx
	#
	#for quick testing
	#python tumbler.py -N 2 1 -c 3 0.001 -l 0.1 -M 3 -a 0 wallet_file 1xxx 1yyy
	wallet = Wallet(wallet_file, max_mix_depth = options.mixdepthsrc + options.mixdepthcount)
	common.bc_interface.sync_wallet(wallet)

	common.nickname = random_nick()
	debug('starting tumbler')
	irc = IRCMessageChannel(common.nickname)
	tumbler = Tumbler(irc, wallet, tx_list, options)
	try:
		debug('connecting to irc')
		irc.run()
	except:
		debug('CRASHING, DUMPING EVERYTHING')
		debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
		debug_dump_object(tumbler)
		debug_dump_object(tumbler.cjtx)
		import traceback
		debug(traceback.format_exc())


if __name__ == "__main__":
	main()
	print('done')

