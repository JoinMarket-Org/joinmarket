import os
from cffi import FFI, ffiplatform


definitions = """
    /* secp256k1.h*/

    typedef struct secp256k1_context_struct secp256k1_context;

    typedef struct {
        unsigned char data[64];
    } secp256k1_pubkey;

    typedef struct {
        unsigned char data[64];
    } secp256k1_ecdsa_signature;

    typedef int (*secp256k1_nonce_function)(
        unsigned char *nonce32,
        const unsigned char *msg32,
        const unsigned char *key32,
        const unsigned char *algo16,
        void *data,
        unsigned int attempt
    );

    #define SECP256K1_FLAGS_TYPE_MASK 255
    #define SECP256K1_FLAGS_TYPE_CONTEXT 1
    #define SECP256K1_FLAGS_TYPE_COMPRESSION 2
    #define SECP256K1_FLAGS_BIT_CONTEXT_VERIFY 256
    #define SECP256K1_FLAGS_BIT_CONTEXT_SIGN   512
    #define SECP256K1_FLAGS_BIT_COMPRESSION    256

    #define SECP256K1_CONTEXT_VERIFY  257
    #define SECP256K1_CONTEXT_SIGN    513
    #define SECP256K1_CONTEXT_NONE    1

    #define SECP256K1_EC_COMPRESSED   258
    #define SECP256K1_EC_UNCOMPRESSED 2

    secp256k1_context* secp256k1_context_create(
        int flags
    );

    secp256k1_context* secp256k1_context_clone(
        const secp256k1_context* ctx
    );

    void secp256k1_context_destroy(
       secp256k1_context* ctx
    );

    int secp256k1_ec_pubkey_parse(
        const secp256k1_context* ctx,
        secp256k1_pubkey* pubkey,
        const unsigned char *input,
        size_t inputlen
    );

    int secp256k1_ec_pubkey_serialize(
        const secp256k1_context* ctx,
        unsigned char *output,
        size_t *outputlen,
        const secp256k1_pubkey* pubkey,
        unsigned int flags
    );

    int secp256k1_ecdsa_signature_parse_compact(
        const secp256k1_context* ctx,
        secp256k1_ecdsa_signature* sig,
        const unsigned char *input64
    );

    int secp256k1_ecdsa_signature_parse_der(
        const secp256k1_context* ctx,
        secp256k1_ecdsa_signature* sig,
        const unsigned char *input,
        size_t inputlen
    );

    int secp256k1_ecdsa_signature_serialize_der(
        const secp256k1_context* ctx,
        unsigned char *output,
        size_t *outputlen,
        const secp256k1_ecdsa_signature* sig
    );

    int secp256k1_ecdsa_signature_serialize_compact(
        const secp256k1_context* ctx,
        unsigned char *output64,
        const secp256k1_ecdsa_signature* sig
    );

    int secp256k1_ecdsa_verify(
        const secp256k1_context* ctx,
        const secp256k1_ecdsa_signature *sig,
        const unsigned char *msg32,
        const secp256k1_pubkey *pubkey
    );

    int secp256k1_ecdsa_signature_normalize(
        const secp256k1_context* ctx,
        secp256k1_ecdsa_signature *sigout,
        const secp256k1_ecdsa_signature *sigin
    );

    extern const secp256k1_nonce_function secp256k1_nonce_function_rfc6979;
    extern const secp256k1_nonce_function secp256k1_nonce_function_default;


    int secp256k1_ecdsa_sign(
        const secp256k1_context* ctx,
        secp256k1_ecdsa_signature *sig,
        const unsigned char *msg32,
        const unsigned char *seckey,
        secp256k1_nonce_function noncefp,
        const void *ndata
    );

    int secp256k1_ec_seckey_verify(
        const secp256k1_context* ctx,
        const unsigned char *seckey
    );

    int secp256k1_ec_pubkey_create(
        const secp256k1_context* ctx,
        secp256k1_pubkey *pubkey,
        const unsigned char *seckey
    );

    int secp256k1_ec_privkey_tweak_add(
        const secp256k1_context* ctx,
        unsigned char *seckey,
        const unsigned char *tweak
    );

    int secp256k1_ec_pubkey_tweak_add(
        const secp256k1_context* ctx,
        secp256k1_pubkey *pubkey,
        const unsigned char *tweak
    );

    int secp256k1_ec_privkey_tweak_mul(
        const secp256k1_context* ctx,
        unsigned char *seckey,
        const unsigned char *tweak
    );

    int secp256k1_ec_pubkey_tweak_mul(
        const secp256k1_context* ctx,
        secp256k1_pubkey *pubkey,
        const unsigned char *tweak
    );

    int secp256k1_context_randomize(
        secp256k1_context* ctx,
        const unsigned char *seed32
    );

    int secp256k1_ec_pubkey_combine(
        const secp256k1_context* ctx,
        secp256k1_pubkey *out,
        const secp256k1_pubkey * const * ins,
        int n
    );
"""

definitions_recovery = """
    /* secp256k1_recovery.h */

    typedef struct {
        unsigned char data[65];
    } secp256k1_ecdsa_recoverable_signature;

    int secp256k1_ecdsa_recoverable_signature_parse_compact(
        const secp256k1_context* ctx,
        secp256k1_ecdsa_recoverable_signature* sig,
        const unsigned char *input64,
        int recid
    );

    int secp256k1_ecdsa_recoverable_signature_convert(
        const secp256k1_context* ctx,
        secp256k1_ecdsa_signature* sig,
        const secp256k1_ecdsa_recoverable_signature* sigin
    );

    int secp256k1_ecdsa_recoverable_signature_serialize_compact(
        const secp256k1_context* ctx,
        unsigned char *output64,
        int *recid,
        const secp256k1_ecdsa_recoverable_signature* sig
    );

    int secp256k1_ecdsa_sign_recoverable(
        const secp256k1_context* ctx,
        secp256k1_ecdsa_recoverable_signature *sig,
        const unsigned char *msg32,
        const unsigned char *seckey,
        secp256k1_nonce_function noncefp,
        const void *ndata
    );

    int secp256k1_ecdsa_recover(
        const secp256k1_context* ctx,
        secp256k1_pubkey *pubkey,
        const secp256k1_ecdsa_recoverable_signature *sig,
        const unsigned char *msg32
    );
"""

definitions_schnorr = """
    /* secp256k1_schnorr.h */

    int secp256k1_schnorr_sign(
        const secp256k1_context* ctx,
        unsigned char *sig64,
        const unsigned char *msg32,
        const unsigned char *seckey,
        secp256k1_nonce_function noncefp,
        const void *ndata
    );

    int secp256k1_schnorr_verify(
        const secp256k1_context* ctx,
        const unsigned char *sig64,
        const unsigned char *msg32,
        const secp256k1_pubkey *pubkey
    );

    int secp256k1_schnorr_recover(
        const secp256k1_context* ctx,
        secp256k1_pubkey *pubkey,
        const unsigned char *sig64,
        const unsigned char *msg32
    );

    int secp256k1_schnorr_generate_nonce_pair(
        const secp256k1_context* ctx,
        secp256k1_pubkey *pubnonce,
        unsigned char *privnonce32,
        const unsigned char *msg32,
        const unsigned char *sec32,
        secp256k1_nonce_function noncefp,
        const void* noncedata
    );

    int secp256k1_schnorr_partial_sign(
        const secp256k1_context* ctx,
        unsigned char *sig64,
        const unsigned char *msg32,
        const unsigned char *sec32,
        const secp256k1_pubkey *pubnonce_others,
        const unsigned char *secnonce32
    );

    int secp256k1_schnorr_partial_combine(
        const secp256k1_context* ctx,
        unsigned char *sig64,
        const unsigned char * const * sig64sin,
        int n
    );
"""

definitions_ecdh = """
    /* secp256k1_ecdh.h */

    int secp256k1_ecdh(
        const secp256k1_context* ctx,
        unsigned char *result,
        const secp256k1_pubkey *point,
        const unsigned char *scalar
    );
"""


def build_ffi(include_recovery=False, include_schnorr=False, include_ecdh=False):
    ffi = FFI()

    source = "#include <secp256k1.h>"
    cdefs = definitions
    if include_recovery:
        cdefs += definitions_recovery
        source += "\n#include <secp256k1_recovery.h>"
    if include_schnorr:
        cdefs += definitions_schnorr
        source += "\n#include <secp256k1_schnorr.h>"
    if include_ecdh:
        cdefs += definitions_ecdh
        source += "\n#include <secp256k1_ecdh.h>"

    incpath = [os.environ['INCLUDE_DIR']] if 'INCLUDE_DIR' in os.environ else None
    libpath = [os.environ['LIB_DIR']] if 'LIB_DIR' in os.environ else None

    ffi.set_source(
        "_libsecp256k1",
        source,
        libraries=["secp256k1"],
        library_dirs=libpath,
        include_dirs=incpath)
    ffi.cdef(cdefs)

    return ffi


_modules = {
    'secp256k1_recovery': [False, {'include_recovery': True}],
    'secp256k1_schnorr': [False, {'include_schnorr': True}],
    'secp256k1_ecdh': [False, {'include_ecdh': True}]
}

# Check which modules are available.
for mod in _modules:
    kwargs = _modules[mod][1]
    try:
        _ffi = build_ffi(**kwargs)
        _ffi.compile()
        _modules[mod][0] = True
    except ffiplatform.VerificationError:
        pass

# Build interface with all active modules.
_kwargs = {}
_not_avail = []
for mod, val in _modules.items():
    if val[0]:
        _kwargs.update(val[1])
    else:
        _not_avail.append(mod)

ffi = build_ffi(**_kwargs)
ffi.compile()

print('\n'.join('{} not supported'.format(entry) for entry in _not_avail))
