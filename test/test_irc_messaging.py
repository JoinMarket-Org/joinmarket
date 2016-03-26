#! /usr/bin/env python
from __future__ import absolute_import
'''Tests of joinmarket bots end-to-end (including IRC and bitcoin) '''

import subprocess
import signal
import os
import pytest
import time
import threading
from commontest import local_command, make_wallets
from joinmarket.message_channel import CJPeerError
import joinmarket.irc
from joinmarket import load_program_config, IRCMessageChannel

python_cmd = "python2"
yg_cmd = "yield-generator-basic.py"
yg_name = None

class DummyMC(IRCMessageChannel):
    def __init__(self, nick):
        super(DummyMC, self).__init__(nick)

def on_order_seen(counterparty, oid, ordertype, minsize,
                                           maxsize, txfee, cjfee):
    global yg_name
    yg_name = counterparty

def on_pubkey(pubkey):
    print "received pubkey: " + pubkey

class RawIRCThread(threading.Thread):

    def __init__(self, ircmsgchan):
        threading.Thread.__init__(self, name='RawIRCThread')
        self.daemon = True
        self.ircmsgchan = ircmsgchan
    
    def run(self):
        self.ircmsgchan.run()

def test_junk_messages(setup_messaging):
    #start a yg bot just to receive messages
    wallets = make_wallets(1,
                           wallet_structures=[[1,0,0,0,0]],
                           mean_amt=1)
    wallet = wallets[0]['wallet']
    ygp = local_command([python_cmd, yg_cmd,\
                             str(wallets[0]['seed'])], bg=True)
    
    #start a raw IRCMessageChannel instance in a thread;
    #then call send_* on it with various errant messages
    mc = DummyMC("irc_ping_test")
    mc.register_orderbookwatch_callbacks(on_order_seen=on_order_seen)
    mc.register_taker_callbacks(on_pubkey=on_pubkey)    
    RawIRCThread(mc).start()
    time.sleep(1)
    mc._IRCMessageChannel__pubmsg("!orderbook")
    time.sleep(1)
    mc._IRCMessageChannel__pubmsg("!orderbook!orderbook")
    time.sleep(1)
    mc._IRCMessageChannel__pubmsg("junk and crap"*20)
    time.sleep(5)
    #try:
    with pytest.raises(CJPeerError) as e_info:
        mc.send_error(yg_name, "fly you fools!")
    #except CJPeerError:
    #    print "CJPeerError raised"
    #    pass
    time.sleep(5)
    mc.shutdown()
    ygp.send_signal(signal.SIGINT)
    ygp.wait()

@pytest.fixture(scope="module")
def setup_messaging():
    #Trigger PING LAG sending artificially
    joinmarket.irc.PING_INTERVAL = 3    
    load_program_config()




