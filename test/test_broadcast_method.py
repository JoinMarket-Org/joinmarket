#! /usr/bin/env python
from __future__ import absolute_import
'''comments here'''

import sys
import time
import sqlite3
from commontest import make_wallets

import bitcoin as btc
import pytest
from joinmarket import load_program_config, jm_single
from joinmarket import get_log, Wallet
from joinmarket import MessageChannel, CoinJoinTX, BlockchainInterface

log = get_log()

msgchan = [None]

msgchan_pushtx_count = [{}]
self_pushtx_count = [0]

sample_tx_hex = (
    "0100000001c74265f31fc5e24895fdc83f7157cc40045235f3a71ae326a219de9de873" +
    "0d8b010000006a473044022076055917470b7ec4f4bb008096266cf816ebb089ad983e" +
    "6a0f63340ba0e6a6cb022059ec938b996a75db10504e46830e13d399f28191b9832bd5" +
    "f61df097b9e0d47801210291941334a00959af4aa5757abf81d2a7d1aca8adb3431c67" +
    "e89419271ba71cb4feffffff023cdeeb03000000001976a914a2426748f14eba44b3f6" +
    "abba3e8bce216ea233f388acf4ebf303000000001976a914bfa366464a464005ba0df8" +
    "6024a6c3ed859f03ac88ac33280600")

class DummyMessageChannel(MessageChannel):

    def run(self): pass
    def shutdown(self): pass
    def _pubmsg(self, msg): pass
    def _privmsg(self, nick, cmd, message): pass
    def _announce_orders(self, orderlist, nick): pass
    def change_nick(self, new_nick):
        self.nick = new_nick
    def fill_orders(self, nick_order_dict, cj_amount, taker_pubkey, commitment):
        pass

    def push_tx(self, nick, txhex):
        msgchan_pushtx_count[0][nick] += 1

class DummyBlockchainInterface(BlockchainInterface):
    def sync_addresses(self, wallet): pass
    def sync_unspent(self, wallet): pass
    def query_utxo_set(self, txouts): pass
    def estimate_fee_per_kb(self, N): pass
    def add_tx_notify(self, txd, unconfirmfun, confirmfun,
            notifyaddr, timeoutfun=None):
        pass

    def pushtx(self, txhex):
        self_pushtx_count[0] += 1
        return True

def dummy_commitment_creator(wallet, utxos, amount):
    return "fake_commitment", "fake_reveal"

def create_testing_cjtx(counterparty_list):
    msgchan_pushtx_count[0] = dict(zip(counterparty_list, [0]*
        len(counterparty_list)))
    self_pushtx_count[0] = 0
    orders = zip(counterparty_list, [[]]*len(counterparty_list))
    input_utxos = {'utxo-hex-here': {'value': 0, 'address': '1addr'}}

    cjtx = CoinJoinTX(DummyMessageChannel(), None, None, 0, orders, input_utxos
        , '1cjaddr', '1changeaddr', 0, None, None, dummy_commitment_creator)
    cjtx.latest_tx = btc.deserialize(sample_tx_hex)
    return cjtx

def test_broadcast_self(setup_tx_notify):
    cjtx = create_testing_cjtx(['counterparty'])
    jm_single().config.set('POLICY', 'tx_broadcast', 'self')
    cjtx.push()
    assert self_pushtx_count[0] == 1
    assert sum(msgchan_pushtx_count[0].values()) == 0
    return True

def test_broadcast_random_peer(setup_tx_notify):
    cjtx = create_testing_cjtx(['one', 'two', 'three', 'four'])
    jm_single().config.set('POLICY', 'tx_broadcast', 'random-peer')
    N = 1000
    for i in xrange(N):
        cjtx.push()
    assert self_pushtx_count[0] > 1
    assert all(a > 1 for a in msgchan_pushtx_count[0].values())
    return True

def test_broadcast_not_self(setup_tx_notify):
    cjtx = create_testing_cjtx(['one', 'two', 'three', 'four'])
    jm_single().config.set('POLICY', 'tx_broadcast', 'not-self')
    N = 1000
    for i in xrange(N):
        cjtx.push()
    assert self_pushtx_count[0] == 0
    assert all(a > 1 for a in msgchan_pushtx_count[0].values())
    return True

def test_broadcast_random_maker(setup_tx_notify):
    cjtx = create_testing_cjtx(['counterparty'])
    jm_single().config.set('POLICY', 'tx_broadcast', 'random-maker')
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    cjtx.db = con.cursor()
    cjtx.db.execute("CREATE TABLE orderbook(counterparty TEXT, "
                    "oid INTEGER, ordertype TEXT, minsize INTEGER, "
                    "maxsize INTEGER, txfee INTEGER, cjfee TEXT);")
    makers = ['one', 'two', 'three', 'four']
    for m in makers:
        cjtx.db.execute(
            'INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);',
            (m, 0, 'absoffer', 0, 2100000000000001, 1000, 1000))
    msgchan_pushtx_count[0] = dict(zip(makers, [0]*len(makers)))
    N = 1000
    for i in xrange(N):
        cjtx.push()
    assert self_pushtx_count[0] == 0
    assert all(a > 1 for a in msgchan_pushtx_count[0].values())
    return True

@pytest.fixture(scope="module")
def setup_tx_notify():
    load_program_config()
    jm_single().bc_interface = DummyBlockchainInterface()
    jm_single().maker_timeout_sec = 1
