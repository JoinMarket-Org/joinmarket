
import sys, os
import getpass, json, datetime
from optparse import OptionParser
data_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(data_dir, 'lib'))

import bitcoin as btc
from common import Wallet, load_program_config, get_addr_vbyte
import common
import old_mnemonic

#structure for cj market wallet
# m/0/ root key
# m/0/n/ nth mixing depth, where n=0 is unmixed, n=1 is coinjoined once, etc
#        pay in coins to mix at n=0 addresses
#	 coins move up a level when they are cj'd and stay at same level if they're the change from a coinjoin
#	 using coins from different levels as inputs to the same tx is probably detrimental to privacy
# m/0/n/0/k kth receive address, for mixing depth n
# m/0/n/1/k kth change address, for mixing depth n


parser = OptionParser(usage='usage: %prog [options] [wallet file] [method]',
	description='Does useful little tasks involving your bip32 wallet. The'
	+ ' method is one of the following: display- shows addresses and balances.'
	+ ' displayall - shows ALL addresses and balances.'
	+ ' summary - shows a summary of mixing depth balances.' 
	+ ' generate - generates a new wallet.'
	+ ' recover - recovers a wallet from the 12 word recovery seed.'
	+ ' showseed - shows the wallet recovery seed and hex seed.')
parser.add_option('-p', '--privkey', action='store_true', dest='showprivkey',
	help='print private key along with address, default false')
parser.add_option('-m', '--maxmixdepth', action='store', type='int', dest='maxmixdepth',
	default=5, help='maximum mixing depth to look for, default=5')
parser.add_option('-g', '--gap-limit', type="int", action='store', dest='gaplimit',
	help='gap limit for wallet, default=6', default=6)
(options, args) = parser.parse_args()

noseed_methods = ['generate', 'recover']
methods = ['display', 'displayall', 'summary'] + noseed_methods

if len(args) < 1:
	parser.error('Needs a wallet file or method')
	sys.exit(0)
load_program_config()

if args[0] in noseed_methods:
	method = args[0]
else:
	seed = args[0]
	method = ('display' if len(args) == 1 else args[1].lower())
	wallet = Wallet(seed, options.maxmixdepth)
	if method != 'showseed':
		common.bc_interface.sync_wallet(wallet, options.gaplimit)

if method == 'display' or method == 'displayall':
	total_balance = 0
	for m in range(wallet.max_mix_depth):
		print 'mixing depth %d m/0/%d/' % (m, m)
		balance_depth = 0
		for forchange in [0, 1]:
			print(' ' + ('receive' if forchange==0 else 'change') +
				' addresses m/0/%d/%d/' % (m, forchange))
			for k in range(wallet.index[m][forchange] + options.gaplimit):
				addr = wallet.get_addr(m, forchange, k)
				balance = 0.0
				for addrvalue in wallet.unspent.values():
					if addr == addrvalue['address']:
						balance += addrvalue['value']
				balance_depth += balance
				used = ('used' if k < wallet.index[m][forchange] else ' new')
				privkey = btc.encode_privkey(wallet.get_key(m, forchange, k), 'wif_compressed',
					get_addr_vbyte()) if options.showprivkey else ''
				if method == 'displayall' or  balance > 0 or (used == ' new' and forchange==0):
					print '  m/0/%d/%d/%03d %-35s%s %.8f btc %s' % (m, forchange, k, addr, used, balance/1e8, privkey)
		print 'for mixdepth=%d balance=%.8fbtc' % (m, balance_depth/1e8)
		total_balance += balance_depth
	print 'total balance = %.8fbtc' % (total_balance/1e8)
elif method == 'summary':
	total_balance = 0
	for m in range(wallet.max_mix_depth):
		balance_depth = 0
		for forchange in [0, 1]:
			for k in range(wallet.index[m][forchange]):
				addr = wallet.get_addr(m, forchange, k)
				for addrvalue in wallet.unspent.values():
					if addr == addrvalue['address']:
						balance_depth += addrvalue['value']
		print 'for mixdepth=%d balance=%.8fbtc' % (m, balance_depth/1e8)
		total_balance += balance_depth
	print 'total balance = %.8fbtc' % (total_balance/1e8)
elif method == 'generate' or method == 'recover':
	try:
		import aes
	except ImportError:
		print 'You must install slowaes\nTry running: sudo pip install slowaes'
		sys.exit(0)
	if method == 'generate':
		seed = btc.sha256(os.urandom(64))[:32]
		words = old_mnemonic.mn_encode(seed)
		print 'Write down this wallet recovery seed\n\n' + ' '.join(words) + '\n'
	elif method == 'recover':
		words = raw_input('Input 12 word recovery seed: ')
		words = words.split(' ')
		seed = old_mnemonic.mn_decode(words)
		print seed
	password = getpass.getpass('Enter wallet encryption passphrase: ')
	password2 = getpass.getpass('Reenter wallet encryption passphrase: ')
	if password != password2:
		print 'ERROR. Passwords did not match'
		sys.exit(0)
	password_key = btc.bin_dbl_sha256(password)
	encrypted_seed = aes.encryptData(password_key, seed.decode('hex'))
	timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
	walletfile = json.dumps({'creator': 'joinmarket project', 'creation_time': timestamp,
		'encrypted_seed': encrypted_seed.encode('hex'), 'network': common.get_network()})
	walletname = raw_input('Input wallet file name (default: wallet.json): ')
	if len(walletname) == 0:
		walletname = 'wallet.json'
	fd = open(os.path.join('wallets', walletname), 'w')
	fd.write(walletfile)
	fd.close()
	print 'saved to ' + walletname
elif method == 'showseed':
	hexseed = wallet.seed
	print 'hexseed = ' + hexseed
	words = old_mnemonic.mn_encode(hexseed)
	print 'Wallet recovery seed\n\n' + ' '.join(words) + '\n'
