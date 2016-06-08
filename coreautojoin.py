#! /usr/bin/env python
from __future__ import absolute_import, print_function

import random
import re
import sys
import os
import threading
from optparse import OptionParser
from getpass import getpass
from decimal import Decimal
from Queue import Queue

# data_dir = os.path.dirname(os.path.realpath(__file__))
# sys.path.insert(0, os.path.join(data_dir, 'joinmarket'))
import time
import datetime

import BaseHTTPServer
import urllib2

from joinmarket import Taker, load_program_config, get_p2pk_vbyte, IRCMessageChannel
from joinmarket import validate_address, jm_single, get_network
from joinmarket import random_nick
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, debug_dump_object
from joinmarket import AbstractWallet, BitcoinCoreInterface

import bitcoin as btc


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

class FeeEstimation:

    def __init__(self, txsize, txfee):
        self.txsize = txsize
        self.txfee = txfee

    def estimate_tx_fee(self, ins, outs, txtype='p2pkh'):
        # Returns an estimate of the number of satoshis required
        # for a transaction with the given number of inputs and outputs,
        # based on the fee rate of the original transaction.

        tx_estimated_bytes = btc.estimate_tx_size(ins, outs, txtype)
        log.debug('Estimated transaction size: ' + str(tx_estimated_bytes))
        return int(tx_estimated_bytes * self.txfee / self.txsize)

# thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class PaymentThread(threading.Thread):
    statement_file = os.path.join('logs', 'coreautojoin-statement.csv')

    def __init__(self, taker):
        threading.Thread.__init__(self, name='PaymentThread')
        self.daemon = True
        self.taker = taker
        self.ignored_makers = []

    def log_statement(self, data):
        if get_network() == 'testnet':
            return

        data = [str(d) for d in data]
        self.income_statement = open(self.statement_file, 'a')
        self.income_statement.write(','.join(data) + '\n')
        self.income_statement.close()

    def create_tx(self):
        crow = self.taker.db.execute(
            'SELECT COUNT(DISTINCT counterparty) FROM orderbook;').fetchone()
        counterparty_count = crow['COUNT(DISTINCT counterparty)']
        counterparty_count -= len(self.ignored_makers)
        if counterparty_count < self.taker.options.makercount:
            log.debug('not enough counterparties to fill order, ending')
            self.taker.msgchan.shutdown()
            return

        utxos = self.taker.utxo_data
        cjamount = self.taker.cjamount
        change_addr = self.taker.changeaddr
        choose_orders_recover = self.sendpayment_choose_orders
        makercount = self.taker.options.makercount
        orders, total_cj_fee = self.sendpayment_choose_orders(cjamount, makercount)
        if not orders:
            log.debug('ERROR not enough liquidity in the orderbook, exiting')
            self.taker.msgchan.shutdown()
            return
        
        total_tx_fee = self.taker.txfee * (makercount + 1)
        total_amount = cjamount + total_cj_fee + total_tx_fee
        print('estimated tx fee = ' + str(total_tx_fee))
        print('total estimated amount spent = ' + str(total_amount))

        auth_addr = self.taker.utxo_data[self.taker.auth_utxo]['address']
        self.taker.start_cj(self.taker.wallet, cjamount, orders, utxos,
            self.taker.destaddr, self.taker.changeaddr, total_tx_fee,
            finishcallback=self.finishcallback,
            choose_orders_recover=choose_orders_recover,
            auth_addr=auth_addr,
            estimate_fee=self.taker.estimateFeeFunc)

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            unsignedcjtx = btc.serialize(coinjointx.latest_tx)
            if unsignedcjtx != None:
                try:
                    signedcjtx = self.taker.wallet.sign_tx(unsignedcjtx)
                    if self.taker.pushtx(signedcjtx):
                        # log transaction
                        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                        self.log_statement([timestamp, jm_single().nickname, self.taker.options.makercount,
                            coinjointx.my_cj_addr, coinjointx.my_change_addr, coinjointx.cj_amount,
                            coinjointx.cjfee_total, coinjointx.total_txfee])
                except RuntimeError as inst:
                    log.debug('ERROR signing transaction')
                    print(inst.args)
                self.taker.wallet.lock_wallet()
            self.taker.msgchan.shutdown()
            return
        self.ignored_makers += coinjointx.nonrespondants
        log.debug('recreating the tx, ignored_makers=' + str(self.ignored_makers))
        self.create_tx()

    def sendpayment_choose_orders(self, cj_amount, makercount, nonrespondants=None, active_nicks=None):
        if nonrespondants is None:
            nonrespondants = []
        if active_nicks is None:
            active_nicks = []
        self.ignored_makers += nonrespondants
        orders = None
        total_cj_fee = -1
        repeat = True
        while repeat:
            orders, total_cj_fee = choose_orders(
                self.taker.db, cj_amount, makercount, self.taker.chooseOrdersFunc,
                self.ignored_makers + active_nicks)
            if not orders:
                return None, 0
            print('chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(total_cj_fee))
            if not self.taker.options.answeryes:
                if len(self.ignored_makers) > 0:
                    noun = 'total'
                else:
                    noun = 'additional'
                total_fee_pc = 1.0 * total_cj_fee / cj_amount
                log.debug(noun + ' coinjoin fee = ' + str(total_cj_fee) + ' sat ' + \
                    str(float('%.3g' % (100.0 * total_fee_pc))) + '%')
                check_high_fee(total_fee_pc)
                if raw_input('send with these orders? (y/n) ')[0] == 'y':
                    repeat = False
        return orders, total_cj_fee

    def run(self):
        if not os.path.isfile(self.statement_file):
            self.log_statement(['timestamp', 'nickname', 'maker count',
                'dest addr', 'change addr', 'cj amount/satoshi',
                'cj fee/satoshi', 'tx fee/satoshi'])
        print('waiting for all orders to certainly arrive')
        time.sleep(self.taker.options.waittime)
        self.create_tx()

class SendPayment(Taker):

    def __init__(self, msgchan, wallet, auth_utxo, cjamount, destaddr, changeaddr,
        txfee, utxo_data, options, chooseOrdersFunc, estimateFeeFunc):
        Taker.__init__(self, msgchan)
        self.msgchan = msgchan
        self.wallet = wallet
        self.auth_utxo = auth_utxo
        self.cjamount = cjamount
        self.destaddr = destaddr
        self.changeaddr = changeaddr
        self.txfee = txfee
        self.utxo_data = utxo_data
        self.options = options
        self.chooseOrdersFunc = chooseOrdersFunc
        self.estimateFeeFunc = estimateFeeFunc

    def on_welcome(self):
        Taker.on_welcome(self)
        PaymentThread(self).start()

    def pushtx(self, tx):
        log.debug('broadcasting transaction\ntxid=' + btc.txhash(tx))
        print(tx)

        tx_broadcast = jm_single().config.get('POLICY', 'tx_broadcast')
        if tx_broadcast == 'random-maker':
            crow = self.db.execute(
                'SELECT DISTINCT counterparty FROM orderbook ORDER BY ' + \
                'RANDOM() LIMIT 1;').fetchone()
            counterparty = crow['counterparty']
            log.debug('pushing tx to ' + counterparty)
            self.msgchan.push_tx(counterparty, tx)
            time.sleep(10) # see github issue #516
            pushed = True
        else:
            pushed = jm_single().bc_interface.pushtx(tx)

        if not pushed:
            log.debug('unable to pushtx')
        return pushed

class AutoCoreWallet(AbstractWallet):

    def __init__(self):
        super(AutoCoreWallet, self).__init__()
        if not isinstance(jm_single().bc_interface, BitcoinCoreInterface):
            raise RuntimeError('Bitcoin Core wallet can only be used when '
                               'blockchain interface is BitcoinCoreInterface')

    def get_key_from_addr(self, addr):
        self.ensure_wallet_unlocked()
        return btc.b58check_to_hex(jm_single().bc_interface.rpc('dumpprivkey', [addr]))

    def sign_tx(self, txhex):
        self.ensure_wallet_unlocked()
        res = jm_single().bc_interface.rpc('signrawtransaction', [txhex])
        if res['complete']:
            return res['hex']
        else:
            raise RuntimeError('error signing transaction', res['errors'])

    @staticmethod
    def ensure_wallet_unlocked():
        wallet_info = jm_single().bc_interface.rpc('getwalletinfo', [])
        if 'unlocked_until' in wallet_info and wallet_info['unlocked_until'] <= 0:
            while True:
                password = getpass('Enter passphrase to unlock wallet: ')
                if password == '':
                    raise RuntimeError('Aborting wallet unlock')
                try:
                    # TODO cleanly unlock wallet after use, not with arbitrary timeout
                    jm_single().bc_interface.rpc('walletpassphrase', [password, 120])
                    break
                except jm_single().JsonRpcError as exc:
                    if exc.code != -14:
                        raise exc
                        # Wrong passphrase, try again.
    
    @staticmethod
    def lock_wallet():
        jm_single().bc_interface.rpc('walletlock', [])

class NotificationRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def __init__(self, request, client_address, server):
        self.txqueue = server.txqueue
        self.base_server = server
        BaseHTTPServer.BaseHTTPRequestHandler.__init__(self, request, client_address, server)

    def do_HEAD(self):
        page = '/walletnotify?'
        status_code = 400
        if self.path.startswith(page):
            txid = self.path[len(page):]
            if re.match('^[0-9a-fA-F]*$', txid):
                self.txqueue.put(txid)
                status_code = 200
        
        request = urllib2.Request('http://localhost:' + str(self.base_server.server_port + 1) + self.path)
        request.get_method = lambda : 'HEAD'
        try:
            urllib2.urlopen(request)
        except:
            pass

        self.send_response(status_code)
        self.end_headers()

    def log_message(self, format, *args):
        return

class NotificationThread(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self, name='NoticationThread')
        self.txqueue = Queue()
        self.daemon = True
        
    def run(self):
        notify_host = 'localhost'
        notify_port = 62602  # defaults
        config = jm_single().config
        if 'notify_host' in config.options("BLOCKCHAIN"):
            notify_host = config.get("BLOCKCHAIN", "notify_host").strip()
        if 'notify_port' in config.options("BLOCKCHAIN"):
            notify_port = int(config.get("BLOCKCHAIN", "notify_port"))
        for inc in xrange(10):
            hostport = (notify_host, notify_port + inc)
            try:
                httpd = BaseHTTPServer.HTTPServer(hostport, NotificationRequestHandler)
            except:
                continue
            httpd.txqueue = self.txqueue
            log.debug('started transaction notification listening thread, host=' + \
                str(hostport[0]) + ' port=' + str(hostport[1]))
            httpd.serve_forever()
        log.debug('failed to bind for transaction notification listening')

def scan_for_txs(txid):
    res = []
    try:
        tx = jm_single().bc_interface.rpc('gettransaction', [txid])
        if tx != None:
            if len(tx['details']) == 1 and tx['confirmations'] == 0:
                if tx['details'][0]['category'] == 'send':
                    res = [{'info': tx, 'tx': btc.deserialize(tx['hex'])}]
    except Exception as inst:
        log.debug('error while getting transaction' + \
            '\n' + str(type(inst)) + \
            '\n' + str(inst.args) + \
            '\n' + str(inst))
    return [i for i in res if len(i['tx']['outs'])==2]

def get_tx_info(tx):
    assert len(tx['info']['details']) == 1
    assert len(tx['tx']['outs']) == 2
    satperbtc = Decimal('1e8')
    cjamount = -long(Decimal(str(tx['info']['details'][0]['amount'])) * satperbtc)
    destaddr = tx['info']['details'][0]['address']
    changeaddr = ''
    txfee = -long(Decimal(str(tx['info']['fee'])) * satperbtc)
    addrs = [btc.script_to_address(o['script']) for o in tx['tx']['outs']]
    for a in addrs:
        if a != destaddr:
            changeaddr = a
    return cjamount, destaddr, changeaddr, txfee

def get_utxo_data(tx, wallet):
    auth_utxo = None
    all_utxos = [i['outpoint']['hash']+':'+str(i['outpoint']['index']) for i in tx['tx']['ins']]
    query_result = jm_single().bc_interface.query_utxo_set(all_utxos)
    if None in query_result:
        log.debug('ERROR: some utxo was not found\n' + str(query_result))
        return None, {}
    assert len(tx['tx']['ins']) == len(query_result)
    utxo_data = {}
    for utxo, data in zip(all_utxos, query_result):
        utxo_data[utxo] = {'address': data['address'], 'value': data['value']}
    for utxo in all_utxos:
        try:
            if utxo_data[utxo]['address'] != btc.privtoaddr(
                    wallet.get_key_from_addr(utxo_data[utxo]['address']),
                    magicbyte=get_p2pk_vbyte()):
                continue
        except Exception as inst:
            log.debug('error while getting key' + \
                '\n' + str(type(inst)) + \
                '\n' + str(inst.args) + \
                '\n' + str(inst))
            continue
        auth_utxo = utxo
        break
    return auth_utxo, utxo_data

def process_transactions(txs, options, wallet, chooseOrdersFunc):
    for tx in txs:
        cjamount, destaddr, changeaddr, txfee = get_tx_info(tx)
        
        print('\nNEW PAYMENT:\n')
        print('ID: ' + tx['info']['txid'])
        print('Destination address: ' + destaddr)
        print('Amount: ' + str(cjamount) + ' sat')
        print('Change address: ' + changeaddr)
        print('Fee: ' + str(txfee) + ' sat')

        proceed_coinjoin = options.answeryes
        if not proceed_coinjoin:
            proceed_coinjoin = (raw_input('\nProceed with coinjoin? (y/n) ')[0] == 'y')
        if proceed_coinjoin:
            jm_single().bc_interface.rpc('abandontransaction', [tx['info']['txid']])
            fee = FeeEstimation(len(tx['info']['hex'])/2, txfee)
            estimateFeeFunc = fee.estimate_tx_fee
            auth_utxo, utxo_data = get_utxo_data(tx, wallet)
            if auth_utxo == None:
                print('ERROR: no p2pkh address for auth utxo')
                continue

            jm_single().nickname = random_nick()
            log.debug('starting sendpayment')
            irc = IRCMessageChannel(jm_single().nickname)
            taker = SendPayment(irc, wallet, auth_utxo, cjamount, destaddr, changeaddr,
                txfee, utxo_data, options, chooseOrdersFunc, estimateFeeFunc)
            try:
                log.debug('starting irc')
                irc.run()
            except:
                log.debug('CRASHING, DUMPING EVERYTHING')
                debug_dump_object(wallet)
                debug_dump_object(taker)
                import traceback
                log.debug(traceback.format_exc())
                return
        elif raw_input('Broadcast current transaction? (y/n) ')[0] == 'y':
            log.debug('broadcasting transaction')
            print(res['hex'])
            jm_single().bc_interface.pushtx(tx['info']['hex'])
        
        time.sleep(1)
        raw_input('\nPress Enter to continue...')

def main():
    parser = OptionParser(
        usage='usage: %prog [options] {<txid> | listen}',
        description='Scans for unconfirmed payments sent using bitcoinqt and '
        +'makes coinjoins using the existing inputs and outputs.')
    parser.add_option(
        '-w',
        '--wait-time',
        action='store',
        type='float',
        dest='waittime',
        help='wait time in seconds to allow orders to arrive, default=15',
        default=15)
    parser.add_option(
        '-N',
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
        help='manually pick which orders to take')
    parser.add_option('--yes',
        action='store_true',
        dest='answeryes',
        default=False,
        help='answer yes to everything')
    (options, args) = parser.parse_args()

    if len(args) < 1:
        parser.error('Needs <txid> or "listen"')
        sys.exit(0)
    txid = args[0]
    load_program_config()

    chooseOrdersFunc = None
    if options.pickorders:
        chooseOrdersFunc = pick_order
    elif options.choosecheapest:
        chooseOrdersFunc = cheapest_order_choose
    else: # choose randomly (weighted)
        chooseOrdersFunc = weighted_order_choose

    wallet = AutoCoreWallet()

    if txid == 'listen':
        thread = NotificationThread()
        thread.start()
        while True:
            if thread.txqueue.empty():
                try:
                    time.sleep(0.1)
                except KeyboardInterrupt:
                    break
            else:
                txs = scan_for_txs(thread.txqueue.get())
                process_transactions(txs, options, wallet, chooseOrdersFunc)
    elif re.match('^[0-9a-fA-F]*$', txid):
        txs = scan_for_txs(txid)
        process_transactions(txs, options, wallet, chooseOrdersFunc)
    else:
        parser.error('Needs <txid> or "listen"')
        sys.exit(0)


if __name__ == "__main__":
    print('_________                 _______       _____      _________     _____       ')
    print('__  ____/____________________    |___  ___  /____________  /________(_)______')
    print('_  /    _  __ \\_  ___/  _ \\_  /| |  / / /  __/  __ \\__ _  /_  __ \\_  /__  __ \\')
    print('/ /___  / /_/ /  /   /  __/  ___ / /_/ // /_ / /_/ / /_/ / / /_/ /  / _  / / /')
    print('\\____/  \\____//_/    \___//_/  |_\\__,_/ \\__/ \\____/\\____/  \\____//_/  /_/ /_/')
    print('')
    main()
    print('done')
