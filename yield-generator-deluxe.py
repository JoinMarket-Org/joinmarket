#! /usr/bin/env python
from __future__ import absolute_import, print_function

import datetime
import os
import time
import binascii
import sys
import random
import decimal

from joinmarket import Maker, IRCMessageChannel
from joinmarket import blockchaininterface, BlockrInterface
from joinmarket import jm_single, get_network, load_program_config
from joinmarket import random_nick
from joinmarket import get_log, calc_cj_fee, debug_dump_object
from joinmarket import Wallet

#CONFIGURATION
mix_levels = 5  # Careful! Only change this if you setup your wallet as such.
nickname = random_nick()
nickserv_password = ''

#min_output_size = 15000 # only create change greater than this amount
min_output_size = random.randrange(15000, 300000)  #random
#min_output_size = jm_single().DUST_THRESHOLD # 546 satoshis

#num_offers = 8 # number of offers to autogenerate
num_offers = random.randrange(4, 7)  #random
#num_offers = mix_levels

#spread types
# fibonacci- will gradually increase at the rate of the fibonacci sequence
# evenly- will be evenly spaced 
# random- random amounts between the high and the low
# custom- use _custom to set it directly
# bymixdepth- (for offers), make offer amounts equal to mixdepths
# note, when using bymixdepth, set 'num_offers = mix_levels' above

# min and max offer sizes
offer_spread = 'fibonacci'  # fibonacci, evenly, random, custom, bymixdepth
offer_low = None  # when None, min_output_size will be used
offer_high = None  # when None, size of largest mix depth will be used
#offer_high = random.randrange(2500000000, 3000000000)
custom_offers = [
    1, 1.5, 10, 100
]  # in bitcoins, used when offer_spread is set to custom

# percent fees for mix levels.
cjfee_spread = 'fibonacci'  # fibonacci, evenly, random, custom
cjfee_low = random.uniform(0.0001, 0.001)
cjfee_high = random.uniform(0.01, 0.015)
custom_cjfees = [
    0.011, 0.012, 0.013, 0.014, 0.015
]  # from smallest to largest, used when cjfee_spread is set to custom

txfee_spread = 'fibonacci'  # fibonacci, evenly, random, custom
txfee_low = random.randrange(100, 300)
txfee_high = random.randrange(4000, 6000)
custom_txfees = [
    300, 500, 800, 1000, 1200
]  # used when txfee_spread is set to custom

# You can overwrite the above autogenerate options for maximum customization
override_offers = None  # comment this line if using below
"""
override_offers = [
    {'ordertype': 'absorder', 'oid': 0, 'minsize': 0,     'maxsize': 100000000,   'cjfee': 0,      'txfee': 2000}, 
    {'ordertype': 'absorder', 'oid': 1, 'minsize': 0,     'maxsize': 1500000000,  'cjfee': 300000, 'txfee': 2000}, 
    {'ordertype': 'relorder', 'oid': 2, 'minsize': 15000, 'maxsize': 100000000,   'cjfee': 0.0001, 'txfee': 2000},
    {'ordertype': 'relorder', 'oid': 3, 'minsize': 15000, 'maxsize': 1000000000,  'cjfee': 0.0002, 'txfee': 2000},
    {'ordertype': 'relorder', 'oid': 4, 'minsize': 15000, 'maxsize': 2500000000,  'cjfee': 0.0003, 'txfee': 2000},
    ]
"""

#END CONFIGURATION

log = get_log()


def fib(n):
    a, b = 0, 1
    for i in range(n):
        a, b = b, a + b
    return a


def fib_seq(low, high, num, for_offers=False):
    if for_offers:
        total = high - low
    else:
        total = high
    num += 1  # because 1,1,2
    fib_sec = total / fib(num)
    x = []
    if for_offers:
        for y in range(2, num):
            x.append(low + (fib_sec * fib(y)))
    else:
        x.append(low)
        for y in range(3, num):
            x.append(fib_sec * fib(y))
    x.append(high)
    return x


def drange(start, stop, step):
    r = start
    while r < stop:
        yield r
        r += step


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
        filtered_mix_balance = sorted(
            list(mix_balance.iteritems()),
            key=lambda a: a[1])  #sort by size

        max_mixdepth_size = filtered_mix_balance[-1][1]
        if max_mixdepth_size is 0:
            print("ALERT: wallet empty")
            sys.exit(0)

        if override_offers:
            log.debug('override_offers = \n' + '\n'.join([str(
                o) for o in override_offers]))
            # make sure custom offers dont create a negative net
            for offer in override_offers:
                if offer['ordertype'] == 'absorder':
                    profit = offer['cjfee']
                    needed = 'make txfee be less then the cjfee'
                elif offer['ordertype'] == 'relorder':
                    profit = calc_cj_fee(offer['ordertype'], offer['cjfee'],
                                         offer['minsize'])
                    if float(offer['cjfee']) > 0:
                        needed = 'set minsize to ' + str(int(int(offer[
                            'txfee'] / float(offer['cjfee']))))
                if int(offer['txfee']) > profit:
                    print("ALERT: negative yield")
                    print('-> ' + str(offer))
                    print(needed)
                    # if you really wanted to, you could comment out the next line.
                    sys.exit(0)
            return override_offers

        offer_lowx = max(offer_low, min_output_size)
        if offer_high:
            offer_highx = min(offer_high, max_mixdepth_size - min_output_size)
        else:
            offer_highx = filtered_mix_balance[-1][1] - min_output_size
            # note, subtracting mix_output_size here to make minimum size change
            # todo, make an offer for exactly the max size with no change

            # Offers
        if offer_spread == 'fibonacci':
            offer_levels = fib_seq(offer_lowx,
                                   offer_highx,
                                   num_offers,
                                   for_offers=True)
        elif offer_spread == 'evenly':
            offer_levels = list(range(
                ((offer_highx - offer_lowx) / num_offers), offer_highx,
                (offer_highx - offer_lowx) / (num_offers - 1))) + [offer_highx]
        elif offer_spread == 'random':
            offer_levels = sorted([random.randrange(offer_lowx, offer_highx)
                                   for n in range(num_offers - 1)] +
                                  [random.randrange(offer_highx - (
                                      offer_highx / num_offers), offer_highx)])
        elif offer_spread == 'bymixdepth':
            offer_levels = [m[1]
                            for m in filtered_mix_balance if m[1] < offer_highx
                           ] + [offer_highx]  # already sorted by size above
        elif offer_spread == 'custom':
            offer_levels = [
                int((decimal.Decimal(str(x)) * 100000000).quantize(0))
                for x in sorted(custom_offers)
            ]  # convert btc to satoshi
            if offer_levels[-1] > offer_highx:
                log.debug(
                    'ALERT: Your custom offers exceeds you max offer size.')
                log.debug('offer = ' + str(offer_levels[-1]) + ' offer_highx = '
                          + str(offer_highx))
                sys.exit(0)
        else:
            log.debug('invalid offer_spread = ' + str(offer_spread))
            sys.exit(0)

        # CJFees
        cjfee_lowx, cjfee_highx = decimal.Decimal(str(
            cjfee_low)) / 100, decimal.Decimal(str(cjfee_high)) / 100
        if cjfee_spread == 'fibonacci':
            cjfee_levels = fib_seq(cjfee_lowx, cjfee_highx, num_offers)
            cjfee_levels = ["%0.7f" % x for x in cjfee_levels]
        elif cjfee_spread == 'evenly':
            cjfee_levels = drange(
                ((cjfee_highx - cjfee_lowx) / num_offers), cjfee_highx,
                (cjfee_highx - cjfee_lowx) / (num_offers - 1))  # evenly spaced
            cjfee_levels = ["%0.7f" % x for x in cjfee_levels] + [cjfee_highx]
        elif cjfee_spread == 'random':
            cjfee_levels = sorted(
                ["%0.7f" % random.uniform(cjfee_lowx, cjfee_highx)
                 for n in range(num_offers)])  # randomly spaced
        elif cjfee_spread == 'custom':
            cjfee_levels = [str(decimal.Decimal(str(x)) / 100)
                            for x in custom_cjfees]
            leftout = num_offers - len(cjfee_levels)
            while leftout > 0:
                log.debug('ALERT: cjfee_custom has too few items')
                cjfee_levels.append(cjfee_levels[-1])
                leftout -= 1
        else:
            log.debug('invalid cjfee_spread = ' + str(cjfee_spread))
            sys.exit(0)

        # TXFees
        if txfee_spread == 'fibonacci':
            txfee_levels = fib_seq(txfee_low, txfee_high, num_offers)
        elif txfee_spread == 'evenly':
            txfee_levels = list(range(
                ((txfee_high - txfee_low) / num_offers), txfee_high, (
                    txfee_high - txfee_low) / (num_offers - 1))) + [txfee_high]
        elif txfee_spread == 'random':
            txfee_levels = sorted([random.randrange(txfee_low, txfee_high)
                                   for n in range(num_offers - 1)] +
                                  [random.randrange(txfee_high - (
                                      txfee_high / num_offers), txfee_high)])
        elif txfee_spread == 'custom':
            txfee_levels = [x for x in sorted(custom_txfees)]

        log.debug('offer_levels = ' + str(offer_levels))
        lower_bound_balances = [offer_lowx] + [x for x in offer_levels[:-1]]
        offer_ranges = zip(offer_levels, lower_bound_balances, cjfee_levels,
                           txfee_levels)
        log.debug('offer_ranges = ' + str(offer_ranges))
        offers = []
        oid = 0
        for upper, lower, cjfee, txfee in offer_ranges:
            # minimum cjfee you require for your offers
            #min_cjfee = random.randrange(txfee, txfee * 5)  # random
            #min_cjfee = int(1.5 * txfee) # 50% net revenue
            min_cjfee = 0  # no profit required
            if float(cjfee) > 0:
                min_needed = int(min_cjfee / float(cjfee))
            else:
                min_needed = min_cjfee
            if min_needed <= lower:
                # create a regular relorder
                offer = {'oid': oid,
                         'ordertype': 'relorder',
                         'minsize': lower,
                         'maxsize': upper,
                         'txfee': txfee,
                         'cjfee': cjfee}
            elif min_needed > lower and min_needed < upper:
                # create two offers. An absolute for lower bound need, and relorder for the rest
                offer = {'oid': oid,
                         'ordertype': 'absorder',
                         'minsize': lower,
                         'maxsize': min_needed - 1,
                         'txfee': txfee,
                         'cjfee': min_cjfee}
                oid += 1
                offers.append(offer)
                offer = {'oid': oid,
                         'ordertype': 'relorder',
                         'minsize': min_needed,
                         'maxsize': upper,
                         'txfee': txfee,
                         'cjfee': cjfee}
            elif min_needed >= upper:
                # just create an absolute offer
                offer = {'oid': oid,
                         'ordertype': 'absorder',
                         'minsize': lower,
                         'maxsize': upper,
                         'txfee': txfee,
                         'cjfee': min_cjfee}
                # todo: combine neighboring absorders into a single one
            oid += 1
            offers.append(offer)

        log.debug('generated offers = \n' + '\n'.join([str(o) for o in offers]))
        return offers

    def oid_to_order(self, cjorder, oid, amount):
        '''Coins rotate circularly from max mixdepth back to mixdepth 0'''
        mix_balance = self.wallet.get_balance_by_mixdepth()
        filtered_mix_balance = [m
                                for m in mix_balance.iteritems()
                                if m[1] >= amount]
        log.debug('mix depths that have enough, filtered_mix_balance = ' + str(
            filtered_mix_balance))

        # clumping. push all coins towards the largest mixdepth
        # the largest amount of coins are available to join with (since joins always come from a single depth)
        # the maker commands a higher fee for the larger amounts 
        # note, no need to consider max_offer_size here
        largest_mixdepth = sorted(filtered_mix_balance,
                                  key=lambda x: x[1],
                                  reverse=True)[0]  # find largest amount
        filtered_mix_balance = sorted(
            filtered_mix_balance,
            key=lambda x: x[0])  # make sure we are in seq of mixdepth num

        filtered_mix_balance[
            (filtered_mix_balance.index(largest_mixdepth) + 1
            ) % self.wallet.max_mix_depth:] + filtered_mix_balance[:(
                filtered_mix_balance.index(largest_mixdepth) + 1
            ) % self.wallet.max_mix_depth]  # order ascending but circularly with largest last

        # use mix depth with the most coins, 
        # creates a more even distribution across mix depths
        # and a more diverse txo selection in each depth
        # filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[1], reverse=True)  #sort largest to smallest amount

        # use mix depth that has the closest amount of coins to what this transaction needs
        # keeps coins moving through mix depths more quickly
        # and its more likely to use txos of a similiar size to this transaction
        # filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[1])  #sort smallest to largest usable amount

        # use a random usable mixdepth. 
        # warning, could expose more txos to malicous taker requests
        # filtered_mix_balance = random.choice(filtered_mix_balance)

        log.debug('sorted order of filtered_mix_balance = ' + str(
            filtered_mix_balance))

        mixdepth = filtered_mix_balance[0][0]

        log.debug('filling offer, mixdepth=' + str(mixdepth))

        # mixdepth is the chosen depth we'll be spending from
        cj_addr = self.wallet.get_internal_addr(
            (mixdepth + 1) % self.wallet.max_mix_depth)
        change_addr = self.wallet.get_internal_addr(mixdepth)

        utxos = self.wallet.select_utxos(mixdepth, amount)
        my_total_in = sum([va['value'] for va in utxos.values()])
        real_cjfee = calc_cj_fee(cjorder.ordertype, cjorder.cjfee, amount)
        change_value = my_total_in - amount - cjorder.txfee + real_cjfee
        if change_value <= min_output_size:
            log.debug('change value=%d below dust threshold, finding new utxos'
                      % (change_value))
            try:
                utxos = self.wallet.select_utxos(mixdepth,
                                                 amount + min_output_size)
            except Exception:
                log.debug(
                    'dont have the required UTXOs to make a output above the dust threshold, quitting')
                return None, None, None

        return utxos, cj_addr, change_addr

    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
        '''
		algorithm - find all the orders which have changed
		'''

        neworders = self.create_my_orders()
        oldorders = self.orderlist
        new_setdiff_old = [o for o in neworders if o not in oldorders]
        old_setdiff_new = [o for o in oldorders if o not in neworders]

        log.debug('neworders = \n' + '\n'.join([str(o) for o in neworders]))
        log.debug('oldorders = \n' + '\n'.join([str(o) for o in oldorders]))
        log.debug('new_setdiff_old = \n' + '\n'.join([str(
            o) for o in new_setdiff_old]))
        log.debug('old_setdiff_new = \n' + '\n'.join([str(
            o) for o in old_setdiff_new]))

        ann_orders = new_setdiff_old
        ann_oids = [o['oid'] for o in ann_orders]
        cancel_orders = [o['oid']
                         for o in old_setdiff_new if o['oid'] not in ann_oids]

        log.debug('can_orders = \n' + '\n'.join([str(o) for o in cancel_orders
                                                ]))
        log.debug('ann_orders = \n' + '\n'.join([str(o) for o in ann_orders]))

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

    jm_single().nickname = nickname
    log.debug('starting yield generator')
    irc = IRCMessageChannel(jm_single().nickname,
                            realname='btcint=' + jm_single().config.get(
                                "BLOCKCHAIN", "blockchain_source"),
                            password=nickserv_password)
    maker = YieldGenerator(irc, wallet)
    try:
        log.debug('connecting to irc')
        irc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
        debug_dump_object(maker)
        debug_dump_object(irc)
        import traceback
        log.debug(traceback.format_exc())


if __name__ == "__main__":
    main()
    print('done')
