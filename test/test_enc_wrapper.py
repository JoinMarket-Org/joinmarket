import base64
import string
import random

import pytest

from joinmarket import init_keypair, get_pubkey, init_pubkey, as_init_encryption


@pytest.mark.parametrize(
    "ab_message,ba_message,num_iterations",
    [
        # short ascii
        ("Attack at dawn", "Not tonight Josephine!", 5),
        # long base64 encoded
        (
            base64.b64encode(''.join(random.choice(string.ascii_letters) for _ in xrange(5000))),
            base64.b64encode(''.join(random.choice(string.ascii_letters) for _ in xrange(5000))),
            5,
        ),
        # large number of messages on the same connection
        ('rand', 'rand', 40000),
        # 1 character
        ('\x00', '\x00', 5),
    ]
)
def test_enc_wrapper(alice_bob_boxes, ab_message, ba_message, num_iterations):
    alice_box, bob_box = alice_bob_boxes

    for i in range(num_iterations):
        ab_message = ''.join(random.choice(string.ascii_letters) for x in range(100)) if ab_message == 'rand' else ab_message
        ba_message = ''.join(random.choice(string.ascii_letters) for x in range(100)) if ba_message == 'rand' else ba_message
        otw_amsg = alice_box.encrypt(ab_message)
        bob_ptext = bob_box.decrypt(otw_amsg)

        assert bob_ptext == ab_message, "Encryption test: FAILED. Alice sent: %s, Bob received: " % (ab_message, bob_ptext)

        otw_bmsg = bob_box.encrypt(ba_message)
        alice_ptext = alice_box.decrypt(otw_bmsg)
        assert alice_ptext == ba_message, "Encryption test: FAILED. Bob sent: %s, Alice received: " % (ba_message, alice_ptext)


@pytest.fixture()
def alice_bob_boxes():
    alice_kp = init_keypair()
    bob_kp = init_keypair()

    # this is the DH key exchange part
    bob_otwpk = get_pubkey(bob_kp, True)
    alice_otwpk = get_pubkey(alice_kp, True)

    bob_pk = init_pubkey(bob_otwpk)
    alice_box = as_init_encryption(alice_kp, bob_pk)
    alice_pk = init_pubkey(alice_otwpk)
    bob_box = as_init_encryption(bob_kp, alice_pk)

    # now Alice and Bob can use their 'box'
    # constructs (both of which utilise the same
    # shared secret) to perform encryption/decryption
    # to test the encryption functionality
    return (alice_box, bob_box)
