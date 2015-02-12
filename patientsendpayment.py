from common import *
import taker
import maker
import bitcoin as btc
import sendpayment

from optparse import OptionParser
from datetime import timedelta
import threading, time


class TakerThread(threading.Thread):

    def __init__(self, tmaker):
        threading.Thread.__init__(self)
        self.daemon = True
        self.tmaker = tmaker
        self.finished = False

    def finishcallback(self):
        self.tmaker.shutdown()

    def run(self):
        time.sleep(self.tmaker.waittime)
        if self.finished:
            return
        print 'giving up waiting'
        #cancel the remaining order
        self.tmaker.modify_orders([0], [])
        orders, total_cj_fee = choose_order(self.tmaker.db, self.tmaker.amount,
                                            self.tmaker.makercount)
        print 'chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
            total_cj_fee)
        total_amount = self.tmaker.amount + total_cj_fee + self.tmaker.txfee
        print 'total amount spent = ' + str(total_amount)

        utxos = self.taker.wallet.select_utxos(self.tmaker.mixdepth,
                                               total_amount)
        self.tmaker.cjtx = taker.CoinJoinTX(
            self.tmaker, self.tmaker.amount, orders, utxos,
            self.tmaker.destaddr,
            self.tmaker.wallet.get_change_addr(self.tmaker.mixdepth),
            self.tmaker.txfee, self.finishcallback)


class PatientSendPayment(maker.Maker, taker.Taker):

    def __init__(self, wallet, destaddr, amount, makercount, txfee, cjfee,
                 waittime, mixdepth):
        self.destaddr = destaddr
        self.amount = amount
        self.makercount = makercount
        self.txfee = txfee
        self.cjfee = cjfee
        self.waittime = waittime
        self.mixdepth = mixdepth
        maker.Maker.__init__(self, wallet)
        taker.Taker.__init__(self)

    def on_privmsg(self, nick, message):
        maker.Maker.on_privmsg(self, nick, message)
        taker.Taker.on_privmsg(self, nick, message)

    def on_welcome(self):
        maker.Maker.on_welcome(self)
        taker.Taker.on_welcome(self)
        self.takerthread = TakerThread(self)
        self.takerthread.start()

    def on_pubmsg(self, nick, message):
        maker.Maker.on_pubmsg(self, nick, message)
        taker.Taker.on_pubmsg(self, nick, message)

    def create_my_orders(self):
        #choose an absolute fee order to discourage people from
        # mixing smaller amounts
        order = {'oid': 0,
                 'ordertype': 'absorder',
                 'minsize': 0,
                 'maxsize': self.amount,
                 'txfee': self.txfee,
                 'cjfee': self.cjfee}
        return [order]

    def oid_to_order(self, oid, amount):
        #TODO race condition (kinda)
        #if an order arrives and before it finishes another order arrives
        # its possible this bot will end up paying to the destaddr more than it
        # intended
        utxos = self.wallet.select_utxos(self.mixdepth, amount)
        return utxos, self.destaddr, self.wallet.get_change_addr(self.mixdepth)

    def on_tx_unconfirmed(self, cjorder, balance, removed_utxos):
        self.amount -= cjorder.cj_amount
        if self.amount == 0:
            self.takerthread.finished = True
            print 'finished sending, exiting..'
            self.shutdown()
        utxo_list = self.wallet.get_utxo_list_by_mixdepth()[self.mixdepth]
        available_balance = 0
        for utxo in utxo_list:
            available_balance = self.wallet.unspent[utxo]['value']
        if available_balance > self.amount:
            order = {'oid': 0,
                     'ordertype': 'absorder',
                     'minsize': 0,
                     'maxsize': self.amount,
                     'txfee': self.txfee,
                     'cjfee': self.cjfee}
            return ([], [order])
        else:
            debug('not enough money left, have to wait until tx confirms')
            return ([0], [])

    def on_tx_confirmed(self, cjorder, confirmations, txid, balance,
                        added_utxos):
        if len(self.orderlist) == 0:
            order = {'oid': 0,
                     'ordertype': 'absorder',
                     'minsize': 0,
                     'maxsize': self.amount,
                     'txfee': self.txfee,
                     'cjfee': self.cjfee}
            return ([], [order])
        else:
            return ([], [])


def main():
    parser = OptionParser(
        usage='usage: %prog [options] [seed] [amount] [destaddr]',
        description='Sends a payment from your wallet to an given address' +
        ' using coinjoin. First acts as a maker, announcing an order and ' +
        'waiting for someone to fill it. After a set period of time, gives' +
        ' up waiting and acts as a taker and coinjoins any remaining coins')
    parser.add_option('-f',
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
    parser.add_option('-m',
                      '--mixdepth',
                      action='store',
                      type='int',
                      dest='mixdepth',
                      help='mixing depth to spend from, default=0',
                      default=0)
    (options, args) = parser.parse_args()

    if len(args) < 3:
        parser.error('Needs a seed, amount and destination address')
        sys.exit(0)
    seed = args[0]
    amount = int(args[1])
    destaddr = args[2]

    waittime = timedelta(hours=options.waittime).total_seconds()
    print 'Running patient sender of a payment'
    print 'txfee=%d cjfee=%d waittime=%s makercount=%d' % (
        options.txfee, options.cjfee, str(timedelta(hours=options.waittime)),
        options.makercount)

    wallet = Wallet(seed, options.mixdepth + 1)
    wallet.sync_wallet()

    utxo_list = wallet.get_utxo_list_by_mixdepth()[options.mixdepth]
    available_balance = 0
    for utxo in utxo_list:
        available_balance += wallet.unspent[utxo]['value']
    if available_balance < amount:
        print 'not enough money at mixdepth=%d, exiting' % (options.mixdepth)
        return

    from socket import gethostname
    nickname = 'ppayer-' + btc.sha256(gethostname())[:6]

    print 'starting irc'
    bot = PatientSendPayment(wallet, destaddr, amount, options.makercount,
                             options.txfee, options.cjfee, waittime,
                             options.mixdepth)
    try:
        bot.run(HOST, PORT, nickname, CHANNEL)
    finally:
        debug('CRASHING, DUMPING EVERYTHING')
        debug('wallet seed = ' + seed)
        debug_dump_object(wallet, ['addr_cache'])
        debug_dump_object(bot)


if __name__ == "__main__":
    main()
    print('done')
