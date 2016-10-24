#! /usr/bin/env python
from __future__ import absolute_import
"""A simple command line tool to create a bunch
of utxos from one (thus giving more potential commitments
for a Joinmarket user, although of course it may be useful
for other reasons).
"""

import binascii
import sys, os
#needed until Jmkt is a package
script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(script_dir))
from optparse import OptionParser
from commitment_utils import get_utxo_info, validate_utxo_data, quit
import bitcoin as btc
from pprint import pformat
from joinmarket import load_program_config
from joinmarket.wallet import estimate_tx_fee
from joinmarket import jm_single, get_p2pk_vbyte, validate_address, get_log

log = get_log()

def sign(utxo, priv, destaddrs):
    """Sign a tx sending the amount amt, from utxo utxo,
    equally to each of addresses in list destaddrs,
    after fees; the purpose is to create a large
    number of utxos.
    """
    results = validate_utxo_data([(utxo, priv)], retrieve=True)
    if not results:
        return False
    assert results[0][0] == utxo
    amt = results[0][1]
    ins = [utxo]
    estfee = estimate_tx_fee(1, len(destaddrs))
    outs = []
    share = int((amt - estfee) / len(destaddrs))
    fee = amt - share*len(destaddrs)
    assert fee >= estfee
    log.info("Using fee: " + str(fee))
    for i, addr in enumerate(destaddrs):
        outs.append({'address': addr, 'value': share})
    unsigned_tx = btc.mktx(ins, outs)
    return btc.sign(unsigned_tx, 0, btc.from_wif_privkey(
        priv, vbyte=get_p2pk_vbyte()))
    
def main():
    parser = OptionParser(
        usage=
        'usage: %prog [options] utxo destaddr1 destaddr2 ..',
        description="For creating multiple utxos from one (for commitments in JM)."
                    "Provide a utxo in form txid:N that has some unspent coins;"
                    "Specify a list of destination addresses and the coins will"
                    "be split equally between them (after bitcoin fees)."

                    "You'll be prompted to enter the private key for the utxo"
                    "during the run; it must be in WIF compressed format."
                    "After the transaction is completed, the utxo strings for"

                    "the new outputs will be shown."
                    "Note that these utxos will not be ready for use as external"

                    "commitments in Joinmarket until 5 confirmations have passed."
                    " BE CAREFUL about handling private keys!"
                    " Don't do this in insecure environments."
                    " Also note this ONLY works for standard (p2pkh) utxos."
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
    if len(args) < 2:
        quit(parser, 'Invalid syntax')
    u = args[0]
    priv = raw_input(
        'input private key for ' + u + ', in WIF compressed format : ')
    u, priv = get_utxo_info(','.join([u, priv]))
    if not u:
        quit(parser, "Failed to parse utxo info: " + u)
    destaddrs = args[1:]
    for d in destaddrs:
        if not validate_address(d):
            quit(parser, "Address was not valid; wrong network?: " + d)
    txsigned = sign(u, priv, destaddrs)
    log.debug("Got signed transaction:\n" + txsigned)
    log.debug("Deserialized:")
    log.debug(pformat(btc.deserialize(txsigned)))
    if raw_input('Would you like to push to the network? (y/n):')[0] != 'y':
        log.info("You chose not to broadcast the transaction, quitting.")
        return
    jm_single().bc_interface.pushtx(txsigned)

if __name__ == "__main__":
    main()
    print('done')
