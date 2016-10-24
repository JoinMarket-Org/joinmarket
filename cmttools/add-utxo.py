#! /usr/bin/env python
from __future__ import absolute_import
"""A very simple command line tool to import utxos to be used
as commitments into joinmarket's commitments.json file, allowing
users to retry transactions more often without getting banned by
the anti-snooping feature employed by makers.
"""

import binascii
import sys
import os
import json
from pprint import pformat

#needed until Jmkt is a package
script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(script_dir))

from optparse import OptionParser
import bitcoin as btc
from joinmarket import load_program_config, jm_single, get_p2pk_vbyte
from joinmarket import Wallet, sync_wallet
from commitment_utils import get_utxo_info, validate_utxo_data, quit

def add_external_commitments(utxo_datas):
    """Persist the PoDLE commitments for this utxo
    to the commitments.json file. The number of separate
    entries is dependent on the taker_utxo_retries entry, by
    default 3.
    """
    def generate_single_podle_sig(u, priv, i):
        """Make a podle entry for key priv at index i, using a dummy utxo value.
        This calls the underlying 'raw' code based on the class PoDLE, not the
        library 'generate_podle' which intelligently searches and updates commitments.
        """
        #Convert priv to hex
        hexpriv = btc.from_wif_privkey(priv, vbyte=get_p2pk_vbyte())
        podle = btc.PoDLE(u, hexpriv)
        r = podle.generate_podle(i)
        return (r['P'], r['P2'], r['sig'],
                r['e'], r['commit'])
    ecs = {}
    for u, priv in utxo_datas:
        ecs[u] = {}
        ecs[u]['reveal']={}
        for j in range(jm_single().config.getint("POLICY", "taker_utxo_retries")):
            P, P2, s, e, commit = generate_single_podle_sig(u, priv, j)
            if 'P' not in ecs[u]:
                ecs[u]['P']=P
            ecs[u]['reveal'][j] = {'P2':P2, 's':s, 'e':e}
        btc.add_external_commitments(ecs)

def main():
    parser = OptionParser(
        usage=
        'usage: %prog [options] [txid:n]',
        description="Adds one or more utxos to the list that can be used to make "
                    "commitments for anti-snooping. Note that this utxo, and its "
                    "PUBkey, will be revealed to makers, so consider the privacy "
                    "implication. "
                    
                    "It may be useful to those who are having trouble making "
                    "coinjoins due to several unsuccessful attempts (especially "
                    "if your joinmarket wallet is new). "
                    
                    "'Utxo' means unspent transaction output, it must not "
                    "already be spent. "
                    "The options -w, -r and -R offer ways to load these utxos "
                    "from a file or wallet. "
                    "If you enter a single utxo without these options, you will be "
                    "prompted to enter the private key here - it must be in "
                    "WIF compressed format. "

                    "BE CAREFUL about handling private keys! "
                    "Don't do this in insecure environments. "
                    
                    "Also note this ONLY works for standard (p2pkh) utxos."
    )
    parser.add_option(
        '-r',
        '--read-from-file',
        action='store',
        type='str',
        dest='in_file',
        help='name of plain text csv file containing utxos, one per line, format: '
        'txid:N, WIF-compressed-privkey'
    )
    parser.add_option(
        '-R',
        '--read-from-json',
        action='store',
        type='str',
        dest='in_json',
        help='name of json formatted file containing utxos with private keys, as '
        'output from "python wallet-tool.py -u -p walletname showutxos"'
        )
    parser.add_option(
        '-w',
        '--load-wallet',
        action='store',
        type='str',
        dest='loadwallet',
        help='name of wallet from which to load utxos and use as commitments.'
        )
    parser.add_option(
        '-g',
        '--gap-limit',
        action='store',
        type='int',
        dest='gaplimit',
        default = 6,
        help='Only to be used with -w; gap limit for Joinmarket wallet, default 6.'
    )
    parser.add_option(
        '-M',
        '--max-mixdepth',
        action='store',
        type='int',
        dest='maxmixdepth',
        default=5,
        help='Only to be used with -w; number of mixdepths for wallet, default 5.'
    )
    parser.add_option(
        '-d',
        '--delete-external',
        action='store_true',
        dest='delete_ext',
        help='deletes the current list of external commitment utxos',
        default=False
        )
    parser.add_option(
        '-v',
        '--validate-utxos',
        action='store_true',
        dest='validate',
        help='validate the utxos and pubkeys provided against the blockchain',
        default=False
    )
    parser.add_option(
        '-o',
        '--validate-only',
        action='store_true',
        dest='vonly',
        help='only validate the provided utxos (file or command line), not add',
        default=False
    )
    parser.add_option('--fast',
                      action='store_true',
                      dest='fastsync',
                      default=False,
                      help=('choose to do fast wallet sync, only for Core and '
                      'only for previously synced wallet'))
    (options, args) = parser.parse_args()
    load_program_config()
    utxo_data = []
    if options.delete_ext:
        other = options.in_file or options.in_json or options.loadwallet
        if len(args) > 0 or other:
            if raw_input("You have chosen to delete commitments, other arguments "
                         "will be ignored; continue? (y/n)") != 'y':
                print "Quitting"
                sys.exit(0)
        c, e = btc.get_podle_commitments()
        print pformat(e)
        if raw_input(
            "You will remove the above commitments; are you sure? (y/n): ") != 'y':
            print "Quitting"
            sys.exit(0)
        btc.update_commitments(external_to_remove=e)
        print "Commitments deleted."
        sys.exit(0)

    #Three options (-w, -r, -R) for loading utxo and privkey pairs from a wallet,
    #csv file or json file.
    if options.loadwallet:
        os.chdir('..') #yuck (see earlier comment about package)
        wallet = Wallet(options.loadwallet,
                            options.maxmixdepth,
                            options.gaplimit)
        os.chdir(os.path.join(os.getcwd(), 'cmttools'))
        sync_wallet(wallet, fast=options.fastsync)
        unsp = {}
        for u, av in wallet.unspent.iteritems():
                    addr = av['address']
                    key = wallet.get_key_from_addr(addr)
                    wifkey = btc.wif_compressed_privkey(key, vbyte=get_p2pk_vbyte())
                    unsp[u] = {'address': av['address'],
                               'value': av['value'], 'privkey': wifkey}
        for u, pva  in unsp.iteritems():
            utxo_data.append((u, pva['privkey']))
    elif options.in_file:
        with open(options.in_file, "rb") as f:
            utxo_info = f.readlines()
        for ul in utxo_info:
            ul = ul.rstrip()
            if ul:
                u, priv = get_utxo_info(ul)
                if not u:
                    quit(parser, "Failed to parse utxo info: " + str(ul))
                utxo_data.append((u, priv))
    elif options.in_json:
        if not os.path.isfile(options.in_json):
            print "File: " + options.in_json + " not found."
            sys.exit(0)
        with open(options.in_json, "rb") as f:
            try:
                utxo_json = json.loads(f.read())
            except:
                print "Failed to read json from " + options.in_json
                sys.exit(0)
        for u, pva in utxo_json.iteritems():
            utxo_data.append((u, pva['privkey']))
    elif len(args) == 1:
        u = args[0]
        priv = raw_input(
            'input private key for ' + u + ', in WIF compressed format : ')
        u, priv = get_utxo_info(','.join([u, priv]))
        if not u:
            quit(parser, "Failed to parse utxo info: " + u)
        utxo_data.append((u, priv))
    else:
        quit(parser, 'Invalid syntax')
    if options.validate or options.vonly:
        if not validate_utxo_data(utxo_data):
            quit(parser, "Utxos did not validate, quitting")
    if options.vonly:
        sys.exit(0)
    
    #We are adding utxos to the external list
    assert len(utxo_data)
    add_external_commitments(utxo_data)

if __name__ == "__main__":
    main()
    print('done')
