import bitcoin as btc
import sys

#structure for cj market wallet
# m/0/ root key
# m/0/n/ nth mixing depth, where n=0 is unmixed, n=1 is coinjoined once, etc
#        pay in coins to mix at n=0 addresses
#	 coins move up a level when they are cj'd and stay at same level if they're the change from a coinjoin
#	 using coins from different levels as inputs to the same tx is probably detrimental to privacy
# m/0/n/0/k kth receive address, for mixing depth n
# m/0/n/1/k kth change address, for mixing depth n

seed = sys.argv[1]  #btc.sha256('dont use brainwallets')
#seed = '256 bits of randomness'

master = btc.bip32_master_key(seed)  #, btc.TESTNET_PRIVATE)
print 'master = ' + master

addr_vbyte = 0x6f  #testnet

m_0 = btc.bip32_ckd(master, 0)
for n in range(2):
    print 'mixing depth ' + str(n) + ' m/0/' + str(n) + '/'
    m_0_n = btc.bip32_ckd(m_0, n)
    for forchange in range(2):
        print(' ' +
              ('receive'
               if forchange == 0 else 'change') + ' addresses m/0/%d/%d/' %
              (n, forchange))
        m_0_n_c = btc.bip32_ckd(m_0_n, forchange)
        for k in range(15):
            m_0_n_c_k = btc.bip32_ckd(m_0_n_c, k)
            priv = btc.bip32_extract_key(m_0_n_c_k)
            print '  m/0/%d/%d/%d/ ' % (n, forchange, k) + btc.privtoaddr(
                priv, addr_vbyte)  # + ' ' + btc.encode_privkey(priv, 'wif')
'''
#default key on http://bip32.org/
m_priv =\
'xprv9s21ZrQH143K2JF8RafpqtKiTbsbaxEeUaMnNHsm5o6wCW3z8ySyH4UxFVSfZ8n7ESu7fgir8imbZKLYVBxFPND1pniTZ81vKfd45EHKX73'

m_pub = btc.bip32_privtopub(m_priv)
print 'm_pub = ' + m_pub

print 'prv(hex) = ' + btc.bip32_extract_key(m_priv)
print 'prv(wif) = ' + btc.encode_privkey(btc.bip32_extract_key(m_priv), 'wif_compressed')
print 'pub(hex) = ' + btc.bip32_extract_key(m_pub)
print 'addr = ' + btc.pubtoaddr(btc.bip32_extract_key(m_pub))

def print_pub_priv(prefix, priv):
	pub = btc.bip32_privtopub(priv)
	print prefix
	print 'pub = ' + pub
	print 'prv = ' + priv

#bip32 test vector
print '\nbip32 test vector\n'
m_priv =\
'xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi'

#i_H = i + 2**31
chain_m_0h = btc.bip32_ckd(m_priv, 0 + 2**31)
print_pub_priv('chain m/0H', chain_m_0h)

chain_m_0h_1 = btc.bip32_ckd(chain_m_0h,  1)
print_pub_priv('chain m/0H/1', chain_m_0h_1)

chain_m_0h_1_2h = btc.bip32_ckd(chain_m_0h_1,  2 + 2**31)
print_pub_priv('chain m/0H/1/2H', chain_m_0h_1_2h)


#bip32 test vector 2
print '\nbip32 test vector 2\n'
m_priv =\
'xprv9s21ZrQH143K31xYSDQpPDxsXRTUcvj2iNHm5NUtrGiGG5e2DtALGdso3pGz6ssrdK4PFmM8NSpSBHNqPqm55Qn3LqFtT2emdEXVYsCzC2U'

print 'master(hex) = ' + btc.bip32_extract_key(m_priv)

chain_m_0 = btc.bip32_ckd(m_priv, 0)
print_pub_priv('chain m/0', chain_m_0)

chain_m_0_214blahH = btc.bip32_ckd(chain_m_0,  2147483647 + 2**31)
print_pub_priv('chain m/0/2147483647H', chain_m_0_214blahH)

chain_m_0_214blahH_1 = btc.bip32_ckd(chain_m_0_214blahH, 1)
print_pub_priv('chain m/0/2147483647H/1', chain_m_0_214blahH_1)
'''
'''
seed = '256 bits of randomness'
m_priv = btc.bip32_master_key(seed)
print 'new seed = ' + m_priv
'''
