#! /usr/bin/env python
from __future__ import absolute_import
'''Test of unusual transaction types creation and push to
network to check validity.'''

import sys
import os
import time
import binascii
import pexpect
import random
import subprocess
import unittest
from commontest import local_command, interact, make_wallets

import bitcoin as btc
import pytest
from joinmarket import load_program_config, jm_single
from joinmarket import get_p2pk_vbyte, get_log, Wallet
from joinmarket.support import chunks, select_gradual, \
     select_greedy, select_greediest

log = get_log()
#just a random selection of pubkeys for receiving multisigs;
#if we ever need the privkeys, they are in a json file somewhere
vpubs = ["03e9a06e539d6bf5cf1ca5c41b59121fa3df07a338322405a312c67b6349a707e9",
         "0280125e42c1984923106e281615dfada44d38c4125c005963b322427110d709d6",
         "02726fa5b19e9406aaa46ee22fd9e81a09dd5eb7c87505b93a11efcf4b945e778c",
         "03600a739be32a14938680b3b3d61b51f217a60df118160d0decab22c9e1329862",
         "028a2f126e3999ff66d01dcb101ab526d3aa1bf5cbdc4bde14950a4cead95f6fcb",
         "02bea84d70e74f7603746b62d79bf035e16d982b56e6a1ee07dfd3b9130e8a2ad9"]


@pytest.mark.parametrize(
    "nw, wallet_structures, mean_amt, sdev_amt, amount, pubs, k", [
        (1, [[2, 1, 4, 0, 0]], 4, 1.4, 600000000, vpubs[1:4], 2),
        (1, [[3, 3, 0, 0, 3]], 4, 1.4, 100000000, vpubs[:4], 3),
    ])
def test_create_p2sh_output_tx(setup_tx_creation, nw, wallet_structures,
                               mean_amt, sdev_amt, amount, pubs, k):
    wallets = make_wallets(nw, wallet_structures, mean_amt, sdev_amt)
    for w in wallets.values():
        jm_single().bc_interface.sync_wallet(w['wallet'])
    for k, w in enumerate(wallets.values()):
        wallet = w['wallet']
        ins_full = wallet.select_utxos(0, amount)
        script = btc.mk_multisig_script(pubs, k)
        #try the alternative argument passing
        pubs.append(k)
        script2 = btc.mk_multisig_script(*pubs)
        assert script2 == script
        output_addr = btc.scriptaddr(script, magicbyte=196)
        txid = make_sign_and_push(ins_full,
                                  wallet,
                                  amount,
                                  output_addr=output_addr)
        assert txid


def make_sign_and_push(ins_full,
                       wallet,
                       amount,
                       output_addr=None,
                       change_addr=None,
                       hashcode=btc.SIGHASH_ALL):
    total = sum(x['value'] for x in ins_full.values())
    ins = ins_full.keys()
    #random output address and change addr
    output_addr = wallet.get_new_addr(1, 1) if not output_addr else output_addr
    change_addr = wallet.get_new_addr(1, 0) if not change_addr else change_addr
    outs = [{'value': amount,
             'address': output_addr}, {'value': total - amount - 100000,
                                       'address': change_addr}]

    tx = btc.mktx(ins, outs)
    de_tx = btc.deserialize(tx)
    for index, ins in enumerate(de_tx['ins']):
        utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
        addr = ins_full[utxo]['address']
        priv = wallet.get_key_from_addr(addr)
        if index % 2:
            priv = binascii.unhexlify(priv)
        tx = btc.sign(tx, index, priv, hashcode=hashcode)
    #pushtx returns False on any error
    print btc.deserialize(tx)
    return jm_single().bc_interface.pushtx(tx)


def test_create_sighash_txs(setup_tx_creation):
    #non-standard hash codes:
    for sighash in [btc.SIGHASH_ANYONECANPAY + btc.SIGHASH_SINGLE,
                    btc.SIGHASH_NONE, btc.SIGHASH_SINGLE]:
        wallet = make_wallets(1, [[2, 0, 0, 0, 1]], 3)[0]['wallet']
        jm_single().bc_interface.sync_wallet(wallet)
        amount = 350000000
        ins_full = wallet.select_utxos(0, amount)
        print "using hashcode: " + str(sighash)
        txid = make_sign_and_push(ins_full, wallet, amount, hashcode=sighash)
        assert txid

    #Create an invalid sighash single (too many inputs)
    extra = wallet.select_utxos(4, 100000000)  #just a few more inputs
    ins_full.update(extra)
    with pytest.raises(Exception) as e_info:
        txid = make_sign_and_push(ins_full,
                                  wallet,
                                  amount,
                                  hashcode=btc.SIGHASH_SINGLE)

    #trigger insufficient funds
    with pytest.raises(Exception) as e_info:
        fake_utxos = wallet.select_utxos(4, 1000000000)


def test_spend_p2sh_utxos(setup_tx_creation):
    #make a multisig address from 3 privs
    privs = [chr(x) * 32 + '\x01' for x in range(1, 4)]
    pubs = [btc.privkey_to_pubkey(binascii.hexlify(priv)) for priv in privs]
    script = btc.mk_multisig_script(pubs, 2)
    msig_addr = btc.scriptaddr(script, magicbyte=196)
    #pay into it
    wallet = make_wallets(1, [[2, 0, 0, 0, 1]], 3)[0]['wallet']
    jm_single().bc_interface.sync_wallet(wallet)
    amount = 350000000
    ins_full = wallet.select_utxos(0, amount)
    txid = make_sign_and_push(ins_full, wallet, amount, output_addr=msig_addr)
    assert txid
    #wait for mining
    time.sleep(4)
    #spend out; the input can be constructed from the txid of previous
    msig_in = txid + ":0"
    ins = [msig_in]
    #random output address and change addr
    output_addr = wallet.get_new_addr(1, 1)
    amount2 = amount - 50000
    outs = [{'value': amount2, 'address': output_addr}]
    tx = btc.mktx(ins, outs)
    sigs = []
    for priv in privs[:2]:
        sigs.append(btc.multisign(tx, 0, script, binascii.hexlify(priv)))
    tx = btc.apply_multisignatures(tx, 0, script, sigs)
    txid = jm_single().bc_interface.pushtx(tx)
    assert txid


@pytest.fixture(scope="module")
def setup_tx_creation():
    load_program_config()
