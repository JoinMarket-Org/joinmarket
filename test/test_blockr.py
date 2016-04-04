#! /usr/bin/env python
from __future__ import absolute_import
'''Blockchain access via blockr tests.'''

import sys
import os
import time
import binascii

import bitcoin as btc
import pytest
from joinmarket import load_program_config, jm_single
from joinmarket.blockchaininterface import BlockrInterface
from joinmarket import get_p2pk_vbyte, get_log, Wallet

log = get_log()

#TODO: some kind of mainnet testing, harder.
blockr_root_url = "https://tbtc.blockr.io/api/v1/"

def test_blockr_bad_request():
    with pytest.raises(Exception) as e_info:
        btc.make_request(blockr_root_url+"address/txs/", "0000")

def test_blockr_bad_pushtx():
    inps = [("00000000", "btc"), ("00000000", "testnet"),
            ('\x00'*8, "testnet"), ('\x00'*8, "x")]
    for i in inps:
        with pytest.raises(Exception) as e_info:
            btc.blockr_pushtx(i[0],i[1])

def test_bci_bad_pushtx():
    inps = [("00000000"), ('\x00'*8)]
    for i in inps:
        with pytest.raises(Exception) as e_info:
            btc.bci_pushtx(i[0])

def test_blockr_estimate_fee(setup_blockr):
    res = []
    for N in [1,3,6]:
        res.append(jm_single().bc_interface.estimate_fee_per_kb(N))
    assert res[0] >= res[2]
    #Note this can fail, it isn't very accurate.
    #assert res[1] >= res[2]
    #sanity checks:
    assert res[0] < 200000
    assert res[2] < 150000
        
@pytest.mark.parametrize(
    "net, seed, gaplimit, showprivkey, method",
    [
        ("testnet",
         #Dont take these testnet coins, itll botch up our tests!!
         "I think i did pretty good with Christmas",
         6,
         True,
         #option "displayall" here will show all addresses from beginning
         "display"),
    ])
def test_blockr_sync(setup_blockr, net, seed, gaplimit, showprivkey, method):
    jm_single().config.set("BLOCKCHAIN", "network", net)
    wallet = Wallet(seed, max_mix_depth = 5)
    jm_single().bc_interface.sync_wallet(wallet)
    
    #copy pasted from wallet-tool; some boiled down form of
    #this should really be in wallet.py in the joinmarket module.
    def cus_print(s):
            print s

    total_balance = 0
    for m in range(wallet.max_mix_depth):
        cus_print('mixing depth %d m/0/%d/' % (m, m))
        balance_depth = 0
        for forchange in [0, 1]:
            cus_print(' ' + ('external' if forchange == 0 else 'internal') +
                      ' addresses m/0/%d/%d/' % (m, forchange))

            for k in range(wallet.index[m][forchange] + gaplimit):
                addr = wallet.get_addr(m, forchange, k)
                balance = 0.0
                for addrvalue in wallet.unspent.values():
                    if addr == addrvalue['address']:
                        balance += addrvalue['value']
                balance_depth += balance
                used = ('used' if k < wallet.index[m][forchange] else ' new')
                if showprivkey:
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
        total_balance += balance_depth
        print('for mixdepth=%d balance=%.8fbtc' % (m, balance_depth / 1e8))
    assert total_balance == 96143257    
    

@pytest.fixture(scope="module")
def setup_blockr(request):
    def blockr_teardown():
        jm_single().config.set("BLOCKCHAIN", "blockchain_source", "regtest")
        jm_single().config.set("BLOCKCHAIN", "network", "testnet")
    request.addfinalizer(blockr_teardown)    
    load_program_config()
    jm_single().config.set("BLOCKCHAIN", "blockchain_source", "blockr")
    jm_single().bc_interface = BlockrInterface(True)
