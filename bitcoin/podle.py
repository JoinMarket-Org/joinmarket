#Proof Of Discrete Logarithm Equivalence
#For algorithm steps, see https://gist.github.com/AdamISZ/9cbba5e9408d23813ca8
import secp256k1
import os
from py2specials import *
from py3specials import *

N = 115792089237316195423570985008687907852837564279074904382605163141518161494337
dummy_pub = secp256k1.PublicKey()

'''NUMS - an alternate basepoint on the secp256k1 curve
For background (taken from https://github.com/AdamISZ/ConfidentialTransactionsDoc/blob/master/essayonCT.pdf)
>>> import bitcoin as btc
>>> import os
>>>H_x = int(sha256(btc.encode_pubkey(btc.G,'hex').decode('hex')).hexdigest(),16)
>>> H_x
	36444060476547731421425013472121489344383018981262552973668657287772036414144L 
>>> H_y = pow(int(H_x*H_x*H_x + 7), int((btc.P+1)//4), int(btc.P))
>>> H_y
	93254584761608041185240733468443117438813272608612929589951789286136240436011L
>>> H = (H_x, H_y)
'''
J_raw = '0350929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0'
J = secp256k1.PublicKey(safe_from_hex(J_raw), raw=True)
        
def getP2(priv):
    priv_raw = priv.private_key
    return J.tweak_mul(priv_raw)
       
def generate_podle(priv):
    '''Given a raw private key, in hex format,
    construct a commitment sha256(P2), which is
    the hash of the value x*J, where x is the private
    key as a raw scalar, and J is a NUMS alternative
    basepoint on the Elliptic Curve. Also construct
    a signature (s,e) of Schnorr type, which will serve
    as a zero knowledge proof that the private key of P2
    is the same as the private key of P (=x*G).
    Signature is constructed as:
    s = k + x*e
    where k is a standard 32 byte nonce and:
    e = sha256(k*G || k*J || P || P2)
    '''
    if len(priv)==66 and priv[-2:]=='01':
        priv = priv[:-2]
    priv = secp256k1.PrivateKey(safe_from_hex(priv))
    P = priv.pubkey
    k = os.urandom(32)
    KG = secp256k1.PrivateKey(k).pubkey
    KJ = J.tweak_mul(k)
    P2 = getP2(priv)
    commitment = hashlib.sha256(P2.serialize()).digest()
    e = hashlib.sha256(''.join([x.serialize() for x in [KG, KJ, P, P2]])).digest()
    k_int = decode(k, 256)
    priv_int = decode(priv.private_key, 256)
    e_int = decode(e, 256)
    sig_int = (k_int + priv_int*e_int) % N
    sig = encode(sig_int, 256, minlen=32)
    P2hex, chex, shex, ehex = [safe_hexlify(x) for x in [P2.serialize(),commitment, sig, e]]
    return {'P2':P2hex, 'commit': chex, 'sig': shex, 'e':ehex}

def verify_podle(Pser, P2ser, sig, e, commitment):
    Pser, P2ser, sig, e, commitment = [safe_from_hex(x) for x in [Pser, P2ser, sig, e, commitment]]
    #check 1: Hash(P2ser) =?= commitment
    if not hashlib.sha256(P2ser).digest() == commitment:
        return False
    sig_priv = secp256k1.PrivateKey(sig,raw=True)
    sG = sig_priv.pubkey
    sJ = J.tweak_mul(sig)
    P = secp256k1.PublicKey(Pser, raw=True)
    P2 = secp256k1.PublicKey(P2ser, raw=True)
    e_int = decode(e, 256)
    minus_e = encode(-e_int % N, 256, minlen=32)
    minus_e_P = P.tweak_mul(minus_e)
    minus_e_P2 = P2.tweak_mul(minus_e)
    KG = dummy_pub.combine([sG.public_key, minus_e_P.public_key])
    KJ = dummy_pub.combine([sJ.public_key, minus_e_P2.public_key])
    KGser = secp256k1.PublicKey(KG).serialize()
    KJser = secp256k1.PublicKey(KJ).serialize()
    #check 2: e =?= H(K_G || K_J || P || P2)
    e_check = hashlib.sha256(KGser + KJser + Pser + P2ser).digest()
    if not e_check == e:
        return False
    return True

if __name__ == '__main__':
    
    for i in range(10000):
        priv = os.urandom(32)
        Priv = secp256k1.PrivateKey(priv)
        Pser = safe_hexlify(Priv.pubkey.serialize())
        podle_sig = generate_podle(safe_hexlify(priv))
        P2ser, s, e, commitment = (podle_sig['P2'], podle_sig['sig'], 
                                   podle_sig['e'], podle_sig['commit'])
        if not verify_podle(Pser, P2ser, s, e, commitment):
            print 'failed to verify'
