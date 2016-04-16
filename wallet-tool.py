from __future__ import absolute_import, print_function

import datetime
import getpass
import json
import os
import sys
from optparse import OptionParser

from joinmarket import load_program_config, get_network, Wallet, encryptData, \
    get_p2pk_vbyte, jm_single, mn_decode, mn_encode, create_wallet_file

import bitcoin as btc

# data_dir = os.path.dirname(os.path.realpath(__file__))
# sys.path.insert(0, os.path.join(data_dir, 'joinmarket'))

# structure for cj market wallet
# m/0/ root key
# m/0/n/ nth mixing depth, where n=0 is unmixed, n=1 is coinjoined once, etc
# pay in coins to mix at n=0 addresses

# coins move up a level when they are cj'd and stay at same level if they're
# the change from a coinjoin

# using coins from different levels as inputs to the same tx is probably
# detrimental to privacy

# m/0/n/0/k kth external address, for mixing depth n
# m/0/n/1/k kth internal address, for mixing depth n

description = (
    'Does useful little tasks involving your bip32 wallet. The '
    'method is one of the following: (display) Shows addresses and '
    'balances. (displayall) Shows ALL addresses and balances. '
    '(summary) Shows a summary of mixing depth balances. (generate) '
    'Generates a new wallet. (recover) Recovers a wallet from the 12 '
    'word recovery seed. (showseed) Shows the wallet recovery seed '
    'and hex seed. (importprivkey) Adds privkeys to this wallet, '
    'privkeys are spaces or commas separated. (listwallets) Lists '
    'all wallets with creator and timestamp.')

parser = OptionParser(usage='usage: %prog [options] [wallet file] [method]',
                      description=description)

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
                  help='maximum mixing depth to look for, default=5')
parser.add_option('-g',
                  '--gap-limit',
                  type="int",
                  action='store',
                  dest='gaplimit',
                  help='gap limit for wallet, default=6',
                  default=6)
parser.add_option('-M',
                  '--mix-depth',
                  type="int",
                  action='store',
                  dest='mixdepth',
                  help='mixing depth to import private key into',
                  default=0)
(options, args) = parser.parse_args()

# if the index_cache stored in wallet.json is longer than the default
# then set maxmixdepth to the length of index_cache
maxmixdepth_configured = True
if not options.maxmixdepth:
    maxmixdepth_configured = False
    options.maxmixdepth = 5

noseed_methods = ['generate', 'recover', 'listwallets']
methods = ['display', 'displayall', 'summary', 'showseed', 'importprivkey']
methods.extend(noseed_methods)
noscan_methods = ['showseed', 'importprivkey']

if len(args) < 1:
    parser.error('Needs a wallet file or method')
    sys.exit(0)

load_program_config()

if args[0] in noseed_methods:
    method = args[0]
else:
    seed = args[0]
    method = ('display' if len(args) == 1 else args[1].lower())
    wallet = Wallet(seed,
                    options.maxmixdepth,
                    options.gaplimit,
                    extend_mixdepth=not maxmixdepth_configured,
                    storepassword=(method == 'importprivkey'))
    if method not in noscan_methods:
        # if nothing was configured, we override bitcoind's options so that
        # unconfirmed balance is included in the wallet display by default
        if 'listunspent_args' not in jm_single().config.options('POLICY'):
            jm_single().config.set('POLICY','listunspent_args', '[0]')
        jm_single().bc_interface.sync_wallet(wallet)

if method == 'display' or method == 'displayall' or method == 'summary':

    def cus_print(s):
        if method != 'summary':
            print(s)

    total_balance = 0
    for m in range(wallet.max_mix_depth):
        cus_print('mixing depth %d m/0/%d/' % (m, m))
        balance_depth = 0
        for forchange in [0, 1]:
            cus_print(' ' + ('external' if forchange == 0 else 'internal') +
                      ' addresses m/0/%d/%d/' % (m, forchange))

            for k in range(wallet.index[m][forchange] + options.gaplimit):
                addr = wallet.get_addr(m, forchange, k)
                balance = 0.0
                for addrvalue in wallet.unspent.values():
                    if addr == addrvalue['address']:
                        balance += addrvalue['value']
                balance_depth += balance
                used = ('used' if k < wallet.index[m][forchange] else ' new')
                if options.showprivkey:
                    if btc.secp_present:
                        privkey = btc.wif_compressed_privkey(
                    wallet.get_key(m, forchange, k), get_p2pk_vbyte())
                    else:
                        privkey = btc.encode_privkey(wallet.get_key(m,
                                forchange, k), 'wif_compressed', get_p2pk_vbyte())
                else:
                    privkey = ''
                if (method == 'displayall' or balance > 0 or
                    (used == ' new' and forchange == 0)):
                    cus_print('  m/0/%d/%d/%03d %-35s%s %.8f btc %s' %
                              (m, forchange, k, addr, used, balance / 1e8,
                               privkey))
        if m in wallet.imported_privkeys:
            cus_print(' import addresses')
            for privkey in wallet.imported_privkeys[m]:
                addr = btc.privtoaddr(privkey, magicbyte=get_p2pk_vbyte())
                balance = 0.0
                for addrvalue in wallet.unspent.values():
                    if addr == addrvalue['address']:
                        balance += addrvalue['value']
                used = (' used' if balance > 0.0 else 'empty')
                balance_depth += balance
                if options.showprivkey:
                    if btc.secp_present:
                        wip_privkey = btc.wif_compressed_privkey(
                    privkey, get_p2pk_vbyte())
                    else:
                        wip_privkey = btc.encode_privkey(privkey,
                                            'wif_compressed', get_p2pk_vbyte())
                else:
                    wip_privkey = ''
                cus_print(' ' * 13 + '%-35s%s %.8f btc %s' % (
                    addr, used, balance / 1e8, wip_privkey))
        total_balance += balance_depth
        print('for mixdepth=%d balance=%.8fbtc' % (m, balance_depth / 1e8))
    print('total balance = %.8fbtc' % (total_balance / 1e8))
elif method == 'generate' or method == 'recover':
    if method == 'generate':
        seed = btc.sha256(os.urandom(64))[:32]
        words = mn_encode(seed)
        print('Write down this wallet recovery seed\n\n' + ' '.join(words) +
              '\n')
    elif method == 'recover':
        words = raw_input('Input 12 word recovery seed: ')
        words = words.split()  # default for split is 1 or more whitespace chars
        if len(words) != 12:
            print('ERROR: Recovery seed phrase must be exactly 12 words.')
            sys.exit(0)
        seed = mn_decode(words)
        print(seed)
    password = getpass.getpass('Enter wallet encryption passphrase: ')
    password2 = getpass.getpass('Reenter wallet encryption passphrase: ')
    if password != password2:
        print('ERROR. Passwords did not match')
        sys.exit(0)
    walletfile = create_wallet_file(password, seed)
    walletname = raw_input('Input wallet file name (default: wallet.json): ')
    if len(walletname) == 0:
        walletname = 'wallet.json'
    walletpath = os.path.join('wallets', walletname)
    # Does a wallet with the same name exist?
    if os.path.isfile(walletpath):
        print('ERROR: ' + walletpath + ' already exists. Aborting.')
        sys.exit(0)
    else:
        fd = open(walletpath, 'w')
        fd.write(walletfile)
        fd.close()
        print('saved to ' + walletname)
elif method == 'showseed':
    hexseed = wallet.seed
    print('hexseed = ' + hexseed)
    words = mn_encode(hexseed)
    print('Wallet recovery seed\n\n' + ' '.join(words) + '\n')
elif method == 'importprivkey':
    print('WARNING: This imported key will not be recoverable with your 12 ' +
          'word mnemonic seed. Make sure you have backups.')
    print('WARNING: Handling of raw ECDSA bitcoin private keys can lead to '
          'non-intuitive behaviour and loss of funds.\n  Recommended instead '
          'is to use the \'sweep\' feature of sendpayment.py ')
    privkeys = raw_input('Enter private key(s) to import: ')
    privkeys = privkeys.split(',') if ',' in privkeys else privkeys.split()
    # TODO read also one key for each line
    for privkey in privkeys:
        # TODO is there any point in only accepting wif format? check what
        # other wallets do
        if not btc.secp_present:
            privkey_format = btc.get_privkey_format(privkey)
            if privkey_format not in ['wif', 'wif_compressed']:
                print('ERROR: privkey not in wallet import format')
                print(privkey, 'skipped')
                continue
            if privkey_format == 'wif':
                # TODO if they actually use an unc privkey, make sure the unc
                # address is used

                # r = raw_input('WARNING: Using uncompressed private key, the vast ' +
                #   'majority of JoinMarket transactions use compressed keys\n' +
                #       'being so unusual is bad for privacy. Continue? (y/n):')
                # if r != 'y':
                #   sys.exit(0)
                print('Uncompressed privkeys not supported (yet)')
                print(privkey, 'skipped')
                continue
        if btc.secp_present:
            privkey_bin = btc.from_wif_privkey(privkey,
                                        vbyte=get_p2pk_vbyte()).decode('hex')[:-1]
        else:
            privkey_bin = btc.encode_privkey(privkey, 'hex').decode('hex')
        encrypted_privkey = encryptData(wallet.password_key, privkey_bin)
        if 'imported_keys' not in wallet.walletdata:
            wallet.walletdata['imported_keys'] = []
        wallet.walletdata['imported_keys'].append(
            {'encrypted_privkey': encrypted_privkey.encode('hex'),
             'mixdepth': options.mixdepth})
    if wallet.walletdata['imported_keys']:
        fd = open(wallet.path, 'w')
        fd.write(json.dumps(wallet.walletdata))
        fd.close()
        print('Private key(s) successfully imported')
elif method == 'listwallets':
    # Fetch list of wallets
    possible_wallets = []
    for (dirpath, dirnames, filenames) in os.walk('wallets'):
        possible_wallets.extend(filenames)
        # Breaking as we only want the top dir, not subdirs
        break
    # For each possible wallet file, read json to list
    walletjsons = []
    for possible_wallet in possible_wallets:
        fd = open(os.path.join('wallets', possible_wallet), 'r')
        try:
            walletfile = fd.read()
            walletjson = json.loads(walletfile)
            # Add filename to json format
            walletjson['filename'] = possible_wallet
            walletjsons.append(walletjson)
        except ValueError:
            pass
    # Sort wallets by date
    walletjsons.sort(key=lambda r: r['creation_time'])
    i = 1
    print(' ')
    for walletjson in walletjsons:
        print('Wallet #' + str(i) + ' (' + walletjson['filename'] + '):')
        print('Creation time:\t' + walletjson['creation_time'])
        print('Creator:\t' + walletjson['creator'])
        print('Network:\t' + walletjson['network'])
        print(' ')
        i += 1
    print(str(i - 1) + ' Wallets have been found.')
