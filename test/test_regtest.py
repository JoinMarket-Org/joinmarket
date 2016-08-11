#! /usr/bin/env python
from __future__ import absolute_import
'''Tests of joinmarket bots end-to-end (including IRC and bitcoin) '''

import subprocess
import signal
from commontest import local_command, make_wallets
import os
import shutil
import pytest
import time
from joinmarket import Taker, load_program_config, IRCMessageChannel
from joinmarket import validate_address, jm_single, get_irc_mchannels
from joinmarket import random_nick, get_p2pk_vbyte, MessageChannelCollection
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, debug_dump_object
import joinmarket.irc
import json
import sendpayment
import bitcoin as btc

#for running bots as subprocesses
python_cmd = 'python2'
yg_cmd = 'yield-generator-basic.py'
#yg_cmd = 'yield-generator-mixdepth.py'
#yg_cmd = 'yield-generator-deluxe.py'


@pytest.mark.parametrize(
    "num_ygs, wallet_structures, mean_amt, mixdepth, sending_amt, ygcfs, fails, donate",
    [
        #Some tests are commented out to keep build test time reasonable.
        # basic 1sp 2yg.
        #(4, [[1, 0, 0, 0, 0]] * 5, 10, 0, 100000000, None, None, 0.5),
        (4, [[1, 0, 0, 0, 0]] * 5, 10, 0, 100000000, None, None, None),
        #Testing different message channel collections. (Needs manual config at
        #the moment - create different config files for each yg).
        #(4, [[1, 0, 0, 0, 0]] * 5, 10, 0, 100000000, ["j2.cfg", "j3.cfg",
        #                                              "j4.cfg", "j5.cfg"], None),
        # 1sp 3yg, 2 mixdepths - testing different failure times to
        #see if recovery works.
        #(5, [[1, 2, 0, 0, 0]] * 6, 4, 1, 1234500, None, None),
        (4, [[1, 2, 0, 0, 0]] * 5, 4, 1, 1234500, None, ('break',0,6), None),
        #(5, [[1, 2, 0, 0, 0]] * 6, 4, 1, 1234500, None, ('shutdown',0,12)),
        #(5, [[1, 2, 0, 0, 0]] * 6, 4, 1, 1234500, None, ('break',1, 6)),
        # 1sp 6yg, 4 mixdepths, sweep from depth 0 (test large number of makers)
        (8, [[1, 3, 0, 0, 0]] * 9, 4, 0, 0, None, None, None),
    ])
def test_sendpayment(setup_regtest, num_ygs, wallet_structures, mean_amt,
                     mixdepth, sending_amt, ygcfs, fails, donate):
    """Test of sendpayment code, with yield generators in background.
    """
    log = get_log()
    makercount = num_ygs
    answeryes = True
    txfee = 5000
    waittime = 5
    amount = sending_amt
    wallets = make_wallets(makercount + 1,
                           wallet_structures=wallet_structures,
                           mean_amt=mean_amt)
    #the sendpayment bot uses the last wallet in the list
    wallet = wallets[makercount]['wallet']

    yigen_procs = []
    if ygcfs:
        assert makercount == len(ygcfs)
    for i in range(makercount):
        if ygcfs:
            #back up default config, overwrite before start
            os.rename("joinmarket.cfg", "joinmarket.cfg.bak")
            shutil.copy2(ygcfs[i], "joinmarket.cfg")
        ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)
        if ygcfs:
            #Note: in case of using multiple configs,
            #the starting config is what is used by sendpayment
            os.rename("joinmarket.cfg.bak", "joinmarket.cfg")

    #A significant delay is needed to wait for the yield generators to sync
    time.sleep(20)
    if donate:
        destaddr = None
    else:
        destaddr = btc.privkey_to_address(
            os.urandom(32),
            from_hex=False,
            magicbyte=get_p2pk_vbyte())
        addr_valid, errormsg = validate_address(destaddr)
        assert addr_valid, "Invalid destination address: " + destaddr + \
           ", error message: " + errormsg

    #TODO paramatetrize this as a test variable
    chooseOrdersFunc = weighted_order_choose

    log.debug('starting sendpayment')

    jm_single().bc_interface.sync_wallet(wallet)
    
    #Trigger PING LAG sending artificially
    joinmarket.irc.PING_INTERVAL = 3
    
    mcs = [IRCMessageChannel(c) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    #hack fix for #356 if multiple orders per counterparty
    #removed for now.
    #if amount==0: makercount=2
    taker = sendpayment.SendPayment(mcc, wallet, destaddr, amount, makercount-2,
                                    txfee, waittime, mixdepth, answeryes,
                                    chooseOrdersFunc)
    try:
        log.debug('starting message channels')
        mcc.run(failures=fails)
    finally:
        if any(yigen_procs):
            for ygp in yigen_procs:
                #NB *GENTLE* shutdown is essential for
                #test coverage reporting!
                ygp.send_signal(signal.SIGINT)
                ygp.wait()
    #wait for block generation
    time.sleep(5)
    if not donate:
        received = jm_single().bc_interface.get_received_by_addr(
            [destaddr], None)['data'][0]['balance']
        if amount != 0:
            assert received == amount, "sendpayment failed - coins not arrived, " +\
               "received: " + str(received)
        #TODO: how to check success for sweep case?
        else:
            assert received != 0


@pytest.fixture(scope="module")
def setup_regtest():
    load_program_config()
