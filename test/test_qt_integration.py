#! /usr/bin/env python
from __future__ import absolute_import
'''test of bitcoin-qt integration'''

import subprocess
import signal
from commontest import local_command, make_wallets
from conftest import start_bitcoind, stop_bitcoind
import os
import pytest
import time
from math import floor

from joinmarket import Taker, load_program_config, IRCMessageChannel
from joinmarket import validate_address, jm_single
from joinmarket import random_nick, get_p2pk_vbyte
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, debug_dump_object

import joinmarket.irc
import sendpayment
import bitcoin as btc

#for running bots as subprocesses
python_cmd = 'python2'
yg_cmd = 'yield-generator-basic.py'
qt_cj_cmd = 'bitcoinqt-coinjoiner.py'

log = get_log()

#quite similar to test_regtest.py
def test_qt_integration(setup_qt_int):
    makercount = 3
    amount = 1
    wallets = make_wallets(makercount,
                           wallet_structures=[[1, 0, 0, 0, 0]] * makercount,
                           mean_amt=10)
    '''
    ## bitcoin core's cpu miner sends the coinbase to an obsolete p2pk address
    ## so it was believed we'd need to send coins to a p2pkh before using
    balance = jm_single().bc_interface.rpc('getbalance', [])
    log.debug('total balance = ' + str(balance))
    out_address = jm_single().bc_interface.rpc('getnewaddress', [])
    send_chunk = 1000.0

    if balance < send_chunk:
        jm_single().bc_interface.rpc('sendtoaddress', [out_address, balance-amount*2])
    else:
        ##sending a tx with too many inputs gives a Transaction Too Large error
        send_count = int(floor(balance / send_chunk))
        leftover = balance - send_count*send_chunk
        for i in range(send_count):
            jm_single().bc_interface.rpc('sendtoaddress', [out_address, send_chunk])
        jm_single().bc_interface.rpc('sendtoaddress', [out_address, leftover-amount*2])
    '''

    log.debug('stopping bitcoind')
    stop_bitcoind()
    log.debug('starting bitcoind with no wallet broadcast')
    start_bitcoind(['-walletbroadcast=0'])

    jm_procs = []
    for i in range(makercount):
        ygp = local_command([python_cmd, yg_cmd,
                             str(wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        jm_procs.append(ygp)

    log.debug('sleeping for some time to wait for ygens to sync')
    time.sleep(240) ##would be improved by detecting when ygens are done

    qt_cjer_proc = local_command([python_cmd, qt_cj_cmd, '--yes', '-N', '2',
        '0.1'], bg=True)
    jm_procs.append(qt_cjer_proc)
    time.sleep(5)

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
    #print 'destaddr = ' + destaddr

    txid = jm_single().bc_interface.rpc('sendtoaddress', [destaddr, amount])
    assert txid != None, "something went wrong, txid = None"

    log.debug('sleeping for some time to allow coinjoining to happen')
    time.sleep(60)
    for p in jm_procs:
        #NB *GENTLE* shutdown is essential for
        #test coverage reporting!
        p.send_signal(signal.SIGINT)
        p.wait()
    #wait for block generation

    #this is complicated by the fact that the coinjoin address
    #in bitcoinqt-coinjoiner.py cant be in the bitcoinqt wallet
    blockcount = jm_single().bc_interface.rpc('getblockcount', [])
    earlier_blockhash = jm_single().bc_interface.rpc('getblockhash', [blockcount - 3])
    tx_list_json = jm_single().bc_interface.rpc('listsinceblock', [earlier_blockhash])
    checked_txids = set()
    found_outputs = []
    import pprint
    for tx in tx_list_json['transactions']:
        if 'category' not in tx or tx['category'] != 'send':
            continue
        if tx['txid'] in checked_txids:
            continue
        checked_txids.add(tx['txid'])
        if tx['confirmations'] < 1:
            continue
        txhex = jm_single().bc_interface.rpc('gettransaction', [tx['txid']])
        if 'hex' not in txhex:
            continue
        txhex = str(txhex['hex'])
        txd = btc.deserialize(txhex)
        outputs = dict([(btc.script_to_address(o['script'],
            get_p2pk_vbyte()), o['value']) for o in txd['outs']])
        addrs = outputs.keys()
        if destaddr in addrs:
            #print 'found destaddr'
            found_outputs.append(outputs)

    #'''
    log.debug('restarting bitcoind back to wallet broadcasting enabled')
    stop_bitcoind()
    start_bitcoind()
    #'''

    log.debug('outputs = ' + str(found_outputs))
    assert len(found_outputs) == 1, " failed to find transaction sending to that address, or found too many txes"
    assert found_outputs[0][destaddr] == amount*1e8, " amount not matching"
    assert len(found_outputs[0]) > 2, " not a coinjoin"

    return True

@pytest.fixture(scope="module")
def setup_qt_int():
    load_program_config()
