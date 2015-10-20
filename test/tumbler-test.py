import sys
import os, time, random
data_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(data_dir, 'lib'))
import subprocess
import unittest
import common
from blockchaininterface import *
import bitcoin as btc
import binascii
import pexpect
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
	#return subprocess.Popen(command, stdout=subprocess.PIPE,
	 #                       stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    else:
	#in case of foreground execution, we can use the output; if not
	#it doesn't matter
	return subprocess.check_output(command)
    

def interact(process, inputs, expected):
    if len(inputs) != len(expected):
	raise Exception("Invalid inputs to interact()")
    for i, inp in enumerate(inputs):
		    process.expect(expected[i])
		    process.sendline(inp)
		    
class TumblerTests(unittest.TestCase):
    def setUp(self):
        #create 7 new random wallets.
        #put about 10 coins in each, spread over random mixdepths
	#in units of 0.5
        
	seeds = common.chunks(binascii.hexlify(os.urandom(15*7)),7)
        self.wallets = {}
	for i in range(7):
	    self.wallets[i] = {'seed':seeds[i], 'wallet': common.Wallet(seeds[i], max_mix_depth=5)}
	#adding coins somewhat randomly, spread over all 5 depths    
        for i in range(7):
	    w = self.wallets[i]['wallet']
	    for j in range(5):
		for k in range(4):
		    base = 0.001 if i==6 else 1.0
		    amt = base + random.random() #average is 0.5 for tumbler, else 1.5
		    common.bc_interface.grab_coins(w.get_receive_addr(j),amt)	
	
    def run_tumble(self, amt):
        yigen_procs = []
	for i in range(6):
	    ygp = local_command(['python','yield-generator.py',\
	                         str(self.wallets[i]['seed'])], bg=True)
	    time.sleep(2) #give it a chance
	    yigen_procs.append(ygp)
	
	#A significant delay is needed to wait for the yield generators to sync 
	time.sleep(60)
	
	#start a tumbler
	amt = amt*1e8 #in satoshis
	#send to any old address
	dest_address = btc.privkey_to_address(os.urandom(32), from_hex=False, magicbyte=common.get_p2pk_vbyte())	
	try:
	    #default mixdepth source is zero, so will take coins from m 0.
	    #see tumbler.py --h for details
	    expected = ['tumble with these tx']
	    test_in = ['y']
	    p = pexpect.spawn('python',['tumbler.py', '-N', '2', '0', #2 is basic case, could increase
	                             '-a', '0', '-M', '5', '-l', '0.5', #drastically shorten waits 
	                             self.wallets[6]['seed'], dest_address])
	    interact(p, test_in, expected)
	    p.expect(pexpect.EOF, timeout=100000)
	    p.close()
	    if p.exitstatus != 0:
		print 'failed due to exit status: '+str(p.exitstatus)
		return False
	    #print('use seed: '+self.wallets[6]['seed'])
	    #print('use dest addr: '+dest_address)
	    #ret = raw_input('quit?')
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
	print('received: '+str(received))
	return True	
    	
    def test_simple_send(self):
        self.failUnless(self.run_tumble(1))


def main():
    os.chdir(data_dir)
    common.load_program_config()
    unittest.main()

if __name__ == '__main__':
    main()
    

