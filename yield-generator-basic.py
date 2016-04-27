#! /usr/bin/env python
from __future__ import absolute_import, print_function

import datetime
import os
import time
from optparse import OptionParser

from joinmarket import Maker, IRCMessageChannel, MatrixMessageChannel
from joinmarket import BlockrInterface
from joinmarket import jm_single, get_network, load_program_config
from joinmarket import random_nick
from joinmarket import get_log, calc_cj_fee, debug_dump_object
from joinmarket import Wallet

# data_dir = os.path.dirname(os.path.realpath(__file__))
# sys.path.insert(0, os.path.join(data_dir, 'joinmarket'))

# import blockchaininterface

txfee = 1000
cjfee_a = 200
cjfee_r = '0.002'
ordertype = 'relorder'
jm_single().nickname = ''
nickserv_password = ''
minsize = 100000
mix_levels = 5


log = get_log()

# is a maker for the purposes of generating a yield from held
# bitcoins without ruining privacy for the taker, the taker could easily check
# the history of the utxos this bot sends, so theres not much incentive
# to ruin the privacy for barely any more yield
# sell-side algorithm:
# add up the value of each utxo for each mixing depth,
# announce a relative-fee order of the highest balance
# spent from utxos that try to make the highest balance even higher
# so try to keep coins concentrated in one mixing depth
class YieldGenerator(Maker):
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

    def create_my_orders(self):
        mix_balance = self.wallet.get_balance_by_mixdepth()
        if len([b for m, b in mix_balance.iteritems() if b > 0]) == 0:
            log.debug('do not have any coins left')
            return []

        # print mix_balance
        max_mix = max(mix_balance, key=mix_balance.get)
        f = '0'
        if ordertype == 'relorder':
            f = cjfee_r
        elif ordertype == 'absorder':
            f = str(txfee + cjfee_a)
        order = {'oid': 0,
                 'ordertype': ordertype,
                 'minsize': minsize,
                 'maxsize': mix_balance[max_mix] - jm_single().DUST_THRESHOLD,
                 'txfee': txfee,
                 'cjfee': f}

        # sanity check
        assert order['minsize'] >= 0
        assert order['maxsize'] > 0
        assert order['minsize'] <= order['maxsize']

        return [order]

    def oid_to_order(self, cjorder, oid, amount):
        total_amount = amount + cjorder.txfee
        mix_balance = self.wallet.get_balance_by_mixdepth()
        max_mix = max(mix_balance, key=mix_balance.get)

        filtered_mix_balance = [m
                                for m in mix_balance.iteritems()
                                if m[1] >= total_amount]
        log.debug('mix depths that have enough = ' + str(filtered_mix_balance))
        filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[0])
        mixdepth = filtered_mix_balance[0][0]
        log.debug('filling offer, mixdepth=' + str(mixdepth))

        # mixdepth is the chosen depth we'll be spending from
        cj_addr = self.wallet.get_internal_addr((mixdepth + 1) %
                                                self.wallet.max_mix_depth)
        change_addr = self.wallet.get_internal_addr(mixdepth)

        utxos = self.wallet.select_utxos(mixdepth, total_amount)
        my_total_in = sum([va['value'] for va in utxos.values()])
        real_cjfee = calc_cj_fee(cjorder.ordertype, cjorder.cjfee, amount)
        change_value = my_total_in - amount - cjorder.txfee + real_cjfee
        if change_value <= jm_single().DUST_THRESHOLD:
            log.debug(('change value={} below dust threshold, '
                       'finding new utxos').format(change_value))
            try:
                utxos = self.wallet.select_utxos(
                    mixdepth, total_amount + jm_single().DUST_THRESHOLD)
            except Exception:
                log.debug('dont have the required UTXOs to make a '
                          'output above the dust threshold, quitting')
                return None, None, None

        return utxos, cj_addr, change_addr

    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
        # if the balance of the highest-balance mixing depth change then
        # reannounce it
        oldorder = self.orderlist[0] if len(self.orderlist) > 0 else None
        neworders = self.create_my_orders()
        if len(neworders) == 0:
            return [0], []  # cancel old order
        # oldorder may not exist when this is called from on_tx_confirmed
        if oldorder:
            if oldorder['maxsize'] == neworders[0]['maxsize']:
                return [], []  # change nothing
        # announce new order, replacing the old order
        return [], [neworders[0]]

    def on_tx_confirmed(self, cjorder, confirmations, txid):
        if cjorder.cj_addr in self.tx_unconfirm_timestamp:
            confirm_time = int(time.time()) - self.tx_unconfirm_timestamp[
                cjorder.cj_addr]
        else:
            confirm_time = 0
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.log_statement([timestamp, cjorder.cj_amount, len(
            cjorder.utxos), sum([av['value'] for av in cjorder.utxos.values(
            )]), cjorder.real_cjfee, cjorder.real_cjfee - cjorder.txfee, round(
                confirm_time / 60.0, 2), ''])
        return self.on_tx_unconfirmed(cjorder, txid, None)


def main():
    global txfee, cjfee_a, cjfee_r, ordertype, nickserv_password, minsize, mix_levels
    import sys

    parser = OptionParser(usage='usage: %prog [options] [wallet file]')
    parser.add_option('-o', '--ordertype', action='store', type='string', dest='ordertype', default=ordertype,
                      help='type of order; can be either relorder or absorder')
    parser.add_option('-t', '--txfee', action='store', type='int', dest='txfee', default=txfee,
                      help='minimum miner fee in satoshis')
    parser.add_option('-c', '--cjfee', action='store', type='string', dest='cjfee', default='',
                      help='requested coinjoin fee in satoshis or proportion')
    parser.add_option('-n', '--nickname', action='store', type='string', dest='nickname', default=jm_single().nickname,
                      help='irc nickname')
    parser.add_option('-p', '--password', action='store', type='string', dest='password', default=nickserv_password,
                      help='irc nickserv password')
    parser.add_option('-s', '--minsize', action='store', type='int', dest='minsize', default=minsize,
                      help='minimum coinjoin size in satoshis')
    parser.add_option('-m', '--mixlevels', action='store', type='int', dest='mixlevels', default=mix_levels,
                      help='number of mixdepths to use')
    (options, args) = parser.parse_args()
    if len(args) < 1:
        parser.error('Needs a wallet')
        sys.exit(0)
    seed = args[0]
    ordertype = options.ordertype
    txfee = options.txfee
    if ordertype == 'relorder':
        if options.cjfee != '':
            cjfee_r = options.cjfee
        # minimum size is such that you always net profit at least 20% of the miner fee
        minsize = max(int(1.2 * txfee / float(cjfee_r)), options.minsize)
    elif ordertype == 'absorder':
        if options.cjfee != '':
            cjfee_a = int(options.cjfee)
        minsize = options.minsize
    else:
        parser.error('You specified an incorrect order type which can be either relorder or absorder')
        sys.exit(0)
    if jm_single().nickname == options.nickname:
        jm_single().nickname = random_nick()
    else:
        jm_single().nickname = options.nickname
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

    # nickname is set way above
    # nickname

    log.debug('starting yield generator')
    #TODO smarter config handling (e.g. what if both?)
    if jm_single().config.has_option("MESSAGING", "matrix_host"):
        mcClass = MatrixMessageChannel
    else:
        mcClass = IRCMessageChannel
    mchannel = mcClass(jm_single().nickname,
                            realname='btcint=' + jm_single().config.get(
                                "BLOCKCHAIN", "blockchain_source"),
                            password=nickserv_password)
    maker = YieldGenerator(mchannel, wallet)
    try:
        log.debug('connecting to message channel')
        mchannel.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
        debug_dump_object(maker)
        debug_dump_object(mchannel)
        import traceback
        log.debug(traceback.format_exc())


if __name__ == "__main__":
    main()
    print('done')
