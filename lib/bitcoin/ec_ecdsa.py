import secp256k1
import binascii

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
    res = newpub.multiply(s)
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
    res = p1.add_privkey(newpriv2)
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


