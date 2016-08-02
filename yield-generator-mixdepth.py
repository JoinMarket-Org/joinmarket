#! /usr/bin/env python
from __future__ import absolute_import, print_function

import datetime
import os
import time
import binascii
import sys

from joinmarket import Maker, IRCMessageChannel, MessageChannelCollection
from joinmarket import blockchaininterface, BlockrInterface
from joinmarket import jm_single, get_network, load_program_config
from joinmarket import get_log, calc_cj_fee, debug_dump_object
from joinmarket import Wallet
from joinmarket import get_irc_mchannels

#data_dir = os.path.dirname(os.path.realpath(__file__))
#sys.path.insert(0, os.path.join(data_dir, 'lib'))

#import bitcoin as btc
#import blockchaininterface

from socket import gethostname
mix_levels = 5

#CONFIGURATION

#miner fee contribution
txfee = 5000
# fees for available mix levels from max to min amounts.
cjfee = ['0.00015', '0.00014', '0.00013', '0.00012', '0.00011']
#cjfee = ["%0.5f" % (0.00015 - n*0.00001) for n in range(mix_levels)]
nickserv_password = ''

#END CONFIGURATION
print(cjfee)
log = get_log()


#is a maker for the purposes of generating a yield from held
# bitcoins without ruining privacy for the taker, the taker could easily check
# the history of the utxos this bot sends, so theres not much incentive
# to ruin the privacy for barely any more yield
#sell-side algorithm:
#add up the value of each utxo for each mixing depth,
# announce a relative-fee order of the balance in each mixing depth
# amounts made to be non-overlapping
# minsize set by the miner fee contribution, so you never earn less in cjfee than miner fee
# cjfee drops as you go down to the lower-balance mixing depths, provides
#  incentive for people to clump coins together for you in one mix depth
#announce an absolute fee order between the dust limit and minimum amount
# so that there is liquidity in the very low amounts too
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
        log.debug('mix_balance = ' + str(mix_balance))
        nondust_mix_balance = dict([(m, b)
                                    for m, b in mix_balance.iteritems()
                                    if b > jm_single().DUST_THRESHOLD])
        if len(nondust_mix_balance) == 0:
            log.debug('do not have any coins left')
            return []
        #sorts the mixdepth_balance map by balance size
        sorted_mix_balance = sorted(
            list(mix_balance.iteritems()),
            key=lambda a: a[1],
            reverse=True)
        minsize = int(
            1.5 * txfee / float(min(cjfee))
        )  #minimum size is such that you always net profit at least 50% of the miner fee
        filtered_mix_balance = [f for f in sorted_mix_balance if f[1] > minsize]
        delta = mix_levels - len(filtered_mix_balance)
        log.debug('minsize=' + str(minsize) + ' calc\'d with cjfee=' + str(min(
            cjfee)))
        lower_bound_balances = filtered_mix_balance[1:] + [(-1, minsize)]
        mix_balance_min = [
            (mxb[0], mxb[1], minb[1])
            for mxb, minb in zip(filtered_mix_balance, lower_bound_balances)
        ]
        mix_balance_min = mix_balance_min[::-1]  #reverse list order
        thecjfee = cjfee[::-1]

        log.debug('mixdepth_balance_min = ' + str(mix_balance_min))
        orders = []
        oid = 0
        for mix_bal_min in mix_balance_min:
            mixdepth, balance, mins = mix_bal_min
            #the maker class reads specific keys from the dict, but others
            # are allowed in there and will be ignored
            order = {'oid': oid + 1,
                     'ordertype': 'reloffer',
                     'minsize': max(mins - jm_single().DUST_THRESHOLD,
                                    jm_single().DUST_THRESHOLD) + 1,
                     'maxsize': max(balance - max(jm_single().DUST_THRESHOLD, txfee),
                                    jm_single().DUST_THRESHOLD),
                     'txfee': txfee,
                     'cjfee': thecjfee[oid + delta],
                     'mixdepth': mixdepth}
            oid += 1
            orders.append(order)

        absorder_size = min(minsize, sorted_mix_balance[0][1])
        if absorder_size != 0:
            lowest_cjfee = thecjfee[min(oid, len(thecjfee) - 1)]
            absorder_fee = calc_cj_fee('reloffer', lowest_cjfee, minsize)
            log.debug('absoffer fee = ' + str(absorder_fee) + ' uses cjfee=' +
                      str(lowest_cjfee))
            #the absoffer is always oid=0
            order = {'oid': 0,
                     'ordertype': 'absoffer',
                     'minsize': jm_single().DUST_THRESHOLD + 1,
                     'maxsize': absorder_size - jm_single().DUST_THRESHOLD,
                     'txfee': txfee,
                     'cjfee': absorder_fee}
            orders = [order] + orders
        log.debug('generated orders = \n' + '\n'.join([str(o) for o in orders]))

        # sanity check
        for order in orders:
            assert order['minsize'] >= 0
            assert order['maxsize'] > 0
            assert order['minsize'] <= order['maxsize']

        return orders

    def oid_to_order(self, cjorder, oid, amount):
        total_amount = amount + cjorder.txfee
        mix_balance = self.wallet.get_balance_by_mixdepth()
        filtered_mix_balance = [m
                                for m in mix_balance.iteritems()
                                if m[1] >= total_amount]
        if not filtered_mix_balance:
            return None, None, None
        log.debug('mix depths that have enough, filtered_mix_balance = ' + str(
            filtered_mix_balance))

        # use mix depth that has the closest amount of coins to what this transaction needs
        # keeps coins moving through mix depths more quickly
        # and its more likely to use txos of a similiar size to this transaction
        filtered_mix_balance = sorted(
            filtered_mix_balance,
            key=lambda x: x[1])  #sort smallest to largest usable amount

        log.debug('sorted order of filtered_mix_balance = ' + str(
            filtered_mix_balance))

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
            log.debug('change value=%d below dust threshold, finding new utxos'
                      % (change_value))
            try:
                utxos = self.wallet.select_utxos(
                    mixdepth, total_amount + jm_single().DUST_THRESHOLD)
            except Exception:
                log.debug(
                    'dont have the required UTXOs to make a output above the dust threshold, quitting')
                return None, None, None

        return utxos, cj_addr, change_addr

    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
        '''
		case 0
		the absoffer will basically never get changed, unless there are no utxos left, when neworders==[]
		case 1
		a single coin is split into two coins across levels
		must announce a new order, plus modify the old order
		case 2
		two existing mixdepths get modified
		announce the modified new orders
		case 3
		one existing mixdepth gets emptied into another
		cancel it, modify the place it went

		algorithm
		find all the orders which have changed, the length of that list tells us which case
		'''

        myorders = self.create_my_orders()
        oldorderlist = self.orderlist
        if len(myorders) == 0:
            return ([o['oid'] for o in oldorderlist], [])

        cancel_orders = []
        ann_orders = []

        neworders = [o for o in myorders if o['ordertype'] == 'reloffer']
        oldorders = [o for o in oldorderlist if o['ordertype'] == 'reloffer']
        #new_setdiff_old = The relative complement of `new` in `old` = members in `new` which are not in `old`
        new_setdiff_old = [o for o in neworders if o not in oldorders]
        old_setdiff_new = [o for o in oldorders if o not in neworders]

        log.debug('neworders = \n' + '\n'.join([str(o) for o in neworders]))
        log.debug('oldorders = \n' + '\n'.join([str(o) for o in oldorders]))
        log.debug('new_setdiff_old = \n' + '\n'.join([str(
            o) for o in new_setdiff_old]))
        log.debug('old_setdiff_new = \n' + '\n'.join([str(
            o) for o in old_setdiff_new]))
        if len(neworders) == len(oldorders):
            ann_orders = new_setdiff_old
        elif len(neworders) > len(oldorders):
            ann_orders = new_setdiff_old
        elif len(neworders) < len(oldorders):
            ann_orders = new_setdiff_old
            ann_oids = [o['oid'] for o in ann_orders]
            cancel_orders = [o['oid']
                             for o in old_setdiff_new
                             if o['oid'] not in ann_oids]

        #check if the absoffer has changed, or if it needs to be newly announced
        new_abs = [o for o in myorders if o['ordertype'] == 'absoffer']
        old_abs = [o for o in oldorderlist if o['ordertype'] == 'absoffer']
        if len(new_abs) > len(old_abs):
            #announce an absoffer where there wasnt one before
            ann_orders = [new_abs[0]] + ann_orders
        elif len(new_abs) == len(old_abs) and len(old_abs) > 0:
            #maxsize is the only thing that changes, except cjfee but that changes at the same time
            if new_abs[0]['maxsize'] != old_abs[0]['maxsize']:
                ann_orders = [new_abs[0]] + ann_orders

        log.debug('can_orders = \n' + '\n'.join([str(o) for o in cancel_orders
                                                ]))
        log.debug('ann_orders = \n' + '\n'.join([str(o) for o in ann_orders]))
        return (cancel_orders, ann_orders)

    def on_tx_confirmed(self, cjorder, confirmations, txid):
        if cjorder.cj_addr in self.tx_unconfirm_timestamp:
            confirm_time = int(time.time()) - self.tx_unconfirm_timestamp[
                cjorder.cj_addr]
            del self.tx_unconfirm_timestamp[cjorder.cj_addr]
        else:
            confirm_time = 0
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.log_statement([timestamp, cjorder.cj_amount, len(
            cjorder.utxos), sum([av['value'] for av in cjorder.utxos.values(
            )]), cjorder.real_cjfee, cjorder.real_cjfee - cjorder.txfee, round(
                confirm_time / 60.0, 2), ''])
        return self.on_tx_unconfirmed(cjorder, txid, None)


def main():
    load_program_config()
    import sys
    seed = sys.argv[1]
    if isinstance(jm_single().bc_interface,
                  blockchaininterface.BlockrInterface):
        print(
            '\nYou are running a yield generator by polling the blockr.io website')
        print(
            'This is quite bad for privacy. That site is owned by coinbase.com')
        print(
            'Also your bot will run faster and more efficently, you can be immediately notified of new bitcoin network')
        print(
            ' information so your money will be working for you as hard as possible')
        print(
            'Learn how to setup JoinMarket with Bitcoin Core: https://github.com/chris-belcher/joinmarket/wiki/Running-JoinMarket-with-Bitcoin-Core-full-node')
        ret = raw_input('\nContinue? (y/n):')
        if ret[0] != 'y':
            return

    wallet = Wallet(seed, max_mix_depth=mix_levels)
    jm_single().bc_interface.sync_wallet(wallet)

    log.debug('starting yield generator')
    mcs = [IRCMessageChannel(c,
                             realname='btcint=' + jm_single().config.get(
                                 "BLOCKCHAIN", "blockchain_source"),
                        password=nickserv_password) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    maker = YieldGenerator(mcc, wallet)
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


if __name__ == "__main__":
    main()
    print('done')
