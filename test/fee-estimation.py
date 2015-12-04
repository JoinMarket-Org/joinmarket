'''
Test module for fee estimation.
'''
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
        self.wallets = commontest.make_wallets(
            self.n,
            wallet_structures=wallet_structures,
            mean_amt=1.00300000)
        #the sender is wallet (n), i.e. index wallets[n-1]
        #we need a counterparty with a huge set of utxos.
        bad_wallet_struct = [[1,0,0,0,0]]
        self.wallets.update(commontest.make_wallets(1, 
                            wallet_structures=bad_wallet_struct, 
                            mean_amt=0.01, start_index=2))
        #having created the bad wallet, add lots of utxos to 
        #the same mixdepth
        print 'creating a crazy amount of utxos in one wallet...'
        r_addr = self.wallets[2]['wallet'].get_receive_addr(0)
        for i in range(60):
            common.bc_interface.grab_coins(r_addr,0.02)
            time.sleep(1)
        #for sweep, create a yg wallet with enough for the mix
        #of the bad wallet above (acting as sender)
        self.wallets.update(commontest.make_wallets(1,
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
        ygp = commontest.local_command(['python','yield-generator.py',\
                                     str(self.wallets[3]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

        #A significant delay is needed to wait for the yield generators to sync
        time.sleep(20)

        dest_address = btc.privkey_to_address(
            os.urandom(32), common.get_p2pk_vbyte())
        try:
            sp_proc = commontest.local_command(['python','sendpayment.py','--yes',
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
        received = common.bc_interface.get_received_by_addr(
            [dest_address], None)['data'][0]['balance']
        return True

    def run_send(self,bad=False):
        yigen_procs = []
        if bad:
            i=2
        else:
            i=0
        ygp = commontest.local_command(['python','yield-generator.py',\
                                 str(self.wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

        #A significant delay is needed to wait for the yield generators to sync
        time.sleep(20)

        #run a single sendpayment call
        amt = 100000000  #in satoshis
        dest_address = btc.privkey_to_address(
            os.urandom(32), common.get_p2pk_vbyte())
        try:
            sp_proc = commontest.local_command(['python','sendpayment.py','--yes','-N', '1',
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

        received = common.bc_interface.get_received_by_addr(
            [dest_address], None)['data'][0]['balance']
        if received != amt:
            return False
        return True


def main():
    os.chdir(data_dir)
    common.load_program_config()
    unittest.main()


if __name__ == '__main__':
    main()
