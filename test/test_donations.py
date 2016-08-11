#! /usr/bin/env python
from __future__ import absolute_import
'''Tests of reusable donation pubkey code using secp256k1 '''

import binascii
import time
import bitcoin as btc
import secp256k1
import pytest

from commontest import make_wallets
from joinmarket import load_program_config, get_p2pk_vbyte, get_log, jm_single
from joinmarket import get_irc_mchannels, Taker
from joinmarket.configure import donation_address

log = get_log()

@pytest.mark.parametrize(
    "amount",
    [(100000000
      ),
     ])
def test_donation_address(setup_donations, amount):
    wallets = make_wallets(1, wallet_structures=[[1,1,1,0,0]],
                               mean_amt=0.5)
    wallet = wallets[0]['wallet']
    jm_single().bc_interface.sync_wallet(wallet)
    #make a rdp from a simple privkey
    rdp_priv = "\x01"*32
    reusable_donation_pubkey = binascii.hexlify(secp256k1.PrivateKey(
        privkey=rdp_priv, raw=True, ctx=btc.ctx).pubkey.serialize())    
    dest_addr, sign_k = donation_address(reusable_donation_pubkey)
    print dest_addr
    jm_single().bc_interface.rpc('importaddress',
                                [dest_addr, '', False])    
    ins_full = wallet.unspent
    total = sum(x['value'] for x in ins_full.values())
    ins = ins_full.keys()
    output_addr = wallet.get_new_addr(1, 1)
    fee_est = 10000
    outs = [{'value': amount,
             'address': dest_addr}, {'value': total - amount - fee_est,
                                       'address': output_addr}]

    tx = btc.mktx(ins, outs)
    de_tx = btc.deserialize(tx)
    for index, ins in enumerate(de_tx['ins']):
        utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
        addr = ins_full[utxo]['address']
        priv = wallet.get_key_from_addr(addr)
        priv = binascii.unhexlify(priv)
        usenonce = binascii.unhexlify(sign_k) if index == 0 else None
        if index == 0:
            log.debug("Applying rdp to input: " + str(ins))
        tx = btc.sign(tx, index, priv, usenonce=usenonce)
    #pushtx returns False on any error
    push_succeed = jm_single().bc_interface.pushtx(tx)
    if push_succeed:
        log.debug(btc.txhash(tx))
    else:
        assert False
    #Role of receiver: regenerate the destination private key,
    #and address, from the nonce of the first input; check it has
    #received the coins.
    detx = btc.deserialize(tx)
    first_utxo_script = detx['ins'][0]['script']
    sig, pub = btc.deserialize_script(first_utxo_script)
    log.debug(sig)
    sig = binascii.unhexlify(sig)
    kGlen = ord(sig[3])
    kG = sig[4:4+kGlen]
    log.debug(binascii.hexlify(kG))
    if kG[0] == "\x00":
        kG = kG[1:]
    #H(rdp private key * K) + rdp should be ==> dest addr
    #Open issue: re-introduce recovery without ECC shenanigans
    #Just cheat by trying both signs for pubkey
    coerced_kG_1 = "02" + binascii.hexlify(kG)
    coerced_kG_2 = "03" + binascii.hexlify(kG)
    for coerc in [coerced_kG_1, coerced_kG_2]:
        c = btc.sha256(btc.multiply(binascii.hexlify(rdp_priv), coerc, True))
        pub_check = btc.add_pubkeys([reusable_donation_pubkey,
                                     btc.privtopub(c+'01', True)], True)
        addr_check = btc.pubtoaddr(pub_check, get_p2pk_vbyte())
        log.debug("Found checked address: " + addr_check)
        if addr_check == dest_addr:
            time.sleep(3)
            received = jm_single().bc_interface.get_received_by_addr(
                    [dest_addr], None)['data'][0]['balance']
            assert received == amount
            return
    assert False

@pytest.fixture(scope="module")
def setup_donations():
    load_program_config()
