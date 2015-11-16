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

''' Just some random thoughts to motivate possible tests;
almost none of this has really been done:

Expectations
1. Any bot should run indefinitely irrespective of the input
messages it receives, except bots which perform a finite action

2. A bot must never spend an unacceptably high transaction fee.

3. A bot must explicitly reject interactions with another bot not
respecting the JoinMarket protocol for its version.

4. Bots must never send bitcoin data in the clear over the wire.
'''

'''helper functions put here to avoid polluting the main codebase.'''

import platform
OS = platform.system()
PINL = '\r\n' if OS == 'Windows' else '\n'

def local_command(command, bg=False, redirect=''):
    if redirect=='NULL':
	if OS=='Windows':
	    command.append(' > NUL 2>&1')
	elif OS=='Linux':
	    command.extend(['>', '/dev/null', '2>&1'])
	else:
	    print "OS not recognised, quitting."
    elif redirect:
	command.extend(['>', redirect])

    if bg:
	FNULL = open(os.devnull,'w')
	return subprocess.Popen(command, stdout=FNULL, stderr=subprocess.STDOUT, close_fds=True)
    else:
	#in case of foreground execution, we can use the output; if not
	#it doesn't matter
	return subprocess.check_output(command)
    

	
class Join2PTests(unittest.TestCase):
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
        
        
    def run_simple_send(self, n, m):
        #start yield generator with wallet1
	yigen_proc = local_command(['python','yield-generator.py', 
	                            str(self.wallets[0]['seed'])],bg=True)
	
	#A significant delay is needed to wait for the yield generator to sync its wallet
	time.sleep(30)
	
	#run a single sendpayment call with wallet2
	amt = n*100000000 #in satoshis
	dest_address = btc.privkey_to_address(os.urandom(32), from_hex=False, magicbyte=common.get_p2pk_vbyte())
	try:
	    for i in range(m):
		sp_proc = local_command(['python','sendpayment.py','--yes','-N','1', self.wallets[1]['seed'],\
	                                       str(amt), dest_address])
	except subprocess.CalledProcessError, e:
	    if yigen_proc:
		yigen_proc.terminate()
	    print e.returncode
	    print e.message
	    raise

	if yigen_proc:
	    yigen_proc.terminate()
	 
	received = common.bc_interface.get_received_by_addr([dest_address], None)['data'][0]['balance']
	if received != amt*m:
	    common.debug('received was: '+str(received)+ ' but amount was: '+str(amt))
	    return False
	return True
    	
    def test_simple_send(self):
        self.failUnless(self.run_simple_send(2, 2))
	

class JoinNPTests(unittest.TestCase):
	
    def setUp(self):
	self.n = 4
        #create n+1 new random wallets.
        #put 10 coins into the first receive address
        #to allow that bot to start.
	wallet_structures = [[2,2,2,0,0]]*(self.n+1)
	self.wallets = commontest.make_wallets(self.n+1, wallet_structures=wallet_structures,
	                                       mean_amt=3.0, sdev_amt=1.0)
	#the sender is wallet (n+1), i.e. index wallets[n]
    
	
    def test_n_partySend(self):
	self.failUnless(self.run_3party_join())
	
    def run_3party_join(self):
	yigen_procs = []
	for i in range(self.n):
	    ygp = local_command(['python','yield-generator.py',\
	                         str(self.wallets[i]['seed'])], bg=True)
	    time.sleep(2) #give it a chance
	    yigen_procs.append(ygp)
	
	#A significant delay is needed to wait for the yield generators to sync 
	time.sleep(60)
	
	#run a single sendpayment call
	amt = 100000000 #in satoshis
	dest_address = btc.privkey_to_address(os.urandom(32), from_hex=False, magicbyte=common.get_p2pk_vbyte())
	try:
	    sp_proc = local_command(['python','sendpayment.py','--yes','-N', '3',\
	                             self.wallets[self.n]['seed'], str(amt), dest_address])
	except subprocess.CalledProcessError, e:
	    for ygp in yigen_procs:
		ygp.kill()
	    print e.returncode
	    print e.message
	    raise
	
	if any(yigen_procs):
	    for ygp in yigen_procs:
		ygp.kill()
		    
	received = common.bc_interface.get_received_by_addr([dest_address], None)['data'][0]['balance']
	if received != amt:
	    return False
	return True	


def main():
    os.chdir(data_dir)
    common.load_program_config()
    unittest.main()

if __name__ == '__main__':
    main()
    

