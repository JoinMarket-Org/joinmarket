#! /usr/bin/env python

from __future__ import absolute_import

import socket, json, threading, pprint, re
from optparse import OptionParser

from joinmarket import Taker, load_program_config, IRCMessageChannel
from joinmarket import validate_address, jm_single, rand_norm_array
from joinmarket import random_nick
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    weighted_order_choose, debug_dump_object
from joinmarket import BlockchainInterface, BitcoinCoreWallet
from joinmarket.wallet import estimate_tx_fee
from joinmarket.configure import get_p2sh_vbyte, get_p2pk_vbyte
from joinmarket.jsonrpc import JsonRpcConnectionError, JsonRpcError
import bitcoin as btc

log = get_log()

def ok_orders(total_fee_pc):
    WARNING_THRESHOLD = 0.02  # 2%
    if total_fee_pc > WARNING_THRESHOLD:
        print('\n'.join(['=' * 60] * 3))
        print('WARNING   ' * 6)
        print('\n'.join(['=' * 60] * 1))
        print('OFFERED COINJOIN FEE IS UNUSUALLY HIGH. DOUBLE/TRIPLE CHECK.')
        print('\n'.join(['=' * 60] * 1))
        print('WARNING   ' * 6)
        print('\n'.join(['=' * 60] * 3))
    jm_single().debug_silence[0] = True
    ret = raw_input('send with these orders? (y/n):')[0] == 'y'
    jm_single().debug_silence[0] = False
    return ret 

def obtain_utxo_data(txid, index):
    try:
        txdata = jm_single().bc_interface.rpc('gettransaction', [txid])
        out = btc.deserialize(str(txdata['hex']))['outs'][index]
        pprint.pprint(btc.deserialize(str(txdata['hex'])))
        addr = btc.script_to_address(out['script'], get_p2pk_vbyte())
        value = out['value']
        return {'address': addr, 'value': value}
    except (JsonRpcError, JsonRpcConnectionError) as e:
        log.debug('transaction not found, returning')
        raise ValueError(repr(e))

class BitcoindTaker(Taker):
    def __init__(self, msgchan, wallet, options, retry_txid):
        super(BitcoindTaker, self).__init__(msgchan)
        self.wallet = wallet
        self.options = options
        self.retry_txid = retry_txid
        self.ignored_makers = []

    def on_welcome(self):
        Taker.on_welcome(self)
        if self.retry_txid:
            threading.Timer(self.options.waittime,
                lambda : self.handle_noncj_txid(self.retry_txid)).start()

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            pushed = coinjointx.self_sign_and_push()
            if pushed:
                log.debug('created fully signed tx')
            return
        self.ignored_makers += coinjointx.nonrespondants
        log.debug('recreating the tx, ignored_makers=' + str(
            self.ignored_makers))
        self.create_tx()

    def bitcoind_choose_orders(self,
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
            self.db, cj_amount, makercount, weighted_order_choose,
            self.ignored_makers + active_nicks)
        if not orders:
            return None, 0
        log.debug('chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
            total_cj_fee))
        total_fee_pc = 1.0 * total_cj_fee / cj_amount
        log.debug('coinjoin fee = ' + str(float('%.3g' % (
            100.0 * total_fee_pc))) + '%')
        if not self.options.answeryes:
            if not ok_orders(total_fee_pc):
                return None, 0
        return orders, total_cj_fee

    def create_tx(self):
        if self.change_addr:
            log.debug('creating a coinjoin with change')
            choose_orders_recover = self.bitcoind_choose_orders
            orders, total_cj_fee = self.bitcoind_choose_orders(
                self.cjamount, self.maker_count)
            if not orders:
                log.debug('unable to create coinjoin')
                return
        else:
            log.debug('creating a sweep coinjoin with no change')
            orders, self.cjamount, total_cj_fee = choose_sweep_orders(
                self.db, input_values, self.txfee,
                self.makercount, weighted_order_choose,
                ignored_makers=None)
            if not orders:
                log.debug("Could not find orders to complete transaction.")
                return
            total_fee_pc = 1.0 * total_cj_fee / self.cj_amount
            log.debug(noun + ' coinjoin fee = ' + str(float('%.3g' % (
                100.0 * total_fee_pc))) + '%')
            if not self.options.answeryes:
                if not ok_orders(total_fee_pc):
                    return
        log.debug('detected coinjoin amount=' + str(self.cjamount) +
            ' cjaddr=' + self.cj_addr + ' change=' + str(self.change_addr))
        self.start_cj(self.wallet, self.cjamount, orders, self.utxos,
            self.cj_addr, self.change_addr, self.txfee,
            self.finishcallback, choose_orders_recover)

    def handle_noncj_txid(self, txid):
        if not re.match('^[0-9a-fA-F]*$', txid):
            log.debug('not a txid')
            return
        try:
            txdata = jm_single().bc_interface.rpc('gettransaction', [txid])
        except (JsonRpcError, JsonRpcConnectionError) as e:
            log.debug('transaction not found, returning')
            return
        if txdata['confirmations'] != 0:
            log.debug('not an unconfirmed tx, returning')
            return
        txd = btc.deserialize(str(txdata['hex']))
        if len(txd['outs']) > 2:
            log.debug('tx has more outputs than 2, unable to make coinjoin of it')
            return
        utxo_list = [(ins['outpoint']['hash'], ins['outpoint']
            ['index']) for ins in txd['ins']]
        self.utxos = dict([(utxo[0] + ':' + str(utxo[1]),
            obtain_utxo_data(*utxo)) for utxo in utxo_list])
        log.debug('utxos = \n' + pprint.pformat(self.utxos))
        input_values = sum([s['value'] for s in self.utxos.values()])
        output_values = sum((o['value'] for o in txd['outs']))
        self.txfee = input_values - output_values
        self.maker_count = int(round(rand_norm_array(
            self.options.makercountrange[0],
            self.options.makercountrange[1], 1)[0]))
        log.debug('txfee=' + str(self.txfee) + ' maker_count=' +
            str(self.maker_count))
        if len(txd['outs']) == 2:
            log.debug('parsing coinjoin with change')
            output_addrs = [(btc.script_to_address(o['script'],
                get_p2pk_vbyte()), o['value']) for o in txd['outs']]
            addr_change = [(a, jm_single().bc_interface.rpc(
                'getreceivedbyaddress', [a[0], 0]) > 0)
                for a in output_addrs]
            log.debug('addr_change = ' + str(addr_change))
            change = zip(*addr_change)[1]
            if change[0] ^ change[1] == False:
                log.debug('unable to find which address is change (' +
                    str(change) + ') returning')
                return
            cj_out = [ac[0] for ac in addr_change if not ac[1]][0]
            self.cj_addr = cj_out[0]
            self.cjamount = cj_out[1]
            self.change_addr = [ac[0][0] for ac in addr_change if ac[1]][0]
        else:
            log.debug('parsing sweep coinjoin')
            self.cjamount = txd['outs'][0]['value']
            self.cj_addr = btc.script_to_address(txd['outs'][0]['script'],
                get_p2pk_vbyte())
            self.change_addr = None
            choose_orders_recover = None
            ##see the identical code in sendpayment.py for an explaination
            est_ins = len(self.utxos) + 3*self.maker_count
            log.debug("Estimated ins: "+str(est_ins))
            est_outs = 2*self.makercount + 1
            log.debug("Estimated outs: "+str(est_outs))
            estimated_fee = estimate_tx_fee(est_ins, est_outs)
            log.debug("We have a fee estimate: "+str(estimated_fee))
            log.debug("And a requested fee of: "+str(self.maker_count*
                self.txfee))
            if estimated_fee > self.maker_count*self.txfee:
                #both values are integers; we can ignore small rounding errors
                self.txfee = estimated_fee / self.maker_count
        self.create_tx()

    def notify_hook(self, requesthandler):
        log.debug('notify hook called')
        walletnotify = '/walletnotify?'
        if requesthandler.path.startswith(walletnotify):
            txid = requesthandler.path[len(walletnotify):]
            self.handle_noncj_txid(txid)

def main():
    parser = OptionParser(
        usage=
        'usage: %prog [options] [wallet file / fromaccount] [amount] [destaddr]',
        description='Sends a single payment from a given mixing depth of your '
        +
        'wallet to an given address using coinjoin and then switches off. Also sends from bitcoinqt. '
        +
        'Setting amount to zero will do a sweep, where the entire mix depth is emptied')
    parser.add_option(
        '-N',
        '--makercountrange',
        type='float',
        nargs=2,
        action='store',
        dest='makercountrange',
        help=
        'Input the mean and spread of number of makers to use. e.g. 3 1.5 will be a normal distribution '
        'with mean 3 and standard deveation 1.5 inclusive, default=3 1.5',
        default=(3, 1.5))
    parser.add_option('--yes',
        action='store_true',
        dest='answeryes',
        default=False,
        help='answer yes to everything')
    parser.add_option(
        '-w',
        '--wait-time',
        action='store',
        type='float',
        dest='waittime',
        help='wait time in seconds to allow orders to arrive, default=5',
        default=5)
    (options, args) = parser.parse_args()

    retry_txid = None
    if len(args) > 0:
        retry_txid = args[0]

    load_program_config()
    #fails if we're not using BitcoinCoreInterface
    wallet = BitcoinCoreWallet("")
    jm_single().nickname = random_nick()
    log.debug('starting joinmarket bitcoind interface')

    irc = IRCMessageChannel(jm_single().nickname)
    taker = BitcoindTaker(irc, wallet, options, retry_txid)

    jm_single().bc_interface.notify_hook = taker.notify_hook
    jm_single().bc_interface.start_notify_thread()

    try:
        log.debug('starting irc')
        irc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'wallet_name', 'seed'])
        debug_dump_object(taker)
        import traceback
        log.debug(traceback.format_exc())
    
if __name__ == "__main__":
    main()
    print('done')
