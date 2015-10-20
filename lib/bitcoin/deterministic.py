from bitcoin.main import *
from ec_ecdsa import *
import hmac
import hashlib
from binascii import hexlify
# Electrum wallets


def electrum_stretch(seed):
    return slowsha(seed)

# Accepts seed or stretched seed, returns master public key


def electrum_mpk(seed):
    if len(seed) == 32:
        seed = electrum_stretch(seed)
    return privkey_to_pubkey(seed)[2:]

# Accepts (seed or stretched seed), index and secondary index
# (conventionally 0 for ordinary addresses, 1 for change) , returns privkey


def electrum_privkey(seed, n, for_change=0):
    if len(seed) == 32:
        seed = electrum_stretch(seed)
    mpk = electrum_mpk(seed)
    offset = dbl_sha256(from_int_representation_to_bytes(n)+b':'+from_int_representation_to_bytes(for_change)+b':'+binascii.unhexlify(mpk))
    return add_privkeys(seed, offset)

# Accepts (seed or stretched seed or master pubkey), index and secondary index
# (conventionally 0 for ordinary addresses, 1 for change) , returns pubkey


def electrum_pubkey(masterkey, n, for_change=0):
    if len(masterkey) == 32:
        mpk = electrum_mpk(electrum_stretch(masterkey))
    elif len(masterkey) == 64:
        mpk = electrum_mpk(masterkey)
    else:
        mpk = masterkey
    bin_mpk = encode_pubkey(mpk, 'bin_electrum')
    offset = bin_dbl_sha256(from_int_representation_to_bytes(n)+b':'+from_int_representation_to_bytes(for_change)+b':'+bin_mpk)
    return add_pubkeys('04'+mpk, privtopub(offset, False))

# seed/stretched seed/pubkey -> address (convenience method)


def electrum_address(masterkey, n, for_change=0, version=0):
    return pubkey_to_address(electrum_pubkey(masterkey, n, for_change), version)

# Given a master public key, a private key from that wallet and its index,
# cracks the secret exponent which can be used to generate all other private
# keys in the wallet

'''
def crack_electrum_wallet(mpk, pk, n, for_change=0):
    bin_mpk = encode_pubkey(mpk, 'bin_electrum')
    offset = dbl_sha256(str(n)+':'+str(for_change)+':'+bin_mpk)
    return subtract_privkeys(pk, offset)
'''

# Below code ASSUMES binary inputs and compressed pubkeys
MAINNET_PRIVATE = b'\x04\x88\xAD\xE4'
MAINNET_PUBLIC = b'\x04\x88\xB2\x1E'
TESTNET_PRIVATE = b'\x04\x35\x83\x94'
TESTNET_PUBLIC = b'\x04\x35\x87\xCF'
PRIVATE = [MAINNET_PRIVATE, TESTNET_PRIVATE]
PUBLIC = [MAINNET_PUBLIC, TESTNET_PUBLIC]

# BIP32 child key derivation


def raw_bip32_ckd(rawtuple, i):
    vbytes, depth, fingerprint, oldi, chaincode, key = rawtuple
    i = int(i)

    if vbytes in PRIVATE:
        priv = key
        pub = privtopub(key, False)
    else:
        pub = key

    if i >= 2**31:
        if vbytes in PUBLIC:
            raise Exception("Can't do private derivation on public key!")
        I = hmac.new(chaincode, b'\x00'+priv[:32]+encode(i, 256, 4), hashlib.sha512).digest()
    else:
        I = hmac.new(chaincode, pub+encode(i, 256, 4), hashlib.sha512).digest()

    if vbytes in PRIVATE:
        newkey = add_privkeys(I[:32]+B'\x01', priv, False)
        fingerprint = bin_hash160(privtopub(key, False))[:4]
    if vbytes in PUBLIC:
        newkey = add_pubkeys([privtopub(I[:32]+'\x01'), key],False)
        fingerprint = bin_hash160(key)[:4]

    return (vbytes, depth + 1, fingerprint, i, I[32:], newkey)


def bip32_serialize(rawtuple):
    vbytes, depth, fingerprint, i, chaincode, key = rawtuple
    i = encode(i, 256, 4)
    chaincode = encode(hash_to_int(chaincode), 256, 32)
    keydata = b'\x00'+key[:-1] if vbytes in PRIVATE else key
    bindata = vbytes + from_int_to_byte(depth % 256) + fingerprint + i + chaincode + keydata
    return changebase(bindata+bin_dbl_sha256(bindata)[:4], 256, 58)


def bip32_deserialize(data):
    dbin = changebase(data, 58, 256)
    if bin_dbl_sha256(dbin[:-4])[:4] != dbin[-4:]:
        raise Exception("Invalid checksum")
    vbytes = dbin[0:4]
    depth = from_byte_to_int(dbin[4])
    fingerprint = dbin[5:9]
    i = decode(dbin[9:13], 256)
    chaincode = dbin[13:45]
    key = dbin[46:78]+b'\x01' if vbytes in PRIVATE else dbin[45:78]
    return (vbytes, depth, fingerprint, i, chaincode, key)


def raw_bip32_privtopub(rawtuple):
    vbytes, depth, fingerprint, i, chaincode, key = rawtuple
    newvbytes = MAINNET_PUBLIC if vbytes == MAINNET_PRIVATE else TESTNET_PUBLIC
    return (newvbytes, depth, fingerprint, i, chaincode, privtopub(key, False))


def bip32_privtopub(data):
    return bip32_serialize(raw_bip32_privtopub(bip32_deserialize(data)))


def bip32_ckd(data, i):
    return bip32_serialize(raw_bip32_ckd(bip32_deserialize(data), i))


def bip32_master_key(seed, vbytes=MAINNET_PRIVATE):
    I = hmac.new(from_string_to_bytes("Bitcoin seed"), seed, hashlib.sha512).digest()
    return bip32_serialize((vbytes, 0, b'\x00'*4, 0, I[32:], I[:32]+b'\x01'))


def bip32_bin_extract_key(data):
    return bip32_deserialize(data)[-1]


def bip32_extract_key(data):
    return safe_hexlify(bip32_deserialize(data)[-1])

'''
# Exploits the same vulnerability as above in Electrum wallets
# Takes a BIP32 pubkey and one of the child privkeys of its corresponding
# privkey and returns the BIP32 privkey associated with that pubkey


def raw_crack_bip32_privkey(parent_pub, priv):
    vbytes, depth, fingerprint, i, chaincode, key = priv
    pvbytes, pdepth, pfingerprint, pi, pchaincode, pkey = parent_pub
    i = int(i)

    if i >= 2**31:
        raise Exception("Can't crack private derivation!")

    I = hmac.new(pchaincode, pkey+encode(i, 256, 4), hashlib.sha512).digest()

    pprivkey = subtract_privkeys(key, I[:32]+b'\x01')

    newvbytes = MAINNET_PRIVATE if vbytes == MAINNET_PUBLIC else TESTNET_PRIVATE
    return (newvbytes, pdepth, pfingerprint, pi, pchaincode, pprivkey)


def crack_bip32_privkey(parent_pub, priv):
    dsppub = bip32_deserialize(parent_pub)
    dspriv = bip32_deserialize(priv)
    return bip32_serialize(raw_crack_bip32_privkey(dsppub, dspriv))

'''
def coinvault_pub_to_bip32(*args):
    if len(args) == 1:
        args = args[0].split(' ')
    vals = map(int, args[34:])
    I1 = ''.join(map(chr, vals[:33]))
    I2 = ''.join(map(chr, vals[35:67]))
    return bip32_serialize((MAINNET_PUBLIC, 0, b'\x00'*4, 0, I2, I1))


def coinvault_priv_to_bip32(*args):
    if len(args) == 1:
        args = args[0].split(' ')
    vals = map(int, args[34:])
    I2 = ''.join(map(chr, vals[35:67]))
    I3 = ''.join(map(chr, vals[72:104]))
    return bip32_serialize((MAINNET_PRIVATE, 0, b'\x00'*4, 0, I2, I3+b'\x01'))


def bip32_descend(*args):
    if len(args) == 2:
        key, path = args
    else:
        key, path = args[0], map(int, args[1:])
    for p in path:
        key = bip32_ckd(key, p)
    return bip32_extract_key(key)

def test():
    #Run code against BIP32 test vectors
    testvector1 = {'seed': binascii.unhexlify('000102030405060708090a0b0c0d0e0f'),
        'depths': [0,2**31,1,2+2**31,2,1000000000],
        'keys':
        [('xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi',
          'xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8'),
         ('xprv9uHRZZhk6KAJC1avXpDAp4MDc3sQKNxDiPvvkX8Br5ngLNv1TxvUxt4cV1rGL5hj6KCesnDYUhd7oWgT11eZG7XnxHrnYeSvkzY7d2bhkJ7',
          'xpub68Gmy5EdvgibQVfPdqkBBCHxA5htiqg55crXYuXoQRKfDBFA1WEjWgP6LHhwBZeNK1VTsfTFUHCdrfp1bgwQ9xv5ski8PX9rL2dZXvgGDnw'),
         ('xprv9wTYmMFdV23N2TdNG573QoEsfRrWKQgWeibmLntzniatZvR9BmLnvSxqu53Kw1UmYPxLgboyZQaXwTCg8MSY3H2EU4pWcQDnRnrVA1xe8fs',
          'xpub6ASuArnXKPbfEwhqN6e3mwBcDTgzisQN1wXN9BJcM47sSikHjJf3UFHKkNAWbWMiGj7Wf5uMash7SyYq527Hqck2AxYysAA7xmALppuCkwQ'),
         ('xprv9z4pot5VBttmtdRTWfWQmoH1taj2axGVzFqSb8C9xaxKymcFzXBDptWmT7FwuEzG3ryjH4ktypQSAewRiNMjANTtpgP4mLTj34bhnZX7UiM',
          'xpub6D4BDPcP2GT577Vvch3R8wDkScZWzQzMMUm3PWbmWvVJrZwQY4VUNgqFJPMM3No2dFDFGTsxxpG5uJh7n7epu4trkrX7x7DogT5Uv6fcLW5'),
         ('xprvA2JDeKCSNNZky6uBCviVfJSKyQ1mDYahRjijr5idH2WwLsEd4Hsb2Tyh8RfQMuPh7f7RtyzTtdrbdqqsunu5Mm3wDvUAKRHSC34sJ7in334',
          'xpub6FHa3pjLCk84BayeJxFW2SP4XRrFd1JYnxeLeU8EqN3vDfZmbqBqaGJAyiLjTAwm6ZLRQUMv1ZACTj37sR62cfN7fe5JnJ7dh8zL4fiyLHV'),
         ('xprvA41z7zogVVwxVSgdKUHDy1SKmdb533PjDz7J6N6mV6uS3ze1ai8FHa8kmHScGpWmj4WggLyQjgPie1rFSruoUihUZREPSL39UNdE3BBDu76',
          'xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy')]}
    testvector2 = {'seed': binascii.unhexlify('fffcf9f6f3f0edeae7e4e1dedbd8d5d2cfccc9c6c3c0bdbab7b4b1aeaba8a5a29f9c999693908d8a8784817e7b7875726f6c696663605d5a5754514e4b484542'),
        'depths': [0,0,2147483647+2**31,1,2147483646+2**31,2],
        'keys':
        [('xprv9s21ZrQH143K31xYSDQpPDxsXRTUcvj2iNHm5NUtrGiGG5e2DtALGdso3pGz6ssrdK4PFmM8NSpSBHNqPqm55Qn3LqFtT2emdEXVYsCzC2U',
          'xpub661MyMwAqRbcFW31YEwpkMuc5THy2PSt5bDMsktWQcFF8syAmRUapSCGu8ED9W6oDMSgv6Zz8idoc4a6mr8BDzTJY47LJhkJ8UB7WEGuduB'),
         ('xprv9vHkqa6EV4sPZHYqZznhT2NPtPCjKuDKGY38FBWLvgaDx45zo9WQRUT3dKYnjwih2yJD9mkrocEZXo1ex8G81dwSM1fwqWpWkeS3v86pgKt',
          'xpub69H7F5d8KSRgmmdJg2KhpAK8SR3DjMwAdkxj3ZuxV27CprR9LgpeyGmXUbC6wb7ERfvrnKZjXoUmmDznezpbZb7ap6r1D3tgFxHmwMkQTPH'),
         ('xprv9wSp6B7kry3Vj9m1zSnLvN3xH8RdsPP1Mh7fAaR7aRLcQMKTR2vidYEeEg2mUCTAwCd6vnxVrcjfy2kRgVsFawNzmjuHc2YmYRmagcEPdU9',
          'xpub6ASAVgeehLbnwdqV6UKMHVzgqAG8Gr6riv3Fxxpj8ksbH9ebxaEyBLZ85ySDhKiLDBrQSARLq1uNRts8RuJiHjaDMBU4Zn9h8LZNnBC5y4a'),
         ('xprv9zFnWC6h2cLgpmSA46vutJzBcfJ8yaJGg8cX1e5StJh45BBciYTRXSd25UEPVuesF9yog62tGAQtHjXajPPdbRCHuWS6T8XA2ECKADdw4Ef',
          'xpub6DF8uhdarytz3FWdA8TvFSvvAh8dP3283MY7p2V4SeE2wyWmG5mg5EwVvmdMVCQcoNJxGoWaU9DCWh89LojfZ537wTfunKau47EL2dhHKon'),
         ('xprvA1RpRA33e1JQ7ifknakTFpgNXPmW2YvmhqLQYMmrj4xJXXWYpDPS3xz7iAxn8L39njGVyuoseXzU6rcxFLJ8HFsTjSyQbLYnMpCqE2VbFWc',
          'xpub6ERApfZwUNrhLCkDtcHTcxd75RbzS1ed54G1LkBUHQVHQKqhMkhgbmJbZRkrgZw4koxb5JaHWkY4ALHY2grBGRjaDMzQLcgJvLJuZZvRcEL'),
         ('xprvA2nrNbFZABcdryreWet9Ea4LvTJcGsqrMzxHx98MMrotbir7yrKCEXw7nadnHM8Dq38EGfSh6dqA9QWTyefMLEcBYJUuekgW4BYPJcr9E7j',
          'xpub6FnCn6nSzZAw5Tw7cgR9bi15UV96gLZhjDstkXXxvCLsUXBGXPdSnLFbdpq8p9HmGsApME5hQTZ3emM2rnY5agb9rXpVGyy3bdW6EEgAtqt')]}    
    
    testvectors = [testvector1, testvector2]
    for t in testvectors:
        master = bip32_master_key(t['seed'])
        if master != t['keys'][0][0]:
            return 'failed: master xpriv'
        masterpub = bip32_privtopub(master)
        if masterpub != t['keys'][0][1]:
            print masterpub
            return 'failed: master xpub'
        currentkey = master
        for i in range(1,len(t['depths'])):
            currentkey = bip32_ckd(currentkey, t['depths'][i])
            print currentkey
            print t['keys'][i][0]
            if currentkey != t['keys'][i][0]:
                print currentkey
                return 'failed: child priv key, should be: '+t['keys'][i][0]
            pub = bip32_privtopub(currentkey)
            print pub
            print t['keys'][i][1]
            if pub != t['keys'][i][1]:
                print pub
                return 'failed: child pub key, should be: '+t['keys'][i][1]
    return 'success'