import sys
import bitcoin as btc
import pytest
import json
from commontest import make_wallets
from joinmarket import load_program_config, get_p2pk_vbyte, get_log

log = get_log()

# This is a primitive version
# to test the basic concept is working (specifically the imports).
# It isn't required that the transaction is valid, only that a valid
# utxo from the wallet can extract a private key.
# A real test of donations fits into the tumbler test cases, although
# with effort an "intermediately realistic" version could be set up.


@pytest.mark.parametrize(
    "tx_type, tx_id, tx_hex, address",
    [("simple-tx",
      "f31916a1d398a4ec18d56a311c942bb6db934cee6aa8ac30af0b30aad9efb841",
      "0100000001c74265f31fc5e24895fdc83f7157cc40045235f3a71ae326a219de9de873" +
      "0d8b010000006a473044022076055917470b7ec4f4bb008096266cf816ebb089ad983e" +
      "6a0f63340ba0e6a6cb022059ec938b996a75db10504e46830e13d399f28191b9832bd5" +
      "f61df097b9e0d47801210291941334a00959af4aa5757abf81d2a7d1aca8adb3431c67" +
      "e89419271ba71cb4feffffff023cdeeb03000000001976a914a2426748f14eba44b3f6" +
      "abba3e8bce216ea233f388acf4ebf303000000001976a914bfa366464a464005ba0df8" +
      "6024a6c3ed859f03ac88ac33280600",
      "msWrR3Gm2mBmdLZH8vGHbHifM53N2vuYBq"),
     
     ])
def test_donation_address(setup_donations, tx_type, tx_id, tx_hex, address):
    wallets = make_wallets(1, wallet_structures=[[1,1,1,0,0]],
                               mean_amt=0.5)
    wallet = wallets[0]['wallet']
    priv, addr = donation_address(tx_hex, wallet)
    print addr
    #just a check that it doesn't throw
    sign_donation_tx(tx_hex, 0, priv)

if not btc.secp_present:
    #See note above, this is NOT the real code, see taker.py   
    def donation_address(tx, wallet):
	from bitcoin.main import multiply, G, deterministic_generate_k, add_pubkeys
	reusable_donation_pubkey = ('02be838257fbfddabaea03afbb9f16e852'
	                            '9dfe2de921260a5c46036d97b5eacf2a')
    
	privkey = wallet.get_key_from_addr(wallet.get_new_addr(0,0))
	msghash = btc.bin_txhash(tx, btc.SIGHASH_ALL)
	# generate unpredictable k
	global sign_k
	sign_k = deterministic_generate_k(msghash, privkey)
	c = btc.sha256(multiply(reusable_donation_pubkey, sign_k))
	sender_pubkey = add_pubkeys(
	        reusable_donation_pubkey, multiply(
	                G, c))
	sender_address = btc.pubtoaddr(sender_pubkey, get_p2pk_vbyte())
	log.debug('sending coins to ' + sender_address)
	return privkey, sender_address
    
    #See note above, this is NOT the real code, see taker.py
    def sign_donation_tx(tx, i, priv):
	from bitcoin.main import fast_multiply, decode_privkey, G, inv, N
	from bitcoin.transaction import der_encode_sig
	k = sign_k
	hashcode = btc.SIGHASH_ALL
	i = int(i)
	if len(priv) <= 33:
	    priv = btc.safe_hexlify(priv)
	pub = btc.privkey_to_pubkey(priv)
	address = btc.pubkey_to_address(pub)
	signing_tx = btc.signature_form(
	        tx, i, btc.mk_pubkey_script(address), hashcode)
    
	msghash = btc.bin_txhash(signing_tx, hashcode)
	z = btc.hash_to_int(msghash)
	# k = deterministic_generate_k(msghash, priv)
	r, y = fast_multiply(G, k)
	s = inv(k, N) * (z + r * decode_privkey(priv)) % N
	rawsig = 27 + (y % 2), r, s
    
	sig = der_encode_sig(*rawsig) + btc.encode(hashcode, 16, 2)
	# sig = ecdsa_tx_sign(signing_tx, priv, hashcode)
	txobj = btc.deserialize(tx)
	txobj["ins"][i]["script"] = btc.serialize_script([sig, pub])
	return btc.serialize(txobj)
else:
    def donation_address(cjtx, wallet):
	privkey = wallet.get_key_from_addr(wallet.get_new_addr(0,0))
	reusable_donation_pubkey = '02be838257fbfddabaea03afbb9f16e8529dfe2de921260a5c46036d97b5eacf2a'
	global sign_k
	import os
	import binascii
	sign_k = os.urandom(32)
	log.debug("Using the following nonce value: "+binascii.hexlify(sign_k))
	c = btc.sha256(btc.multiply(binascii.hexlify(sign_k),
                                    reusable_donation_pubkey, True))
	sender_pubkey = btc.add_pubkeys([reusable_donation_pubkey,
                                         btc.privtopub(c+'01', True)], True)
	sender_address = btc.pubtoaddr(sender_pubkey, get_p2pk_vbyte())
	log.debug('sending coins to ' + sender_address)
	return privkey, sender_address

    def sign_donation_tx(tx, i, priv):
	return btc.sign(tx, i, priv, usenonce=sign_k)
    
@pytest.fixture(scope="module")
def setup_donations():
    load_program_config()
