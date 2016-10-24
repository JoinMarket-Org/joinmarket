from __future__ import absolute_import

import sys
import threading
import time
from datetime import timedelta
from optparse import OptionParser
# data_dir = os.path.dirname(os.path.realpath(__file__))
# sys.path.insert(0, os.path.join(data_dir, 'joinmarket'))
from joinmarket import Maker, Taker, load_program_config, IRCMessageChannel
from joinmarket import validate_address, jm_single
from joinmarket import get_log, choose_orders, weighted_order_choose, \
    debug_dump_object, sync_wallet
from joinmarket import Wallet

log = get_log()


class TakerThread(threading.Thread):
    def __init__(self, tmaker):
        threading.Thread.__init__(self, name='TakerThread')
        self.daemon = True
        self.tmaker = tmaker
        self.finished = False

    def finishcallback(self, coinjointx):
        self.tmaker.msgchan.shutdown()

    def run(self):
        # TODO this thread doesnt wake up for what could be hours
        # need a loop that periodically checks self.finished
        # TODO another issue is, what if the bot has run out of utxos and
        # needs to wait for some tx to confirm before it can trade
        # presumably it needs to wait here until the tx confirms
        time.sleep(self.tmaker.waittime)
        if self.finished:
            return
        print 'giving up waiting'
        # cancel the remaining order
        self.tmaker.modify_orders([0], [])
        orders, total_cj_fee = choose_orders(self.tmaker.db, self.tmaker.amount,
                                             self.tmaker.makercount,
                                             weighted_order_choose)
        print 'chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
                total_cj_fee)
        total_amount = self.tmaker.amount + total_cj_fee + self.tmaker.txfee
        print 'total amount spent = ' + str(total_amount)

        utxos = self.tmaker.wallet.select_utxos(self.tmaker.mixdepth,
                                                total_amount)
        self.tmaker.start_cj(
                self.tmaker.wallet, self.tmaker.amount, orders, utxos,
                self.tmaker.destaddr,
                self.tmaker.wallet.get_internal_addr(self.tmaker.mixdepth),
                self.tmaker.txfee, self.finishcallback)


class PatientSendPayment(Maker, Taker):
    def __init__(self, msgchan, wallet, destaddr, amount, makercount, txfee,
                 cjfee, waittime, mixdepth):
        self.destaddr = destaddr
        self.amount = amount
        self.makercount = makercount
        self.txfee = txfee
        self.cjfee = cjfee
        self.waittime = waittime
        self.mixdepth = mixdepth
        Maker.__init__(self, msgchan, wallet)
        Taker.__init__(self, msgchan)

    def get_crypto_box_from_nick(self, nick):
        if self.cjtx:
            return Taker.get_crypto_box_from_nick(self, nick)
        else:
            return Maker.get_crypto_box_from_nick(self, nick)

    def on_welcome(self):
        Maker.on_welcome(self)
        Taker.on_welcome(self)
        self.takerthread = TakerThread(self)
        self.takerthread.start()

    def create_my_orders(self):
        # choose an absolute fee order to discourage people from
        # mixing smaller amounts
        order = {'oid': 0,
                 'ordertype': 'absoffer',
                 'minsize': 0,
                 'maxsize': self.amount,
                 'txfee': self.txfee,
                 'cjfee': self.cjfee}
        return [order]

    def oid_to_order(self, cjorder, oid, amount):
        # TODO race condition (kinda)
        # if an order arrives and before it finishes another order arrives
        # its possible this bot will end up paying to the destaddr more than it
        # intended
        utxos = self.wallet.select_utxos(self.mixdepth, amount)
        return utxos, self.destaddr, self.wallet.get_internal_addr(self.mixdepth)

    def on_tx_unconfirmed(self, cjorder, balance, removed_utxos):
        self.amount -= cjorder.cj_amount
        if self.amount == 0:
            self.takerthread.finished = True
            print 'finished sending, exiting..'
            self.msgchan.shutdown()
            return [], []
        available_balance = self.wallet.get_balance_by_mixdepth()[self.mixdepth]
        if available_balance >= self.amount:
            order = {'oid': 0,
                     'ordertype': 'absoffer',
                     'minsize': 0,
                     'maxsize': self.amount,
                     'txfee': self.txfee,
                     'cjfee': self.cjfee}
            return [], [order]
        else:
            log.warn('not enough money left, have to wait until tx confirms')
            return [0], []

    def on_tx_confirmed(self, cjorder, confirmations, txid, balance):
        if len(self.orderlist) == 0:
            order = {'oid': 0,
                     'ordertype': 'absoffer',
                     'minsize': 0,
                     'maxsize': self.amount,
                     'txfee': self.txfee,
                     'cjfee': self.cjfee}
            return [], [order]
        else:
            return [], []


def main():
    parser = OptionParser(
            usage=
            'usage: %prog [options] [wallet file / fromaccount] [amount] [destaddr]',
            description='Sends a payment from your wallet to an given address' +
                        ' using coinjoin. First acts as a maker, announcing an order and ' +
                        'waiting for someone to fill it. After a set period of time, gives' +
                        ' up waiting and acts as a taker and coinjoins any remaining coins.' +
                        ' NOTE: In the current state of JoinMarket software, this script' +
                        ' only works if your JoinMarket wallet contains the private key of your' +
                        ' destination address. So you can only send to yourself and you need' +
                        ' to import the privkey')
    parser.add_option(
            '-f',
            '--txfee',
            action='store',
            type='int',
            dest='txfee',
            default=10000,
            help='miner fee contribution, in satoshis, default=10000')
    parser.add_option(
            '-N',
            '--makercount',
            action='store',
            type='int',
            dest='makercount',
            help=
            'how many makers to coinjoin with when taking liquidity, default=2',
            default=2)
    parser.add_option(
            '-w',
            '--wait-time',
            action='store',
            type='float',
            dest='waittime',
            help='wait time in hours as a maker before becoming a taker, default=8',
            default=8)
    parser.add_option(
            '-c',
            '--cjfee',
            action='store',
            type='int',
            dest='cjfee',
            help=
            'coinjoin fee asked for when being a maker, in satoshis per order filled, default=50000',
            default=50000)
    parser.add_option(
            '-m',
            '--mixdepth',
            action='store',
            type='int',
            dest='mixdepth',
            help='mixing depth to spend from, default=0',
            default=0)
    parser.add_option(
            '--rpcwallet',
            action='store_true',
            dest='userpcwallet',
            default=False,
            help=
            'Use the Bitcoin Core wallet through json rpc, instead of the internal joinmarket '
            + 'wallet. Requires blockchain_source=json-rpc')
    parser.add_option('--fast',
                      action='store_true',
                      dest='fastsync',
                      default=False,
                      help=('choose to do fast wallet sync, only for Core and '
                      'only for previously synced wallet'))
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
        print 'ERROR: Address invalid. ' + errormsg
        return

    waittime = timedelta(hours=options.waittime).total_seconds()
    print 'txfee=%d cjfee=%d waittime=%s makercount=%d' % (
        options.txfee, options.cjfee, str(timedelta(hours=options.waittime)),
        options.makercount)

    # todo: this section doesn't make a lot of sense
    if not options.userpcwallet:
        wallet = Wallet(wallet_name, options.mixdepth + 1)
    else:
        print 'not implemented yet'
        sys.exit(0)
    # wallet = BitcoinCoreWallet(fromaccount=wallet_name)
    sync_wallet(wallet, fast=options.fastsync)

    available_balance = wallet.get_balance_by_mixdepth()[options.mixdepth]
    if available_balance < amount:
        print 'not enough money at mixdepth=%d, exiting' % options.mixdepth
        return

    log.info('Running patient sender of a payment')
    mcs = [IRCMessageChannel(c) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    PatientSendPayment(mcc, wallet, destaddr, amount, options.makercount,
                             options.txfee, options.cjfee, waittime,
                             options.mixdepth)
    try:
        mcc.run()
    except:
        log.warn('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
        # todo: looks wrong.  dump on the class object?
        # debug_dump_object(taker)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
    print('done')
