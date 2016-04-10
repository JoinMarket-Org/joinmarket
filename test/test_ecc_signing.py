#! /usr/bin/env python
from __future__ import absolute_import
'''Test ECDSA signing and other key operations, including legacy message
signature conversion.'''

import bitcoin as btc
import binascii
from joinmarket.configure import load_program_config, get_p2pk_vbyte
from joinmarket import jm_single
import json
import pytest

vectors = None

def test_valid_sigs(setup_ecc):
    for v in vectors['vectors']:
        msg = v['msg']
        sig = v['sig']
        priv = v['privkey']
        assert sig == btc.ecdsa_raw_sign(msg, priv, True, rawmsg=True)+'01'
        #check that the signature verifies against the key(pair)
        pubkey = btc.privtopub(priv)
        assert btc.ecdsa_raw_verify(msg, pubkey, sig[:-2], True, rawmsg=True)
        #check that it fails to verify against corrupted signatures
        for i in [0,1,2,4,7,25,55]:
            #corrupt one byte
            binsig = binascii.unhexlify(sig)
            checksig = binascii.hexlify(binsig[:i] + chr(
                (ord(binsig[i])+1) %256) + binsig[i+1:-1])
            
            #this kind of corruption will sometimes lead to an assert
            #failure (if the DER format is corrupted) and sometimes lead
            #to a signature verification failure.
            try:
                res = btc.ecdsa_raw_verify(msg, pubkey, checksig, True, rawmsg=True)
            except:
                continue
            assert res==False

def test_legacy_conversions(setup_ecc):
    #run some checks of legacy conversion
    for v in vectors['vectors']:
        msg = v['msg']
        sig = binascii.unhexlify(v['sig'])[:-1]
        priv = v['privkey']
        #check back-and-forth translation
        assert btc.legacy_ecdsa_verify_convert(
            btc.legacy_ecdsa_sign_convert(sig)) == sig
        
        #Correct cases passed, now try invalid signatures
        
        #screw up r-length
        bad_sig = sig[:3] + '\x90' + sig[4:]
        with pytest.raises(Exception) as e_info:
            fake_sig = btc.legacy_ecdsa_sign_convert(bad_sig)
        #screw up s-length
        rlen = ord(sig[3])
        bad_sig = sig[:4+rlen+1] + '\x90' + sig[4+rlen+2:]
        with pytest.raises(Exception) as e_info:
            fake_sig = btc.legacy_ecdsa_sign_convert(bad_sig)
        #valid length, but doesn't match s
        bad_sig = sig[:4+rlen+1] + '\x06' + sig[4+rlen+2:]
        with pytest.raises(Exception) as e_info:
            fake_sig = btc.legacy_ecdsa_sign_convert(bad_sig)    
        #invalid inputs to legacy convert
        #too short
        bad_sig = '\x07'*32
        assert not btc.legacy_ecdsa_verify_convert(bad_sig)
        #r OK, s too short
        bad_sig = '\x07'*64
        assert not btc.legacy_ecdsa_verify_convert(bad_sig)
        #note - no parity byte check, we don't bother (this is legacy)
        

@pytest.fixture(scope='module')
def setup_ecc():
    global vectors
    with open("test/ecc_sigs_rfc6979_valid.json", "r") as f:
        json_data = f.read()
    vectors = json.loads(json_data)    