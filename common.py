
import bitcoin as btc
from decimal import Decimal
from math import factorial
import sys, datetime, json, time, pprint
import threading

HOST = 'irc.freenode.net'
CHANNEL = '#joinmarket-pit-test'
PORT = 6667

#for the mainnet its #joinmarket-pit

#TODO make this var all in caps
command_prefix = '!'
MAX_PRIVMSG_LEN = 400

ordername_list = ["absorder", "relorder"]

def debug(msg):
	print datetime.datetime.now().strftime("[%Y/%m/%d %H:%M:%S] ") + msg

def chunks(d, n):
	return [d[x: x+n] for x in xrange(0, len(d), n)]

def get_network():
	return 'testnet'

#TODO change this name into get_addr_ver() or something
def get_addr_vbyte():
	if get_network() == 'testnet':
		return 0x6f
	else:
		return 0x00

def get_signed_tx(wallet, ins, outs):
	tx = btc.mktx(ins, outs)
	for index, utxo in enumerate(ins):
		addr = wallet.unspent[utxo['output']]['address']
		tx = btc.sign(tx, index, wallet.get_key_from_addr(addr))
	return tx
	
def debug_dump_object(obj, skip_fields=[]):
	print 'Class debug dump, name:' + obj.__class__.__name__
	for k, v in obj.__dict__.iteritems():
		if k in skip_fields:
			continue
		print 'key=' + k
		if isinstance(v, str):
			print 'string: len:' + str(len(v))
			print v
		elif isinstance(v, dict) or isinstance(v, list):
			pprint.pprint(v)
		else:
			print v


class Wallet(object):
	def __init__(self, seed, max_mix_depth=2):
		self.max_mix_depth = max_mix_depth
		master = btc.bip32_master_key(seed)
		m_0 = btc.bip32_ckd(master, 0)
		mixing_depth_keys = [btc.bip32_ckd(m_0, c) for c in range(max_mix_depth)]
		self.keys = [(btc.bip32_ckd(m, 0), btc.bip32_ckd(m, 1)) for m in mixing_depth_keys]

		#self.index = [[0, 0]]*max_mix_depth
		self.index = []
		for i in range(max_mix_depth):
			self.index.append([0, 0])

		#example
		#index = self.index[mixing_depth]
		#key = btc.bip32_ckd(self.keys[mixing_depth][index[0]], index[1])

		self.addr_cache = {}
		self.unspent = {}

	def get_key(self, mixing_depth, forchange, i):
		return btc.bip32_extract_key(btc.bip32_ckd(self.keys[mixing_depth][forchange], i))

	def get_addr(self, mixing_depth, forchange, i):
		return btc.privtoaddr(self.get_key(mixing_depth, forchange, i), get_addr_vbyte())

	def get_new_addr(self, mixing_depth, forchange):
		index = self.index[mixing_depth]
		addr = self.get_addr(mixing_depth, forchange, index[forchange])
		self.addr_cache[addr] = (mixing_depth, forchange, index[forchange])
		index[forchange] += 1
		return addr

	def get_receive_addr(self, mixing_depth):
		return self.get_new_addr(mixing_depth, False)

	def get_change_addr(self, mixing_depth):
		return self.get_new_addr(mixing_depth, True)

	def get_key_from_addr(self, addr):
		if addr in self.addr_cache:
			return self.get_key(*self.addr_cache[addr])
		else:
			return None

	def remove_old_utxos(self, tx):
		removed_utxos = {}
		for ins in tx['ins']:
			utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
			if utxo not in self.unspent:
				continue
			removed_utxos[utxo] = self.unspent[utxo]
			del self.unspent[utxo]
		debug('removed utxos, wallet now is \n' + pprint.pformat(self.get_mix_utxo_list()))
		return removed_utxos

	def add_new_utxos(self, tx, txid):
		added_utxos = {}
		for index, outs in enumerate(tx['outs']):
			addr = btc.script_to_address(outs['script'], get_addr_vbyte())
			if addr not in self.addr_cache:
				continue
			addrdict = {'address': addr, 'value': outs['value']}
			utxo = txid + ':' + str(index)
			added_utxos[utxo] = addrdict
			self.unspent[utxo] = addrdict
		debug('added utxos, wallet now is \n' + pprint.pformat(self.get_mix_utxo_list()))
		return added_utxos

	def get_mix_utxo_list(self):
		'''
		returns a list of utxos sorted by different mix levels
		'''
		mix_utxo_list = {}
		for utxo, addrvalue in self.unspent.iteritems():
			mixdepth = self.addr_cache[addrvalue['address']][0]
			if mixdepth not in mix_utxo_list:
				mix_utxo_list[mixdepth] = []
			mix_utxo_list[mixdepth].append(utxo)
		return mix_utxo_list

	def select_utxos(self, mixdepth, amount):
		utxo_list = self.get_mix_utxo_list()[mixdepth]
		unspent = [{'utxo': utxo, 'value': self.unspent[utxo]['value']}
			for utxo in utxo_list]
		inputs = btc.select(unspent, amount)
		debug('for mixdepth=' + str(mixdepth) + ' amount=' + str(amount) + ' selected:')
		pprint.pprint(inputs)
		return [i['utxo'] for i in inputs]

	def sync_wallet(self, gaplimit=6):
		debug('synchronizing wallet')
		self.download_wallet_history(gaplimit)
		self.find_unspent_addresses()
		self.print_debug_wallet_info()

	def download_wallet_history(self, gaplimit=6):
		'''
		sets Wallet internal indexes to be at the next unused address
		'''
		addr_req_count = 20

		for mix_depth in range(self.max_mix_depth):
			for forchange in [0, 1]:
				unused_addr_count = 0
				last_used_addr = ''
				while unused_addr_count < gaplimit:
					addrs = [self.get_new_addr(mix_depth, forchange) for i in range(addr_req_count)]

					#TODO send a pull request to pybitcointools
					# because this surely should be possible with a function from it
					if get_network() == 'testnet':
						blockr_url = 'http://tbtc.blockr.io/api/v1/address/txs/'
					elif network == 'btc':
						blockr_url = 'http://btc.blockr.io/api/v1/address/txs/'
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
					self.index[mix_depth][forchange] = 0
				else:
					self.index[mix_depth][forchange] = self.addr_cache[last_used_addr][2] + 1

	def find_unspent_addresses(self):
		'''
		finds utxos in the wallet
		assumes you've already called download_wallet_history() so
		you know which addresses have been used
		'''

		addr_req_count = 20

		#TODO handle the case where there are so many addresses it cant
		# fit into one api call (>50 or so)
		addrs = {}
		for m in range(self.max_mix_depth):
			for forchange in [0, 1]:
				for n in range(self.index[m][forchange]):
					addrs[self.get_addr(m, forchange, n)] = m
		if len(addrs) == 0:
			print 'no tx used'
			return

		i = 0
		addrkeys = addrs.keys()
		while i < len(addrkeys):
			inc = min(len(addrkeys) - i, addr_req_count)
			req = addrkeys[i:i + inc]
			i += inc

			#TODO send a pull request to pybitcointools 
			# unspent() doesnt tell you which address, you get a bunch of utxos
			# but dont know which privkey to sign with
			if get_network() == 'testnet':
				blockr_url = 'http://tbtc.blockr.io/api/v1/address/unspent/'
			elif network == 'btc':
				blockr_url = 'http://btc.blockr.io/api/v1/address/unspent/'
			res = btc.make_request(blockr_url+','.join(req))
			data = json.loads(res)['data']
			if 'unspent' in data:
				data = [data]
			for dat in data:
				for u in dat['unspent']:
					self.unspent[u['tx']+':'+str(u['n'])] = {'address':
						dat['address'], 'value': int(u['amount'].replace('.', ''))}

	def print_debug_wallet_info(self):
		debug('printing debug wallet information')
		print 'utxos'
		pprint.pprint(self.unspent)
		print 'wallet.index'
		pprint.pprint(self.index)


#awful way of doing this, but works for now
# and -walletnotify for people who do
#timeouts in minutes
def add_addr_notify(address, unconfirmfun, confirmfun, unconfirmtimeout=5,
	unconfirmtimeoutfun=None, confirmtimeout=120, confirmtimeoutfun=None):

	class NotifyThread(threading.Thread):
		def __init__(self, address, unconfirmfun, confirmfun, unconfirmtimeout,
				unconfirmtimeoutfun, confirmtimeout, confirmtimeoutfun):
			threading.Thread.__init__(self)
			self.daemon = True
			self.address = address
			self.unconfirmfun = unconfirmfun
			self.confirmfun = confirmfun
			self.unconfirmtimeout = unconfirmtimeout*60
			self.unconfirmtimeoutfun = unconfirmtimeoutfun
			self.confirmtimeout = confirmtimeout*60
			self.confirmtimeoutfun = confirmtimeoutfun

		def run(self):
			st = int(time.time())
			while True:
				time.sleep(5)
				if int(time.time()) - st > self.unconfirmtimeout:
					if unconfirmtimeoutfun != None:
						unconfirmtimeoutfun()
					debug('checking for unconfirmed tx timed out')
					return
				if get_network() == 'testnet':
					blockr_url = 'http://tbtc.blockr.io/api/v1/address/balance/'
				else:
					blockr_url = 'http://btc.blockr.io/api/v1/address/balance/'
				res = btc.make_request(blockr_url + self.address + '?confirmations=0')
				data = json.loads(res)['data']
				if data['balance'] > 0:
					break
			self.unconfirmfun(data['balance']*1e8)
			st = int(time.time())
			while True:
				time.sleep(5 * 60)
				if int(time.time()) - st > self.confirmtimeout:
					if confirmtimeoutfun != None:
						confirmtimeoutfun()
					debug('checking for confirmed tx timed out')
					return
				if get_network() == 'testnet':
					blockr_url = 'http://tbtc.blockr.io/api/v1/address/txs/'
				else:
					blockr_url = 'http://btc.blockr.io/api/v1/address/txs/'
				res = btc.make_request(blockr_url + self.address + '?confirmations=0')
				data = json.loads(res)['data']
				if data['nb_txs'] == 0:
					continue
				if data['txs'][0]['confirmations'] >= 1: #confirmation threshold
					break
			self.confirmfun(data['txs'][0]['confirmations'],
				data['txs'][0]['tx'], data['txs'][0]['amount']*1e8)

	NotifyThread(address, unconfirmfun, confirmfun, unconfirmtimeout,
		unconfirmtimeoutfun, confirmtimeout, confirmtimeoutfun).start()


def calc_cj_fee(ordertype, cjfee, cj_amount):
	real_cjfee = None
	if ordertype == 'absorder':
		real_cjfee = int(cjfee)
	elif ordertype == 'relorder':
		real_cjfee = int((Decimal(cjfee) * Decimal(cj_amount)).quantize(Decimal(1)))
	else:
		raise RuntimeError('unknown order type: ' + str(ordertype))
	return real_cjfee

def calc_total_input_value(utxos):
	input_sum = 0
	for utxo in utxos:
		tx = btc.blockr_fetchtx(utxo[:64], get_network())
		input_sum += int(btc.deserialize(tx)['outs'][int(utxo[65:])]['value'])
	return input_sum

def choose_order(db, cj_amount, n):
	
	sqlorders = db.execute('SELECT * FROM orderbook;').fetchall()
	orders = [(o['counterparty'], o['oid'],	calc_cj_fee(o['ordertype'], o['cjfee'], cj_amount))
		for o in sqlorders if cj_amount >= o['minsize'] and cj_amount <= o['maxsize']]
	orders = sorted(orders, key=lambda k: k[2])
	debug('considered orders = ' + str(orders))
	total_cj_fee = 0
	chosen_orders = []
	for i in range(n):
		chosen_order = orders[0] #choose the cheapest, later this will be chosen differently
		orders = [o for o in orders if o[0] != chosen_order[0]] #remove all orders from that same counterparty
		chosen_orders.append(chosen_order)
		total_cj_fee += chosen_order[2]
	chosen_orders = [o[:2] for o in chosen_orders]
	return dict(chosen_orders), total_cj_fee

def nCk(n, k):
	'''
	n choose k
	'''
	return factorial(n) / factorial(k) / factorial(n - k)

def create_combination(li, n):
	'''
	Creates a list of combinations of elements of a given list
	For example, combination(['apple', 'orange', 'pear'], 2)
		= [('apple', 'orange'), ('apple', 'pear'), ('orange', 'pear')]
	'''
	if n < 2:
		raise ValueError('n must be >= 2')
	result = []
	if n == 2:
		#creates a list oft
		for i, e1 in enumerate(li):
			for e2 in li[i+1:]:
				result.append((e1, e2))
	else:
		for i, e in enumerate(li):
			if len(li[i:]) < n:
				#there wont be 
				continue
			combn1 = create_combination(li[i:], n - 1)
			for c in combn1:
				if e not in c:
					result.append((e,) + c)

	assert len(result) == nCk(len(li), n)
	return result

def choose_sweep_order(db, my_total_input, my_tx_fee, n):
	'''
	choose an order given that we want to be left with no change
	i.e. sweep an entire group of utxos

	solve for cjamount when mychange = 0
	for an order with many makers, a mixture of absorder and relorder
	mychange = totalin - cjamount - mytxfee - sum(absfee) - sum(relfee*cjamount)
	=> 0 = totalin - mytxfee - sum(absfee) - cjamount*(1 + sum(relfee))
	=> cjamount = (totalin - mytxfee - sum(absfee)) / (1 + sum(relfee))
	'''
	def calc_zero_change_cj_amount(ordercombo):
		sumabsfee = 0
		sumrelfee = Decimal('0')
		for order in ordercombo:
			if order['ordertype'] == 'absorder':
				sumabsfee += int(order['cjfee'])
			elif order['ordertype'] == 'relorder':
				sumrelfee += Decimal(order['cjfee'])
			else:
				raise RuntimeError('unknown order type: ' + str(ordertype))
		cjamount = (my_total_input - my_tx_fee - sumabsfee) / (1 + sumrelfee)
		cjamount = int(cjamount.quantize(Decimal(1)))
		return cjamount

	def amount_in_range(ordercombo, cjamount):
		for order in ordercombo:
			if order['maxsize'

	sqlorders = db.execute('SELECT * FROM orderbook;').fetchall()
	orderkeys = ['counterparty', 'oid', 'ordertype', 'minsize', 'maxsize', 'txfee', 'cjfee']
	orderlist = [dict([(k, o[k]) for k in orderkeys]) for o in sqlorders]

	ordercombos = create_combination(orderlist, n)

	print 'with cjamount'
	ordercombos = [(c, calc_zero_change_cj_amount(c)) for c in ordercombos]
	#ordercombos = [for oc in ordercombos if oc[1] > ]
	ordercombos = sorted(ordercombos, key=lambda k: k[1])
	pprint.pprint(ordercombos)
	return None

	orders = [(o['counterparty'], o['oid'],	calc_zero_change_cj_amount(o['ordertype'], o['cjfee']),
		o['minsize'], o['maxsize']) for o in sqlorders]
	#filter cj_amounts that are not in range
	orders = [o[:3] for o in orders if o[2] >= o[3] and o[2] <= o[4]]
	orders = sorted(orders, key=lambda k: k[2])
	print 'sweep orders = ' + str(orders)
	return orders[-1] #choose one with the highest cj_amount, most left over after paying everything else
