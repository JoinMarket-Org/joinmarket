#! /usr/bin/env python
from __future__ import absolute_import
'''Tests of Proof of discrete log equivalence commitments.'''
import os
import secp256k1
import bitcoin as btc
import binascii
import json
import pytest

import subprocess
import signal
from commontest import local_command, make_wallets
import shutil
import time
from pprint import pformat
from joinmarket import Taker, load_program_config, IRCMessageChannel
from joinmarket import validate_address, jm_single, get_irc_mchannels
from joinmarket import random_nick, get_p2pk_vbyte, MessageChannelCollection
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, debug_dump_object
import joinmarket.irc
import sendpayment


#for running bots as subprocesses
python_cmd = 'python2'
yg_cmd = 'yield-generator-basic.py'
#yg_cmd = 'yield-generator-mixdepth.py'
#yg_cmd = 'yield-generator-deluxe.py'

log = get_log()

def test_commitments_empty(setup_podle):
    """Ensure that empty commitments file
    results in {}
    """
    assert btc.get_podle_commitments() == ([], {})

def test_commitment_retries(setup_podle):
    """Assumes no external commitments available.
    Generate pretend priv/utxo pairs and check that they can be used
    taker_utxo_retries times.
    """
    allowed = jm_single().config.getint("POLICY", "taker_utxo_retries")
    #make some pretend commitments
    dummy_priv_utxo_pairs = [(btc.sha256(os.urandom(10)),
           btc.sha256(os.urandom(10))+":0") for _ in range(10)]
    #test a single commitment request of all 10
    for x in dummy_priv_utxo_pairs:
        p = btc.generate_podle([x], allowed)
        assert p
    #At this point slot 0 has been taken by all 10.
    for i in range(allowed-1):
        p = btc.generate_podle(dummy_priv_utxo_pairs[:1], allowed)
        assert p
    p = btc.generate_podle(dummy_priv_utxo_pairs[:1], allowed)
    assert p is None

def generate_single_podle_sig(priv, i):
    """Make a podle entry for key priv at index i, using a dummy utxo value.
    This calls the underlying 'raw' code based on the class PoDLE, not the
    library 'generate_podle' which intelligently searches and updates commitments.
    """
    dummy_utxo = btc.sha256(priv) + ":3"
    podle = btc.PoDLE(dummy_utxo, binascii.hexlify(priv))
    r = podle.generate_podle(i)
    return (r['P'], r['P2'], r['sig'],
            r['e'], r['commit'])

def test_rand_commitments(setup_podle):
    #TODO bottleneck i believe is tweak_mul due
    #to incorrect lack of precomputed context in upstream library.
    for i in range(20):
        priv = os.urandom(32)
        Pser, P2ser, s, e, commitment = generate_single_podle_sig(priv, 1 + i%5)
        assert btc.verify_podle(Pser, P2ser, s, e, commitment)
        #tweak commitments to verify failure
        tweaked = [x[::-1] for x in [Pser, P2ser, s, e, commitment]]
        for i in range(5):
            #Check failure on garbling of each parameter
            y = [Pser, P2ser, s, e, commitment]
            y[i] = tweaked[i]
            fail = False
            try: 
                fail = btc.verify_podle(*y)
            except:
                pass
            finally:
                assert not fail

def test_nums_verify(setup_podle):
    """Check that the NUMS precomputed values are
    valid according to the code; assertion check
    implicit.
    """
    btc.verify_all_NUMS()

@pytest.mark.parametrize(
    "num_ygs, wallet_structures, mean_amt, mixdepth, sending_amt",
    [
        (3, [[1, 0, 0, 0, 0]] * 4, 10, 0, 100000000),
    ])
def test_failed_sendpayment(setup_podle, num_ygs, wallet_structures, mean_amt,
                     mixdepth, sending_amt):
    """Test of initiating joins, but failing to complete,
    to see commitment usage. YGs in background as per test_regtest.
    Use sweeps to avoid recover_from_nonrespondants without intruding
    into sendpayment code.
    """
    makercount = num_ygs
    answeryes = True
    txfee = 5000
    waittime = 3
    #Don't want to wait too long, but must account for possible
    #throttling with !auth
    jm_single().maker_timeout_sec = 12
    amount = 0
    wallets = make_wallets(makercount + 1,
                           wallet_structures=wallet_structures,
                           mean_amt=mean_amt)
    #the sendpayment bot uses the last wallet in the list
    wallet = wallets[makercount]['wallet']

    yigen_procs = []
    for i in range(makercount):
        ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

    #A significant delay is needed to wait for the yield generators to sync
    time.sleep(20)
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

    #Allow taker more retries than makers allow, so as to trigger
    #blacklist failure case
    jm_single().config.set("POLICY", "taker_utxo_retries", "4")
    #override ioauth receipt with a dummy do-nothing callback:
    def on_ioauth(*args):
        log.debug("Taker received: " + ','.join([str(x) for x in args]))

    class DummySendPayment(sendpayment.SendPayment):
        def __init__(self, msgchan, wallet, destaddr, amount, makercount, txfee,
                 waittime, mixdepth, answeryes, chooseOrdersFunc, on_ioauth):
            self.on_ioauth = on_ioauth
            self.podle_fails = 0
            self.podle_allowed_fails = 3 #arbitrary; but do it more than once
            self.retries = 0
            super(DummySendPayment, self).__init__(msgchan, wallet,
                    destaddr, amount, makercount, txfee, waittime,
                    mixdepth, answeryes, chooseOrdersFunc)
        def on_welcome(self):
            Taker.on_welcome(self)
            DummyPaymentThread(self).start()        

    class DummyPaymentThread(sendpayment.PaymentThread):
        def finishcallback(self, coinjointx):
            #Don't ignore makers and just re-start
            self.taker.retries += 1
            if self.taker.podle_fails == self.taker.podle_allowed_fails:
                self.taker.msgchan.shutdown()
                return
            self.create_tx()
        def create_tx(self):
            try:
                super(DummyPaymentThread, self).create_tx()
            except btc.PoDLEError:
                log.debug("Got one commit failure, continuing")
                self.taker.podle_fails += 1

    taker = DummySendPayment(mcc, wallet, destaddr, amount, makercount,
                                    txfee, waittime, mixdepth, answeryes,
                                    chooseOrdersFunc, on_ioauth)
    try:
        log.debug('starting message channels')
        mcc.run()
    finally:
        if any(yigen_procs):
            for ygp in yigen_procs:
                #NB *GENTLE* shutdown is essential for
                #test coverage reporting!
                ygp.send_signal(signal.SIGINT)
                ygp.wait()
    #We should have been able to try (tur -1) + podle_allowed_fails times
    assert taker.retries == jm_single().config.getint(
        "POLICY", "taker_utxo_retries") + taker.podle_allowed_fails
    #wait for block generation
    time.sleep(2)
    received = jm_single().bc_interface.get_received_by_addr(
        [destaddr], None)['data'][0]['balance']
    #Sanity check no transaction succeeded
    assert received == 0

def test_external_commitment_used(setup_podle):
    tries = jm_single().config.getint("POLICY","taker_utxo_retries")
    #Don't want to wait too long, but must account for possible
    #throttling with !auth
    jm_single().maker_timeout_sec = 12
    amount = 50000000
    wallets = make_wallets(3,
                        wallet_structures=[[1,0,0,0,0],[1,0,0,0,0],[1,1,0,0,0]],
                        mean_amt=1)
    #the sendpayment bot uses the last wallet in the list
    wallet = wallets[2]['wallet']
    yigen_procs = []
    for i in range(2):
        ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

    #A significant delay is needed to wait for the yield generators to sync
    time.sleep(10)
    destaddr = btc.privkey_to_address(
            binascii.hexlify(os.urandom(32)),
            magicbyte=get_p2pk_vbyte())
    addr_valid, errormsg = validate_address(destaddr)
    assert addr_valid, "Invalid destination address: " + destaddr + \
           ", error message: " + errormsg

    log.debug('starting sendpayment')

    jm_single().bc_interface.sync_wallet(wallet)
    
    #Trigger PING LAG sending artificially
    joinmarket.irc.PING_INTERVAL = 3
    
    mcs = [IRCMessageChannel(c) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    #add all utxo in mixdepth 0 to 'used' list of commitments,
    utxos = wallet.get_utxos_by_mixdepth()[0]
    for u, addrval in utxos.iteritems():
        priv = wallet.get_key_from_addr(addrval['address'])
        podle = btc.PoDLE(u, priv)
        for i in range(tries):
            #loop because we want to use up all retries of this utxo
            commitment = podle.generate_podle(i)['commit']
            btc.update_commitments(commitment=commitment)

    #create a new utxo, notionally from an external source; to make life a little
    #easier we'll pay to another mixdepth, but this is OK because
    #taker does not source from here currently, only from the utxos chosen
    #for the transaction, not the whole wallet. So we can treat it as if
    #external (don't access its privkey).
    utxos = wallet.get_utxos_by_mixdepth()[1]
    ecs = {}
    for u, addrval in utxos.iteritems():
        priv = wallet.get_key_from_addr(addrval['address'])
        ecs[u] = {}
        ecs[u]['reveal']={}
        for j in range(tries):
            P, P2, s, e, commit = generate_single_podle_sig(
                binascii.unhexlify(priv), j)
            if 'P' not in ecs[u]:
                ecs[u]['P'] = P
            ecs[u]['reveal'][j] = {'P2':P2, 's':s, 'e':e}
    btc.update_commitments(external_to_add=ecs)
    #Now the conditions described above hold. We do a normal single
    #sendpayment.
    taker = sendpayment.SendPayment(mcc, wallet, destaddr, amount, 2,
                                    5000, 3, 0, True,
                                    weighted_order_choose)
    try:
        log.debug('starting message channels')
        mcc.run()
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
    assert received == amount, "sendpayment failed - coins not arrived, " +\
           "received: " + str(received)
    #Cleanup - remove the external commitments added
    btc.update_commitments(external_to_remove=ecs)

@pytest.mark.parametrize(
    "consume_tx, age_required, cmt_age",
    [
        (True, 9, 5),
        (True, 9, 12),
    ])
def test_tx_commitments_used(setup_podle, consume_tx, age_required, cmt_age):
    tries = jm_single().config.getint("POLICY","taker_utxo_retries")
    #remember and reset at the end
    taker_utxo_age = jm_single().config.getint("POLICY", "taker_utxo_age")
    jm_single().config.set("POLICY", "taker_utxo_age", str(age_required))
    #Don't want to wait too long, but must account for possible
    #throttling with !auth
    jm_single().maker_timeout_sec = 12
    amount = 0
    wallets = make_wallets(3,
                        wallet_structures=[[1,2,1,0,0],[1,2,0,0,0],[2,2,1,0,0]],
                        mean_amt=1)
    #the sendpayment bot uses the last wallet in the list
    wallet = wallets[2]['wallet']

    #make_wallets calls grab_coins which mines 1 block per individual payout,
    #so the age of the coins depends on where they are in that list. The sendpayment
    #is the last wallet in the list, and we choose the non-tx utxos which are in
    #mixdepth 1 and 2 (2 and 1 utxos in each respectively). We filter for those
    #that have sufficient age, so to get 1 which is old enough, it will be the oldest,
    #which will have an age of 2 + 1 (the first utxo spent to that wallet).
    #So if we need an age of 6, we need to mine 3 more blocks.
    blocks_reqd = cmt_age - 3
    jm_single().bc_interface.tick_forward_chain(blocks_reqd)
    yigen_procs = []
    for i in range(2):
        ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[i]['seed'])], bg=True)
        time.sleep(2)  #give it a chance
        yigen_procs.append(ygp)

    time.sleep(5)
    destaddr = btc.privkey_to_address(
            binascii.hexlify(os.urandom(32)),
            magicbyte=get_p2pk_vbyte())
    addr_valid, errormsg = validate_address(destaddr)
    assert addr_valid, "Invalid destination address: " + destaddr + \
           ", error message: " + errormsg

    log.debug('starting sendpayment')

    jm_single().bc_interface.sync_wallet(wallet)
    log.debug("Here is the whole wallet: \n" + str(wallet.unspent))
    #Trigger PING LAG sending artificially
    joinmarket.irc.PING_INTERVAL = 3

    mcs = [IRCMessageChannel(c) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    if consume_tx:
        #add all utxo in mixdepth 0 to 'used' list of commitments,
        utxos = wallet.get_utxos_by_mixdepth()[0]
        for u, addrval in utxos.iteritems():
            priv = wallet.get_key_from_addr(addrval['address'])
            podle = btc.PoDLE(u, priv)
            for i in range(tries):
                #loop because we want to use up all retries of this utxo
                commitment = podle.generate_podle(i)['commit']
                btc.update_commitments(commitment=commitment)

    #Now test a sendpayment from mixdepth 0 with all the depth 0 utxos
    #used up, so that the other utxos in the wallet get used.
    taker = sendpayment.SendPayment(mcc, wallet, destaddr, amount, 2,
                                    5000, 3, 0, True,
                                    weighted_order_choose)
    try:
        log.debug('starting message channels')
        mcc.run()
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
    jm_single().config.set("POLICY", "taker_utxo_age", str(taker_utxo_age))
    if cmt_age < age_required:
        assert received == 0, "Coins arrived but shouldn't"
    else:
        assert received != 0, "sendpayment failed - coins not arrived, " +\
           "received: " + str(received)

def test_external_commitments(setup_podle):
    """Add this generated commitment to the external list
    {txid:N:{'P':pubkey, 'reveal':{1:{'P2':P2,'s':s,'e':e}, 2:{..},..}}}
    Note we do this *after* the sendpayment test so that the external
    commitments will not erroneously used (they are fake).
    """
    ecs = {}
    tries = jm_single().config.getint("POLICY","taker_utxo_retries")
    for i in range(10):
        priv = os.urandom(32)
        dummy_utxo = btc.sha256(priv)+":2"
        ecs[dummy_utxo] = {}
        ecs[dummy_utxo]['reveal']={}
        for j in range(tries):
            P, P2, s, e, commit = generate_single_podle_sig(priv, j)
            if 'P' not in ecs[dummy_utxo]:
                ecs[dummy_utxo]['P']=P
            ecs[dummy_utxo]['reveal'][j] = {'P2':P2, 's':s, 'e':e}
    btc.add_external_commitments(ecs)
    used, external = btc.get_podle_commitments()
    for  u in external:
        assert external[u]['P'] == ecs[u]['P']
        for i in range(tries):
            for x in ['P2', 's', 'e']:
                assert external[u]['reveal'][str(i)][x] == ecs[u]['reveal'][i][x]

@pytest.fixture(scope="module")
def setup_podle(request):
    load_program_config()
    prev_commits = False
    #back up any existing commitments
    pcf = btc.get_commitment_file()
    log.debug("Podle file: " + pcf)
    if os.path.exists(pcf):
        os.rename(pcf, pcf + ".bak")
        prev_commits = True
    def teardown():
        if prev_commits:
            os.rename(pcf + ".bak", pcf)
        else:
            os.remove(pcf)
    request.addfinalizer(teardown)
