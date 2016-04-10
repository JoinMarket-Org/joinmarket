#! /usr/bin/env python
from __future__ import absolute_import
'''Wallet functionality tests.'''

import sys
import os
import time
import binascii
import pexpect
import random
import subprocess
import unittest
from commontest import local_command, interact, make_wallets

import bitcoin as btc
import pytest
from joinmarket import load_program_config, jm_single
from joinmarket import get_p2pk_vbyte, get_log, Wallet
from joinmarket.support import chunks, select_gradual, \
     select_greedy, select_greediest

log = get_log()

@pytest.mark.parametrize(
    "pwd, in_privs",
    [
        ("import-pwd", ["L1RrrnXkcKut5DEMwtDthjwRcTTwED36thyL1DebVrKuwvohjMNi",
                        "Kz6UJmQACJmLtaQj5A3JAge4kVTNQ8gbvXuwbmCj7bsaabudb3RD"]
         ),
    ])
def test_import_privkey(setup_wallets, setup_import, pwd, in_privs):
    """This tests successful import of WIF compressed private keys
    into the wallet for mainnet.
    """
    test_in = [pwd, ' '.join(in_privs)]
    expected = ['Enter wallet decryption passphrase:',
                'to import:']
    testlog = open('test/testlog-' + pwd, 'wb')
    p = pexpect.spawn('python wallet-tool.py test_import_wallet.json importprivkey',
                      logfile=testlog)
    interact(p, test_in, expected)
    #p.expect('Private key(s) successfully imported')
    #time.sleep(1)
    #p.close()
    testlog.close()

@pytest.fixture(scope='function')
def setup_import(request):
    try:
        os.remove("wallets/test_import_wallet.json")
    except:
        pass
    #generate a new *mainnet* wallet
    jm_single().config.set("BLOCKCHAIN", "network", "mainnet")
    pwd = 'import-pwd'
    test_in = [pwd, pwd, 'test_import_wallet.json']
    expected = ['Enter wallet encryption passphrase:',
                'Reenter wallet encryption passphrase:',
                'Input wallet file name']
    testlog = open('test/testlog-' + pwd, 'wb')
    p = pexpect.spawn('python wallet-tool.py generate', logfile=testlog)
    interact(p, test_in, expected)
    p.expect('saved to')
    time.sleep(1)
    p.close()
    testlog.close()
    #anything to check in the log?
    with open(os.path.join('test', 'testlog-' + pwd)) as f:
        print f.read()
    if p.exitstatus != 0:
        raise Exception('failed due to exit status: ' + str(p.exitstatus))
    def import_teardown():
        jm_single().config.set("BLOCKCHAIN", "network", "testnet")
    request.addfinalizer(import_teardown)


@pytest.mark.parametrize(
    "nw, wallet_structures, mean_amt, sdev_amt, amount",
    [
        #TODO create structures that cover edge cases like
        #"return [high[0]]" in select_greediest
        (3, [[1, 0, 0, 0, 0], [0, 4, 2, 0, 1], [2, 6, 0, 0, 0]], 4, 1.4,
         800000000),
    ])
def test_utxo_selection(setup_wallets, nw, wallet_structures, mean_amt,
                        sdev_amt, amount):
    """Check that all the utxo selection algorithms work with a random
    variety of wallet contents.
    """
    wallets = make_wallets(nw, wallet_structures, mean_amt, sdev_amt)
    for w in wallets.values():
        jm_single().bc_interface.sync_wallet(w['wallet'])
    for k, w in enumerate(wallets.values()):
        for algo in [select_gradual, select_greedy, select_greediest, None]:
            wallet = w['wallet']
            if algo:
                wallet.utxo_selector = algo
            if k == 0:
                with pytest.raises(Exception) as e_info:
                    selected = wallet.select_utxos(1, amount)
            else:
                selected = wallet.select_utxos(1, amount)
                algostr = algo.__name__ if algo else "default"
                print 'selected these for algo ' + algostr + ':'
                print selected
                #basic check:
                #does this algo actually generate sufficient coins?
                total_selected = sum([x['value'] for x in selected.values()])
                assert total_selected > amount, "Selection algo: " + algo + \
                       "failed to select sufficient coins, total: " + \
                       str(total_selected) + ", should be: " + str(amount)


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
            interact(p, test_in, expected)
            p.expect('saved to')
            time.sleep(1)
            p.close()
            testlog.close()
            #anything to check in the log?
            with open(os.path.join('test', 'testlog-' + pwd)) as f:
                print f.read()
            if p.exitstatus != 0:
                print 'failed due to exit status: ' + str(p.exitstatus)
                print 'signal status is: ' + str(p.signalstatus)
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
            interact(p, test_in, expected)
            p.expect('saved to')
            time.sleep(1)
            p.close()
            testlog.close()
            #anything to check in the log?
            with open(os.path.join('test_recover')) as f:
                print f.read()
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

def test_pkcs7_bad_padding():
    #used in seed decryption; check that it throws
    #if wrongly padded (this caused a REAL bug before!)
    import joinmarket.slowaes
    bad_padded = ['\x07'*14, '\x07'*31, '\x07'*31+'\x11', '\x07'*31+'\x00',
                  '\x07'*14+'\x01\x02']
    for b in bad_padded:
        with pytest.raises(Exception) as e_info:
            fake_unpadded = joinmarket.slowaes.strip_PKCS7_padding(b)

def test_aes():
    #test general AES operation; probably not needed
    import joinmarket.slowaes as sa
    cleartext = "This is a test!"
    iv = [103, 35, 148, 239, 76, 213, 47, 118, 255, 222, 123, 176, 106, 134, 98,
          92]
    for ks in [16,24,32]:
        for mode in ["CFB", "CBC", "OFB"]:
            cypherkey = map(ord, os.urandom(ks))
            moo = sa.AESModeOfOperation()
            mode, orig_len, ciph = moo.encrypt(cleartext, moo.modeOfOperation[mode],
                                               cypherkey, ks,
                                               iv)
            decr = moo.decrypt(ciph, orig_len, mode, cypherkey,
                               ks, iv)
            assert decr==cleartext


@pytest.fixture(scope="module")
def setup_wallets():
    load_program_config()
