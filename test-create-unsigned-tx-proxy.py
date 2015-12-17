from __future__ import absolute_import
import requests

import bitcoin as btc
import libnacl.public
from joinmarket import get_log
from joinmarket import load_program_config
from joinmarket.configure import jm_single

log = get_log()

address1  = 'n1aUo5P6mij5fJSGaefmdCTgjM7xxWhbVs'
sk1 = btc.b58check_to_bin('L5cFx7NvWSWidwNtKnBQw5VrguTax2dGYajuz12S81UhX2ewRehH')
pk1 = btc.privkey_to_pubkey(sk1)

authUtxo = 'cb2caca7500d2d943b4cd03db20ee67fcabc6afa9548e930e81632d164f6bfa1:0'

load_program_config()
nacl_sk_hex = jm_single().config.get("JM_PROXY", "nacl_sk_hex")
auth_pkey = libnacl.public.SecretKey(nacl_sk_hex.decode('hex')).pk.encode('hex')

utxos = [authUtxo]

naclKeySig = btc.ecdsa_sign(auth_pkey, sk1)

data = {'testnet': True,
        'authUtxo': authUtxo,
        'authUtxoPK': pk1.encode('hex'),
        'naclKeySig': naclKeySig.encode('hex'),
        'makerCount': 1,
        'utxos': utxos,
        'change': 'mtrxCNUMYXRy2hQh2bBPeLjtRHWFKZcRkU',
        'recipient': 'mzGNyEEJNYtRi7fGnMAKTV5EZDFN8J9jTX',
        'amount': 600000}
log.debug(data)

authPK = pk1
sigGood = btc.ecdsa_verify(auth_pkey, naclKeySig, authPK)
log.debug('sig is good: {0}'.format(sigGood))

r = requests.post('http://127.0.0.1:5000/joinmarket/v1/getUnsignedTransaction', json=data)
log.debug(r.json())
