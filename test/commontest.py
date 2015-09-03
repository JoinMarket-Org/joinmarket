import sys
import os, time
data_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(data_dir, 'lib'))
import subprocess
import unittest
import common
from blockchaininterface import *
import bitcoin as btc
import binascii
import pexpect
import random

'''Some helper functions for testing'''


'''This code is intended to provide
subprocess startup cross-platform with 
some useful options; it could do with
some simplification/improvement.'''
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
	#using subprocess.PIPE seems to cause problems
	FNULL = open(os.devnull,'w')
	return subprocess.Popen(command, stdout=FNULL, stderr=subprocess.STDOUT, close_fds=True)
    else:
	#in case of foreground execution, we can use the output; if not
	#it doesn't matter
	return subprocess.check_output(command)

def make_wallets(n, wallet_structures = None, mean_amt=1, sdev_amt=0):
    '''n: number of wallets to be created
       wallet_structure: array of n arrays , each subarray
       specifying the number of addresses to be populated with coins
       at each depth (for now, this will only populate coins into 'receive' addresses)
       mean_amt: the number of coins (in btc units) in each address as above
       sdev_amt: if randomness in amouts is desired, specify here.
       Returns: a dict of dicts of form {0:{'seed':seed,'wallet':Wallet object},1:..,}'''
    if len(wallet_structures) != n:
	raise Exception("Number of wallets doesn't match wallet structures")
    seeds = common.chunks(binascii.hexlify(os.urandom(15*n)),n)
    wallets = {}
    for i in range(n):
	wallets[i] = {'seed':seeds[i], 'wallet': common.Wallet(seeds[i], max_mix_depth=5)}
	for j in range(5):
	    for k in range(wallet_structures[i][j]):
		deviation = sdev_amt*random.random()
		amt = mean_amt - sdev_amt/2.0 + deviation
		if amt < 0: amt = 0.001
		common.bc_interface.grab_coins(wallets[i]['wallet'].get_receive_addr(j),amt)
    return wallets

def interact(process, inputs, expected):
    if len(inputs) != len(expected):
	raise Exception("Invalid inputs to interact()")
    for i, inp in enumerate(inputs):
		    process.expect(expected[i])
		    process.sendline(inp)