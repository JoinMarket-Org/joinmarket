#! /usr/bin/env python
from __future__ import absolute_import

import sys
import threading
import time
from optparse import OptionParser

# data_dir = os.path.dirname(os.path.realpath(__file__))
# sys.path.insert(0, os.path.join(data_dir, 'joinmarket'))

# from common import *
# import common
from joinmarket import taker as takermodule
from joinmarket import load_program_config, validate_address, \
    jm_single, get_p2pk_vbyte, random_nick
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose
from joinmarket import AbstractWallet, IRCMessageChannel, debug_dump_object, \
     MessageChannelCollection, get_irc_mchannels

import bitcoin as btc
import sendpayment

log = get_log()


# thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class PaymentThread(threading.Thread):

    def __init__(self, taker):
        threading.Thread.__init__(self, name='PaymentThread')
        self.daemon = True
        self.taker = taker
        self.ignored_makers = []

    def create_tx(self):
        crow = self.taker.db.execute(
            'SELECT COUNT(DISTINCT counterparty) FROM orderbook;').fetchone()

        counterparty_count = crow['COUNT(DISTINCT counterparty)']
        counterparty_count -= len(self.ignored_makers)
        if counterparty_count < self.taker.options.makercount:
            print 'not enough counterparties to fill order, ending'
            self.taker.msgchan.shutdown()
            return

        utxos = self.taker.utxo_data
        change_addr = None
        choose_orders_recover = None
        if self.taker.cjamount == 0:
            total_value = sum([va['value'] for va in utxos.values()])
            orders, cjamount, total_cj_fee = choose_sweep_orders(
                self.taker.db, total_value, self.taker.options.txfee,
                self.taker.options.makercount, self.taker.chooseOrdersFunc,
                self.ignored_makers)
            if not self.taker.options.answeryes:
                log.debug('total cj fee = ' + str(total_cj_fee))
                total_fee_pc = 1.0 * total_cj_fee / cjamount
                log.debug('total coinjoin fee = ' + str(float('%.3g' % (
                    100.0 * total_fee_pc))) + '%')
                sendpayment.check_high_fee(total_fee_pc)
                if raw_input('send with these orders? (y/n):')[0] != 'y':
                    # noinspection PyTypeChecker
                    self.finishcallback(None)
                    return
        else:
            orders, total_cj_fee = self.sendpayment_choose_orders(
                self.taker.cjamount, self.taker.options.makercount)
            if not orders:
                log.debug(
                    'ERROR not enough liquidity in the orderbook, exiting')
                return
            total_amount = self.taker.cjamount + total_cj_fee + \
                           self.taker.options.txfee
            print 'total amount spent = ' + str(total_amount)
            cjamount = self.taker.cjamount
            change_addr = self.taker.changeaddr
            choose_orders_recover = self.sendpayment_choose_orders

        self.taker.start_cj(self.taker.wallet, cjamount, orders, utxos,
                            self.taker.destaddr, change_addr,
                            self.taker.options.txfee, self.finishcallback,
                            choose_orders_recover)

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            tx = btc.serialize(coinjointx.latest_tx)
            print 'unsigned tx = \n\n' + tx + '\n'
            log.debug('created unsigned tx, ending')
            self.taker.msgchan.shutdown()
            return
        self.ignored_makers += coinjointx.nonrespondants
        log.debug('recreating the tx, ignored_makers=' + str(
            self.ignored_makers))
        self.create_tx()

    def sendpayment_choose_orders(self,
                                  cj_amount,
                                  makercount,
                                  nonrespondants=None,
                                  active_nicks=None):
        if active_nicks is None:
            active_nicks = []
        if nonrespondants is None:
            nonrespondants = []
        self.ignored_makers += nonrespondants
        orders, total_cj_fee = choose_orders(
            self.taker.db, cj_amount, makercount, self.taker.chooseOrdersFunc,
            self.ignored_makers + active_nicks)
        if not orders:
            return None, 0
        print 'chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
            total_cj_fee)
        if not self.taker.options.answeryes:
            if len(self.ignored_makers) > 0:
                noun = 'total'
            else:
                noun = 'additional'
            total_fee_pc = 1.0 * total_cj_fee / cj_amount
            log.debug(noun + ' coinjoin fee = ' + str(float('%.3g' % (
                100.0 * total_fee_pc))) + '%')
            sendpayment.check_high_fee(total_fee_pc)
            if raw_input('send with these orders? (y/n):')[0] != 'y':
                log.debug('ending')
                self.taker.msgchan.shutdown()
                return None, -1
        return orders, total_cj_fee

    def run(self):
        print 'waiting for all orders to certainly arrive'
        time.sleep(self.taker.options.waittime)
        self.create_tx()


class CreateUnsignedTx(takermodule.Taker):

    def __init__(self, msgchan, wallet, cjamount, destaddr,
                 changeaddr, utxo_data, options, chooseOrdersFunc):
        takermodule.Taker.__init__(self, msgchan)
        self.wallet = wallet
        self.cjamount = cjamount
        self.destaddr = destaddr
        self.changeaddr = changeaddr
        self.utxo_data = utxo_data
        self.options = options
        self.chooseOrdersFunc = chooseOrdersFunc

    def on_welcome(self):
        takermodule.Taker.on_welcome(self)
        PaymentThread(self).start()


def main():
    parser = OptionParser(
        usage='usage: %prog [options] [cjamount] [cjaddr] [changeaddr] [utxos..]',
        description=('Creates an unsigned coinjoin transaction. Outputs '
                     'a partially signed transaction hex string. The user '
                     'must sign their inputs independently and broadcast '
                     'them. The JoinMarket protocol requires the taker to '
                     'have a single p2pk UTXO input to use to '
                     'authenticate the  encrypted messages. For this '
                     'reason you must pass auth utxo and the '
                     'corresponding private key'))

    # for cjamount=0 do a sweep, and ignore change address
    parser.add_option('-f',
                      '--txfee',
                      action='store',
                      type='int',
                      dest='txfee',
                      default=10000,
                      help='total miner fee in satoshis, default=10000')
    parser.add_option(
        '-w',
        '--wait-time',
        action='store',
        type='float',
        dest='waittime',
        help='wait time in seconds to allow orders to arrive, default=5',
        default=5)
    parser.add_option('-N',
                      '--makercount',
                      action='store',
                      type='int',
                      dest='makercount',
                      help='how many makers to coinjoin with, default=2',
                      default=2)
    parser.add_option(
        '-C',
        '--choose-cheapest',
        action='store_true',
        dest='choosecheapest',
        default=False,
        help='override weightened offers picking and choose cheapest')
    parser.add_option(
        '-P',
        '--pick-orders',
        action='store_true',
        dest='pickorders',
        default=False,
        help=
        'manually pick which orders to take. doesn\'t work while sweeping.')
    parser.add_option('--yes',
                      action='store_true',
                      dest='answeryes',
                      default=False,
                      help='answer yes to everything')
    # TODO implement parser.add_option('-n', '--no-network',
    # action='store_true', dest='nonetwork', default=False, help='dont query
    # the blockchain interface, instead user must supply value of UTXOs on '
    # + ' command line in the format txid:output/value-in-satoshi')
    (options, args) = parser.parse_args()

    if len(args) < 4:
        parser.error(
            'Needs an amount, destination address, change address and utxos ')
        sys.exit(0)
    cjamount = int(args[0])
    destaddr = args[1]
    changeaddr = args[2]
    cold_utxos = args[3:]

    load_program_config()
    addr_valid1, errormsg1 = validate_address(destaddr)
    errormsg2 = None
    # if amount = 0 dont bother checking changeaddr so user can write any junk
    if cjamount != 0:
        addr_valid2, errormsg2 = validate_address(changeaddr)
    else:
        addr_valid2 = True
    if not addr_valid1 or not addr_valid2:
        if not addr_valid1:
            print 'ERROR: Address invalid. ' + errormsg1
        else:
            print 'ERROR: Address invalid. ' + errormsg2
        return

    query_result = jm_single().bc_interface.query_utxo_set(cold_utxos)
    if None in query_result:
        print query_result
    utxo_data = {}
    for utxo, data in zip(cold_utxos, query_result):
        utxo_data[utxo] = {'address': data['address'], 'value': data['value']}
    print("Got this utxo data: " + str(utxo_data))
    if options.pickorders and cjamount != 0:  # cant use for sweeping
        chooseOrdersFunc = pick_order
    elif options.choosecheapest:
        chooseOrdersFunc = cheapest_order_choose
    else:  # choose randomly (weighted)
        chooseOrdersFunc = weighted_order_choose

    log.debug('starting sendpayment')

    wallet = AbstractWallet()
    wallet.unspent = None
    mcs = [IRCMessageChannel(c, jm_single().nickname) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    taker = CreateUnsignedTx(mcc, wallet, cjamount, destaddr,
                             changeaddr, utxo_data, options, chooseOrdersFunc)
    try:
        log.debug('starting message channels')
        mcc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'wallet_name', 'seed'])
        debug_dump_object(taker)
        import traceback
        log.debug(traceback.format_exc())


if __name__ == "__main__":
    main()
    print('done')
