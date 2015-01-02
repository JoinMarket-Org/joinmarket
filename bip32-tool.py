import bitcoin as btc
from common import Wallet

import sys
from optparse import OptionParser

#structure for cj market wallet
# m/0/ root key
# m/0/n/ nth mixing depth, where n=0 is unmixed, n=1 is coinjoined once, etc
#        pay in coins to mix at n=0 addresses
#	 coins move up a level when they are cj'd and stay at same level if they're the change from a coinjoin
#	 using coins from different levels as inputs to the same tx is probably detrimental to privacy
# m/0/n/0/k kth receive address, for mixing depth n
# m/0/n/1/k kth change address, for mixing depth n

parser = OptionParser(
    usage='usage: %prog [options] [seed] [method]',
    description='Does useful little lasts involving your bip32 wallet. The' +
    ' method is one of the following: Display- shows all addresses and balances'
    +
    '. Combine- combines all utxos into one output for each mixing level. Used for'
    + ' testing and is detrimental to privacy.')
parser.add_option('-p',
                  '--privkey',
                  action='store_true',
                  dest='showprivkey',
                  help='print private key along with address, default false')
parser.add_option('-m',
                  '--maxmixdepth',
                  action='store',
                  type='int',
                  dest='maxmixdepth',
                  default=2,
                  help='maximum mixing depth to look for, default=2')
parser.add_option('-g',
                  '--gap-limit',
                  action='store',
                  dest='gaplimit',
                  help='gap limit for wallet, default=6',
                  default=6)
(options, args) = parser.parse_args()

if len(args) < 1:
    parser.error('Needs a seed')
    sys.exit(0)
seed = args[0]

method = ('display' if len(args) == 1 else args[1].lower())

#seed = '256 bits of randomness'

print_privkey = options.showprivkey

wallet = Wallet(seed, options.maxmixdepth)
print 'downloading wallet history'
wallet.download_wallet_history(options.gaplimit)
wallet.find_unspent_addresses()

if method == 'display':
    for m in range(wallet.max_mix_depth):
        print 'mixing depth %d m/0/%d/' % (m, m)
        for forchange in [0, 1]:
            print(' ' +
                  ('receive'
                   if forchange == 0 else 'change') + ' addresses m/0/%d/%d/' %
                  (m, forchange))
            for k in range(wallet.index[m][forchange] + options.gaplimit):
                addr = wallet.get_addr(m, forchange, k)
                balance = 0.0
                for addrvalue in wallet.unspent.values():
                    if addr == addrvalue['address']:
                        balance += addrvalue['value']
                used = ('used' if k < wallet.index[m][forchange] else ' new')
                print '  m/0/%d/%d/%02d %s %s %.8fbtc' % (m, forchange, k, addr,
                                                          used, balance / 1e8)
elif method == 'combine':
    ins = []
    outs = []
    for m in range(wallet.max_mix_depth):
        for forchange in [0, 1]:
            balance = 0
            for k in range(wallet.index[m][forchange]):
                addr = wallet.get_addr(m, forchange, k)
                for utxo, addrvalue in wallet.unspent.iteritems():
                    if addr != addrvalue['address']:
                        continue
                    ins.append({'output': utxo})
                    balance += addrvalue['value']

            if balance > 0:
                destaddr = wallet.get_addr(m, forchange,
                                           wallet.index[m][forchange])
                outs.append({'address': destaddr, 'value': balance})
    tx = btc.mktx(ins, outs)
    for index, utxo in enumerate(ins):
        addr = wallet.unspent[utxo['output']]['address']
        tx = btc.sign(tx, index, wallet.get_key_from_addr(addr))
    print tx
