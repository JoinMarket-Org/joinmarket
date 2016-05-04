#! /usr/bin/env python
from __future__ import absolute_import

import random
import sys
import threading
from optparse import OptionParser

# data_dir = os.path.dirname(os.path.realpath(__file__))
# sys.path.insert(0, os.path.join(data_dir, 'joinmarket'))
import time

from joinmarket import Taker, load_program_config, IRCMessageChannel
from joinmarket import validate_address, jm_single
from joinmarket import random_nick
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, debug_dump_object
from joinmarket import Wallet, BitcoinCoreWallet
from joinmarket.wallet import estimate_tx_fee

log = get_log()


def check_high_fee(total_fee_pc):
    WARNING_THRESHOLD = 0.02  # 2%
    if total_fee_pc > WARNING_THRESHOLD:
        print('\n'.join(['=' * 60] * 3))
        print('WARNING   ' * 6)
        print('\n'.join(['=' * 60] * 1))
        print('OFFERED COINJOIN FEE IS UNUSUALLY HIGH. DOUBLE/TRIPLE CHECK.')
        print('\n'.join(['=' * 60] * 1))
        print('WARNING   ' * 6)
        print('\n'.join(['=' * 60] * 3))


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
        if counterparty_count < self.taker.makercount:
            print('not enough counterparties to fill order, ending')
            self.taker.msgchan.shutdown()
            return

        utxos = None
        orders = None
        cjamount = 0
        change_addr = None
        choose_orders_recover = None
        if self.taker.amount == 0:
            utxos = self.taker.wallet.get_utxos_by_mixdepth()[
                self.taker.mixdepth]
            #do our best to estimate the fee based on the number of
            #our own utxos; this estimate may be significantly higher
            #than the default set in option.txfee * makercount, where
            #we have a large number of utxos to spend. If it is smaller,
            #we'll be conservative and retain the original estimate.
            est_ins = len(utxos)+3*self.taker.makercount
            log.debug("Estimated ins: "+str(est_ins))
            est_outs = 2*self.taker.makercount + 1
            log.debug("Estimated outs: "+str(est_outs))
            estimated_fee = estimate_tx_fee(est_ins, est_outs)
            log.debug("We have a fee estimate: "+str(estimated_fee))
            log.debug("And a requested fee of: "+str(
                self.taker.txfee * self.taker.makercount))
            if estimated_fee > self.taker.makercount * self.taker.txfee:
                #both values are integers; we can ignore small rounding errors
                self.taker.txfee = estimated_fee / self.taker.makercount
            total_value = sum([va['value'] for va in utxos.values()])
            orders, cjamount, total_cj_fee = choose_sweep_orders(
                self.taker.db, total_value, self.taker.txfee,
                self.taker.makercount, self.taker.chooseOrdersFunc,
                self.ignored_makers)
            if not orders:
                raise Exception("Could not find orders to complete transaction.")
            if not self.taker.answeryes:
                log.debug('total cj fee = ' + str(total_cj_fee))
                total_fee_pc = 1.0 * total_cj_fee / cjamount
                log.debug('total coinjoin fee = ' + str(float('%.3g' % (
                    100.0 * total_fee_pc))) + '%')
                check_high_fee(total_fee_pc)
                if raw_input('send with these orders? (y/n):')[0] != 'y':
                    self.taker.msgchan.shutdown()
                    return
        else:
            orders, total_cj_fee = self.sendpayment_choose_orders(
                self.taker.amount, self.taker.makercount)
            if not orders:
                log.debug(
                    'ERROR not enough liquidity in the orderbook, exiting')
                return
            total_amount = self.taker.amount + total_cj_fee + \
	        self.taker.txfee*self.taker.makercount
            print 'total estimated amount spent = ' + str(total_amount)
            #adjust the required amount upwards to anticipate a tripling of 
            #transaction fee after re-estimation; this is sufficiently conservative
            #to make failures unlikely while keeping the occurence of failure to
            #find sufficient utxos extremely rare. Indeed, a tripling of 'normal'
            #txfee indicates undesirable behaviour on maker side anyway.
            utxos = self.taker.wallet.select_utxos(self.taker.mixdepth, 
                total_amount+2*self.taker.txfee*self.taker.makercount)
            cjamount = self.taker.amount
            change_addr = self.taker.wallet.get_internal_addr(self.taker.mixdepth)
            choose_orders_recover = self.sendpayment_choose_orders

        self.taker.start_cj(self.taker.wallet, cjamount, orders, utxos,
			self.taker.destaddr, change_addr, 
                         self.taker.makercount*self.taker.txfee,
                            self.finishcallback, choose_orders_recover)

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            pushed = coinjointx.self_sign_and_push()
            if pushed:
                log.debug('created fully signed tx, ending')
            else:
                #Error should be in log, will not retry.
                log.debug('failed to push tx, ending.')
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
        if nonrespondants is None:
            nonrespondants = []
        if active_nicks is None:
            active_nicks = []
        self.ignored_makers += nonrespondants
        orders, total_cj_fee = choose_orders(
            self.taker.db, cj_amount, makercount, self.taker.chooseOrdersFunc,
            self.ignored_makers + active_nicks)
        if not orders:
            return None, 0
        print('chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
            total_cj_fee))
        if not self.taker.answeryes:
            if len(self.ignored_makers) > 0:
                noun = 'total'
            else:
                noun = 'additional'
            total_fee_pc = 1.0 * total_cj_fee / cj_amount
            log.debug(noun + ' coinjoin fee = ' + str(float('%.3g' % (
                100.0 * total_fee_pc))) + '%')
            check_high_fee(total_fee_pc)
            if raw_input('send with these orders? (y/n):')[0] != 'y':
                log.debug('ending')
                self.taker.msgchan.shutdown()
                return None, -1
        return orders, total_cj_fee

    def run(self):
        print('waiting for all orders to certainly arrive')
        time.sleep(self.taker.waittime)
        self.create_tx()


class SendPayment(Taker):

    def __init__(self, msgchan, wallet, destaddr, amount, makercount, txfee,
                 waittime, mixdepth, answeryes, chooseOrdersFunc, isolated=False):
        Taker.__init__(self, msgchan)
        self.wallet = wallet
        self.destaddr = destaddr
        self.amount = amount
        self.makercount = makercount
        self.txfee = txfee
        self.waittime = waittime
        self.mixdepth = mixdepth
        self.answeryes = answeryes
        self.chooseOrdersFunc = chooseOrdersFunc
        #extra variables for GUI-style
        self.isolated = isolated
        self.txid = None

    def on_welcome(self):
        Taker.on_welcome(self)
        if not self.isolated:
            PaymentThread(self).start()


def main():
    parser = OptionParser(
        usage=
        'usage: %prog [options] [wallet file / fromaccount] [amount] [destaddr]',
        description='Sends a single payment from a given mixing depth of your '
        +
        'wallet to an given address using coinjoin and then switches off. Also sends from bitcoinqt. '
        +
        'Setting amount to zero will do a sweep, where the entire mix depth is emptied')
    parser.add_option('-f',
        '--txfee',
        action='store',
        type='int',
        dest='txfee',
        default=5000,
        help='number of satoshis per participant to use as the initial estimate '+
        'for the total transaction fee, default=5000, note that this is adjusted '+
        'based on the estimated fee calculated after tx construction, based on '+
        'policy set in joinmarket.cfg.')
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
                      help='how many makers to coinjoin with, default random from 2 to 4',
                      default=random.randint(2, 4))
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
    parser.add_option('-m',
                      '--mixdepth',
                      action='store',
                      type='int',
                      dest='mixdepth',
                      help='mixing depth to spend from, default=0',
                      default=0)
    parser.add_option('-g',
                      '--gap-limit',
                      type="int",
                      action='store',
                      dest='gaplimit',
                      help='gap limit for wallet, default=6',
                      default=6)
    parser.add_option('--yes',
                      action='store_true',
                      dest='answeryes',
                      default=False,
                      help='answer yes to everything')
    parser.add_option(
        '--rpcwallet',
        action='store_true',
        dest='userpcwallet',
        default=False,
        help=('Use the Bitcoin Core wallet through json rpc, instead '
              'of the internal joinmarket wallet. Requires '
              'blockchain_source=json-rpc'))
    (options, args) = parser.parse_args()

    if len(args) < 3:
        parser.error('Needs a wallet, amount and destination address')
        sys.exit(0)
    wallet_name = args[0]
    amount = int(args[1])
    destaddr = args[2]

    load_program_config()
    addr_valid, errormsg = validate_address(destaddr)
    if not addr_valid:
        print('ERROR: Address invalid. ' + errormsg)
        return

    chooseOrdersFunc = None
    if options.pickorders:
        chooseOrdersFunc = pick_order
        if amount == 0:
            print 'WARNING: You may have to pick offers multiple times'
            print 'WARNING: due to manual offer picking while sweeping'
    elif options.choosecheapest:
        chooseOrdersFunc = cheapest_order_choose
    else:  # choose randomly (weighted)
        chooseOrdersFunc = weighted_order_choose

    jm_single().nickname = random_nick()

    log.debug('starting sendpayment')

    if not options.userpcwallet:
        wallet = Wallet(wallet_name, options.mixdepth + 1, options.gaplimit)
    else:
        wallet = BitcoinCoreWallet(fromaccount=wallet_name)
    jm_single().bc_interface.sync_wallet(wallet)

    irc = IRCMessageChannel(jm_single().nickname)
    taker = SendPayment(irc, wallet, destaddr, amount, options.makercount,
                        options.txfee, options.waittime, options.mixdepth,
                        options.answeryes, chooseOrdersFunc)
    try:
        log.debug('starting irc')
        irc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'wallet_name', 'seed'])
        debug_dump_object(taker)
        import traceback
        log.debug(traceback.format_exc())


#PaymentThread object modified (not a thread, refactored a bit)
#The reason is that Qt won't work with python threads, and we need
#separate threads for separate steps (returning chosen orders to gui),
#so the threading is in the gui code.
class PT(object):

    def __init__(self, taker):
        self.taker = taker
        self.ignored_makers = []

    def create_tx(self):
        time.sleep(self.taker.waittime)
        crow = self.taker.db.execute(
            'SELECT COUNT(DISTINCT counterparty) FROM orderbook;').fetchone()
        counterparty_count = crow['COUNT(DISTINCT counterparty)']
        counterparty_count -= len(self.ignored_makers)
        if counterparty_count < self.taker.makercount:
            log.debug('not enough counterparties to fill order, ending')
            #NB: don't shutdown msgchan here, that is done by the caller
            #after setting GUI state to reflect the reason for shutdown.
            return None, None, None, None

        utxos = None
        orders = None
        cjamount = None
        change_addr = None
        choose_orders_recover = None
        if self.taker.amount == 0:
            utxos = self.taker.wallet.get_utxos_by_mixdepth()[
                self.taker.mixdepth]
            #do our best to estimate the fee based on the number of
            #our own utxos; this estimate may be significantly higher
            #than the default set in option.txfee * makercount, where
            #we have a large number of utxos to spend. If it is smaller,
            #we'll be conservative and retain the original estimate.
            est_ins = len(utxos)+3*self.taker.makercount
            log.debug("Estimated ins: "+str(est_ins))
            est_outs = 2*self.taker.makercount + 1
            log.debug("Estimated outs: "+str(est_outs))
            estimated_fee = estimate_tx_fee(est_ins, est_outs)
            log.debug("We have a fee estimate: "+str(estimated_fee))
            log.debug("And a requested fee of: "+str(
                self.taker.txfee * self.taker.makercount))
            if estimated_fee > self.taker.makercount * self.taker.txfee:
                #both values are integers; we can ignore small rounding errors
                self.taker.txfee = estimated_fee / self.taker.makercount
            total_value = sum([va['value'] for va in utxos.values()])
            orders, cjamount = choose_sweep_orders(
                self.taker.db, total_value, self.taker.txfee,
                self.taker.makercount, self.taker.chooseOrdersFunc,
                self.ignored_makers)
            if not orders:
                raise Exception("Could not find orders to complete transaction.")
            total_cj_fee = total_value - cjamount - \
                self.taker.txfee*self.taker.makercount

        else:
            orders, total_cj_fee = self.sendpayment_choose_orders(
                self.taker.amount, self.taker.makercount)
            cjamount = self.taker.amount
            if not orders:
                log.debug(
                    'ERROR not enough liquidity in the orderbook, exiting')
                return None, None, None, None
        return orders, total_cj_fee, cjamount, utxos

    def do_tx(self, total_cj_fee, orders, cjamount, utxos,
              donate=False, donate_trigger=1000000, donation_address=None):
        #for non-sweep, we now have to set amount, change address and utxo selection
        if self.taker.amount > 0:
            total_amount = self.taker.amount + total_cj_fee + \
                self.taker.txfee*self.taker.makercount
            log.debug('total estimated amount spent = ' + str(total_amount))
            #adjust the required amount upwards to anticipate a tripling of
            #transaction fee after re-estimation; this is sufficiently conservative
            #to make failures unlikely while keeping the occurence of failure to
            #find sufficient utxos extremely rare. Indeed, a tripling of 'normal'
            #txfee indicates undesirable behaviour on maker side anyway.
            try:
                utxos = self.taker.wallet.select_utxos(self.taker.mixdepth,
                        total_amount+2*self.taker.txfee*self.taker.makercount)
            except Exception as e:
                log.debug("Failed to select coins: "+repr(e))
                return
            my_total_in = sum([va['value'] for u, va in utxos.iteritems()])
            log.debug("using coinjoin amount: "+str(cjamount))
            change_amount = my_total_in-cjamount
            log.debug("using change amount: "+str(change_amount))
            if donate and change_amount < donate_trigger*1e8:
                #sanity check
                res = validate_address(donation_address)
                if not res[0]:
                    log.debug("Donation address invalid! Error: "+res[1])
                    return
                change_addr = donation_address
            else:
                change_addr = self.taker.wallet.get_internal_addr(self.taker.mixdepth)
            log.debug("using change address: "+change_addr)

        #For sweeps, we reset the change address to None, and use the provided
        #amount and utxos (calculated in the first step)
        else:
            change_addr = None

        choose_orders_recover = self.sendpayment_choose_orders
        log.debug("About to start coinjoin")
        try:
            self.taker.start_cj(self.taker.wallet, cjamount, orders, utxos,
                            self.taker.destaddr, change_addr,
                             self.taker.makercount*self.taker.txfee,
                                self.finishcallback, choose_orders_recover)
        except Exception as e:
            log.debug("failed to start coinjoin: "+repr(e))

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            pushed = coinjointx.self_sign_and_push()
            if pushed:
                log.debug('created fully signed tx, ending')
                self.taker.txid = coinjointx.txid
            else:
                #Error should be in log, will not retry.
                log.debug('failed to push tx, ending.')
            self.taker.msgchan.shutdown()
            return
        self.ignored_makers += coinjointx.nonrespondants
        log.debug('tx negotation failed, ignored_makers=' + str(
            self.ignored_makers))
        #triggers endpoint for GUI
        self.taker.msgchan.shutdown()

    def sendpayment_choose_orders(self,
                                  cj_amount,
                                  makercount,
                                  nonrespondants=None,
                                  active_nicks=None):
        if nonrespondants is None:
            nonrespondants = []
        if active_nicks is None:
            active_nicks = []
        self.ignored_makers += nonrespondants
        orders, total_cj_fee = choose_orders(
            self.taker.db, cj_amount, makercount, self.taker.chooseOrdersFunc,
            self.ignored_makers + active_nicks)
        if not orders:
            return None, 0
        log.debug('chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
            total_cj_fee))
        return orders, total_cj_fee

if __name__ == "__main__":
    main()
    print('done')
