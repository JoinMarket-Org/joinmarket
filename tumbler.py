
from optparse import OptionParser
import datetime
import numpy as np
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
	txcounts = np.random.normal(options.txcountparams[0],
		options.txcountparams[1], options.mixdepthcount)
	txcounts = lower_bounded_int(txcounts, 1)
	tx_list = []
	for m, txcount in enumerate(txcounts):
		#assume that the sizes of outputs will follow a power law
		amount_ratios = 1.0 - np.random.power(options.amountpower, txcount)
		amount_ratios /= sum(amount_ratios)
		#transaction times are uncorrelated and therefore follow poisson
		blockheight_waits = np.random.poisson(options.timelambda, txcount)
		#number of makers to use follows a normal distribution
		makercounts = np.random.normal(options.makercountrange[0], options.makercountrange[1], txcount)
		makercounts = lower_bounded_int(makercounts, 2)
		for amount_ratio, blockheight_wait, makercount in zip(amount_ratios, blockheight_waits, makercounts):
			tx = {'amount_ratio': amount_ratio, 'blockheight_wait': blockheight_wait,
				'srcmixdepth': m + options.mixdepthsrc, 'makercount': makercount}
			tx_list.append(tx)
	pprint(tx_list)
	block_count = sum([tx['blockheight_wait'] for tx in tx_list])
	print 'requires ' + str(block_count) + ' blocks'
	print('estimated time taken ' + str(block_count*10) +
		' minutes or ' + str(block_count/6.0) + ' hours')
	maker_count = sum([tx['makercount'] for tx in tx_list])
	relorder_fee = 0.001
	print('uses ' + str(maker_count) + ' makers, at ' + str(relorder_fee*100) + '% per maker, estimated total cost '
		+ str(round((1 - (1 - relorder_fee)**maker_count) * 100, 3)) + '%')

def main():
	parser = OptionParser(usage='usage: %prog [options] [seed] [tumble-file / destaddr...]',
		description='Sends bitcoins to many different addresses using coinjoin in'
			' an attempt to break the link between them. Sending to multiple '
			' addresses is highly recommended for privacy. This tumbler can'
			' be configured to ask for more address mid-run, giving the user'
			' a chance to click `Generate New Deposit Address` on whatever service'
			' they are using.')
	parser.add_option('-m', '--mixdepthsource', type='int', dest='mixdepthsrc',
		help='mixing depth to spend from, default=0', default=0)
	parser.add_option('-f', '--txfee', type='int', dest='txfee',
		default=10000, help='miner fee contribution, in satoshis, default=10000')
	parser.add_option('-a', '--addrask', type='int', dest='addrask',
		default=2, help='How many more addresses to ask for in the terminal. Should '
			'be similar to --txcountparams. default=2')
	parser.add_option('-N', '--makercountrange', type='float', nargs=2, action='store',
		dest='makercountrange',
		help='Input the range of makers to use. e.g. 3-5 will random use between '
		'3 and 5 makers inclusive, default=3 4', default=(3, 1))
	parser.add_option('-M', '--mixdepthcount', type='int', dest='mixdepthcount',
		help='how many mixing depths to mix through', default=3)
	parser.add_option('-c', '--txcountparams', type='float', nargs=2, dest='txcountparams', default=(5, 1),
		help='The number of transactions to take coins from one mixing depth to the next, it is'
		' randomly chosen following a normal distribution. Should be similar to --addrask. '
		'This option controlled the parameters of that normal curve. (mean, standard deviation). default=(3, 1)')
	parser.add_option('--amountpower', type='float', dest='amountpower', default=100.0,
		help='the output amounts follow a power law distribution, this is the power, default=100.0')
	parser.add_option('-l', '--timelambda', type='float', dest='timelambda', default=2,
		help='the number of blocks to wait between transactions is randomly chosen '
		' following a poisson distribution. This parameter is the lambda of that '
		' distribution. default=2 blocks')

	parser.add_option('-w', '--wait-time', action='store', type='float', dest='waittime',
		help='wait time in seconds to allow orders to arrive, default=5', default=5)
	(options, args) = parser.parse_args()

	if len(args) < 2:
		parser.error('Needs a seed and destination addresses')
		sys.exit(0)
	seed = args[0]
	destaddrs = args[1:]

	if len(destaddrs) + options.addrask <= 1:
		print '='*50
		print 'WARNING: You are only using one destination address'
		print 'this is almost useless for privacy'
		print '='*50

	print 'seed=' + seed
	print 'destaddrs=' + str(destaddrs)
	print str(options)
	generate_tumbler_tx(destaddrs, options)

	#a couple of overarching modes
	#im-running-from-the-nsa, takes about 80 hours, costs a lot
	#python tumbler.py -a 10 -N 10 5 -c 10 5 -l 5 -M 10 seed 1xxx
	#
	#quick and cheap, takes about 90 minutes
	#python tumbler.py -N 2 1 -c 3 0.001 -l 2 -M 2 seed 1xxx 1yyy
	#
	#default, good enough for most, takes about 5 hours
	#python tumbler.py seed 1

if __name__ == "__main__":
	main()
	print('done')
