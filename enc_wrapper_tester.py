import enc_wrapper as e
import binascii

alice_kp = e.init_keypair(fname='alice1.txt')
bob_kp = e.init_keypair(fname='bob1.txt')

#this is the DH key exchange part
bob_otwpk = e.get_pubkey(bob_kp, True)
print "sending pubkey from bob to alice: " + bob_otwpk
alice_otwpk = e.get_pubkey(alice_kp, True)
print "sending pubkey from bob to alice: " + alice_otwpk

bob_pk = e.init_pubkey(bob_otwpk)
alice_box = e.as_init_encryption(alice_kp, bob_pk)
alice_pk = e.init_pubkey(alice_otwpk)
bob_box = e.as_init_encryption(bob_kp, alice_pk)

#now Alice and Bob can use their 'box'
#constructs (both of which utilise the same
#shared secret) to perform encryption/decryption
for i in range(8):
    alice_message = 'Attack at dawn ! \n\n x' + str(i)

    otw_amsg = alice_box.encrypt(alice_message)
    print "Sending from alice to bob: " + otw_amsg

    bob_ptext = bob_box.decrypt(otw_amsg)
    print "Bob received: " + bob_ptext

    bob_message = 'Not tonight Josephine.' + str(i) * 45
    otw_bmsg = bob_box.encrypt(bob_message)
    print "Sending from bob to alice: " + otw_bmsg

    alice_ptext = alice_box.decrypt(otw_bmsg)
    print "Alice received: " + alice_ptext
