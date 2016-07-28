#! /usr/bin/env python
from __future__ import absolute_import
"""A very simple command line tool to import utxos to be used
as commitments into joinmarket's commitments.json file, allowing
users to retry transactions more often without getting banned by
the anti-snooping feature employed by makers.
"""

import binascii
import sys
from optparse import OptionParser
import bitcoin as btc

from joinmarket import load_program_config
from joinmarket import jm_single, get_p2pk_vbyte

def quit(parser, errmsg):
    parser.error(errmsg)
    sys.exit(0)

def get_utxo_info(upriv):
    """Verify that the input string parses correctly as (utxo, priv)
    and return that.
    """
    try:
        u, priv = upriv.split(',')
        u = u.strip()
        priv = priv.strip()
        txid, n = u.split(':')
        assert len(txid)==64
        assert len(n) in [1,2]
        n = int(n)
        assert n in range(256)
    except:
        #not sending data to stdout in case privkey info
        print "Failed to parse utxo information for utxo"
    try:
        hexpriv = btc.from_wif_privkey(priv, vbyte=get_p2pk_vbyte())
    except:
        print "failed to parse privkey, make sure it's WIF compressed format."
    return u, priv
    
def validate_utxo_data(utxo_datas):
    """For each txid: N, privkey, first
    convert the privkey and convert to address,
    then use the blockchain instance to look up
    the utxo and check that its address field matches.
    """
    for u, priv in utxo_datas:
        print 'validating this utxo: ' + str(u)
        hexpriv = btc.from_wif_privkey(priv, vbyte=get_p2pk_vbyte())
        addr = btc.privkey_to_address(hexpriv, magicbyte=get_p2pk_vbyte())
        print 'claimed address: ' + addr
        res = jm_single().bc_interface.query_utxo_set([u])
        print 'blockchain shows this data: ' + str(res)
        if len(res) != 1:
            print "utxo not found on blockchain: " + str(u)
            return False
        if res[0]['address'] != addr:
            print "privkey corresponds to the wrong address for utxo: " + str(u)
            print "blockchain returned address: " + res[0]['address']
            print "your privkey gave this address: " + addr
            return False
    print 'all utxos validated OK'
    return True

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
        'usage: %prog [options] [txid:n] [WIF commpressed private key]',
        description="Adds one or more utxos to the list that can be used to make"
                    "commitments for anti-snooping. Note that this utxo, and its"
                    "PUBkey, will be revealed to makers, so consider the privacy"
                    " implication."
                    
                    " It may be useful to those who are having trouble making"
                    " coinjoins due to several unsuccessful attempts (especially"
                    " if your joinmarket wallet is new)."
                    
                    " 'Utxo' means unspent transaction output, it must not"
                    " already be spent."
                    
                    " BE CAREFUL about passing private keys on the command line!"
                    " Don't do this in insecure environments."
                    
                    " Also note this ONLY works for standard (p2pkh) utxos."
    )
    parser.add_option(
        '-r',
        '--read-from-file',
        action='store',
        type='str',
        dest='in_file',
        help='name of plain text file containing utxos, one per line, format (txid:N), (WIF compressed privkey)'
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
    (options, args) = parser.parse_args()
    load_program_config()
    utxo_data = []
    if options.in_file:
        with open(options.in_file, "rb") as f:
            utxo_info = f.readlines()
            print utxo_info
        for ul in utxo_info:
            ul = ul.rstrip()
            if ul:
                u, priv = get_utxo_info(ul)
                if not u:
                    quit(parser, "Failed to parse utxo info: " + str(ul))
                utxo_data.append((u, priv))
    elif len(args) == 2:
        u, priv = args[:2]
        u, priv = get_utxo_info(','.join([u, priv]))
        if not u:
            quit(parser, "Failed to parse utxo info: " + str(args[:2]))
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
