#!/usr/bin/python
from .py2specials import *
from .py3specials import *
import binascii
import hashlib
import re
import sys
import os
import base64
import time
import random
import hmac
from bitcoin.ripemd import *
import secp256k1

def privkey_to_address(priv, from_hex=True, magicbyte=0):
    return pubkey_to_address(privkey_to_pubkey(priv, from_hex), magicbyte)
privtoaddr = privkey_to_address

# Hashes
def bin_hash160(string):
    intermed = hashlib.sha256(string).digest()
    digest = ''
    try:
        digest = hashlib.new('ripemd160', intermed).digest()
    except:
        digest = RIPEMD160(intermed).digest()
    return digest

def hash160(string):
    return safe_hexlify(bin_hash160(string))

def bin_sha256(string):
    binary_data = string if isinstance(string, bytes) else bytes(string, 'utf-8')
    return hashlib.sha256(binary_data).digest()

def sha256(string):
    return bytes_to_hex_string(bin_sha256(string))

def bin_ripemd160(string):
    try:
        digest = hashlib.new('ripemd160', string).digest()
    except:
        digest = RIPEMD160(string).digest()
    return digest

def ripemd160(string):
    return safe_hexlify(bin_ripemd160(string))

def bin_dbl_sha256(s):
    bytes_to_hash = from_string_to_bytes(s)
    return hashlib.sha256(hashlib.sha256(bytes_to_hash).digest()).digest()

def dbl_sha256(string):
    return safe_hexlify(bin_dbl_sha256(string))

def bin_slowsha(string):
    string = from_string_to_bytes(string)
    orig_input = string
    for i in range(100000):
        string = hashlib.sha256(string + orig_input).digest()
    return string

def slowsha(string):
    return safe_hexlify(bin_slowsha(string))

def hash_to_int(x):
    if len(x) in [40, 64]:
        return decode(x, 16)
    return decode(x, 256)

def num_to_var_int(x):
    x = int(x)
    if x < 253: return from_int_to_byte(x)
    elif x < 65536: return from_int_to_byte(253)+encode(x, 256, 2)[::-1]
    elif x < 4294967296: return from_int_to_byte(254) + encode(x, 256, 4)[::-1]
    else: return from_int_to_byte(255) + encode(x, 256, 8)[::-1]

# WTF, Electrum?
def electrum_sig_hash(message):
    padded = b"\x18Bitcoin Signed Message:\n" + num_to_var_int(len(message)) + from_string_to_bytes(message)
    return bin_dbl_sha256(padded)

def random_key():
    # Gotta be secure after that java.SecureRandom fiasco...
    entropy = random_string(32) \
        + str(random.randrange(2**256)) \
        + str(int(time.time() * 1000000))
    return sha256(entropy)

def random_electrum_seed():
    entropy = os.urandom(32) \
        + str(random.randrange(2**256)) \
        + str(int(time.time() * 1000000))
    return sha256(entropy)[:32]

# Encodings

def b58check_to_bin(inp):
    leadingzbytes = len(re.match('^1*', inp).group(0))
    data = b'\x00' * leadingzbytes + changebase(inp, 58, 256)
    assert bin_dbl_sha256(data[:-4])[:4] == data[-4:]
    return data[1:-4]


def get_version_byte(inp):
    leadingzbytes = len(re.match('^1*', inp).group(0))
    data = b'\x00' * leadingzbytes + changebase(inp, 58, 256)
    assert bin_dbl_sha256(data[:-4])[:4] == data[-4:]
    return ord(data[0])


def hex_to_b58check(inp, magicbyte=0):
    return bin_to_b58check(binascii.unhexlify(inp), magicbyte)


def b58check_to_hex(inp):
    return safe_hexlify(b58check_to_bin(inp))

def pubkey_to_address(pubkey, magicbyte=0):
    if len(pubkey) in [66, 130]:
        return bin_to_b58check(
            bin_hash160(binascii.unhexlify(pubkey)), magicbyte)
    return bin_to_b58check(bin_hash160(pubkey), magicbyte)

pubtoaddr = pubkey_to_address

def wif_compressed_privkey(priv,vbyte=0):
    return bin_to_b58check(binascii.unhexlify(priv), 128+int(vbyte))

#Note: these 2 functions require priv/pubkeys in binary not hex
def ecdsa_sign(msg, priv):
    #Compatibility issue: old bots will be confused
    #by different msg hashing algo; need to keep electrum_sig_hash, temporarily.
    hashed_msg = electrum_sig_hash(msg)
    dersig = ecdsa_raw_sign(hashed_msg, priv, False, rawmsg=True)
    #see comments to legacy* functions
    sig = legacy_ecdsa_sign_convert(dersig)
    return base64.b64encode(sig)

def ecdsa_verify(msg, sig, pub):
    #See note to ecdsa_sign
    hashed_msg = electrum_sig_hash(msg)
    sig = base64.b64decode(sig)
    #see comments to legacy* functions
    sig = legacy_ecdsa_verify_convert(sig)
    if not sig:
        print 'legacy returned false'
        return False
    return ecdsa_raw_verify(hashed_msg, pub, sig, False,rawmsg=True)

#A sadly necessary hack until all joinmarket bots are running secp256k1 code.
#pybitcointools *message* signatures (not transaction signatures) used an old signature
#format, basically: [27+y%2] || 32 byte r || 32 byte s,
#instead of DER. These two functions translate the new version into the old so that 
#counterparty bots can verify successfully.
def legacy_ecdsa_sign_convert(dersig):
    #note there is no sanity checking of DER format (e.g. leading length byte)
    dersig = dersig[2:] #e.g. 3045
    rlen = ord(dersig[1]) #ignore leading 02
    if rlen==32:
        r = dersig[2:34]
        ssig = dersig[34:]
    elif rlen==33:
        r = dersig[3:35] #leading 00 in canonical DER stripped
        ssig = dersig[35:]
    else:
        raise Exception("Incorrectly formatted DER sig:"+binascii.hexlify(dersig))
    slen = ord(ssig[1]) #ignore leading 02
    if slen==32:
        s = ssig[2:34]
    elif slen==33:
        s = ssig[3:35] #leading 00 in canonical DER stripped
    else:
        raise Exception("Incorrectly formatted DER sig:"+binascii.hexlify(dersig))
    #note: in the original pybitcointools implementation, 
    #verification ignored the leading byte (it's only needed for pubkey recovery)
    #so we just ignore parity here.
    return chr(27)+r+s

def legacy_ecdsa_verify_convert(sig):
    sig = sig[1:] #ignore parity byte
    try:
        r, s = sig[:32],sig[32:]
    except:
        #signature is invalid.
        return False
    if not len(s)==32:
        #signature is invalid.
        return False
    #canonicalize r and s
    r, s = ['\x00'+x if ord(x[0])>127 else x for x in [r,s]]
    rlen = chr(len(r))
    slen = chr(len(s))
    total_len = 2+len(r)+2+len(s)
    return '\x30'+chr(total_len)+'\x02'+rlen+r+'\x02'+slen+s

#Use secp256k1 to handle all EC and ECDSA operations.
#Data types: only hex and binary.
#Compressed and uncompressed private and public keys.

def hexbin(func):
    '''To enable each function to 'speak' either hex or binary,
    requires that the decorated function's final positional argument
    is a boolean flag, True for hex and False for binary.
    '''
    def func_wrapper(*args, **kwargs):
        if args[-1]:
            newargs = []
            for arg in args[:-1]:
                if isinstance(arg, (list, tuple)):
                    newargs += [[x.decode('hex') for x in arg]]
                else:
                    newargs += [arg.decode('hex')]
            newargs += [False]
            returnval = func(*newargs, **kwargs)
            if isinstance(returnval, bool):
                return returnval
            else:
                return binascii.hexlify(returnval)
        else:
            return func(*args, **kwargs)
    return func_wrapper

def read_privkey(priv):
    if len(priv)==33:
        if priv[-1]=='\x01':
            compressed=True
        else:
            raise Exception("Invalid private key")
    elif len(priv)==32:
        compressed=False
    else:
        raise Exception("Invalid private key")
    return (compressed, priv[:32])

@hexbin
def privkey_to_pubkey(priv, usehex):
    '''Take 32/33 byte raw private key as input.
    If 32 bytes, return compressed (33 byte) raw public key.
    If 33 bytes, read the final byte as compression flag,
    and return compressed/uncompressed public key as appropriate.'''
    compressed, priv = read_privkey(priv)
    #secp256k1 checks for validity of key value.
    newpriv = secp256k1.PrivateKey(privkey=priv)
    return newpriv.pubkey.serialize(compressed=compressed)

privtopub = privkey_to_pubkey

@hexbin
def multiply(s, pub, usehex, rawpub=True):
    '''Input binary compressed pubkey P(33 bytes)
    and scalar s(32 bytes), return s*P.
    The return value is a binary compressed public key.
    Note that the called function does the type checking
    of the scalar s.
    ('raw' options passed in)
    '''
    newpub = secp256k1.PublicKey(pub, raw=rawpub)
    res = newpub.tweak_mul(s)
    return res.serialize()

@hexbin
def add_pubkeys(pubkeys, usehex):
    '''Input a list of binary compressed pubkeys
    and return their sum as a binary compressed pubkey.'''
    r = secp256k1.PublicKey() #dummy holding object
    pubkey_list = [secp256k1.PublicKey(x, raw=True).public_key for x in pubkeys]
    r.combine(pubkey_list)
    return r.serialize()

@hexbin
def add_privkeys(priv1, priv2, usehex):
    '''Add privkey 1 to privkey 2.
    Input keys must be in binary either compressed or not.
    Returned key will have the same compression state.
    Error if compression state of both input keys is not the same.'''
    y, z = [read_privkey(x) for x in [priv1, priv2]]
    if y[0] != z[0]:
        raise Exception("cannot add privkeys, mixed compression formats")
    else:
        compressed = y[0]
    newpriv1, newpriv2 = (y[1], z[1])
    p1 = secp256k1.PrivateKey(newpriv1, raw=True)
    res = p1.tweak_add(newpriv2)
    if compressed:
        res += '\x01'
    return res

@hexbin
def ecdsa_raw_sign(msg, priv, usehex, rawpriv=True, rawmsg=False, usenonce=None):
    '''Take the binary message msg and sign it with the private key
    priv. 
    By default priv is just a 32 byte string, if rawpriv is false
    it is assumed to be DER encoded.
    If rawmsg is True, no sha256 hash is applied to msg before signing.
    In this case, msg must be a precalculated hash (256 bit).
    If rawmsg is False, the secp256k1 lib will hash the message as part 
    of the ECDSA-SHA256 signing algo.
    If usenonce is not None, its value is passed to the secp256k1 library
    sign() function as the ndata value, which is then used in conjunction
    with a custom nonce generating function, such that the nonce used in the ECDSA
    sign algorithm is exactly that value (ndata there, usenonce here). 32 bytes.
    Return value: the calculated signature.'''
    if rawmsg and len(msg) != 32:
        raise Exception("Invalid hash input to ECDSA raw sign.")
    if rawpriv:
        compressed, p = read_privkey(priv)
        newpriv = secp256k1.PrivateKey(p, raw=True)
    else:
        newpriv = secp256k1.PrivateKey(priv,raw=False)
    if usenonce and len(usenonce) != 32:
        raise ValueError("Invalid nonce passed to ecdsa_sign: "+str(usenonce))
    
    sig = newpriv.ecdsa_sign(msg, raw=rawmsg, randnonce=usenonce)
    return newpriv.ecdsa_serialize(sig)

@hexbin
def ecdsa_raw_verify(msg, pub, sig, usehex, rawmsg=False):
    '''Take the binary message msg and binary signature sig,
    and verify it against the pubkey pub.
    If rawmsg is True, no sha256 hash is applied to msg before verifying.
    In this case, msg must be a precalculated hash (256 bit).
    If rawmsg is False, the secp256k1 lib will hash the message as part 
    of the ECDSA-SHA256 verification algo.
    Return value: True if the signature is valid for this pubkey, False 
    otherwise. '''
    if rawmsg and len(msg) != 32:
        raise Exception("Invalid hash input to ECDSA raw sign.")
    newpub = secp256k1.PublicKey(pubkey = pub, raw=True)
    sigobj = newpub.ecdsa_deserialize(sig)
    return newpub.ecdsa_verify(msg, sigobj, raw=rawmsg)



