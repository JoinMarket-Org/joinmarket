#! /usr/bin/env python
from __future__ import absolute_import
'''Tests of joinmarket bots messaging (using matrix) '''

import subprocess
import signal
import os
import pytest
import time
import threading
from commontest import local_command, make_wallets
from joinmarket.message_channel import CJPeerError
from joinmarket.irc import random_nick
from joinmarket import load_program_config, MatrixMessageChannel

python_cmd = "python2"
yg_cmd = "yield-generator-basic.py"
yg_name = None

class DummyMC(MatrixMessageChannel):
    def __init__(self, username=None):
        super(DummyMC, self).__init__(username)

def on_order_seen(counterparty, oid, ordertype, minsize,
                                           maxsize, txfee, cjfee):
    global yg_name
    print "received order from: " + counterparty
    yg_name = counterparty

def on_pubkey(pubkey):
    print "received pubkey: " + pubkey

class RawMatrixThread(threading.Thread):

    def __init__(self, matrixmsgchan):
        #NB Don't name threads if they're not unique!!
        threading.Thread.__init__(self)
        self.daemon = True
        self.matrixmsgchan = matrixmsgchan
    
    def run(self):
        self.matrixmsgchan.run()

#The two tests below are in a very primitive
#state; a lot more investigation is needed.

def test_privmsg(setup_messaging):
    
    mc = DummyMC(random_nick())
    def oof(nick, oid, amount, taker_pubkey):
        print "got a fill from: " + nick
        print "this oid: " + str(oid)
        #mc.privmsg(nick, "auth", "blah blah")
    mc.register_maker_callbacks(on_order_fill=oof)
    RawMatrixThread(mc).start()
    while not mc.logged_in:
        time.sleep(0.1)
        
    mc2 = DummyMC(random_nick())
    def oos(counterparty, oid, ordertype, minsize,
                                               maxsize, txfee, cjfee):
        print "got a order from cty: " + counterparty
        mc2.privmsg(counterparty, "fill", ' '.join([str(oid), str(23456), "deadbeef"]))
    mc2.register_orderbookwatch_callbacks(on_order_seen=oos)
    RawMatrixThread(mc2).start()
    while not mc2.logged_in:
        time.sleep(0.1)
    
    orders = []
    for oid in range(10):
        order = {'oid': oid + 1,
                         'ordertype': 'relorder',
                         'minsize': 22,
                         'maxsize': 500,
                         'txfee': 2000,
                         'cjfee': 7,
                         'mixdepth': oid}
        orders.append(order)
    mc.announce_orders(orders)
    time.sleep(10)
    mc.shutdown()
    mc2.shutdown()

def test_junk_messages(setup_messaging):
    #start a yg bot just to receive messages
    wallets = make_wallets(1,
                           wallet_structures=[[1,0,0,0,0]],
                           mean_amt=1)
    wallet = wallets[0]['wallet']
    ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[0]['seed'])], bg=True)
    
    time.sleep(20)
    #start a raw IRCMessageChannel instance in a thread;
    #then call send_* on it with various errant messages
    mc = DummyMC()
    mc.register_orderbookwatch_callbacks(on_order_seen=on_order_seen)
    mc.register_taker_callbacks(on_pubkey=on_pubkey)    
    RawMatrixThread(mc).start()
    while not mc.logged_in:
        time.sleep(0.1)
    mc.request_orderbook()
    time.sleep(1)
    #now try directly
    mc.pubmsg("!orderbook")
    time.sleep(1)
    #should be ignored; can we check?
    mc.pubmsg("!orderbook!orderbook")
    time.sleep(1)
    #assuming MAX_MATRIX_LINE_LENGTH is not something crazy
    #small like a few hundred, this should succeed
    mc.pubmsg("junk and crap"*45)
    time.sleep(2)
    #try a long order announcement in public
    #because we don't want to build a real orderbook,
    #call the underlying IRC announce function.
    #TODO: how to test that the sent format was correct?
    mc._announce_orders(["!abc def gh 0001"]*30, None)
    time.sleep(5)
    #try:
    with pytest.raises(CJPeerError) as e_info:
        mc.send_error(yg_name, "fly you fools!")
    time.sleep(5)
    mc.shutdown()
    ygp.send_signal(signal.SIGINT)
    ygp.wait()

@pytest.fixture(scope="module")
def setup_messaging():  
    load_program_config()




