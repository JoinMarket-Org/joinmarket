#! /usr/bin/env python
from __future__ import absolute_import
'''Full simulated pit for testing the tumbler bot.'''

import sys
import os
import time
import binascii
import pexpect
import random
import subprocess
import unittest
from commontest import local_command, make_wallets, interact

data_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(data_dir))

import bitcoin as btc

from joinmarket import load_program_config, jm_single
from joinmarket import get_p2pk_vbyte, get_log, Wallet
from joinmarket.support import chunks

python_cmd = 'python2'
yg_cmd = 'yield-generator-basic.py'
#yg_cmd = 'yield-generator-mixdepth.py'
#yg_cmd = 'yield-generator-deluxe.py'

log = get_log()


class TumblerTests(unittest.TestCase):

    def setUp(self):
        #create 7 new random wallets.
        #put about 10 coins in each, spread over random mixdepths
        #in units of 0.5

        seeds = chunks(binascii.hexlify(os.urandom(15 * 7)), 7)
        self.wallets = {}
        for i in range(7):
            self.wallets[i] = {'seed': seeds[i],
                               'wallet': Wallet(seeds[i],
                                                max_mix_depth=5)}
        #adding coins somewhat randomly, spread over all 5 depths
        for i in range(7):
            w = self.wallets[i]['wallet']
            for j in range(5):
                for k in range(4):
                    base = 0.001 if i == 6 else 1.0
                    amt = base + random.random(
                    )  #average is 0.5 for tumbler, else 1.5
                    jm_single().bc_interface.grab_coins(
                        w.get_receive_addr(j), amt)

    def run_tumble(self, amt):
        yigen_procs = []
        for i in range(6):
            ygp = local_command([python_cmd, yg_cmd,\
                                 str(self.wallets[i]['seed'])], bg=True)
            time.sleep(2)  #give it a chance
            yigen_procs.append(ygp)

#A significant delay is needed to wait for the yield generators to sync
        time.sleep(60)

        #start a tumbler
        amt = amt * 1e8  #in satoshis
        #send to any old address
        dest_address = btc.privkey_to_address(os.urandom(32), get_p2pk_vbyte())
        try:
            #default mixdepth source is zero, so will take coins from m 0.
            #see tumbler.py --h for details
            expected = ['tumble with these tx']
            test_in = ['y']
            p = pexpect.spawn(python_cmd,
                              ['tumbler.py', '-N', '2', '0', '-a', '0', '-M',
                               '5', '-w', '10', '-l', '0.2', '-s', '1000000',
                               self.wallets[6]['seed'], dest_address])
            interact(p, test_in, expected)
            p.expect(pexpect.EOF, timeout=100000)
            p.close()
            if p.exitstatus != 0:
                print 'failed due to exit status: ' + str(p.exitstatus)
                return False
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
        print('received: ' + str(received))
        return True

    def test_simple_send(self):
        self.failUnless(self.run_tumble(1))


def main():
    os.chdir(data_dir)
    load_program_config()
    unittest.main()


if __name__ == '__main__':
    main()
