#from joinmarket import *
import subprocess
import unittest
import json, threading, abc, pprint, time, random, sys
import BaseHTTPServer, SimpleHTTPServer
from decimal import Decimal
import bitcoin as btc

import common

def get_blockchain_interface_instance(config):
	source = config.get("BLOCKCHAIN", "blockchain_source")
	bitcoin_cli_cmd = config.get("BLOCKCHAIN", "bitcoin_cli_cmd").split(' ')
	testnet = common.get_network()=='testnet'
	if source == 'json-rpc':
		bc_interface = BitcoinCoreInterface(bitcoin_cli_cmd, testnet)
	elif source == 'regtest':
		bc_interface = RegtestBitcoinCoreInterface(bitcoin_cli_cmd)
	elif source == 'blockr':
		bc_interface = BlockrInterface(testnet)
	else:
		raise ValueError("Invalid blockchain source")	
	return bc_interface


#download_wallet_history() find_unspent_addresses() #finding where to put index and my utxos
#add address notify()
#fetchtx() needs to accept a list of addresses too
#pushtx()
class BlockchainInterface(object):
	__metaclass__ = abc.ABCMeta
	def __init__(self):
		pass

	@abc.abstractmethod
	def sync_wallet(self, wallet, gaplimit=6):
		'''Finds used addresses and utxos, puts in wallet.index and wallet.unspent'''
		pass

	@abc.abstractmethod
	def add_tx_notify(self, txd, unconfirmfun, confirmfun):
		'''Invokes unconfirmfun and confirmfun when tx is seen on the network'''
		pass

	@abc.abstractmethod
	def fetchtx(self, txid):
		'''Returns a txhash of a given txid, or list of txids'''
		pass

	@abc.abstractmethod
	def pushtx(self, txhex):
		'''pushes tx to the network, returns txhash'''
		pass

class BlockrInterface(BlockchainInterface):
	def __init__(self, testnet = False):
		super(BlockrInterface, self).__init__()
		self.network = 'testnet' if testnet else 'btc' #see bci.py in bitcoin module
		self.blockr_domain = 'tbtc' if testnet else 'btc'
    
	def sync_wallet(self, wallet, gaplimit=6):
		common.debug('downloading wallet history')
		#sets Wallet internal indexes to be at the next unused address
		addr_req_count = 20
		for mix_depth in range(wallet.max_mix_depth):
			for forchange in [0, 1]:
				unused_addr_count = 0
				last_used_addr = ''
				while unused_addr_count < gaplimit:
					addrs = [wallet.get_new_addr(mix_depth, forchange) for i in range(addr_req_count)]

					#TODO send a pull request to pybitcointools
					# because this surely should be possible with a function from it
					blockr_url = 'http://' + self.blockr_domain + '.blockr.io/api/v1/address/txs/'
					res = btc.make_request(blockr_url+','.join(addrs))
					data = json.loads(res)['data']
					for dat in data:
						if dat['nb_txs'] != 0:
							last_used_addr = dat['address']
						else:
							unused_addr_count += 1
							if unused_addr_count >= gaplimit:
								break
				if last_used_addr == '':
					wallet.index[mix_depth][forchange] = 0
				else:
					wallet.index[mix_depth][forchange] = wallet.addr_cache[last_used_addr][2] + 1

		#finds utxos in the wallet

		addrs = {}
		for m in range(wallet.max_mix_depth):
			for forchange in [0, 1]:
				for n in range(wallet.index[m][forchange]):
					addrs[wallet.get_addr(m, forchange, n)] = m
		if len(addrs) == 0:
			common.debug('no tx used')
			return

		#TODO handle the case where there are so many addresses it cant
		# fit into one api call (>50 or so)
		i = 0
		addrkeys = addrs.keys()
		while i < len(addrkeys):
			inc = min(len(addrkeys) - i, addr_req_count)
			req = addrkeys[i:i + inc]
			i += inc

			#TODO send a pull request to pybitcointools 
			# unspent() doesnt tell you which address, you get a bunch of utxos
			# but dont know which privkey to sign with
			
			blockr_url = 'http://' + self.blockr_domain + '.blockr.io/api/v1/address/unspent/'
			res = btc.make_request(blockr_url+','.join(req))
			data = json.loads(res)['data']
			if 'unspent' in data:
				data = [data]
			for dat in data:
				for u in dat['unspent']:
					wallet.unspent[u['tx']+':'+str(u['n'])] = {'address':
						dat['address'], 'value': int(u['amount'].replace('.', ''))}

	def add_tx_notify(self, txd, unconfirmfun, confirmfun):
		unconfirm_timeout = 5*60 #seconds
		unconfirm_poll_period = 5
		confirm_timeout = 120*60
		confirm_poll_period = 5*60
		class NotifyThread(threading.Thread):
			def __init__(self, blockr_domain, txd, unconfirmfun, confirmfun):
				threading.Thread.__init__(self)
				self.daemon = True
				self.blockr_domain = blockr_domain
				self.unconfirmfun = unconfirmfun
				self.confirmfun = confirmfun
				self.tx_output_set = set([(sv['script'], sv['value']) for sv in txd['outs']])
				self.output_addresses = [btc.script_to_address(scrval[0],
					common.get_addr_vbyte()) for scrval in self.tx_output_set]
				common.debug('txoutset=' + pprint.pformat(self.tx_output_set))
				common.debug('outaddrs=' + ','.join(self.output_addresses))

			def run(self):
				st = int(time.time())
				unconfirmed_txid = None
				unconfirmed_txhex = None
				while not unconfirmed_txid:
					time.sleep(unconfirm_poll_period)
					if int(time.time()) - st > unconfirm_timeout:
						common.debug('checking for unconfirmed tx timed out')
						return
					blockr_url = 'http://' + self.blockr_domain + '.blockr.io/api/v1/address/unspent/'
					random.shuffle(self.output_addresses) #seriously weird bug with blockr.io
					data = json.loads(btc.make_request(blockr_url + ','.join(self.output_addresses) + '?unconfirmed=1'))['data']
					shared_txid = None
					for unspent_list in data:
						txs = set([str(txdata['tx']) for txdata in unspent_list['unspent']])
						if not shared_txid:
							shared_txid = txs
						else:	
							shared_txid = shared_txid.intersection(txs)
					common.debug('sharedtxid = ' + str(shared_txid))
					if len(shared_txid) == 0:
						continue
					blockr_url = 'http://' + self.blockr_domain + '.blockr.io/api/v1/tx/raw/'
					data = json.loads(btc.make_request(blockr_url + ','.join(shared_txid)))['data']
					if not isinstance(data, list):
						data = [data]
					for txinfo in data:
						outs = set([(sv['script'], sv['value']) for sv in btc.deserialize(txinfo['tx']['hex'])['outs']])
						print 'outs = ' + str(outs)
						if outs == self.tx_output_set:
							unconfirmed_txid = txinfo['tx']['txid']
							unconfirmed_txhex = txinfo['tx']['hex']
							break

				self.unconfirmfun(btc.deserialize(unconfirmed_txhex), unconfirmed_txid)

				st = int(time.time())
				confirmed_txid = None
				confirmed_txhex = None
				while not confirmed_txid:
					time.sleep(confirm_poll_period)
					if int(time.time()) - st > confirm_timeout:
						common.debug('checking for confirmed tx timed out')
						return
					blockr_url = 'http://' + self.blockr_domain + '.blockr.io/api/v1/address/txs/'
					data = json.loads(btc.make_request(blockr_url + ','.join(self.output_addresses)))['data']
					shared_txid = None
					for addrtxs in data:
						txs = set([str(txdata['tx']) for txdata in addrtxs['txs']])
						if not shared_txid:
							shared_txid = txs
						else:	
							shared_txid = shared_txid.intersection(txs)
					common.debug('sharedtxid = ' + str(shared_txid))
					if len(shared_txid) == 0:
						continue
					blockr_url = 'http://' + self.blockr_domain + '.blockr.io/api/v1/tx/raw/'
					data = json.loads(btc.make_request(blockr_url + ','.join(shared_txid)))['data']
					if not isinstance(data, list):
						data = [data]
					for txinfo in data:
						outs = set([(sv['script'], sv['value']) for sv in btc.deserialize(txinfo['tx']['hex'])['outs']])
						print 'outs = ' + str(outs)
						if outs == self.tx_output_set:
							confirmed_txid = txinfo['tx']['txid']
							confirmed_txhex = txinfo['tx']['hex']
							break
				self.confirmfun(btc.deserialize(confirmed_txhex), confirmed_txid, 1)

		NotifyThread(self.blockr_domain, txd, unconfirmfun, confirmfun).start()

	def fetchtx(self, txid):
		return btc.blockr_fetchtx(txid, self.network)

	def pushtx(self, txhex):
		data = json.loads(btc.blockr_pushtx(txhex, self.network))
		if data['status'] != 'success':
			#error message generally useless so there might not be a point returning
			common.debug(data) 
			return None
		return data['data']
		
class NotifyRequestHeader(SimpleHTTPServer.SimpleHTTPRequestHandler):
	def __init__(self, request, client_address, base_server):
		self.btcinterface = base_server.btcinterface
		self.base_server = base_server
		SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(self, request, client_address, base_server)

	def do_HEAD(self):
		print 'httpd received HEAD ' + self.path + ' request'
		pages = ('/walletnotify?', '/alertnotify?')
		if not self.path.startswith(pages):
			return
		if self.path.startswith('/walletnotify?'):
			txid = self.path[len(pages[0]):]
			txd = btc.deserialize(self.btcinterface.fetchtx(txid))
			tx_output_set = set([(sv['script'], sv['value']) for sv in txd['outs']])
			print 'outs = ' + str(tx_output_set)

			unconfirmfun, confirmfun = None, None
			for tx_out, ucfun, cfun in self.btcinterface.txnotify_fun:
				if tx_out == tx_output_set:
					unconfirmfun = ucfun
					confirmfun = cfun
					break
			if not unconfirmfun:
				common.debug('txid=' + txid + ' not being listened for')
				return
			txdata = json.loads(self.btcinterface.rpc(['gettxout', txid, '0', 'true']))
			if txdata['confirmations'] == 0:
				unconfirmfun(txd, txid)
			else:
				confirmfun(txd, txid, txdata['confirmations'])
				self.btcinterface.txnotify_fun.remove((tx_out, unconfirmfun, confirmfun))

		elif self.path.startswith('/alertnotify?'):
			message = self.path[len(pages[1]):]
			print 'got an alert, shit, shutting down. message=' + message
			sys.exit(0)
		self.send_response(200)
		#self.send_header('Connection', 'close')
		self.end_headers()

class BitcoinCoreNotifyThread(threading.Thread):
	def __init__(self, btcinterface):
		threading.Thread.__init__(self)
		self.daemon = True
		self.btcinterface = btcinterface

	def run(self):
		common.debug('started bitcoin core notify listening thread')
		hostport = ('localhost', 62602)
		httpd = BaseHTTPServer.HTTPServer(hostport, NotifyRequestHeader)
		httpd.btcinterface = self.btcinterface
		httpd.serve_forever()

#must run bitcoind with -txindex=1 -server
#-walletnotify="wget --spider -q http://localhost:62602/walletnotify?%s"
#and make sure wget is installed

#TODO must add the tx addresses as watchonly if case we ever broadcast a tx
# with addresses not belonging to us
class BitcoinCoreInterface(BlockchainInterface):
	def __init__(self, bitcoin_cli_cmd, testnet = False):
		super(BitcoinCoreInterface, self).__init__()
		self.command_params = bitcoin_cli_cmd
		if testnet:
			self.command_params += ['-testnet']
		self.notifythread = None
		self.txnotify_fun = []

	def rpc(self, args):
		try:
			if args[0] != 'importaddress':
				common.debug('rpc: ' + str(self.command_params + args))
			res = subprocess.check_output(self.command_params + args)
			return res
		except subprocess.CalledProcessError, e:
			raise #something here

	def add_watchonly_addresses(self, addr_list, wallet_name):
		common.debug('importing ' + str(len(addr_list)) + ' into account ' + wallet_name)
		for addr in addr_list:
			self.rpc(['importaddress', addr, wallet_name, 'false'])
		print 'now restart bitcoind with -rescan'
		sys.exit(0)

	def sync_wallet(self, wallet, gaplimit=6):
		wallet_name = 'joinmarket-wallet-' + btc.dbl_sha256(wallet.keys[0][0])[:6]
		addr_req_count = 50
		wallet_addr_list = []
		for mix_depth in range(wallet.max_mix_depth):
			for forchange in [0, 1]:
				wallet_addr_list += [wallet.get_new_addr(mix_depth, forchange) for i in range(addr_req_count)]
				wallet.index[mix_depth][forchange] = 0
		imported_addr_list = json.loads(self.rpc(['getaddressesbyaccount', wallet_name]))
		if not set(wallet_addr_list).issubset(set(imported_addr_list)):
			self.add_watchonly_addresses(wallet_addr_list, wallet_name)
			return

		#TODO get all the transactions above 1000, by looping until len(result) < 1000
		ret = self.rpc(['listtransactions', wallet_name, '1000', '0', 'true'])
		txs = json.loads(ret)
		if len(txs) == 1000:
			raise Exception('time to stop putting off this bug and actually fix it, see the TODO')
		used_addr_list = [tx['address'] for tx in txs]
		too_few_addr_mix_change = []
		for mix_depth in range(wallet.max_mix_depth):
			for forchange in [0, 1]:
				unused_addr_count = 0
				last_used_addr = ''
				breakloop = False
				while not breakloop:
					if unused_addr_count >= gaplimit:
						break
					mix_change_addrs = [wallet.get_new_addr(mix_depth, forchange) for i in range(addr_req_count)]
					for mc_addr in mix_change_addrs:
						if mc_addr not in imported_addr_list:
							too_few_addr_mix_change.append((mix_depth, forchange))
							breakloop = True
							break
						if mc_addr in used_addr_list:
							last_used_addr = mc_addr
						else:
							unused_addr_count += 1
							if unused_addr_count >= gaplimit:
								breakloop = True
								break

				if last_used_addr == '':
					wallet.index[mix_depth][forchange] = 0
				else:
					wallet.index[mix_depth][forchange] = wallet.addr_cache[last_used_addr][2] + 1

		wallet_addr_list = []
		if len(too_few_addr_mix_change) > 0:
			common.debug('too few addresses in ' + str(too_few_addr_mix_change))
			for mix_depth, forchange in too_few_addr_mix_change:
				wallet_addr_list += [wallet.get_new_addr(mix_depth, forchange) for i in range(addr_req_count)]
			self.add_watchonly_addresses(wallet_addr_list, wallet_name)
			return

		unspent_list = json.loads(self.rpc(['listunspent']))
		for u in unspent_list:
			if u['account'] != wallet_name:
				continue
			wallet.unspent[u['txid'] + ':' + str(u['vout'])] = {'address': u['address'],
				'value': int(u['amount']*1e8)}

	def add_tx_notify(self, txd, unconfirmfun, confirmfun):
		if not self.notifythread:
			self.notifythread = BitcoinCoreNotifyThread(self)
			self.notifythread.start()
		tx_output_set = set([(sv['script'], sv['value']) for sv in txd['outs']])
		self.txnotify_fun.append((tx_output_set, unconfirmfun, confirmfun))

	def fetchtx(self, txid):
		return self.rpc(['getrawtransaction', txid]).strip()

	def pushtx(self, txhex):
		return self.rpc(['sendrawtransaction', txhex]).strip()

#class for regtest chain access
#running on local daemon. Only 
#to be instantiated after network is up
#with > 100 blocks.
class RegtestBitcoinCoreInterface(BitcoinCoreInterface):
	def __init__(self, bitcoin_cli_cmd):
		super(BitcoinCoreInterface, self).__init__(bitcoin_cli_cmd, False)
		self.command_params = bitcoin_cli_cmd + ['-regtest']

	def pushtx(self, txhex):
		ret = super(RegtestBitcoinCoreInterface, self).send_tx(txhex)
		self.tick_forward_chain(1)
		return ret

	def tick_forward_chain(self, n):
		'''Special method for regtest only;
		instruct to mine n blocks.'''
		self.rpc(['setgenerate','true', str(n)])

	def grab_coins(self, receiving_addr, amt=50):
		'''
		NOTE! amt is passed in Coins, not Satoshis!
		Special method for regtest only:
		take coins from bitcoind's own wallet
		and put them in the receiving addr.
		Return the txid.
		'''
		if amt > 500:
			raise Exception("too greedy")
		'''
		if amt > self.current_balance:
		#mine enough to get to the reqd amt
		reqd = int(amt - self.current_balance)
		reqd_blocks = str(int(reqd/50) +1)
		if self.rpc(['setgenerate','true', reqd_blocks]):
		raise Exception("Something went wrong")
		'''
		#now we do a custom create transaction and push to the receiver
		txid = self.rpc(['sendtoaddress', receiving_addr, str(amt)])
		if not txid:
			raise Exception("Failed to broadcast transaction")
		#confirm
		self.tick_forward_chain(1)
		return txid        

def main():
	#TODO some useful quick testing here, so people know if they've set it up right
	myBCI = RegtestBitcoinCoreInterface()
	#myBCI.send_tx('stuff')
	print myBCI.get_utxos_from_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
	print myBCI.get_balance_at_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
	txid = myBCI.grab_coins('mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd',23)
	print txid
	print myBCI.get_balance_at_addr(['mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd'])
	print myBCI.get_utxos_from_addr(['mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd'])

if __name__ == '__main__':
    main()




