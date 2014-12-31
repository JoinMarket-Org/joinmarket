#A wrapper for public key
#authenticated encryption
#using Diffie Hellman key
#exchange to set up a 
#symmetric encryption.

import libnacl.public
import binascii


def init_keypair(fname=None):
    '''Create a new encryption 
    keypair; stored in file fname
    if provided. The keypair object
    is returned.
    '''
    kp = libnacl.public.SecretKey()
    if fname:
        #Note: handles correct file permissions
        kp.save(fname)
    return kp


#the next two functions are useful 
#for exchaging pubkeys with counterparty
def get_pubkey(kp, as_hex=False):
    '''Given a keypair object,
    return its public key, 
    optionally in hex.'''
    return kp.hex_pk() if as_hex else kp.pk


def init_pubkey(hexpk, fname=None):
    '''Create a pubkey object from a
    hex formatted string.
    Save to file fname if specified.
    '''
    pk = libnacl.public.PublicKey(binascii.unhexlify(hexpk))
    if fname:
        pk.save(fname)
    return pk


def as_init_encryption(kp, c_pk):
    '''Given an initialised
    keypair kp and a counterparty
    pubkey c_pk, create a Box 
    ready for encryption/decryption.
    '''
    return libnacl.public.Box(kp.sk, c_pk)


'''
After initialisation, it's possible
to use the box object returned from
as_init_encryption to directly change
from plaintext to ciphertext:
    ciphertext = box.encrypt(plaintext)
    plaintext = box.decrypt(ciphertext)
Notes:
 1. use binary format for ctext/ptext
 2. Nonce is handled at the implementation layer.
'''

#TODO: Sign, verify.
