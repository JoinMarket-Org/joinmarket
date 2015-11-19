import sys
import os, time
data_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(data_dir, 'lib'))
import subprocess
import unittest
import common
import commontest
from blockchaininterface import *
import bitcoin as btc
import binascii
	
class BlackListPassTests(unittest.TestCase):
    '''This test case intends to simulate
    a single join with a single counterparty. In that sense,
    it's not realistic, because nobody (should) do joins with only 1 maker, 
    but this test has the virtue of being the simplest possible thing 
    that JoinMarket can do. '''
    def setUp(self):
        #create 2 new random wallets.
        #put 10 coins into the first receive address
        #to allow that bot to start.
	self.wallets = commontest.make_wallets(2, 
	            wallet_structures=[[1,0,0,0,0],[1,0,0,0,0]], mean_amt=10)
        
        
    def blacklist_run(self, n, m, fake):
	if os.path.isfile('logs/blacklist'):
	    os.remove('logs/blacklist')
        #start yield generator with wallet1
	yigen_proc = commontest.local_command(['python','yield-generator.py', 
	                            str(self.wallets[0]['seed'])],bg=True)
	
	#A significant delay is needed to wait for the yield generator to sync its wallet
	time.sleep(10)
	
	#run a single sendpayment call with wallet2
	amt = n*100000000 #in satoshis
	dest_address = btc.privkey_to_address(os.urandom(32), from_hex=False, magicbyte=common.get_p2pk_vbyte())
	try:
	    for i in range(m):
		sp_proc = commontest.local_command(['python','sendpayment.py','--yes','-N','1', self.wallets[1]['seed'],\
	                                       str(amt), dest_address])
	except subprocess.CalledProcessError, e:
	    if yigen_proc:
		yigen_proc.terminate()
	    print e.returncode
	    print e.message
	    raise

	if yigen_proc:
	    yigen_proc.terminate()
	if not fake:
	    received = common.bc_interface.get_received_by_addr([dest_address], None)['data'][0]['balance']
	    if received != amt*m:
		common.debug('received was: '+str(received)+ ' but amount was: '+str(amt))
		return False
	#check sanity in blacklist
	with open('logs/blacklist','rb') as f:
	    blacklist_lines = f.readlines()
	if not fake:
	    required_bl_lines = m
	    bl_count = 1
	else:
	    required_bl_lines = 1
	    bl_count = m
	if len(blacklist_lines) != required_bl_lines:
	    common.debug('wrong number of blacklist lines: '+str(len(blacklist_lines)))
	    return False
	
	for bl in blacklist_lines:
	    if len(bl.split(',')[0].strip()) != 64:
		common.debug('malformed utxo: '+str(len(bl.split(',')[0].strip())))
		return False
	    if int(bl.split(',')[1]) != bl_count:
		common.debug('wrong blacklist count:'+str(bl.split(',')[1]))
		return False
	return True
    	
    def test_blacklist(self):
        self.failUnless(self.blacklist_run(2, 2, False))
	



def main():
    os.chdir(data_dir)
    common.load_program_config()
    unittest.main()

if __name__ == '__main__':
    #Big kludge, but there is currently no way to inject this code:
    print """this test is to be run in two modes, first
    with no changes, then second adding a 'return' in 
    taker.CoinJoinTX.push() return (so it does nothing),
    and further changing the third parameter to blacklist_run to 'True'
    and the second parameter to '3' from '2'
    In both cases the test should pass for success.
    Also, WARNING! This test will delete your blacklist, better
    not run it in a "real" repo or back it up.
    """
    raw_input("OK?")
    main()
    

