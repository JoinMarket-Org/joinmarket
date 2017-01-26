#! /usr/bin/env python
from __future__ import absolute_import
'''comments here'''

import sys
import time
import random
from commontest import make_wallets
import pytest

import bitcoin as btc
from joinmarket import load_program_config, jm_single, get_p2pk_vbyte
from joinmarket import tor_broadcast_tx

def test_p2p_broadcast(setup_tx_notify):
    #listen up kids, dont do this to generate private
    #keys that hold real money, or else you'll be robbed
    src_privkey = random.getrandbits(256)
    src_privkey = btc.encode(src_privkey, 16, 64) + '01'
    src_addr = btc.privtoaddr(src_privkey, magicbyte=get_p2pk_vbyte())
    dst_addr = btc.pubtoaddr('03' + btc.encode(random.getrandbits(256), 16),
        get_p2pk_vbyte())

    jm_single().bc_interface.rpc('importaddress', [src_addr, "", False])
    jm_single().bc_interface.rpc('importaddress', [dst_addr, "", False])
    jm_single().bc_interface.rpc('generatetoaddress', [1, src_addr])
    jm_single().bc_interface.rpc('generate', [101])
    src_utxos = jm_single().bc_interface.rpc('listunspent', [0, 500,
        [src_addr]])

    inputs = [{'output': src_utxos[0]['txid'] + ':' + str(src_utxos[0]['vout']
        )}]
    outs = [{'address': dst_addr, 'value': int(src_utxos[0]['amount']*1e8)}]
    tx = btc.mktx(inputs, outs)
    tx = btc.sign(tx, 0, src_privkey)

    bad_tx = random.getrandbits(len(tx)*4)
    bad_tx = btc.encode(bad_tx, 16, len(tx))

    utxo_before = jm_single().bc_interface.rpc('listunspent', [0, 500, [dst_addr]])

    #jm_single().bc_interface.rpc('sendrawtransaction', [tx])
    pushed = tor_broadcast_tx(tx, None, 'regtest',
        remote_hostport=('localhost', 18444))
    assert pushed

    pushed = tor_broadcast_tx(tx, None, 'regtest',
        remote_hostport=('localhost', 18444))
    assert not pushed #node should already have the same tx, reject

    pushed = tor_broadcast_tx(bad_tx, None, 'regtest',
        remote_hostport=('localhost', 18444))
    assert not pushed #bad tx should be rejected

    jm_single().bc_interface.rpc('generate', [1])
    utxo_after  = jm_single().bc_interface.rpc('listunspent', [0, 500, [dst_addr]])

    return len(utxo_after) - 1 == len(utxo_before)

@pytest.fixture(scope="module")
def setup_tx_notify():
    load_program_config()
