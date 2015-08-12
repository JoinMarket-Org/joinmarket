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
import pexpect


class TestWalletCreation(unittest.TestCase):

    def test_generate(self):
        print 'wallet generation and encryption password tests'
        #testing a variety of passwords
        self.failUnless(self.run_generate('abc123'))
        self.failUnless(self.run_generate(
            'dddddddddddddddddddddddddddddddddddddddddddd'))
        #null password is accepted
        self.failUnless(self.run_generate(''))
        #binary password is accepted; good luck with that!
        self.failUnless(self.run_generate('\x01' * 10))
        #password with NULL bytes is *not* accepted
        self.failIf(self.run_generate('\x00' * 10))

    def run_generate(self, pwd):
        try:
            test_in = [pwd, pwd, 'testwallet.json']
            expected = ['Enter wallet encryption passphrase:',
                        'Reenter wallet encryption passphrase:',
                        'Input wallet file name']
            testlog = open('test/testlog-' + pwd, 'wb')
            p = pexpect.spawn('python wallet-tool.py generate', logfile=testlog)
            commontest.interact(p, test_in, expected)
            p.expect('saved to')
            #time.sleep(2)
            p.close()
            testlog.close()
            #anything to check in the log?
            if p.exitstatus != 0:
                print 'failed due to exit status: ' + str(p.exitstatus)
                return False
            #check the wallet exists (and contains appropriate json?)
            if not os.path.isfile('wallets/testwallet.json'):
                print 'failed due to wallet missing'
                return False
            os.remove('wallets/testwallet.json')
        except:
            return False
        return True


class TestWalletRecovery(unittest.TestCase):

    def setUp(self):
        self.testseed = 'earth gentle mouth circle despite pocket adore student board dress blanket worthless'

    def test_recover(self):
        print 'wallet recovery from seed test'
        self.failUnless(self.run_recover(self.testseed))
        #try using an invalid word list; can add more variants
        wrongseed = 'oops ' + self.testseed
        self.failIf(self.run_recover(wrongseed))

    def run_recover(self, seed):
        try:
            testlog = open('test_recover', 'wb')
            p = pexpect.spawn('python wallet-tool.py recover', logfile=testlog)
            expected = ['Input 12 word recovery seed',
                        'Enter wallet encryption passphrase:',
                        'Reenter wallet encryption passphrase:',
                        'Input wallet file name']
            test_in = [seed, 'abc123', 'abc123', 'test_recover_wallet.json']
            commontest.interact(p, test_in, expected)
            p.expect('saved to')
            p.close()
            testlog.close()
            #anything to check in the log?
            if p.exitstatus != 0:
                print 'failed due to exit status: ' + str(p.exitstatus)
                return False
            #check the wallet exists (and contains appropriate json? todo)
            if not os.path.isfile('wallets/test_recover_wallet.json'):
                print 'failed due to wallet missing'
                return False
            os.remove('wallets/test_recover_wallet.json')
        except:
            return False
        return True


if __name__ == '__main__':
    os.chdir(data_dir)
    common.load_program_config()
    unittest.main()
