#! /usr/bin/env python

import time, os, binascii, sys, datetime
import pprint
data_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(data_dir, 'lib'))

from maker import *
from irc import IRCMessageChannel, random_nick
import bitcoin as btc
import common, blockchaininterface

from socket import gethostname
from decimal import Decimal
import random


#CONFIGURATION
mix_levels = 5 #Careful! Only change this if you setup your wallet as such.
nickname = random_nick()
nickserv_password = ''

#min_output_size = 15000 # only create change greater than this amount
min_output_size = random.randrange(15000, 300000) #random
#min_output_size = common.DUST_THRESHOLD # 546 satoshis

#num_offers = 8 # number of offers to autogenerate
num_offers = random.randrange(6, 11) #random
#num_offers = mix_levels

#txfee = 3000 # miner fee contribution in satoshis
txfee = random.randrange(500, 5000) #random

# minimum cjfee you require for your offers
min_cjfee = random.randrange(txfee, txfee * 5) #random
#min_cjfee = int(1.5 * txfee) # 50% net revenue
#min_cjfee = 0 #no profit required

#spread types
#fibonacci- will gradually increase at the rate of the fibonacci sequence
#evenly- will be evenly spaced 
#random- random amounts between the high and the low
#custom- use _custom to set it directly
#bymixdepth- (for offers), make offer amounts equal to mixdepths
#note, when using bymixdepth, set 'num_offers = mix_levels' above

# percent fees for mix levels.
cjfee_spread = 'fibonacci' #fibonacci, evenly, random, custom
cjfee_low  = random.uniform(0.0001, 0.001) 
cjfee_high = random.uniform(0.01, 0.015) 
#custom_cjfees = [0.011, 0.012, 0.013, 0.014, 0.015] #from smallest to largest

# min and max offer sizes
offer_spread = 'fibonacci' #fibonacci, evenly, random, bymixdepth, custom
min_offer_size = None  #when None, min_output_size will be used
max_offer_size = None  #when None, size of largest mix depth will be used
#max_offer_size = random.randrange(2500000000, 3000000000)
#custom_offers_levels = [1, 1.5, 10, 100] #in bitcoins

# You can overwrite the above autogenerate options 
custom_offers = None  #comment this line if using below
"""
custom_offers = [
    {'ordertype': 'absorder', 'oid': 0, 'minsize': 0,     'maxsize': 100000000,   'cjfee': 0,      'txfee': 2000}, 
    {'ordertype': 'absorder', 'oid': 1, 'minsize': 0,     'maxsize': 1500000000,  'cjfee': 300000, 'txfee': 2000}, 
    {'ordertype': 'relorder', 'oid': 2, 'minsize': 15000, 'maxsize': 100000000,   'cjfee': 0.0001, 'txfee': 2000},
    {'ordertype': 'relorder', 'oid': 3, 'minsize': 15000, 'maxsize': 1000000000,  'cjfee': 0.0002, 'txfee': 2000},
    {'ordertype': 'relorder', 'oid': 4, 'minsize': 15000, 'maxsize': 2500000000,  'cjfee': 0.0003, 'txfee': 2000},
    ]
"""

#END CONFIGURATION


def fib(n):
    a, b = 0, 1
    for i in range(n):
        a, b = b, a + b
    return a

def fib_seq(low, high, num):
    fib_div = fib(num + 1)
    total = high - low
    fib_sec = total / fib_div
    x = []
    for y in range(2, num + 1):
        x.append(low + (fib_sec * fib(y)))
    return x

def drange(start, stop, step):
    r = start
    while r < stop:
            yield r
            r += step


class YieldGenerator(Maker):
	statement_file = os.path.join('logs', 'yigen-statement.csv')

	def __init__(self, msgchan, wallet):
		Maker.__init__(self, msgchan, wallet)
		self.msgchan.register_channel_callbacks(self.on_welcome, self.on_set_topic,
			None, None, self.on_nick_leave, None)
		self.tx_unconfirm_timestamp = {}

	def log_statement(self, data):
		if common.get_network() == 'testnet':
			return

		data = [str(d) for d in data]
		self.income_statement = open(self.statement_file, 'a')
		self.income_statement.write(','.join(data) + '\n')
		self.income_statement.close()

	def on_welcome(self):
		Maker.on_welcome(self)
		if not os.path.isfile(self.statement_file):
			self.log_statement(['timestamp', 'cj amount/satoshi', 'my input count',
				'my input value/satoshi', 'cjfee/satoshi', 'earned/satoshi',
				'confirm time/min', 'notes'])

		timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
		self.log_statement([timestamp, '', '', '', '', '', '', 'Connected'])

	def create_my_orders(self):
                if custom_offers:
                    debug('custom_offers = \n' + '\n'.join([str(o) for o in custom_offers]))
                    #make sure custom offers dont create a negative net
		    for offer in custom_offers:
			if offer['ordertype'] == 'absorder':
			    profit = offer['cjfee']
                            needed = 'make txfee be less then the cjfee'
			elif offer['ordertype'] == 'relorder':
			    profit = calc_cj_fee(offer['ordertype'], offer['cjfee'], offer['minsize']) 
                            if float(offer['cjfee']) > 0:
                                needed = 'set minsize to ' + str(int(int(offer['txfee'] / float(offer['cjfee']))))
			if int(offer['txfee']) > profit:
                            print("ALERT: negative yield")
			    print '-> ' + str(offer)
                            print needed
			    sys.exit(0) #if you really wanted to, you could comment out this line.     
                    return custom_offers

		mix_balance = self.wallet.get_balance_by_mixdepth()
		debug('mix_balance = ' + str(mix_balance))
		filtered_mix_balance = sorted(list(mix_balance.iteritems()), key=lambda a: a[1]) #sort by size

                offer_low = max(min_offer_size, min_output_size)
                if max_offer_size:
                    offer_high = min(max_offer_size, filtered_mix_balance[-1][1] - min_output_size)
                else:
                    offer_high = filtered_mix_balance[-1][1] - min_output_size
                    #note, subtracting mix_output_size here to make minimum size change
                    #todo, make an offer for exactly the max size with no change

		if offer_spread == 'fibonacci':
                    offer_levels = fib_seq(offer_low, offer_high, num_offers) + [offer_high]
		elif offer_spread == 'evenly':
                    offer_levels = list(range(((offer_high - offer_low) / num_offers), offer_high, 
                        (offer_high - offer_low) / (num_offers - 1))) + [offer_high]
		elif offer_spread == 'random':
                    offer_levels = sorted([random.randrange(offer_low, offer_high) 
                        for n in range(num_offers-1)] + [random.randrange(offer_high - (offer_high / num_offers), offer_high)])
		elif offer_spread == 'bymixdepth':
                    offer_levels = [m[1] for m in filtered_mix_balance if m[1] < offer_high] + [offer_high] #already sorted by size above
		elif offer_spread == 'custom':
                    offer_levels = [int((Decimal(str(x)) * 100000000).quantize(0)) for x in sorted(custom_offers_levels)] #convert btc to satoshi
                    if offer_levels[-1] > offer_high:
                        debug('ALERT: Your custom offers exceeds you max offer size.')
                        debug('offer = ' + str(offer_levels[-1]) + ' offer_high = ' + str(offer_high))
                        sys.exit(0)
                else:
		    debug('invalid offer_spread = ' + str(offer_spread))
                    sys.exit(0)

                cjfee_lowx, cjfee_highx = Decimal(str(cjfee_low)) / 100, Decimal(str(cjfee_high)) / 100
		if cjfee_spread == 'fibonacci':
                    cjfee_levels = fib_seq(cjfee_lowx, cjfee_highx, num_offers) + [cjfee_highx]
                    cjfee_levels = ["%0.7f" % x for x in cjfee_levels]
		elif cjfee_spread == 'evenly':
                    cjfee_levels = drange(((cjfee_highx-cjfee_lowx)/num_offers), cjfee_highx, 
                        (cjfee_highx - cjfee_lowx) / (num_offers - 1)) #evenly spaced
                    cjfee_levels = ["%0.7f" % x for x in cjfee_levels] + [cjfee_highx]
		elif cjfee_spread == 'random':
                    cjfee_levels = sorted(["%0.7f" % random.uniform(cjfee_lowx, cjfee_highx) 
                        for n in range(num_offers)]) #randomly spaced
		elif cjfee_spread == 'custom':
                    cjfee_levels = [str(Decimal(str(x)) / 100) for x in custom_cjfees]
		    leftout = num_offers - len(cjfee_levels)
		    while leftout > 0:
		        debug('ALERT: cjfee_custom has too few items')
			cjfee_levels.append(cjfee_levels[-1])
			leftout -= 1
                else:
		    debug('invalid cjfee_spread = ' + str(cjfee_spread))
                    sys.exit(0)

		debug('offer_levels = ' + str(offer_levels))
                lower_bound_balances = [offer_low] + [x for x in offer_levels[:-1]]
		offer_ranges = zip(offer_levels, lower_bound_balances, cjfee_levels)
		debug('offer_ranges = ' + str(offer_ranges))
		offers=[]
		oid = 0
		for upper, lower, fee in offer_ranges:
		    if float(fee) > 0:
		    	min_needed = int(min_cjfee / float(fee))
		    else:
			min_needed = min_cjfee
		    if min_needed <= lower:
                        #create a regular relorder
                        offer = {'oid': oid, 'ordertype': 'relorder', 'minsize': lower,
                                'maxsize': upper, 'txfee': txfee, 'cjfee': fee}
		    elif min_needed > lower and min_needed < upper:
                        #create two offers. An absolute for lower bound need, and relorder for the rest
                        offer = {'oid': oid, 'ordertype': 'absorder', 'minsize': lower,
                                'maxsize': min_needed - 1, 'txfee': txfee, 'cjfee': min_cjfee}
                        oid += 1
                        offers.append(offer)
                        offer = {'oid': oid, 'ordertype': 'relorder', 'minsize': min_needed,
                                'maxsize': upper, 'txfee': txfee, 'cjfee': fee}
		    elif min_needed >= upper:
                        #just create an absolute offer
                        offer = {'oid': oid, 'ordertype': 'absorder', 'minsize': lower,
                                'maxsize': upper, 'txfee': txfee, 'cjfee': min_cjfee}
                        #todo: combine neighboring absorders into a single one
                    oid += 1
                    offers.append(offer)

		debug('generated offers = \n' + '\n'.join([str(o) for o in offers]))
		return offers

        def oid_to_order(self, cjorder, oid, amount):
                mix_balance = self.wallet.get_balance_by_mixdepth()
                #remove mix depths that do not have enough
                filtered_mix_balance = [m for m in mix_balance.iteritems() if m[1] >= amount] 
                debug('have enough, filtered_mix_balance = ' + str(filtered_mix_balance))

                #when we have more then one usable mix depth, and the max mix depth is one of them
                #then remove it so that coins keep moving down the mix depths
                if len(filtered_mix_balance) > 1 and self.wallet.max_mix_depth in [x[0] for x in filtered_mix_balance]:
                    filtered_mix_balance = [x for x in filtered_mix_balance if x[0] != self.wallet.max_mix_depth]
                    debug('excluding the max mix depth, ' + str(self.wallet.max_mix_depth))

                #clump into the largest mixdepth 
                #use the first usable mixdepth that is before the mixdepth with the largest amount
                #the largest amount of coins are available to join with (since joins always come from a single depth)
                #the maker commands a higher fee for the larger amounts 
                #note, no need to consider max_offer_size here
                largest_mixdepth = sorted(filtered_mix_balance, key= lambda x: x[1], reverse=True)[0][0] #find largest amount
                filtered_mix_balance = [m for m in mix_balance.iteritems() if m[0] <= largest_mixdepth] #use mixdepths before and including the largest
                filtered_mix_balance = sorted(filtered_mix_balance, key= lambda x: x[0]) #make sure we are in seq of mixdepth num

                #use mix depth with the most coins, 
                #creates a more even distribution across mix depths
                #and a more diverse txo selection in each depth
                #filtered_mix_balance = sorted(filtered_mix_balance, key= lambda x: x[1], reverse=True) #sort largest to smallest amount

                #use mix depth that has the closest amount of coins to what this transaction needs
                #keeps coins moving through mix depths more quickly
                #and its more likely to use txos of a similiar size to this transaction
                #filtered_mix_balance = sorted(filtered_mix_balance, key= lambda x: x[1]) #sort smallest to largest usable amount

                #use a random usable mixdepth. 
                #warning, could expose more txos to malicous taker requests
                #filtered_mix_balanace = random.choice(filtered_mix_balance)

                mixdepth = filtered_mix_balance[0][0]

                debug('filling offer, mixdepth=' + str(mixdepth))

                #mixdepth is the chosen depth we'll be spending from
                cj_addr = self.wallet.get_receive_addr((mixdepth + 1) % self.wallet.max_mix_depth)
                change_addr = self.wallet.get_change_addr(mixdepth)

                utxos = self.wallet.select_utxos(mixdepth, amount)
                my_total_in = sum([va['value'] for va in utxos.values()])
                real_cjfee = calc_cj_fee(cjorder.ordertype, cjorder.cjfee, amount)
                change_value = my_total_in - amount - cjorder.txfee + real_cjfee
                if change_value <= min_output_size:
                        debug('change value=%d below dust threshold, finding new utxos' % (change_value))
                        try:
                                utxos = self.wallet.select_utxos(mixdepth, amount + min_output_size)
                        except Exception:
                                debug('dont have the required UTXOs to make a output above the dust threshold, quitting')
                                return None, None, None

                return utxos, cj_addr, change_addr

	def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
		self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
		'''
		algorithm - find all the orders which have changed
		'''

		neworders = self.create_my_orders()
		oldorders = self.orderlist
		new_setdiff_old = [o for o in neworders if o not in oldorders]
		old_setdiff_new = [o for o in oldorders if o not in neworders]

		debug('neworders = \n' + '\n'.join([str(o) for o in neworders]))
		debug('oldorders = \n' + '\n'.join([str(o) for o in oldorders]))
		debug('new_setdiff_old = \n' + '\n'.join([str(o) for o in new_setdiff_old]))
		debug('old_setdiff_new = \n' + '\n'.join([str(o) for o in old_setdiff_new]))

		ann_orders = new_setdiff_old
		ann_oids = [o['oid'] for o in ann_orders]
		cancel_orders = [o['oid'] for o in old_setdiff_new if o['oid'] not in ann_oids]

		debug('can_orders = \n' + '\n'.join([str(o) for o in cancel_orders]))
		debug('ann_orders = \n' + '\n'.join([str(o) for o in ann_orders]))

		return (cancel_orders, ann_orders)

	def on_tx_confirmed(self, cjorder, confirmations, txid):
		if cjorder.cj_addr in self.tx_unconfirm_timestamp:
			confirm_time = int(time.time()) - self.tx_unconfirm_timestamp[cjorder.cj_addr]
		else:
			confirm_time = 0
		del self.tx_unconfirm_timestamp[cjorder.cj_addr]
		timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
		self.log_statement([timestamp, cjorder.cj_amount, len(cjorder.utxos),
			sum([av['value'] for av in cjorder.utxos.values()]), cjorder.real_cjfee,
			cjorder.real_cjfee - cjorder.txfee, round(confirm_time / 60.0, 2), ''])
		return self.on_tx_unconfirmed(cjorder, txid, None)

def main():
	common.load_program_config()
	import sys
	seed = sys.argv[1]
	if isinstance(common.bc_interface, blockchaininterface.BlockrInterface):
		print '\nYou are running a yield generator by polling the blockr.io website'
		print 'This is quite bad for privacy. That site is owned by coinbase.com'
                print 'Also your bot will run faster and more efficently, you can be immediately notified of new bitcoin network'
		print ' information so your money will be working for you as hard as possible'
		print 'Learn how to setup JoinMarket with Bitcoin Core: https://github.com/chris-belcher/joinmarket/wiki/Running-JoinMarket-with-Bitcoin-Core-full-node'
		ret = raw_input('\nContinue? (y/n):')
		if ret[0] != 'y':
			return

	wallet = Wallet(seed, max_mix_depth = mix_levels)
	common.bc_interface.sync_wallet(wallet)
	
	common.nickname = nickname
	debug('starting yield generator')
	irc = IRCMessageChannel(common.nickname, realname='btcint=' + common.config.get("BLOCKCHAIN", "blockchain_source"),
		password=nickserv_password)
	maker = YieldGenerator(irc, wallet)
	try:
		debug('connecting to irc')
		irc.run()
	except:
		debug('CRASHING, DUMPING EVERYTHING')
		debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
		debug_dump_object(maker)
		debug_dump_object(irc)
		import traceback
		debug(traceback.format_exc())

if __name__ == "__main__":
	main()
	print('done')
