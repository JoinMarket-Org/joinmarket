#! /usr/bin/env python

from maker import *
import bitcoin as btc

import pprint
import pdb

txfee = 1000
cjfee = '0.01' # 1% fee
mix_levels = 4

#is a maker for the purposes of generating a yield from held bitcoins
#for each mixing level, adds up the balance of all the addresses and put up
# a relative fee order, oid=mix depth
#TODO theres no need for seperate orders, just announce the order with the highest size
# and when it arrives choose which mixdepth you want, best algorithm is probably
# to try to keep coins concentrated into one depth so you can join larger amounts
#TODO when a nick with an open order quits, is kicked or dies, remove him from open orders
class YieldGenerator(Maker):
	def __init__(self, wallet):
		Maker.__init__(self, wallet)
	
	def create_my_orders(self):
		mix_utxo_list = self.wallet.get_mix_utxo_list()
		orderlist = []
		for mixdepth, utxo_list in mix_utxo_list.iteritems():
			total_value = 0
			for utxo in utxo_list:
				total_value += self.wallet.unspent[utxo]['value']
			order = {'oid': mixdepth, 'ordertype': 'relorder', 'minsize': 0,
				'maxsize': total_value, 'txfee': txfee, 'cjfee': cjfee,
				'utxos': utxo_list}
			orderlist.append(order)
		return orderlist

	def oid_to_order(self, oid, amount):
		order = [o for o in self.orderlist if o['oid'] == oid][0]
		unspent = [{'utxo': utxo, 'value': self.wallet.unspent[utxo]['value']}
			for utxo in order['utxos']]
		inputs = btc.select(unspent, amount)
		mixdepth = oid
		cj_addr = self.wallet.get_receive_addr((mixdepth + 1) % self.wallet.max_mix_depth)
		change_addr = self.wallet.get_change_addr(mixdepth)
		return [i['utxo'] for i in inputs], cj_addr, change_addr

	def on_tx_unconfirmed(self, cjorder, balance, removed_utxos):
		#want to replace the current relorders with the same
		# thing except reduced maxvalue to take into account the use
		source_mixdepth = self.wallet.addr_cache[removed_utxos.values()[0]['address']][0]
		debug('source mixdepth = %d' % (source_mixdepth))
		removed_utxos_balance = sum([addrvalue['value'] for addrvalue in removed_utxos.values()])
		debug('removed_utxos_balance = %d' % (removed_utxos_balance))

		oldorder = [order for order in self.orderlist if order['oid'] == source_mixdepth][0]
		neworder = oldorder.copy()
		neworder['maxsize'] = oldorder['maxsize'] - removed_utxos_balance
		[neworder['utxos'].remove(u) for u in removed_utxos.keys()]
		#TODO if the maxsize left is zero or below the dust limit, just cancel the order
		debug('neworder\n' + pprint.pformat(neworder))

		#to_announce = self.create_my_orders()
		return ([], [neworder])

	def on_tx_confirmed(self, cjorder, confirmations, txid, balance, added_utxos):
		#add the new available utxos to the maxsize and announce it
		# if we dont have a mixdepth of that level, make one

		to_announce = []
		for utxo, addrvalue in added_utxos.iteritems():
			mixdepth = self.wallet.addr_cache[addrvalue['address']][0]
			debug('mixdepth=%d' % (mixdepth))
			oldorder_search = [order for order in self.orderlist if order['oid'] == mixdepth]
			debug('len=' + str(len(oldorder_search)) + ' oldorder_search=\n' + pprint.pformat(oldorder_search))
			if len(oldorder_search) == 0:
				#there were no existing orders at that mixing depth
				neworder = {'oid': mixdepth, 'ordertype': 'relorder', 'minsize': 0,
					'maxsize': addrvalue['value'], 'txfee': txfee, 'cjfee': cjfee,
					'utxos': [utxo]}
			else:
				#assert len(oldorder_search) == 1
				oldorder = oldorder_search[0]
				neworder = oldorder.copy()
				neworder['maxsize'] = oldorder['maxsize'] + addrvalue['value']
				neworder['utxos'].append(utxo)
			to_announce.append(neworder)
		return ([], to_announce)

def main():
	import sys
	seed = sys.argv[1] #btc.sha256('dont use brainwallets except for holding testnet coins')

	print 'downloading wallet history'
	wallet = Wallet(seed, max_mix_depth = mix_levels)
	wallet.download_wallet_history()
	wallet.find_unspent_addresses()


	from socket import gethostname
	nickname = 'yield-gen-' + btc.sha256(gethostname())[:6]

	maker = YieldGenerator(wallet)
	print 'connecting to irc'
	maker.run(HOST, PORT, nickname, CHANNEL)

if __name__ == "__main__":
	main()
	print('done')
