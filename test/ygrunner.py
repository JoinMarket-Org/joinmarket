#! /usr/bin/env python
from __future__ import absolute_import
'''Creates wallets and yield generators in regtest. 
   Provides seed for joinmarket-qt test.
   This should be run via pytest, even though
   it's NOT part of the test-suite, because that
   makes it much easier to handle start up and
   shut down of the environment.
   Run it like:
   PYTHONPATH=.:$PYTHONPATH py.test \
   --btcroot=/path/to/bitcoin/bin/ \
   --btcpwd=123456abcdef --btcconf=/blah/bitcoin.conf \
   --nirc=2 -s test/ygrunner.py
   '''

import subprocess
import signal
from commontest import local_command, make_wallets
import os
import pytest
import sys
import time
from joinmarket import load_program_config, jm_single

#for running bots as subprocesses
python_cmd = 'python2'
#yg_cmd = 'yield-generator-basic.py'
yg_cmd = 'yield-generator-mixdepth.py'
#yg_cmd = 'yield-generator-deluxe.py'

@pytest.mark.parametrize(
    "num_ygs, wallet_structures, mean_amt",
    [
        # 1sp 3yg, 2 mixdepths, sweep from depth1
        (4, [[1, 3, 0, 0, 0]] * 5, 2),
    ])
def test_start_ygs(setup_ygrunner, num_ygs, wallet_structures, mean_amt):
    """Set up some wallets, for the ygs and 1 sp.
    Then start the ygs in background and publish
    the seed of the sp wallet for easy import into -qt
    """
    wallets = make_wallets(num_ygs + 1,
                           wallet_structures=wallet_structures,
                           mean_amt=mean_amt)
    #the sendpayment bot uses the last wallet in the list
    wallet = wallets[num_ygs]['wallet']
    print "Seed : " + wallets[num_ygs]['seed']
    #useful to see the utxos on screen sometimes
    jm_single().bc_interface.sync_wallet(wallet)
    print wallet.unspent

    yigen_procs = []
    for i in range(num_ygs):
        ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)
    try:
        while True:
            time.sleep(20)
            print 'waiting'   
    finally:
        if any(yigen_procs):
            for ygp in yigen_procs:
                #NB *GENTLE* shutdown is essential for
                #test coverage reporting!
                ygp.send_signal(signal.SIGINT)
                ygp.wait()

@pytest.fixture(scope="module")
def setup_ygrunner():
    load_program_config()
    