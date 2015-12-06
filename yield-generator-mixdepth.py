#! /usr/bin/env python

import time, os, binascii, sys, datetime
import pprint
data_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(data_dir, 'lib'))

from maker import *
from irc import IRCMessageChannel, random_nick
import bitcoin as btc
import common, blockchaininterface

from socket import gethostname
mix_levels = 5

#CONFIGURATION

#miner fee contribution
txfee = 5000
# fees for available mix levels from max to min amounts.
cjfee = ['0.00015', '0.00014', '0.00013', '0.00012', '0.00011']
#cjfee = ["%0.5f" % (0.00015 - n*0.00001) for n in range(mix_levels)]
nickname = random_nick()
nickserv_password = ''

#END CONFIGURATION
print cjfee


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
        if common.get_network() == 'testnet':
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
        debug('mix_balance = ' + str(mix_balance))
        nondust_mix_balance = dict([(m, b)
                                    for m, b in mix_balance.iteritems()
                                    if b > common.DUST_THRESHOLD])
        if len(nondust_mix_balance) == 0:
            debug('do not have any coins left')
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
        debug('minsize=' + str(minsize) + ' calc\'d with cjfee=' + str(min(
            cjfee)))
        lower_bound_balances = filtered_mix_balance[1:] + [(-1, minsize)]
        mix_balance_min = [
            (mxb[0], mxb[1], minb[1])
            for mxb, minb in zip(filtered_mix_balance, lower_bound_balances)
        ]
        mix_balance_min = mix_balance_min[::-1]  #reverse list order
        thecjfee = cjfee[::-1]

        debug('mixdepth_balance_min = ' + str(mix_balance_min))
        orders = []
        oid = 0
        for mix_bal_min in mix_balance_min:
            mixdepth, balance, mins = mix_bal_min
            #the maker class reads specific keys from the dict, but others
            # are allowed in there and will be ignored
            order = {'oid': oid + 1,
                     'ordertype': 'relorder',
                     'minsize': max(mins - common.DUST_THRESHOLD,
                                    common.DUST_THRESHOLD) + 1,
                     'maxsize': max(balance - common.DUST_THRESHOLD,
                                    common.DUST_THRESHOLD),
                     'txfee': txfee,
                     'cjfee': thecjfee[oid],
                     'mixdepth': mixdepth}
            oid += 1
            orders.append(order)

        absorder_size = min(minsize, sorted_mix_balance[0][1])
        if absorder_size != 0:
            lowest_cjfee = thecjfee[min(oid, len(thecjfee) - 1)]
            absorder_fee = calc_cj_fee('relorder', lowest_cjfee, minsize)
            debug('absorder fee = ' + str(absorder_fee) + ' uses cjfee=' + str(
                lowest_cjfee))
            #the absorder is always oid=0
            order = {'oid': 0,
                     'ordertype': 'absorder',
                     'minsize': common.DUST_THRESHOLD + 1,
                     'maxsize': absorder_size - common.DUST_THRESHOLD,
                     'txfee': txfee,
                     'cjfee': absorder_fee}
            orders = [order] + orders
        debug('generated orders = \n' + '\n'.join([str(o) for o in orders]))
        return orders

    def oid_to_order(self, cjorder, oid, amount):
        order = [o for o in self.orderlist if o['oid'] == oid][0]
        if order['ordertype'] == 'relorder':
            mixdepth = order['mixdepth']
        else:
            #for the absolute fee order, take from the lowest balance higher than dust
            mix_balance = self.wallet.get_balance_by_mixdepth()
            filtered_mix_balance = dict([(m, b)
                                         for m, b in mix_balance.iteritems()
                                         if b > common.DUST_THRESHOLD])
            filtered_mix_balance = sorted(
                list(mix_balance.iteritems()),
                key=lambda a: a[1])
            mixdepth = filtered_mix_balance[0][0]
        debug('filling order, mixdepth=' + str(mixdepth))

        #mixdepth is the chosen depth we'll be spending from
        cj_addr = self.wallet.get_receive_addr(
            (mixdepth + 1) % self.wallet.max_mix_depth)
        change_addr = self.wallet.get_change_addr(mixdepth)

        utxos = self.wallet.select_utxos(mixdepth, amount)
        my_total_in = sum([va['value'] for va in utxos.values()])
        real_cjfee = calc_cj_fee(cjorder.ordertype, cjorder.cjfee, amount)
        change_value = my_total_in - amount - cjorder.txfee + real_cjfee
        if change_value <= common.DUST_THRESHOLD:
            debug('change value=%d below dust threshold, finding new utxos' %
                  (change_value))
            try:
                utxos = self.wallet.select_utxos(mixdepth,
                                                 amount + common.DUST_THRESHOLD)
            except Exception:
                debug(
                    'dont have the required UTXOs to make a output above the dust threshold, quitting')
                return None, None, None

        return utxos, cj_addr, change_addr

    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
        '''
		case 0
		the absorder will basically never get changed, unless there are no utxos left, when neworders==[]
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
        oldorders = self.orderlist
        if len(myorders) == 0:
            return ([o['oid'] for o in oldorders], [])

        cancel_orders = []
        ann_orders = []

        neworders = [o for o in myorders if o['ordertype'] == 'relorder']
        oldorders = [o for o in oldorders if o['ordertype'] == 'relorder']
        #new_setdiff_old = The relative complement of `new` in `old` = members in `new` which are not in `old`
        new_setdiff_old = [o for o in neworders if o not in oldorders]
        old_setdiff_new = [o for o in oldorders if o not in neworders]

        debug('neworders = \n' + '\n'.join([str(o) for o in neworders]))
        debug('oldorders = \n' + '\n'.join([str(o) for o in oldorders]))
        debug('new_setdiff_old = \n' + '\n'.join([str(o) for o in
                                                  new_setdiff_old]))
        debug('old_setdiff_new = \n' + '\n'.join([str(o) for o in
                                                  old_setdiff_new]))
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

        #check if the absorder has changed, or if it needs to be newly announced
        new_abs = [o for o in myorders if o['ordertype'] == 'absorder']
        old_abs = [o for o in oldorders if o['ordertype'] == 'absorder']
        if len(new_abs) > len(old_abs):
            #announce an absorder where there wasnt one before
            ann_orders = [new_abs[0]] + ann_orders
        elif len(new_abs) == len(old_abs) and len(old_abs) > 0:
            #maxsize is the only thing that changes, except cjfee but that changes at the same time
            if new_abs[0]['maxsize'] != old_abs[0]['maxsize']:
                ann_orders = [new_abs[0]] + ann_orders

        debug('can_orders = \n' + '\n'.join([str(o) for o in cancel_orders]))
        debug('ann_orders = \n' + '\n'.join([str(o) for o in ann_orders]))
        return (cancel_orders, ann_orders)

    def on_tx_confirmed(self, cjorder, confirmations, txid):
        if cjorder.cj_addr in self.tx_unconfirm_timestamp:
            confirm_time = int(time.time()) - self.tx_unconfirm_timestamp[
                cjorder.cj_addr]
        else:
            confirm_time = 0
        del self.tx_unconfirm_timestamp[cjorder.cj_addr]
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.log_statement([timestamp, cjorder.cj_amount, len(
            cjorder.utxos), sum([av['value'] for av in cjorder.utxos.values(
            )]), cjorder.real_cjfee, cjorder.real_cjfee - cjorder.txfee, round(
                confirm_time / 60.0, 2), ''])
        return self.on_tx_unconfirmed(cjorder, txid, None)


def main():
    common.load_program_config()
    import sys
    seed = sys.argv[1]
    if isinstance(common.bc_interface, blockchaininterface.BlockrInterface):
        print '\nYou are running a yield generator by polling the blockr.io website'
        print 'This is quite bad for privacy. That site is owned by coinbase.com'
        print 'Also your bot will run faster and more efficently, you can be immediately notified of new bitcoin network'
        print ' information so your money will be working for you as hard as possible'
        print 'Learn how to setup JoinMarket with Bitcoin Core: https://github.com/chris-belcher/joinmarket/wiki/Running-JoinMarket-with-Bitcoin-Core-full-node'
        ret = raw_input('\nContinue? (y/n):')
        if ret[0] != 'y':
            return

    wallet = Wallet(seed, max_mix_depth=mix_levels)
    common.bc_interface.sync_wallet(wallet)

    common.nickname = nickname
    debug('starting yield generator')
    irc = IRCMessageChannel(common.nickname,
                            realname='btcint=' + common.config.get(
                                "BLOCKCHAIN", "blockchain_source"),
                            password=nickserv_password)
    maker = YieldGenerator(irc, wallet)
    try:
        debug('connecting to irc')
        irc.run()
    except:
        debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
        debug_dump_object(maker)
        debug_dump_object(irc)
        import traceback
        debug(traceback.format_exc())


if __name__ == "__main__":
    main()
    print('done')
