#! /usr/bin/env python
from __future__ import absolute_import
'''
Test module for fee estimation.
'''

#NOTE: This is terrible code, just
#the result of me fiddling around trying
#to generate the most important error condition
#arising from fee estimation.
#Please do make a better designed version, and 
#one which triggers a broader class of the possible
#success and failure conditions arising from fee
#estimation. AG 2015-12-13.

import sys
import os
import time
import binascii
import pexpect
import random
import subprocess
import unittest
from commontest import local_command, make_wallets

data_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(data_dir))

import bitcoin as btc

from joinmarket import load_program_config, jm_single
from joinmarket import get_p2pk_vbyte, get_log

python_cmd = 'python2'
yg_cmd = 'yield-generator-basic.py'
#yg_cmd = 'yield-generator-mixdepth.py'
#yg_cmd = 'yield-generator-deluxe.py'

log = get_log()

import binascii
''' Purpose of test:
To check that fee estimation gives sane values for normal
transactions and completes successfully.
To check that in case of excessive maker utxos, the code fails
(exits) with a sensible error message.

We use a static value for fees since estimatefee() does not 
work for regtest (perhaps with some serious monkeying about).
Testing that fee estimates are retrieved OK from the web
(currently via blockcypher, may change) for blockr instances
has to be done separately; this is only testing the code logic,
*given* a fee estimate.
'''

class FeeEstimateTests(unittest.TestCase):
    '''Estimation of fees test case.
    '''
    def setUp(self):
        self.n = 2
        #create n new random wallets.
        #put coins into the first mixdepth for each
        #The amount is 1btc + 300,000 satoshis, to account
        #for a 0.2% fee for 1 counterparty + a large tx fee.
        #(but not large enough to handle the bad wallet)
        wallet_structures = [[1, 0, 0, 0, 0]] * (self.n)
        self.wallets = make_wallets(
            self.n,
            wallet_structures=wallet_structures,
            mean_amt=1.00300000)
        #the sender is wallet (n), i.e. index wallets[n-1]
        #we need a counterparty with a huge set of utxos.
        bad_wallet_struct = [[1,0,0,0,0]]
        self.wallets.update(make_wallets(1, 
                            wallet_structures=bad_wallet_struct, 
                            mean_amt=0.01, start_index=2))
        #having created the bad wallet, add lots of utxos to 
        #the same mixdepth
        print 'creating a crazy amount of utxos in one wallet...'
        r_addr = self.wallets[2]['wallet'].get_receive_addr(0)
        for i in range(60):
            jm_single().bc_interface.grab_coins(r_addr,0.02)
            time.sleep(1)
        #for sweep, create a yg wallet with enough for the mix
        #of the bad wallet above (acting as sender)
        self.wallets.update(make_wallets(1,
                            wallet_structures=[[1,0,0,0,0]],
                            mean_amt=3, start_index=3))

    def test_sweep(self):
        self.failUnless(self.run_sweep())

    def test_send_without_bad(self):
        self.failUnless(self.run_send(bad=False))
    
    def test_send_with_bad(self):
        self.failIf(self.run_send(bad=True))

    def run_sweep(self):
        #currently broken due to flooding; to make it work
        #change the 60 loop for the bad wallet to 20
        yigen_procs = []
        ygp = local_command([python_cmd,yg_cmd,\
                                     str(self.wallets[3]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

        #A significant delay is needed to wait for the yield generators to sync
        time.sleep(20)

        dest_address = btc.privkey_to_address(
            os.urandom(32), get_p2pk_vbyte())
        try:
            sp_proc = local_command([python_cmd,'sendpayment.py','--yes',
                        '-N', '1',self.wallets[2]['seed'], '0', dest_address])
        except subprocess.CalledProcessError, e:
            for ygp in yigen_procs:
                ygp.kill()
            print e.returncode
            print e.message
            raise
        if any(yigen_procs):
            for ygp in yigen_procs:
                ygp.kill()
        received = jm_single().bc_interface.get_received_by_addr(
            [dest_address], None)['data'][0]['balance']
        return True

    def run_send(self,bad=False):
        yigen_procs = []
        if bad:
            i=2
        else:
            i=0
        ygp = local_command([python_cmd,yg_cmd,\
                                 str(self.wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

        #A significant delay is needed to wait for the yield generators to sync
        time.sleep(20)

        #run a single sendpayment call
        amt = 100000000  #in satoshis
        dest_address = btc.privkey_to_address(
            os.urandom(32), get_p2pk_vbyte())
        try:
            sp_proc = local_command([python_cmd,'sendpayment.py','--yes',
                                                '-N', '1',
                                self.wallets[1]['seed'], str(amt), dest_address])
        except subprocess.CalledProcessError, e:
            for ygp in yigen_procs:
                ygp.kill()
            print e.returncode
            print e.message
            raise

        if any(yigen_procs):
            for ygp in yigen_procs:
                ygp.kill()

        received = jm_single().bc_interface.get_received_by_addr(
            [dest_address], None)['data'][0]['balance']
        if received != amt:
            return False
        return True


def main():
    os.chdir(data_dir)
    load_program_config()
    unittest.main()


if __name__ == '__main__':
    main()
