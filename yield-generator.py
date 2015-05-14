#! /usr/bin/env python

import time, os, binascii, sys, datetime
import pprint
data_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(data_dir, 'lib'))

from maker import *
from irc import IRCMessageChannel, random_nick
import bitcoin as btc
import common

from socket import gethostname

txfee = 1000
cjfee = '0.002' # 0.2% fee
nickname = random_nick()
nickserv_password = ''
minsize = int(1.2 * txfee / float(cjfee)) #minimum size is such that you always net profit at least 20% of the miner fee
mix_levels = 5



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
	def __init__(self, msgchan, wallet):
		Maker.__init__(self, msgchan, wallet)
		self.msgchan.register_channel_callbacks(self.on_welcome, self.on_set_topic,
			None, None, self.on_nick_leave, None)
		self.tx_unconfirm_timestamp = {}

	def log_statement(self, data):
		data = [str(d) for d in data]
		self.income_statement = open(os.path.join('logs', 'yigen-statement.csv'), 'aw')
		self.income_statement.write(','.join(data) + '\n')
		self.income_statement.close()

	def on_welcome(self):
		Maker.on_welcome(self)
		self.log_statement(['timestamp', 'cj amount/satoshi', 'my input count',
			'my input value/satoshi', 'cjfee/satoshi', 'earned/satoshi',
			'confirm time/min', 'notes'])
		timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
		self.log_statement([timestamp, '', '', '', '', '', '', 'Connected'])

	def create_my_orders(self):
		mix_balance = self.wallet.get_balance_by_mixdepth()
		if len([b for m, b in mix_balance.iteritems() if b > 0]) == 0:
			debug('do not have any coins left')
			return []

		#print mix_balance
		max_mix = max(mix_balance, key=mix_balance.get)
		order = {'oid': 0, 'ordertype': 'relorder', 'minsize': minsize,
			'maxsize': mix_balance[max_mix] - common.DUST_THRESHOLD, 'txfee': txfee, 'cjfee': cjfee}
		return [order]

	def oid_to_order(self, cjorder, oid, amount):
		mix_balance = self.wallet.get_balance_by_mixdepth()
		max_mix = max(mix_balance, key=mix_balance.get)

		#algo attempts to make the largest-balance mixing depth get an even larger balance
		debug('finding suitable mixdepth')
		mixdepth = (max_mix - 1) % self.wallet.max_mix_depth
		while True:
			if mixdepth in mix_balance and mix_balance[mixdepth] >= amount:
				break
			mixdepth = (mixdepth - 1) % self.wallet.max_mix_depth
		#mixdepth is the chosen depth we'll be spending from
		cj_addr = self.wallet.get_receive_addr((mixdepth + 1) % self.wallet.max_mix_depth)
		change_addr = self.wallet.get_change_addr(mixdepth)

		utxos = self.wallet.select_utxos(mixdepth, amount)
		my_total_in = sum([va['value'] for va in utxos.values()])
		real_cjfee = calc_cj_fee(cjorder.ordertype, cjorder.cjfee, amount)
		change_value = my_total_in - amount - cjorder.txfee + real_cjfee
		if change_value <= common.DUST_THRESHOLD:
			debug('change value=%d below dust threshold, finding new utxos' % (change_value))
			try:
				utxos = self.wallet.select_utxos(mixdepth, amount + common.DUST_THRESHOLD)
			except Exception:
				debug('dont have the required UTXOs to make a output above the dust threshold, quitting')
				return None, None, None

		return utxos, cj_addr, change_addr

	def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
		self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
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

	def on_tx_confirmed(self, cjorder, confirmations, txid):
		confirm_time = int(time.time()) - self.tx_unconfirm_timestamp[cjorder.cj_addr]
		timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
		self.log_statement([timestamp, cjorder.cj_amount, len(cjorder.utxos),
			sum([av['value'] for av in cjorder.utxos.values()]), cjorder.real_cjfee,
			cjorder.real_cjfee - cjorder.txfee, round(confirm_time / 60.0, 2), ''])
		return self.on_tx_unconfirmed(cjorder, txid, None)

def main():
	common.load_program_config()
	import sys
	seed = sys.argv[1]
	wallet = Wallet(seed, max_mix_depth = mix_levels)
	common.bc_interface.sync_wallet(wallet)
	wallet.print_debug_wallet_info()
	
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
