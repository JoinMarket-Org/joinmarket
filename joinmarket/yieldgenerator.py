#! /usr/bin/env python
from __future__ import absolute_import, print_function

import datetime
import os
import time
import abc
from optparse import OptionParser

from joinmarket import Maker, IRCMessageChannel, MessageChannelCollection
from joinmarket import BlockrInterface
from joinmarket import jm_single, get_network, load_program_config
from joinmarket import get_log, calc_cj_fee, debug_dump_object
from joinmarket import Wallet
from joinmarket import get_irc_mchannels

log = get_log()

# is a maker for the purposes of generating a yield from held
# bitcoins
class YieldGenerator(Maker):
    __metaclass__ = abc.ABCMeta
    statement_file = os.path.join('logs', 'yigen-statement.csv')

    def __init__(self, msgchan, wallet):
        Maker.__init__(self, msgchan, wallet)
        self.msgchan.register_channel_callbacks(self.on_welcome,
                                                self.on_set_topic, None, None,
                                                self.on_nick_leave, None)
        self.tx_unconfirm_timestamp = {}

    def log_statement(self, data):
        if get_network() == 'testnet':
            return

        data = [str(d) for d in data]
        self.income_statement = open(self.statement_file, 'a')
        self.income_statement.write(','.join(data) + '\n')
        self.income_statement.close()

    def on_welcome(self):
        Maker.on_welcome(self)
        if not os.path.isfile(self.statement_file):
            self.log_statement(
                ['timestamp', 'cj amount/satoshi', 'my input count',
                 'my input value/satoshi', 'cjfee/satoshi', 'earned/satoshi',
                 'confirm time/min', 'notes'])

        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.log_statement([timestamp, '', '', '', '', '', '', 'Connected'])

    @abc.abstractmethod
    def create_my_orders(self):
        """Must generate a set of orders to be displayed
        according to the contents of the wallet + some algo.
        (Note: should be called "create_my_offers")
        """

    @abc.abstractmethod
    def oid_to_order(self, cjorder, oid, amount):
        """Must convert an order with an offer/order id
        into a set of utxos to fill the order.
        Also provides the output addresses for the Taker.
        """

    @abc.abstractmethod
    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        """Performs action on receipt of transaction into the
        mempool in the blockchain instance (e.g. announcing orders)
        """

    @abc.abstractmethod
    def on_tx_confirmed(self, cjorder, confirmations, txid):
        """Performs actions on receipt of 1st confirmation of
        a transaction into a block (e.g. announce orders)
        """


def ygmain(ygclass, txfee=1000, cjfee_a=200, cjfee_r=0.002, ordertype='reloffer',
           nickserv_password='', minsize=100000, mix_levels=5):
    import sys

    parser = OptionParser(usage='usage: %prog [options] [wallet file]')
    parser.add_option('-o', '--ordertype', action='store', type='string',
                      dest='ordertype', default=ordertype,
                      help='type of order; can be either reloffer or absoffer')
    parser.add_option('-t', '--txfee', action='store', type='int',
                      dest='txfee', default=txfee,
                      help='minimum miner fee in satoshis')
    parser.add_option('-c', '--cjfee', action='store', type='string',
                      dest='cjfee', default='',
                      help='requested coinjoin fee in satoshis or proportion')
    parser.add_option('-p', '--password', action='store', type='string',
                      dest='password', default=nickserv_password,
                      help='irc nickserv password')
    parser.add_option('-s', '--minsize', action='store', type='int',
                      dest='minsize', default=minsize,
                      help='minimum coinjoin size in satoshis')
    parser.add_option('-m', '--mixlevels', action='store', type='int',
                      dest='mixlevels', default=mix_levels,
                      help='number of mixdepths to use')
    (options, args) = parser.parse_args()
    if len(args) < 1:
        parser.error('Needs a wallet')
        sys.exit(0)
    seed = args[0]
    ordertype = options.ordertype
    txfee = options.txfee
    if ordertype == 'reloffer':
        if options.cjfee != '':
            cjfee_r = options.cjfee
        # minimum size is such that you always net profit at least 20%
        #of the miner fee
        minsize = max(int(1.2 * txfee / float(cjfee_r)), options.minsize)
    elif ordertype == 'absoffer':
        if options.cjfee != '':
            cjfee_a = int(options.cjfee)
        minsize = options.minsize
    else:
        parser.error('You specified an incorrect order type which ' +\
                     'can be either reloffer or absoffer')
        sys.exit(0)
    nickserv_password = options.password
    mix_levels = options.mixlevels

    load_program_config()
    if isinstance(jm_single().bc_interface, BlockrInterface):
        c = ('\nYou are running a yield generator by polling the blockr.io '
             'website. This is quite bad for privacy. That site is owned by '
             'coinbase.com Also your bot will run faster and more efficently, '
             'you can be immediately notified of new bitcoin network '
             'information so your money will be working for you as hard as '
             'possibleLearn how to setup JoinMarket with Bitcoin Core: '
             'https://github.com/chris-belcher/joinmarket/wiki/Running'
             '-JoinMarket-with-Bitcoin-Core-full-node')
        print(c)
        ret = raw_input('\nContinue? (y/n):')
        if ret[0] != 'y':
            return

    wallet = Wallet(seed, max_mix_depth=mix_levels)
    jm_single().bc_interface.sync_wallet(wallet)

    log.debug('starting yield generator')
    mcs = [IRCMessageChannel(c, realname='btcint=' + jm_single().config.get(
                                 "BLOCKCHAIN", "blockchain_source"),
                        password=nickserv_password) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    maker = ygclass(mcc, wallet, [options.txfee, cjfee_a, cjfee_r,
                                  options.ordertype, options.minsize, mix_levels])
    try:
        log.debug('connecting to message channels')
        mcc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
        debug_dump_object(maker)
        debug_dump_object(mcc)
        import traceback
        log.debug(traceback.format_exc())

