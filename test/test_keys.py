#! /usr/bin/env python
from __future__ import absolute_import
'''Public and private key validity and formatting tests.'''

import bitcoin as btc
import binascii
from joinmarket.configure import load_program_config, get_p2pk_vbyte
from joinmarket import jm_single
import json
import pytest


def test_wif_privkeys_invalid(setup_keys):
    #none of these are valid as any kind of key or address
    with open("test/base58_keys_invalid.json", "r") as f:
        json_data = f.read()
    invalid_key_list = json.loads(json_data)
    for k in invalid_key_list:
        bad_key = k[0]
        for netval in ["mainnet", "testnet"]:
            jm_single().config.set("BLOCKCHAIN", "network", netval)
            #if using py.test -s ; sanity check to see what's actually being tested
            print 'testing this key: ' + bad_key
            if "decode_privkey" in dir(btc):
                try:
                    bad_key_format = btc.get_privkey_format(bad_key)
                    print 'has correct format: ' + bad_key_format
                except:
                    pass
            #should throw exception
            with pytest.raises(Exception) as e_info:
                if "decode_privkey" in dir(btc):
                    from_wif_key = btc.decode_privkey(bad_key)
                else:
                    from_wif_key = btc.from_wif_compressed_privkey(
                        bad_key, btc.get_version_byte(bad_key))
                #in case the b58 check encoding is valid, we should
                #also check if the leading version byte is in the
                #expected set, and throw an error if not.
                if chr(btc.get_version_byte(bad_key)) not in '\x80\xef':
                    raise Exception("Invalid version byte")
                #the bitcoin library should throw
                #if the compression byte is not there (test not needed
                #for secp256k1 branch since the wif_compressed function checks)
                if "decode_privkey" in dir(btc):
                    if "compressed" in btc.get_privkey_format(bad_key) and \
                   btc.b58check_to_bin(x)[-1] != '\x01':
                        raise Exception("Invalid compression byte")


def test_wif_privkeys_valid(setup_keys):
    with open("test/base58_keys_valid.json", "r") as f:
        json_data = f.read()
    valid_keys_list = json.loads(json_data)
    for a in valid_keys_list:
        key, hex_key, prop_dict = a
        if prop_dict["isPrivkey"]:
            netval = "testnet" if prop_dict["isTestnet"] else "mainnet"
            jm_single().config.set("BLOCKCHAIN", "network", netval)
            print 'testing this key: ' + key
            assert chr(btc.get_version_byte(
                key)) in '\x80\xef', "not valid network byte"
            if "decode_privkey" in dir(btc):
                from_wif_key = btc.decode_privkey(key)
                expected_key = btc.decode_privkey(hex_key)
            else:
                comp = prop_dict["isCompressed"]
                from_wif_key = btc.from_wif_privkey(
                    key,
                    compressed=comp,
                    vbyte=btc.get_version_byte(key))
                expected_key = hex_key
                if comp: expected_key += '01'
            assert from_wif_key == expected_key, "Incorrect key decoding: " + \
                   str(from_wif_key) + ", should be: " + str(expected_key)


@pytest.fixture(scope="module")
def setup_keys():
    load_program_config()
