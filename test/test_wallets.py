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
from decimal import Decimal
from commontest import local_command, interact, make_wallets, make_sign_and_push

import bitcoin as btc
import pytest
from joinmarket import load_program_config, jm_single
from joinmarket import get_p2pk_vbyte, get_log, Wallet
from joinmarket.support import chunks, select_gradual, \
     select_greedy, select_greediest
from joinmarket.wallet import estimate_tx_fee

log = get_log()

def do_tx(wallet, amount):
    ins_full = wallet.select_utxos(0, amount)
    cj_addr = wallet.get_internal_addr(1)
    change_addr = wallet.get_internal_addr(0)
    wallet.update_cache_index()
    txid = make_sign_and_push(ins_full, wallet, amount,
                              output_addr=cj_addr,
                              change_addr=change_addr,
                              estimate_fee=True)
    assert txid
    time.sleep(2) #blocks
    jm_single().bc_interface.sync_unspent(wallet)

"""
@pytest.mark.parametrize(
    "num_txs, gap_count, gap_limit, wallet_structure, amount, wallet_file, password",
    [
        (3, 450, 461, [11,3,4,5,6], 150000000, 'test_import_wallet.json', 'import-pwd'
         ),
    ])
def test_wallet_gap_sync(setup_wallets, num_txs, gap_count, gap_limit,
                     wallet_structure, amount, wallet_file, password):
    #Starting with a nonexistent index_cache, try syncing with a large
    #gap limit
    setup_import(mainnet=False)
    wallet = make_wallets(1,[wallet_structure],
                          fixed_seeds=[wallet_file],
                          test_wallet=True, passwords=[password])[0]['wallet']
    wallet.gaplimit = gap_limit
    #Artificially insert coins at position (0, wallet_structures[0] + gap_count)
    dest = wallet.get_addr(0, 0, wallet_structure[0] + gap_count)
    btcamt = amount/(1e8)
    jm_single().bc_interface.grab_coins(dest, amt=float(Decimal(btcamt).quantize(Decimal(10)**-8)))
    time.sleep(2)
    sync_count = 0
    jm_single().bc_interface.wallet_synced = False
    while not jm_single().bc_interface.wallet_synced:
        wallet.index = []
        for i in range(5):
            wallet.index.append([0, 0])
        jm_single().bc_interface.sync_wallet(wallet)
        sync_count += 1
        #avoid infinite loop
        assert sync_count < 10
        log.debug("Tried " + str(sync_count) + " times")

    assert jm_single().bc_interface.wallet_synced
"""

@pytest.mark.parametrize(
    "num_txs, fake_count, wallet_structure, amount, wallet_file, password",
    [
        (3, 13, [11,3,4,5,6], 150000000, 'test_import_wallet.json', 'import-pwd'
         ),
        #Uncomment all these for thorough tests. Passing currently.
        #Lots of used addresses
        #(7, 1, [51,3,4,5,6], 150000000, 'test_import_wallet.json', 'import-pwd'
        #),
        #(3, 1, [3,1,4,5,6], 50000000, 'test_import_wallet.json', 'import-pwd'
        #),
        #No spams/fakes
        #(2, 0, [5,20,1,1,1], 50000000, 'test_import_wallet.json', 'import-pwd'
        # ),
        #Lots of transactions and fakes
        #(25, 30, [30,20,1,1,1], 50000000, 'test_import_wallet.json', 'import-pwd'
        # ),
    ])
def test_wallet_sync(setup_wallets, num_txs, fake_count,
                     wallet_structure, amount, wallet_file, password):
    setup_import(mainnet=False)
    wallet = make_wallets(1,[wallet_structure],
                          fixed_seeds=[wallet_file],
                          test_wallet=True, passwords=[password])[0]['wallet']
    sync_count = 0
    jm_single().bc_interface.wallet_synced = False
    while not jm_single().bc_interface.wallet_synced:
        jm_single().bc_interface.sync_wallet(wallet)
        sync_count += 1
        #avoid infinite loop
        assert sync_count < 10
        log.debug("Tried " + str(sync_count) + " times")

    assert jm_single().bc_interface.wallet_synced
    #do some transactions with the wallet, then close, then resync
    for i in range(num_txs):
        do_tx(wallet, amount)
        log.debug("After doing a tx, index is now: " + str(wallet.index))
        #simulate a spammer requesting a bunch of transactions. This
        #mimics what happens in CoinJoinOrder.__init__()
        for j in range(fake_count):
            #Note that as in a real script run,
            #the initial call to sync_wallet will
            #have set wallet_synced to True, so these will
            #trigger actual imports.
            cj_addr = wallet.get_internal_addr(0)
            change_addr = wallet.get_internal_addr(0)
            wallet.update_cache_index()
            log.debug("After doing a spam, index is now: " + str(wallet.index))

    assert wallet.index[0][1] == num_txs+fake_count*2*num_txs

    #Attempt re-sync, simulating a script restart.

    jm_single().bc_interface.wallet_synced = False
    sync_count = 0
    #Probably should be fixed in main code:
    #wallet.index_cache is only assigned in Wallet.__init__(),
    #meaning a second sync in the same script, after some transactions,
    #will not know about the latest index_cache value (see is_index_ahead_of_cache),
    #whereas a real re-sync will involve reading the cache from disk.
    #Hence, simulation of the fact that the cache index will
    #be read from the file on restart:
    wallet.index_cache = wallet.index

    while not jm_single().bc_interface.wallet_synced:
        #Wallet.__init__() resets index to zero.
        wallet.index = []
        for i in range(5):
            wallet.index.append([0, 0])
        #Wallet.__init__() also updates the cache index
        #from file, but we can reuse from the above pre-loop setting,
        #since nothing else in sync will overwrite the cache.

        #for regtest add_watchonly_addresses does not exit(), so can
        #just repeat as many times as possible. This might
        #be usable for non-test code (i.e. no need to restart the
        #script over and over again)?
        sync_count += 1
        log.debug("TRYING SYNC NUMBER: " + str(sync_count))
        jm_single().bc_interface.sync_wallet(wallet)
        #avoid infinite loop on failure.
        assert sync_count < 10
    #Wallet should recognize index_cache on sync, so should not need to
    #run sync process more than twice (twice if cache bump has moved us
    #past the first round of imports).
    assert sync_count <= 2
    #validate the wallet index values after sync
    for i, ws in enumerate(wallet_structure):
        assert wallet.index[i][0] == ws #spends into external only
    #Same number as above; note it includes the spammer's extras.
    assert wallet.index[0][1] == num_txs+fake_count*2*num_txs
    assert wallet.index[1][1] == num_txs #one change per transaction
    for i in range(2,5):
        assert wallet.index[i][1] == 0 #unused

    #Now try to do more transactions as sanity check.
    do_tx(wallet, 50000000)


@pytest.mark.parametrize(
    "wallet_structure, wallet_file, password, ic",
    [
        #As usual, more test cases are preferable but time
        #of build test is too long, so only one activated.
        #([11,3,4,5,6], 'test_import_wallet.json', 'import-pwd',
        # [(12,3),(100,99),(7, 40), (200, 201), (10,0)]
        # ),
        ([1,3,0,2,9], 'test_import_wallet.json', 'import-pwd',
         [(0,7),(100,99),(0, 0), (200, 201), (21,41)]
         ),
    ])
def test_wallet_sync_from_scratch(setup_wallets, wallet_structure,
                                  wallet_file, password, ic):
    """Simulate a scenario in which we use a new bitcoind, thusly:
    generate a new wallet and simply pretend that it has an existing
    index_cache. This will force import of all addresses up to
    the index_cache values.
    """
    setup_import(mainnet=False)
    wallet = make_wallets(1,[wallet_structure],
                              fixed_seeds=[wallet_file],
                              test_wallet=True, passwords=[password])[0]['wallet']
    sync_count = 0
    jm_single().bc_interface.wallet_synced = False
    wallet.index_cache = ic
    while not jm_single().bc_interface.wallet_synced:
        wallet.index = []
        for i in range(5):
            wallet.index.append([0, 0])
        jm_single().bc_interface.sync_wallet(wallet)
        sync_count += 1
        #avoid infinite loop
        assert sync_count < 10
        log.debug("Tried " + str(sync_count) + " times")
    #after #586 we expect to ALWAYS succeed within 2 rounds
    assert sync_count == 2
    #for each external branch, the new index may be higher than
    #the original index_cache if there was a higher used address
    expected_wallet_index = []
    for i, val in enumerate(wallet_structure):
        if val > wallet.index_cache[i][0]:
            expected_wallet_index.append([val, wallet.index_cache[i][1]])
        else:
            expected_wallet_index.append([wallet.index_cache[i][0],
                                          wallet.index_cache[i][1]])
    assert wallet.index == expected_wallet_index


@pytest.mark.parametrize(
    "pwd, in_privs",
    [
        ("import-pwd", ["L1RrrnXkcKut5DEMwtDthjwRcTTwED36thyL1DebVrKuwvohjMNi",
                        "Kz6UJmQACJmLtaQj5A3JAge4kVTNQ8gbvXuwbmCj7bsaabudb3RD"]
         ),
    ])
def test_import_privkey(setup_wallets, pwd, in_privs):
    """This tests successful import of WIF compressed private keys
    into the wallet for mainnet.
    """
    setup_import()
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

def setup_import(mainnet=True):
    try:
        os.remove("wallets/test_import_wallet.json")
    except:
        pass
    if mainnet:
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
    jm_single().config.set("BLOCKCHAIN", "network", "testnet")

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
        jm_single().bc_interface.wallet_synced = False
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
