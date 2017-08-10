#! /usr/bin/env python2
from __future__ import absolute_import

import sys
import threading
import time
import random
from datetime import timedelta
from optparse import OptionParser
from joinmarket import Maker, Taker, load_program_config, IRCMessageChannel, \
     MessageChannelCollection, get_irc_mchannels
from joinmarket import validate_address, jm_single, get_p2pk_vbyte
from joinmarket import get_log, choose_orders, weighted_order_choose, \
    debug_dump_object, sync_wallet
from joinmarket import Wallet

import bitcoin as btc

log = get_log()

def is_bip32_pubkey(s):
    try:
        key = btc.bip32_deserialize(s)
        return key[0] in btc.PUBLIC
    except Exception:
        return False

def get_next_address(send_job):
    if 'addresses' in send_job:
        this_index = send_job['index']
        send_job['index'] = (send_job['index'] + 1) % len(send_job['addresses'])
        return send_job['addresses'][this_index]
    elif 'xpub' in send_job:
        send_job['index'] += 1
        return btc.pubtoaddr(btc.bip32_extract_key(btc.bip32_ckd(
            send_job['xpub'], send_job['index']-1)), get_p2pk_vbyte())
    else:
        assert False


class TakerThread(threading.Thread):
    def __init__(self, tmaker):
        threading.Thread.__init__(self, name='TakerThread')
        self.daemon = True
        self.tmaker = tmaker
        self.finished = False
        self.ignored_makers = []

    def create_tx(self):
        crow = self.tmaker.db.execute(
            'SELECT COUNT(DISTINCT counterparty) FROM orderbook;').fetchone()
        counterparty_count = crow['COUNT(DISTINCT counterparty)']
        counterparty_count -= len(self.ignored_makers)
        if counterparty_count < self.tmaker.options.makercount:
            print('not enough counterparties to fill order, ending')
            self.tmaker.msgchan.shutdown()
            return

        ###copypasted from sendpayment.py
        #todo: find a way to do this without duplicating code
        cjamount = self.tmaker.send_jobs[self.tmaker.job_index]['amount']
        destaddr = get_next_address(self.tmaker.send_jobs[
            self.tmaker.job_index])

        choose_orders_recover = None
        orders, total_cj_fee = self.patientsendpayment_choose_orders(
            cjamount, self.tmaker.options.makercount)
        if not orders:
            log.error(
                'ERROR not enough liquidity in the orderbook, exiting')
            return
        total_amount = cjamount + total_cj_fee + \
        self.tmaker.options.txfee*self.tmaker.options.makercount
        print 'total estimated amount spent = ' + str(total_amount)
        #adjust the required amount upwards to anticipate an increase in 
        #transaction fees after re-estimation; this is sufficiently conservative
        #to make failures unlikely while keeping the occurence of failure to
        #find sufficient utxos extremely rare. Indeed, a doubling of 'normal'
        #txfee indicates undesirable behaviour on maker side anyway.
        utxos = self.tmaker.wallet.select_utxos(self.tmaker.options.mixdepth, 
            total_amount + self.tmaker.options.txfee*
            self.tmaker.options.makercount)
        change_addr = self.tmaker.wallet.get_internal_addr(
            self.tmaker.options.mixdepth)
        choose_orders_recover = self.patientsendpayment_choose_orders

        self.tmaker.start_cj(self.tmaker.wallet, cjamount, orders, utxos,
            destaddr, change_addr, 
            self.tmaker.options.makercount*self.tmaker.options.txfee,
            self.finishcallback, choose_orders_recover)

    def patientsendpayment_choose_orders(self,
                                         cj_amount,
                                         makercount,
                                         nonrespondants=None,
                                         active_nicks=None):
        if nonrespondants is None:
            nonrespondants = []
        if active_nicks is None:
            active_nicks = []
        self.ignored_makers += nonrespondants
        while True:
            orders, total_cj_fee = choose_orders(
                    self.tmaker.db, cj_amount, makercount, weighted_order_choose,
                    self.ignored_makers + active_nicks)
            abs_cj_fee = 1.0 * total_cj_fee / makercount
            rel_cj_fee = abs_cj_fee / cj_amount
            log.info('rel/abs average fee = ' + str(rel_cj_fee) + ' / ' + str(
                    abs_cj_fee))

            if rel_cj_fee > self.tmaker.options.maxcjfee[
                0] and abs_cj_fee > self.tmaker.options.maxcjfee[1]:
                log.warn('cj fee higher than maxcjfee, waiting ' + str(
                        self.tmaker.options.liquiditywait) + ' seconds')
                time.sleep(self.tmaker.options.liquiditywait)
                continue
            if orders is None:
                log.warn('waiting for liquidity ' + str(
                        self.tmaker.options.liquiditywait) +
                          'secs, hopefully more orders should come in')
                time.sleep(self.tmaker.options.liquiditywait)
                continue
            break
        log.info('chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
                total_cj_fee))
        return orders, total_cj_fee

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            pushed = coinjointx.self_sign_and_push()
            log.info('created fully signed tx, push success = ' + str(pushed))

            if self.tmaker.job_index+1 < len(self.tmaker.send_jobs):
                self.tmaker.job_index += 1
                log.info('moved onto the next job = ' + str(self.tmaker
                    .send_jobs[self.tmaker.job_index]))
                time.sleep(5)
                self.create_tx()
            else:
                log.info('finished sending, exiting..')
                time.sleep(10) # see github issue #516
                self.tmaker.msgchan.shutdown()
        else:
            self.ignored_makers += coinjointx.nonrespondants
            log.info('recreating the tx, ignored_makers=' + str(
                self.ignored_makers))
            self.create_tx()

    def run(self):
        # TODO what if the bot has run out of utxos and
        # needs to wait for some tx to confirm before it can trade
        # presumably it needs to wait here until the tx confirms
        #solution to this is to have a boolean flag that the taker loops over checking
        log.info('waiting for ' + str(self.tmaker.waittime) + ' seconds')
        st = int(time.time())
        while int(time.time()) - st < self.tmaker.waittime:
            if self.finished:
                log.info('finished, exiting taker thread')
                return
            time.sleep(2)
        log.info('giving up waiting')
        # cancel the remaining order
        self.tmaker.modify_orders(self.tmaker.get_patient_send_oids(), [])
        self.create_tx()

class PatientSendPayment(Maker, Taker):
    def __init__(self, msgchan, wallet, send_jobs, options, waittime):
        self.send_jobs = send_jobs
        self.job_index = 0
        self.options = options
        self.waittime = waittime
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
        if self.waittime > 0:
            ##zero means never be a taker
            self.takerthread = TakerThread(self)
            self.takerthread.start()

    def get_patient_send_oids(self):
        return [0, 1]

    def create_patient_send_orders(self):
        # choose an absolute fee order to encourage people to
        # mix bigger amounts

        minsize = max(jm_single().DUST_THRESHOLD, self.options.minoutputsize)
        range_order = \
                {'oid': 0,
                 'ordertype': 'absoffer',
                 'minsize': minsize,
                 'maxsize': self.send_jobs[self.job_index]['amount'] - minsize,
                 'txfee': self.options.txfee,
                 'cjfee': self.options.cjfee_base + self.options.cjfee_add}
        exact_order = \
                {'oid': 1,
                 'ordertype': 'absoffer',
                 'minsize': self.send_jobs[self.job_index]['amount'],
                 'maxsize': self.send_jobs[self.job_index]['amount'],
                 'txfee': self.options.txfee,
                 'cjfee': self.options.cjfee_base}
        return [range_order, exact_order]

    def create_my_orders(self):
        return self.create_patient_send_orders()

    def oid_to_order(self, cjorder, oid, amount):
        # TODO race condition (kinda)
        # if an order arrives and before it finishes another order arrives
        # its possible this bot will end up paying to the destaddr more than it
        # intended
        # because the amount -= cjorder.cj_amount happens in on_tx_unconfirmed
        #this would have to be solved by cancelling our order right after 
        # sending the signatures and then waiting some timeout before assuming
        # the taker didnt broadcast
        utxos = self.wallet.select_utxos(self.options.mixdepth, self.send_jobs[
            self.job_index]['amount'])
        destaddr = get_next_address(self.send_jobs[self.job_index])
        return utxos, destaddr, self.wallet.get_internal_addr(
            self.options.mixdepth)

    def on_tx_unconfirmed(self, cjorder, balance, removed_utxos):
        self.send_jobs[self.job_index]['amount'] -= cjorder.cj_amount
        if self.send_jobs[self.job_index]['amount']<self.options.minoutputsize:
            if self.job_index+1 < len(self.send_jobs):
                self.job_index += 1
                log.info('moved onto the next job = ' + str(self.send_jobs[
                    self.job_index]))
            else:
                self.takerthread.finished = True
                log.info('finished sending, exiting..')
                self.tmaker.msgchan.shutdown()
                return [], []
        available_balance = self.wallet.get_balance_by_mixdepth()[
            self.options.mixdepth]
        if available_balance >= self.send_jobs[self.job_index]['amount']:
            return [], self.create_patient_send_orders()
        else:
            log.warn('not enough money left, have to wait until tx confirms')
            return self.get_patient_send_oids(), []

    def on_tx_confirmed(self, cjorder, confirmations, txid):
        if len(self.orderlist) == 0:
            # didnt have any confirmed utxos in
            # on_tx_unconfirmed() so create order here
            return [], self.create_patient_send_orders()
        else:
            return [], []

def main():
    parser = OptionParser(
            usage=
            'usage: %prog [options] [wallet file] [[dest..] [amount]..]',
            description='Sends a payment from your wallet to an given address'
                        + ' using coinjoin but for users who dont mind '
                        + 'waiting. First acts as a maker, announcing an order'
                        + ' and waiting for someone to fill it. After a set '
                        + 'period of time, gives up waiting and acts as a taker'
                        + ' and coinjoins any remaining coins. Is able to send'
                        + ' to multiple locations one after another. [dest] '
                        + 'can be multiple addresses or a xpub BIP32 key. xpub'
                        + ' keys can be optionally followed with :index to '
                        + 'start from another address than zero')
    parser.add_option(
            '-f',
            '--txfee',
            action='store',
            type='int',
            dest='txfee',
            default=1000,
            help='miner fee contribution, in satoshis, default=1000')
    parser.add_option(
            '-N',
            '--makercount',
            action='store',
            type='int',
            dest='makercount',
            help='how many makers to coinjoin with, default random '
                 'from 5 to 7',
            default=random.randint(5, 7))
    parser.add_option(
            '-w',
            '--wait-time',
            action='store',
            type='float',
            dest='waittime',
            help='wait time in hours as a maker before becoming a taker, ' +
                'or zero to wait forever, default=8',
            default=8)
    parser.add_option(
            '-c',
            '--base-cjfee',
            action='store',
            type='int',
            dest='cjfee_base',
            help=
            'base coinjoin fee asked for when being a maker, in satoshis per' +
                ' order filled, default=500',
            default=500)
    parser.add_option(
            '-a',
            '--add-cjfee',
            action='store',
            type='int',
            dest='cjfee_add',
            help=
            'additional coinjoin fee asked for when being a maker when '
                + 'coinjoin amount not exact, in satoshis per order filled'
                + ', default=1000',
            default=1000)
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
            'Use the Bitcoin Core wallet through json rpc, instead of the '
            + 'internal joinmarket wallet. Requires blockchain_source=json-rpc.'
            + ' NOT IMPLEMENTED YET')
    parser.add_option('--fast',
                      action='store_true',
                      dest='fastsync',
                      default=False,
                      help=('choose to do fast wallet sync, only for Core and '
                      'only for previously synced wallet'))
    parser.add_option(
            '-x',
            '--maxcjfee',
            type='float',
            dest='maxcjfee',
            nargs=2,
            default=(0.01, 10000),
            help='maximum coinjoin fee and bitcoin value the taker is ' +
                 'willing to pay to a single market maker. Both values need' +
                 ' to be exceeded, so if the fee is 30% but only 500satoshi ' +
                 'is paid the tx will go ahead. default=0.01, 10000 ' +
                 '(1%, 10000satoshi)')
    parser.add_option(
            '-q',
            '--liquiditywait',
            type='int',
            dest='liquiditywait',
            default=20,
            help=
            'amount of seconds to wait after failing to choose suitable orders'
            ' before trying again, default 20')
    parser.add_option(
            '-u',
            '--minoutputsize',
            type='int',
            dest='minoutputsize',
            nargs=1,
            default=30000,
            help='minimum size of output in satoshis produced by '
                'patientsendpayment. default=30000 satoshi')
    
    (options, args) = parser.parse_args()

    if len(args) < 3:
        parser.error('Needs a wallet, amount and destination address')
        sys.exit(0)
    wallet_name = args[0]

    load_program_config()

    send_jobs = []
    destination = None
    for ar in args[1:]:
        if ar.isdigit():
            if destination == None:
                log.error('found amount without destination')
                return
            elif isinstance(destination, list):
                send_jobs.append( {'amount': int(ar), 'addresses': 
                    destination, 'index': 0} )
            elif isinstance(destination, tuple):
                send_jobs.append( {'amount': int(ar), 'xpub': destination[0]
                , 'index': destination[1]} )
            else:
                assert False
            destination = None
        else:
            if validate_address(ar)[0]:
                if destination == None:
                    destination = []
                destination.append(ar)
            else:
                index = 0
                colon = ar.find(':')
                if colon > -1:
                    index = int(ar[colon+1:])
                    ar = ar[:colon]
                if is_bip32_pubkey(ar):
                    destination = (ar, index)
                else:
                    log.error('unable to parse destination: ' + ar)
                    return
    if destination != None:
        log.error('missing amount')
        return

    for j in send_jobs:
        print('sending ' + str(j['amount']) + ' satoshi to: ')
        if 'addresses' in j:
            for a in j['addresses']:
                print('  ' + get_next_address(j))
        else:
            print('  ' + j['xpub'] + '\n  starting from index: ' + 
                str(j['index']) + '. first 5 addresses:')
            index_cache = j['index']
            for i in range(5):
                print('    ' + get_next_address(j))
            j['index'] = index_cache

    waittime = timedelta(hours=options.waittime).total_seconds()

    # todo: this section doesn't make a lot of sense
    if not options.userpcwallet:
        wallet = Wallet(wallet_name, options.mixdepth + 1)
    else:
        print 'not implemented yet'
        sys.exit(0)
    # wallet = BitcoinCoreWallet(fromaccount=wallet_name)
    sync_wallet(wallet, fast=options.fastsync)

    available_balance = wallet.get_balance_by_mixdepth()[options.mixdepth]
    total_amount = sum((j['amount'] for j in send_jobs))
    if available_balance < total_amount:
        print 'not enough money at mixdepth=%d, exiting' % options.mixdepth
        return

    log.info('Running patient sender of a payment')
    mcs = [IRCMessageChannel(c) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    PatientSendPayment(mcc, wallet, send_jobs, options, waittime)
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
