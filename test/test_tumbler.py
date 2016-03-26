#! /usr/bin/env python
from __future__ import absolute_import
'''Tests of joinmarket bots end-to-end (including IRC and bitcoin) '''

import subprocess
import signal
from commontest import local_command, make_wallets
import os
import pytest
import time
from joinmarket import Taker, load_program_config, IRCMessageChannel
from joinmarket import validate_address, jm_single
from joinmarket import random_nick, get_p2pk_vbyte
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, debug_dump_object
import json
import tumbler
import bitcoin as btc
import copy
from pprint import pprint

#for running bots as subprocesses
python_cmd = 'python2'
yg_cmd = 'yield-generator-basic.py'
#yg_cmd = 'yield-generator-mixdepth.py'
#yg_cmd = 'yield-generator-deluxe.py'

class Options(object):
    pass

def get_options():
    options = Options()
    options.mixdepthsrc = 0
    options.mixdepthcount = 4
    options.minmakercount = 2
    options.makercountrange = (6, 0)
    options.maxcjfee = (0.01, 10000)
    options.txfee = 5000
    options.addrcount = 3
    options.donateamount = 0.5
    options.txcountparams = (4, 1)
    options.mintxcount = 1
    options.amountpower = 100
    options.timelambda = 0.2
    options.waittime = 10
    options.mincjamount = 1000000
    options.liquiditywait = 5
    return options

def test_generate_tumbler_tx():
    options = get_options()
    destaddrs = ["A","B","C"]
    tx_list = tumbler.generate_tumbler_tx(destaddrs, options)
    from pprint import pformat
    print pformat(tx_list)

@pytest.mark.parametrize(
    "num_ygs, wallet_structures, mean_amt, sdev_amt, yg_excess",
    [
        # basic 1sp 2yg
        (6, [[4, 4, 4, 4, 4]] * 7, 0.5, 0.3, 10),
    ])
def test_tumbler(setup_tumbler, num_ygs, wallet_structures, mean_amt, sdev_amt,
                 yg_excess):
    """Test of tumbler code, with yield generators in background.
    """
    log = get_log()
    options = Options()
    options.mixdepthsrc = 0
    options.mixdepthcount = 4
    options.minmakercount = 2
    options.makercountrange = (num_ygs, 0)
    options.maxcjfee = (0.01, 10000)
    options.txfee = 5000
    options.addrcount = 3
    options.donateamount = 0.5
    options.txcountparams = (4, 1)
    options.mintxcount = 1
    options.amountpower = 100
    options.timelambda = 0.2
    options.waittime = 10
    options.mincjamount = 1000000
    options.liquiditywait = 5

    wallets = make_wallets(num_ygs + 1,
                           wallet_structures=wallet_structures,
                           mean_amt=mean_amt, sdev_amt=sdev_amt)
    #need to make sure that at least some ygs have substantially
    #more coins for last stages of sweep/spend in tumble:
    for i in range(num_ygs):
        jm_single().bc_interface.grab_coins(
                            wallets[i]['wallet'].get_external_addr(0), yg_excess)    
    #the tumbler bot uses the last wallet in the list
    wallet = wallets[num_ygs]['wallet']

    yigen_procs = []
    for i in range(num_ygs):
        ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

    #A significant delay is needed to wait for the yield generators to sync
    time.sleep(20)
    destaddrs = []
    for i in range(3):
        if btc.secp_present:
            destaddr = btc.privkey_to_address(
                os.urandom(32),
                from_hex=False,
                magicbyte=get_p2pk_vbyte())
        else:
            destaddr = btc.privkey_to_address(
                os.urandom(32),
                magicbyte=get_p2pk_vbyte())
        addr_valid, errormsg = validate_address(destaddr)
        assert addr_valid, "Invalid destination address: " + destaddr + \
                   ", error message: " + errormsg
        destaddrs.append(destaddr)
    tx_list = tumbler.generate_tumbler_tx(destaddrs, options)
    pprint(tx_list)
    if options.addrcount + 1 > options.mixdepthcount:
        print('not enough mixing depths to pay to all destination addresses, '
              'increasing mixdepthcount')
        options.mixdepthcount = options.addrcount + 1

    tx_list2 = copy.deepcopy(tx_list)
    tx_dict = {}
    for tx in tx_list2:
        srcmixdepth = tx['srcmixdepth']
        tx.pop('srcmixdepth')
        if srcmixdepth not in tx_dict:
            tx_dict[srcmixdepth] = []
        tx_dict[srcmixdepth].append(tx)
    dbg_tx_list = []
    for srcmixdepth, txlist in tx_dict.iteritems():
        dbg_tx_list.append({'srcmixdepth': srcmixdepth, 'tx': txlist})
    log.debug('tumbler transaction list')
    pprint(dbg_tx_list)

    total_wait = sum([tx['wait'] for tx in tx_list])
    print('creates ' + str(len(tx_list)) + ' transactions in total')
    print('waits in total for ' + str(len(tx_list)) + ' blocks and ' + str(
            total_wait) + ' minutes')
    total_block_and_wait = len(tx_list) * 10 + total_wait
    print('estimated time taken ' + str(total_block_and_wait) + ' minutes or ' +
          str(round(total_block_and_wait / 60.0, 2)) + ' hours')

    jm_single().nickname = random_nick()

    log.debug('starting tumbler')

    jm_single().bc_interface.sync_wallet(wallet)
    irc = IRCMessageChannel(jm_single().nickname)
    tumbler_bot = tumbler.Tumbler(irc, wallet, tx_list, options)
    try:
        log.debug('starting irc')
        irc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'wallet_name', 'seed'])
        debug_dump_object(tumbler_bot)
        import traceback
        log.debug(traceback.format_exc())
    finally:
        if any(yigen_procs):
            for ygp in yigen_procs:
                #NB *GENTLE* shutdown is essential for
                #test coverage reporting!
                ygp.send_signal(signal.SIGINT)
                ygp.wait()
    #wait for block generation
    time.sleep(5)
    received = jm_single().bc_interface.get_received_by_addr(
        [destaddr], None)['data'][0]['balance']
    assert received != 0
    """TODO: figure out a sensible assertion check for the destination
    if amount != 0:
        assert received == amount, "sendpayment failed - coins not arrived, " +\
           "received: " + str(received)
    """


@pytest.fixture(scope="module")
def setup_tumbler():
    load_program_config()
