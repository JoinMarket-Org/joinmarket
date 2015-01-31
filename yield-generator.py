#! /usr/bin/env python

from maker import *
import bitcoin as btc
import time

import pprint

from socket import gethostname

txfee = 1000
cjfee = '0.01' # 1% fee
mix_levels = 5
nickname = 'yigen-' + btc.sha256(gethostname())[:6]
nickserv_password = ''
minsize = int(2 * txfee / float(cjfee)) #minimum size is such that you always net profit at least the miners fee



#is a maker for the purposes of generating a yield from held
# bitcoins without ruining privacy for the taker, the taker could easily check
# the history of the utxos this bot sends, so theres not much incentive
# to ruin the privacy for barely any more yield
#sell-side algorithm:
#add up the value of each utxo for each mixing depth,
# announce a relative-fee order of the highest balance
#spent from utxos that try to make the highest balance even higher
# so try to keep coins concentrated in one mixing depth
class YieldGenerator(Maker):
	def __init__(self, wallet):
		Maker.__init__(self, wallet)

	def on_connect(self):
		if len(nickserv_password) > 0:
			self.send_raw('PRIVMSG NickServ :identify ' + nickserv_password)

	def create_my_orders(self):
		mix_balance = self.wallet.get_balance_by_mixdepth()
		if len([b for m, b in mix_balance.iteritems() if b > 0]) == 0:
			debug('do not have any coins left')
			return []

		#print mix_balance
		max_mix = max(mix_balance, key=mix_balance.get)
		order = {'oid': 0, 'ordertype': 'relorder', 'minsize': minsize,
			'maxsize': mix_balance[max_mix], 'txfee': txfee, 'cjfee': cjfee}
		return [order]

	def oid_to_order(self, oid, amount):
		mix_balance = self.wallet.get_balance_by_mixdepth()
		max_mix = max(mix_balance, key=mix_balance.get)

		#algo attempts to make the largest-balance mixing depth get an even larger balance
		mixdepth = (max_mix - 1) % self.wallet.max_mix_depth
		while True:
			if mixdepth in mix_balance and mix_balance[mixdepth] > amount:
				break
			mixdepth = (mixdepth - 1) % self.wallet.max_mix_depth
		#mixdepth is the chosen depth we'll be spending from
		utxos = self.wallet.select_utxos(mixdepth, amount)
		cj_addr = self.wallet.get_receive_addr((mixdepth + 1) % self.wallet.max_mix_depth)
		change_addr = self.wallet.get_change_addr(mixdepth)
		return utxos, cj_addr, change_addr

	def on_tx_unconfirmed(self, cjorder, balance, removed_utxos):
		#if the balance of the highest-balance mixing depth change then reannounce it
		oldorder = self.orderlist[0] if len(self.orderlist) > 0 else None	
		neworders = self.create_my_orders()
		if len(neworders) == 0:
			return ([0], []) #cancel old order
		if oldorder: #oldorder may not exist when this is called from on_tx_confirmed
			if oldorder['maxsize'] == neworders[0]['maxsize']:
				return ([], []) #change nothing
		#announce new order, replacing the old order
		return ([], [neworders[0]])

	def on_tx_confirmed(self, cjorder, confirmations, txid, balance, added_utxos):
		return self.on_tx_unconfirmed(None, None, None)

def main():
	import sys
	seed = sys.argv[1] #btc.sha256('dont use brainwallets except for holding testnet coins')

	wallet = Wallet(seed, max_mix_depth = mix_levels)
	wallet.sync_wallet()
	maker = YieldGenerator(wallet)
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
