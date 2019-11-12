#! /usr/bin/env python2
from __future__ import absolute_import, print_function

import getpass
import json
import os
import sys
import sqlite3
from datetime import datetime
from optparse import OptionParser

from joinmarket import load_program_config, get_network, Wallet, encryptData, \
    get_p2pk_vbyte, jm_single, mn_decode, mn_encode, BitcoinCoreInterface, \
    JsonRpcError, sync_wallet

import bitcoin as btc

description = (
    'Does useful little tasks involving your bip32 wallet. The method is one of\n'
    'the following:\n\n'
    'display\t\t\tShows addresses and balances.\n'
    'displayall\t\tShows ALL addresses and balances.\n'
    'summary\t\t\tShows a summary of mixing depth balances.\n'
    'generate\t\tGenerates a new wallet.\n'
    'recover\t\t\tRecovers a wallet from the 12 word recovery seed.\n'
    'changepassphrase\tChange encyption password for specified wallet.\n'
    'showutxos\t\tShows all utxos in the wallet, including the\n'
        '\t\t\tcorresponding private keys if -p is chosen; the data\n'
        '\t\t\tis also written to a file "walletname.json.utxos" if\n'
        '\t\t\tthe option -u is chosen (so be careful about private\n'
        '\t\t\tkeys).\n'
    'showseed\t\tShows the wallet recovery seed and hex seed.\n'
    'importprivkey\t\tAdds privkeys to this wallet. Privkeys are spaces\n'
        '\t\t\tor commas separated.\n'
    'dumpprivkey\t\tExport a single private key, specify an hd wallet\n'
        '\t\t\tpath.\n'
    'listwallets\t\tLists all wallets with creator and timestamp.\n'
    'history\t\t\tShow all historical transaction details. Requires\n'
        '\t\t\tBitcoin Core.\n'
    'signmessage\t\tSign a message with the private key from an address\n'
    '\t\t\tin the wallet. Use with -H and specify an HD wallet\n'
    '\t\t\tpath for the address.')

parser = OptionParser(usage='usage: %prog [options] [wallet file] [method]\n\n' + description)

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
                  help='how many mixing depths to display, default=5')
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
parser.add_option('--csv',
                  action='store_true',
                  dest='csv',
                  default=False,
                  help=('When using the history method, output as csv'))
parser.add_option('-v', '--verbosity',
                  action='store',
                  type='int',
                  dest='verbosity',
                  default=1,
                  help=('History method verbosity, 0 (least) to 6 (most), '
                        '<=2 batches earnings, even values also list TXIDs'))
parser.add_option('--fast',
                  action='store_true',
                  dest='fastsync',
                  default=False,
                  help=('choose to do fast wallet sync, only for Core and '
                  'only for previously synced wallet'))
parser.add_option('-H',
                  '--hd',
                  action='store',
                  type='str',
                  dest='hd_path',
                  help='hd wallet path (e.g. m/0/0/0/000)')
(options, args) = parser.parse_args()

# if the index_cache stored in wallet.json is longer than the default
# then set maxmixdepth to the length of index_cache
maxmixdepth_configured = True
if not options.maxmixdepth:
    maxmixdepth_configured = False
    options.maxmixdepth = -1

noseed_methods = ['generate', 'recover', 'listwallets']
methods = ['display', 'displayall', 'summary', 'showseed', 'importprivkey',
    'history', 'showutxos']
methods.extend(noseed_methods)
noscan_methods = ['changepassphrase', 'showseed', 'importprivkey', 'dumpprivkey',
                  'signmessage']

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
    if method == 'history' and not isinstance(jm_single().bc_interface,
            BitcoinCoreInterface):
        print('showing history only available when using the Bitcoin Core ' +
            'blockchain interface')
        sys.exit(0)
    if method not in noscan_methods:
        # if nothing was configured, we override bitcoind's options so that
        # unconfirmed balance is included in the wallet display by default
        if 'listunspent_args' not in jm_single().config.options('POLICY'):
            jm_single().config.set('POLICY','listunspent_args', '[0]')

        sync_wallet(wallet, fast=options.fastsync)

if method == 'showutxos':
    unsp = {}
    max_tries = jm_single().config.getint("POLICY", "taker_utxo_retries")
    for mixdepth, utxos in wallet.get_utxos_by_mixdepth().iteritems():
        for u, av in utxos.iteritems():
            key = wallet.get_key_from_addr(av['address'])
            tries = btc.podle.get_podle_tries(u, key, max_tries)
            tries_remaining = max(0, max_tries - tries);

            unsp[u] = {'mixdepth': mixdepth, 'address': av['address'], 'value': av['value'], 'tries': tries, 'tries_remaining': tries_remaining, 'external': False}

            if options.showprivkey:
                wifkey = btc.wif_compressed_privkey(key, vbyte=get_p2pk_vbyte())
                unsp[u]['privkey'] = wifkey

    used_commitments, external_commitments = btc.podle.get_podle_commitments()
    for u, ec in external_commitments.iteritems():
        tries = btc.podle.get_podle_tries(utxo=u, max_tries=max_tries, external=True)
        tries_remaining = max(0, max_tries - tries);
        unsp[u] = {'tries': tries, 'tries_remaining': tries_remaining, 'external': True}

    print(json.dumps(unsp, indent=4))
    sys.exit(0)

if method == 'display' or method == 'displayall' or method == 'summary':

    def cus_print(s):
        if method != 'summary':
            print(s)

    total_balance = 0
    for m in range(wallet.max_mix_depth):
        cus_print('mixing depth %d m/0/%d/' % (m, m))
        balance_depth = 0
        for forchange in [0, 1]:
            if forchange == 0:
                xpub_key = btc.bip32_privtopub(wallet.keys[m][forchange])
            else:
                xpub_key = ''
            cus_print(' ' + ('external' if forchange == 0 else 'internal') +
                      ' addresses m/0/%d/%d' % (m, forchange) + ' ' + xpub_key)

            for k in range(wallet.index[m][forchange] + options.gaplimit):
                addr = wallet.get_addr(m, forchange, k)
                balance = 0.0
                for addrvalue in wallet.unspent.values():
                    if addr == addrvalue['address']:
                        balance += addrvalue['value']
                balance_depth += balance
                used = ('used' if k < wallet.index[m][forchange] else ' new')
                if options.showprivkey:
                    privkey = btc.wif_compressed_privkey(
                    wallet.get_key(m, forchange, k), get_p2pk_vbyte())
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
                    wip_privkey = btc.wif_compressed_privkey(
                    privkey, get_p2pk_vbyte())
                else:
                    wip_privkey = ''
                cus_print(' ' * 13 + '%-35s%s %.8f btc %s' % (
                    addr, used, balance / 1e8, wip_privkey))
        total_balance += balance_depth
        print('for mixdepth=%d balance=%.8fbtc' % (m, balance_depth / 1e8))
    print('total balance = %.8fbtc' % (total_balance / 1e8))
elif method == 'generate' or method == 'recover':

    def query_yes_no(question, default="yes"):
        valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
        if default is None:
            prompt = " [y/n] "
        elif default == "yes":
            prompt = " [Y/n] "
        elif default == "no":
            prompt = " [y/N] "
        else:
            raise ValueError("invalid default answer: '%s'" % default)

        while True:
            sys.stdout.write(question + prompt)
            choice = raw_input().lower()
            if default is not None and choice == '':
                return valid[default]
            elif choice in valid:
                return valid[choice]
            else:
                sys.stdout.write("Please respond with 'yes' or 'no' "
                       "(or 'y' or 'n').\n")

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
    if password == "":
        print('============= WARNING =============')
        print('Using no password is very dangerous')
        print('===================================')
        abort = query_yes_no('Abort?')
        if abort:
            sys.exit(0)
    password_key = btc.bin_dbl_sha256(password)
    encrypted_seed = encryptData(password_key, seed.decode('hex'))
    timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    walletfile = json.dumps({'creator': 'joinmarket project',
                             'creation_time': timestamp,
                             'encrypted_seed': encrypted_seed.encode('hex'),
                             'network': get_network()})

    default_walletname = 'wallet.json'
    walletpath = os.path.join('wallets', default_walletname)
    input_greeting = 'Input wallet file name (default: wallet.json): '
    i = 1
    while os.path.isfile(walletpath):
        temp_walletname = default_walletname
        default_walletname = 'wallet{0}.json'.format(i)
        walletpath = os.path.join('wallets', default_walletname)
        input_greeting = input_greeting.replace(temp_walletname, default_walletname)
        i += 1

    walletname = raw_input(input_greeting)
    if len(walletname) == 0:
        walletname = default_walletname
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
elif method == 'changepassphrase':
    """ Changes encryption password directly..
    Replaces old encrypted seed with new seed. Users should have their seed
    backed up
    """
    seed = wallet.seed # old seed
    words = mn_encode(seed)
    print("WARNING: Please remember to have a backup of the seed or old" +
    " wallet.json before attempting to change the passphrase.")
    password = getpass.getpass('Enter new wallet encryption passphrase: ')
    password2 = getpass.getpass('Reenter new wallet encryption passphrase: ')
    if password != password2:
        print('ERROR. Passwords did not match')
        sys.exit(0)
    password_key = btc.bin_dbl_sha256(password)
    encrypted_seed = encryptData(password_key, seed.decode('hex'))
    walletname = args[0] # wallet name
    walletpath = os.path.join('wallets', walletname)
    fd = open(walletpath, 'r')
    walletfile = fd.read()
    fd.close()
    walletdata = json.loads(walletfile)
    walletdata['encrypted_seed'] = encrypted_seed.encode('hex')
    walletfile = json.dumps(walletdata)
    fd = open(walletpath, 'w')
    fd.write(walletfile)
    fd.close()
    print(walletname + ": passphrase has been updated")
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
    if len(args) > 3 and args[2] == \
            'cli-import-WARNING-DANGEROUS-DONT-USE-WITHOUT-UNDERSTANDING':
        privkeys = args[3]
    else:
        privkeys = raw_input('Enter private key(s) to import: ')
    privkeys = privkeys.split(',') if ',' in privkeys else privkeys.split()
    # TODO read also one key for each line
    for privkey in privkeys:
        # TODO is there any point in only accepting wif format? check what
        # other wallets do
        privkey_bin = btc.from_wif_privkey(privkey,
                                        vbyte=get_p2pk_vbyte()).decode('hex')[:-1]
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
elif method == 'dumpprivkey':
    if options.hd_path.startswith('m/0/'):
        m, forchange, k = [int(y) for y in options.hd_path[4:].split('/')]
        key = wallet.get_key(m, forchange, k)
        wifkey = btc.wif_compressed_privkey(key, vbyte=get_p2pk_vbyte())
        print(wifkey)
    else:
        print('%s is not a valid hd wallet path' % options.hd_path)
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
elif method == 'signmessage':
    message = args[2]
    if options.hd_path.startswith('m/0/'):
        m, forchange, k = [int(y) for y in options.hd_path[4:].split('/')]
        key = wallet.get_key(m, forchange, k)
        addr = btc.privkey_to_address(key, magicbyte=get_p2pk_vbyte())
        print('Using address: ' + addr)
    else:
        print('%s is not a valid hd wallet path' % options.hd_path)
    sig = btc.ecdsa_sign(message, key, formsg=True)
    print("Signature: " + str(sig))
    print("To verify this in Bitcoin Core use the RPC command 'verifymessage'")
elif method == 'history':
    #sort txes in a db because python can be really bad with large lists
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    tx_db = con.cursor()
    tx_db.execute("CREATE TABLE transactions(txid TEXT, "
                  "blockhash TEXT, blocktime INTEGER);")
    jm_single().debug_silence[0] = True
    wallet_name = jm_single().bc_interface.get_wallet_name(wallet)
    for wn in [wallet_name, ""]:
        buf = range(1000)
        t = 0
        while len(buf) == 1000:
            buf = jm_single().bc_interface.rpc('listtransactions', [wn,
                1000, t, True])
            t += len(buf)
            tx_data = ((tx['txid'], tx['blockhash'], tx['blocktime']) for tx
                in buf if 'txid' in tx and 'blockhash' in tx and 'blocktime'
                in tx)
            tx_db.executemany('INSERT INTO transactions VALUES(?, ?, ?);',
                tx_data)
    txes = tx_db.execute('SELECT DISTINCT txid, blockhash, blocktime '
                         'FROM transactions ORDER BY blocktime').fetchall()
    wallet_addr_cache = wallet.addr_cache
    wallet_addr_set = set(wallet_addr_cache.keys())

    def s():
        return ',' if options.csv else ' '
    def sat_to_str(sat):
        return '%.8f'%(sat/1e8)
    def sat_to_str_p(sat):
        return '%+.8f'%(sat/1e8)
    def skip_n1(v):
        return '% 2s'%(str(v)) if v != -1 else ' #'
    def skip_n1_btc(v):
        return sat_to_str(v) if v != -1 else '#' + ' '*10
    def print_row(index, time, tx_type, amount, delta, balance, cj_n,
                  miner_fees, utxo_count, mixdepth_src, mixdepth_dst, txid):
        data = [index, datetime.fromtimestamp(time).strftime("%Y-%m-%d %H:%M"),
                tx_type, sat_to_str(amount), sat_to_str_p(delta),
                sat_to_str(balance), skip_n1(cj_n), sat_to_str(miner_fees),
                '% 3d' % utxo_count, skip_n1(mixdepth_src), skip_n1(mixdepth_dst)]
        if options.verbosity % 2 == 0: data += [txid]
        print(s().join(map('"{}"'.format, data)))

    field_names = ['tx#', 'timestamp', 'type', 'amount/btc',
        'balance-change/btc', 'balance/btc', 'coinjoin-n', 'total-fees',
        'utxo-count', 'mixdepth-from', 'mixdepth-to']
    if options.verbosity % 2 == 0: field_names += ['txid']
    if options.csv:
        print('Bumping verbosity level to 4 due to --csv flag')
        options.verbosity = 1
    if options.verbosity > 0: print(s().join(field_names))
    if options.verbosity <= 2: cj_batch = [0]*8 + [[]]*2
    balance = 0
    utxo_count = 0
    deposits = []
    deposit_times = []
    for i, tx in enumerate(txes):
        rpctx = jm_single().bc_interface.rpc('gettransaction', [tx['txid']])
        txhex = str(rpctx['hex'])
        txd = btc.deserialize(txhex)
        output_addr_values = dict(((btc.script_to_address(sv['script'],
            get_p2pk_vbyte()), sv['value']) for sv in txd['outs']))
        our_output_addrs = wallet_addr_set.intersection(
            output_addr_values.keys())

        from collections import Counter
        value_freq_list = sorted(Counter(output_addr_values.values())
            .most_common(), key=lambda x: -x[1])
        non_cj_freq = 0 if len(value_freq_list)==1 else sum(zip(
            *value_freq_list[1:])[1])
        is_coinjoin = (value_freq_list[0][1] > 1 and value_freq_list[0][1] in
            [non_cj_freq, non_cj_freq+1])
        cj_amount = value_freq_list[0][0]
        cj_n = value_freq_list[0][1]

        rpc_inputs = []
        for ins in txd['ins']:
            try:
                wallet_tx = jm_single().bc_interface.rpc('gettransaction',
                    [ins['outpoint']['hash']])
            except JsonRpcError:
                continue
            input_dict = btc.deserialize(str(wallet_tx['hex']))['outs'][ins[
                'outpoint']['index']]
            rpc_inputs.append(input_dict)

        rpc_input_addrs = set((btc.script_to_address(ind['script'],
            get_p2pk_vbyte()) for ind in rpc_inputs))
        our_input_addrs = wallet_addr_set.intersection(rpc_input_addrs)
        our_input_values = [ind['value'] for ind in rpc_inputs if btc.
            script_to_address(ind['script'], get_p2pk_vbyte()) in
            our_input_addrs]
        our_input_value = sum(our_input_values)
        utxos_consumed = len(our_input_values)

        tx_type = None
        amount = 0
        delta_balance = 0
        fees = 0
        mixdepth_src = -1
        mixdepth_dst = -1
        #TODO this seems to assume all the input addresses are from the same
        # mixdepth, which might not be true
        if len(our_input_addrs) == 0 and len(our_output_addrs) > 0:
            #payment to us
            amount = sum([output_addr_values[a] for a in our_output_addrs])
            tx_type = 'deposit    '
            cj_n = -1
            delta_balance = amount
            mixdepth_dst = tuple(wallet_addr_cache[a][0] for a in
                our_output_addrs)
            if len(mixdepth_dst) == 1:
                mixdepth_dst = mixdepth_dst[0]
        elif len(our_input_addrs) > 0 and len(our_output_addrs) == 0:
            #we swept coins elsewhere
            if is_coinjoin:
                tx_type = 'cj sweepout'
                amount = cj_amount
                fees = our_input_value - cj_amount
            else:
                tx_type = 'sweep out  '
                amount = sum([v for v in output_addr_values.values()])
                fees = our_input_value - amount
            delta_balance = -our_input_value
            mixdepth_src = wallet_addr_cache[list(our_input_addrs)[0]][0]
        elif len(our_input_addrs) > 0 and len(our_output_addrs) == 1:
            #payment out somewhere with our change address getting the remaining
            change_value = output_addr_values[list(our_output_addrs)[0]]
            if is_coinjoin:
                tx_type = 'cj withdraw'
                amount = cj_amount
            else:
                tx_type = 'withdraw'
                #TODO does tx_fee go here? not my_tx_fee only?
                amount = our_input_value - change_value
                cj_n = -1
            delta_balance = change_value - our_input_value
            fees = our_input_value - change_value - cj_amount
            mixdepth_src = wallet_addr_cache[list(our_input_addrs)[0]][0]
        elif len(our_input_addrs) > 0 and len(our_output_addrs) == 2:
            #payment to self
            out_value = sum([output_addr_values[a] for a in our_output_addrs])
            if not is_coinjoin:
                print('this is wrong TODO handle non-coinjoin internal')
            tx_type = 'cj internal'
            amount = cj_amount
            delta_balance = out_value - our_input_value
            mixdepth_src = wallet_addr_cache[list(our_input_addrs)[0]][0]
            cj_addr = list(set([a for a,v in output_addr_values.iteritems()
                if v == cj_amount]).intersection(our_output_addrs))[0]
            mixdepth_dst = wallet_addr_cache[cj_addr][0]
        else:
            tx_type = 'unknown type'
        balance += delta_balance
        utxo_count += (len(our_output_addrs) - utxos_consumed)
        index = '% 4d'%(i)
        if options.verbosity > 0:
            if options.verbosity <= 2:
                n = cj_batch[0]
                if tx_type == 'cj internal':
                    cj_batch[0] += 1
                    cj_batch[1] += rpctx['blocktime']
                    cj_batch[2] += amount
                    cj_batch[3] += delta_balance
                    cj_batch[4] = balance
                    cj_batch[5] += cj_n
                    cj_batch[6] += fees
                    cj_batch[7] += utxo_count
                    cj_batch[8] += [mixdepth_src]
                    cj_batch[9] += [mixdepth_dst]
                elif tx_type != 'unknown type':
                    if n > 0:
                        # print the previously-accumulated batch
                        print_row('N='+str(n), cj_batch[1]/n, 'cj batch',
                                  cj_batch[2], cj_batch[3], cj_batch[4],
                                  cj_batch[5]/n, cj_batch[6], cj_batch[7]/n,
                                  min(cj_batch[8]), max(cj_batch[9]), '...')
                    cj_batch = [0]*8 + [[]]*2 # reset the batch collector
                    # print batch terminating row
                    print_row(index, rpctx['blocktime'], tx_type, amount,
                              delta_balance, balance, cj_n, fees, utxo_count,
                              mixdepth_src, mixdepth_dst, tx['txid'])
            elif options.verbosity >= 5 or \
                 (options.verbosity >= 3 and tx_type != 'unknown type'):
                print_row(index, rpctx['blocktime'], tx_type, amount,
                          delta_balance, balance, cj_n, fees, utxo_count,
                          mixdepth_src, mixdepth_dst, tx['txid'])

        if tx_type != 'cj internal':
            deposits.append(delta_balance)
            deposit_times.append(rpctx['blocktime'])

    # we could have a leftover batch!
    if options.verbosity <= 2:
        n = cj_batch[0]
        if n > 0:
            print_row('N='+str(n), cj_batch[1]/n, 'cj batch', cj_batch[2],
                      cj_batch[3], cj_batch[4], cj_batch[5]/n, cj_batch[6],
                      cj_batch[7]/n, min(cj_batch[8]), max(cj_batch[9]), '...')

    bestblockhash = jm_single().bc_interface.rpc('getbestblockhash', [])
    try:
        #works with pruning enabled, but only after v0.12
        now = jm_single().bc_interface.rpc('getblockheader', [bestblockhash]
            )['time']
    except JsonRpcError:
        now = jm_single().bc_interface.rpc('getblock', [bestblockhash])['time']
    print('     %s best block is %s' % (datetime.fromtimestamp(now)
        .strftime("%Y-%m-%d %H:%M"), bestblockhash))
    print('total profit = ' + str(float(balance - sum(deposits)) / float(100000000)) + ' BTC')
    try:
        #https://gist.github.com/chris-belcher/647da261ce718fc8ca10
        import numpy as np
        from scipy.optimize import brentq
        deposit_times = np.array(deposit_times)
        now -= deposit_times[0]
        deposit_times -= deposit_times[0]
        deposits = np.array(deposits)
        def f(r, deposits, deposit_times, now, final_balance):
            return np.sum(np.exp((now - deposit_times) / 60.0 / 60 / 24 /
                365)**r * deposits) - final_balance
        r = brentq(f, a=1, b=-1, args=(deposits, deposit_times, now,
            balance))
        print('continuously compounded equivalent annual interest rate = ' +
            str(r * 100) + ' %')
        print('(as if yield generator was a bank account)')
    except ImportError:
        print('numpy/scipy not installed, unable to calculate effective ' +
            'interest rate')

    total_wallet_balance = sum(wallet.get_balance_by_mixdepth().values())
    if balance != total_wallet_balance:
        print(('BUG ERROR: wallet balance (%s) does not match balance from ' +
            'history (%s)') % (sat_to_str(total_wallet_balance),
            sat_to_str(balance)))
    if utxo_count != len(wallet.unspent):
        print(('BUG ERROR: wallet utxo count (%d) does not match utxo count from ' +
            'history (%s)') % (len(wallet.unspent), utxo_count))
