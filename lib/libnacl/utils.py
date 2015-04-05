# -*- coding: utf-8 -*-

import struct
import time

# Import nacl libs
import libnacl
import libnacl.encode
import libnacl.public
import libnacl.sign
import libnacl.dual


def load_key(path, serial='json'):
    '''
    Read in a key from a file and return the applicable key object based on
    the contents of the file
    '''
    with open(path, 'rb') as fp_:
        packaged = fp_.read()
    if serial == 'msgpack':
        import msgpack
        key_data = msgpack.loads(packaged)
    elif serial == 'json':
        import json
        key_data = json.loads(packaged.decode(encoding='UTF-8'))
    if 'priv' in key_data and 'sign' in key_data:
        return libnacl.dual.DualSecret(
                libnacl.encode.hex_decode(key_data['priv']),
                libnacl.encode.hex_decode(key_data['sign']))
    elif 'priv' in key_data:
        return libnacl.public.SecretKey(
                libnacl.encode.hex_decode(key_data['priv']))
    elif 'sign' in key_data:
        return libnacl.sign.Signer(
                libnacl.encode.hex_decode(key_data['sign']))
    elif 'pub' in key_data:
        return libnacl.public.PublicKey(
                libnacl.encode.hex_decode(key_data['pub']))
    elif 'verify' in key_data:
        return libnacl.sign.Verifier(key_data['verify'])
    raise ValueError('Found no key data')


def salsa_key():
    '''
    Generates a salsa2020 key
    '''
    return libnacl.randombytes(libnacl.crypto_secretbox_KEYBYTES)


def rand_nonce():
    '''
    Generates and returns a random bytestring of the size defined in libsodium
    as crypto_box_NONCEBYTES
    '''
    return libnacl.randombytes(libnacl.crypto_box_NONCEBYTES)


def time_nonce():
    '''
    Generates and returns a nonce as in rand_nonce() but using a timestamp for the first 8 bytes.

    This function now exists mostly for backwards compatibility, as rand_nonce() is usually preferred.
    '''
    nonce = rand_nonce()
    return (struct.pack('=d', time.time()) + nonce)[:len(nonce)]

