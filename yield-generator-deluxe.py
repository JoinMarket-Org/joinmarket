#! /usr/bin/env python
from __future__ import absolute_import, print_function

import datetime
import os
import time
import binascii
import sys
import random
import decimal

from joinmarket import Maker, IRCMessageChannel, MessageChannelCollection
from joinmarket import blockchaininterface, BlockrInterface
from joinmarket import jm_single, get_network, load_program_config
from joinmarket import get_log, calc_cj_fee, debug_dump_object
from joinmarket import Wallet
from joinmarket import get_irc_mchannels

#CONFIGURATION
mix_levels = 5  # Careful! Only change this if you setup your wallet as such.
nickserv_password = ''

#Spread Types
# fibonacci- will gradually increase at the rate of the fibonacci sequence
# evenly- will be evenly spaced 
# random- random amounts between the high and the low
# custom- use _custom to set it directly
# bymixdepth- (for offers), make offer amounts equal to mixdepths
# note, when using bymixdepth, set 'num_offers = mix_levels'

# min and max offer sizes
offer_spread = 'fibonacci'  # fibonacci, evenly, random, custom, bymixdepth
offer_low = None  # satoshis. when None, min_output_size will be used
offer_high = None  # satoshis. when None, size of largest mix depth will be used
#offer_low = random.randrange(21000000, 1e8)  #random
#offer_high = random.randrange(150 * 1e8, 200 * 1e8)
custom_offers = [
    1.01 * 1e8, 112345657, 1 * 1e8, 10 * 1e8, 100 * 1e8
]  # used when offer_spread is set to custom

# percent fees for mix levels.
cjfee_spread = 'fibonacci'  # fibonacci, evenly, random, custom
cjfee_low = random.uniform(0.0004, 0.0005)
cjfee_high = random.uniform(0.001, 0.01)
custom_cjfees = [
    0.01, 0.0123, 0.013, 0.014, 0.015
]  # used when cjfee_spread is set to custom

txfee_spread = 'fibonacci'  # fibonacci, evenly, random, custom
txfee_low = 0
txfee_high = 0
#txfee_low = random.randrange(1, 100)
#txfee_high = random.randrange(3000, 5000)
custom_txfees = [
    250, 500, 1000, 2000, 5000
]  # used when txfee_spread is set to custom

# number of offers to autogenerate
num_offers = random.randrange(6, 9)  # varied
#num_offers = 8 
#num_offers = mix_levels

# only create change greater than this amount
min_output_size = random.randrange(15000, 300000)  # varied
#min_output_size = random.randrange(5e6, 21e6)  # varied
#min_output_size = 15000 
#min_output_size = jm_single().DUST_THRESHOLD # 546 satoshis

# minimum profit you require for a transaction (exact absoffers for dust exempt)
profit_req_per_transaction = 1

# You can override the above autogenerate options for maximum customization
override_offers = None  # comment this line if using below
"""
override_offers = [
    {'ordertype': 'absoffer', 'oid': 0, 'minsize': 0,     'maxsize': 100000000,   'cjfee': 0,      'txfee': 2000},
    {'ordertype': 'absoffer', 'oid': 1, 'minsize': 0,     'maxsize': 1500000000,  'cjfee': 300000, 'txfee': 2000},
    {'ordertype': 'reloffer', 'oid': 2, 'minsize': 15000, 'maxsize': 100000000,   'cjfee': 0.0001, 'txfee': 2000},
    {'ordertype': 'reloffer', 'oid': 3, 'minsize': 15000, 'maxsize': 1000000000,  'cjfee': 0.0002, 'txfee': 2000},
    {'ordertype': 'reloffer', 'oid': 4, 'minsize': 15000, 'maxsize': 2500000000,  'cjfee': 0.0003, 'txfee': 2000},
    ]
"""

#END CONFIGURATION

log = get_log()
if offer_low:
    log.debug('offer_low = ' + str(offer_low) + " (" + str(offer_low / 1e8) +
              " btc)")
if offer_high:
    log.debug('offer_high = ' + str(offer_high) + " (" + str(offer_high / 1e8) +
              " btc)")
log.debug('cjfee_low = ' + str(cjfee_low))
log.debug('cjfee_high = ' + str(cjfee_high))
log.debug('txfee_low = ' + str(txfee_low))
log.debug('txfee_high = ' + str(txfee_high))
log.debug('min_output_size = ' + str(min_output_size) + " (" + str(
    min_output_size / 1e8) + " btc)")
profit_req_per_transaction = max(profit_req_per_transaction, -250)  # safe guard
log.debug('profit_req_per_transaction = ' + str(profit_req_per_transaction))


def fib(n):
    a, b = 0, 1
    for i in range(n):
        a, b = b, a + b
    return a


def fib_seq(low, high, num, upper_bound=False):
    x = []
    if upper_bound:
        num += 1
    else:
        x.append(low)
    fib_sec = (high - low) / decimal.Decimal(fib(num))
    for y in range(2, (num + 1)):
        x.append(low + (fib_sec * fib(y)))
    return x


# range function for decimals
def drange(start, stop, step):
    r = start
    while r < stop:
        yield r
        r += step
    yield stop


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
        log.debug('mix_btcance = ' + str([(x, y / 1e8)
                                          for x, y in mix_balance.iteritems()]))
        sorted_mix_balance = sorted(
            list(mix_balance.iteritems()),
            key=lambda a: a[1])  #sort by size

        largest_mixdepth_size = sorted_mix_balance[-1][1]
        if largest_mixdepth_size <= min_output_size:
            print("ALERT: not enough funds available in wallet")
            return []

        if override_offers:
            log.debug('override_offers = \n' + '\n'.join([str(
                o) for o in override_offers]))
            # make sure custom offers dont create a negative net
            for offer in override_offers:
                if offer['ordertype'] == 'absoffer':
                    profit = offer['cjfee']
                    needed = 'make txfee be less then the cjfee'
                elif offer['ordertype'] == 'reloffer':
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

	if txfee_spread == 'custom':
	    maximum_conf_txfees = max(custom_txfees)
	else:
	    maximum_conf_txfees = txfee_high
        if offer_high:
            offer_highx = min(offer_high,
                              largest_mixdepth_size - max(min_output_size,maximum_conf_txfees))
        else:
            offer_highx = largest_mixdepth_size - max(min_output_size,maximum_conf_txfees)
            # note, subtracting mix_output_size here to make minimum size change
            # todo, make an offer for exactly the max size with no change

            # Offers
        if offer_spread == 'fibonacci':
            offer_levels = fib_seq(offer_lowx,
                                   offer_highx,
                                   num_offers,
                                   upper_bound=True)
            offer_levels = [int(round(x)) for x in offer_levels]
        elif offer_spread == 'evenly':
            first_upper_bound = (offer_highx - offer_lowx) / num_offers
            offer_levels = list(range(first_upper_bound, offer_highx, (
                offer_highx - first_upper_bound) / (num_offers - 1)))
            offer_levels = offer_levels[0:(num_offers - 1)] + [offer_highx]
        elif offer_spread == 'random':
            offer_levels = sorted([random.randrange(offer_lowx, offer_highx)
                                   for n in range(num_offers - 1)] +
                                  [random.randrange(offer_highx - (
                                      offer_highx / num_offers), offer_highx)])
        elif offer_spread == 'bymixdepth':
            offer_levels = []
            for m in sorted_mix_balance:
                if m[1] == 0:
                    continue
                elif m[1] <= offer_lowx:
                    # todo, low mix balances get an absolute offer
                    continue
                elif m[1] > offer_highx:
                    offer_levels += [offer_highx]
                    break
                else:
                    offer_levels += [m[1]]
            # note, offer_levels len can be less then num_offers here
        elif offer_spread == 'custom':
            assert len(custom_offers) == num_offers
            offer_levels = [
                int((decimal.Decimal(str(x))).quantize(0))
                for x in sorted(custom_offers)
            ]
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
        cjfee_lowx = decimal.Decimal(str(cjfee_low)) / 100
        cjfee_highx = decimal.Decimal(str(cjfee_high)) / 100
        if cjfee_spread == 'fibonacci':
            cjfee_levels = fib_seq(cjfee_lowx, cjfee_highx, num_offers)
            cjfee_levels = ["%0.7f" % x for x in cjfee_levels]
        elif cjfee_spread == 'evenly':
            cjfee_levels = drange(cjfee_lowx, cjfee_highx,
                                  (cjfee_highx - cjfee_lowx) /
                                  (num_offers - 1))  # evenly spaced
            cjfee_levels = ["%0.7f" % x for x in cjfee_levels]
        elif cjfee_spread == 'random':
            cjfee_levels = sorted(
                ["%0.7f" % random.uniform(
                    float(cjfee_lowx), float(cjfee_highx))
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
            txfee_levels = [int(round(x)) for x in txfee_levels]
        elif txfee_spread == 'evenly':
            txfee_levels = list(range(txfee_low, txfee_high, (
                txfee_high - txfee_low) / (num_offers - 1)))
            txfee_levels = txfee_levels[0:(num_offers - 1)] + [txfee_high]
        elif txfee_spread == 'random':
            txfee_levels = sorted([random.randrange(txfee_low, txfee_high)
                                   for n in range(num_offers - 1)] +
                                  [random.randrange(txfee_high - (
                                      txfee_high / num_offers), txfee_high)])
        elif txfee_spread == 'custom':
            txfee_levels = [x for x in custom_txfees]
        else:
            log.debug('invalid txfee_spread = ' + str(txfee_spread))
            sys.exit(0)

        log.debug('offer_levels = ' + str(offer_levels))
        lower_bound_balances = [offer_lowx] + [x for x in offer_levels[:-1]]
        if offer_spread == 'bymixdepth':
            cjfee_levels = cjfee_levels[-len(offer_levels):]
            txfee_levels = txfee_levels[-len(offer_levels):]
        offer_ranges = zip(offer_levels, lower_bound_balances, cjfee_levels,
                           txfee_levels)
        log.debug('offer_ranges = ' + str(offer_ranges))
        offers = []
        oid = 0

        # create absoffers for mixdepth dust
        offer_levels = []
        for m in sorted_mix_balance:
            if m[1] == 0:
                continue
            #elif False: # disabled
            #elif m[1] <= 2e8:  # absoffer all mixdepths less then
            elif m[1] <= offer_lowx:
                offer = {'oid': oid,
                         'ordertype': 'absoffer',
                         'minsize': m[1],
                         'maxsize': m[1],
                         'txfee': 0,
                         'cjfee': 0}
                #'txfee': txfee_low,
                #'cjfee': min_revenue}
                oid += 1
                offers.append(offer)
            elif m[1] > offer_lowx:
                break

        for upper, lower, cjfee, txfee in offer_ranges:
            cjfee = float(cjfee)
            if cjfee == 0:
                min_needed = profit_req_per_transaction + txfee
            elif cjfee > 0:
                min_needed = int((profit_req_per_transaction + txfee + 1) / cjfee)
            elif cjfee < 0:
                sys.exit('negative fee not supported here')
            if min_needed <= lower:
                # create a regular reloffer
                offer = {'oid': oid,
                         'ordertype': 'reloffer',
                         'minsize': lower,
                         'maxsize': upper,
                         'txfee': txfee,
                         'cjfee': cjfee}
            elif min_needed > lower and min_needed < upper:
                # create two offers. An absolute for lower bound need, and reloffer for the rest
                offer = {'oid': oid,
                         'ordertype': 'absoffer',
                         'minsize': lower,
                         'maxsize': min_needed - 1,
                         'txfee': txfee,
                         'cjfee': profit_req_per_transaction + txfee}
                oid += 1
                offers.append(offer)
                offer = {'oid': oid,
                         'ordertype': 'reloffer',
                         'minsize': min_needed,
                         'maxsize': upper,
                         'txfee': txfee,
                         'cjfee': cjfee}
            elif min_needed >= upper:
                # just create an absolute offer
                offer = {'oid': oid,
                         'ordertype': 'absoffer',
                         'minsize': lower,
                         'maxsize': upper,
                         'txfee': txfee,
                         'cjfee': profit_req_per_transaction + txfee}
                # todo: combine neighboring absoffers into a single one
            oid += 1
            offers.append(offer)

        deluxe_offer_display = []
        header = 'oid'.rjust(5)
        header += 'type'.rjust(7)
        header += 'minsize btc'.rjust(15)
        header += 'maxsize btc'.rjust(15)
        header += 'min revenue satosh'.rjust(22)
        header += 'max revenue satosh'.rjust(22)
        deluxe_offer_display.append(header)
        for o in offers:
            line = str(o['oid']).rjust(5)
            if o['ordertype'] == 'absoffer':
                line += 'abs'.rjust(7)
            elif o['ordertype'] == 'reloffer':
                line += 'rel'.rjust(7)
            line += str(o['minsize'] / 1e8).rjust(15)
            line += str(o['maxsize'] / 1e8).rjust(15)
            if o['ordertype'] == 'absoffer':
                line += str(o['cjfee']).rjust(22)
            elif o['ordertype'] == 'reloffer':
                line += str(int(float(o['cjfee']) * int(o['minsize']))).rjust(
                    22)
                line += str(int(float(o['cjfee']) * int(o['maxsize']))).rjust(
                    22)
            deluxe_offer_display.append(line)

        log.debug('deluxe offer display = \n' + '\n'.join([str(
            x) for x in deluxe_offer_display]))

        log.debug('generated offers = \n' + '\n'.join([str(o) for o in offers]))

        # sanity check
        for offer in offers:
            assert offer['minsize'] >= 0
            assert offer['maxsize'] > 0
            assert offer['minsize'] <= offer['maxsize']

        return offers

    def oid_to_order(self, cjorder, oid, amount):
        '''Coins rotate circularly from max mixdepth back to mixdepth 0'''
        mix_balance = self.wallet.get_balance_by_mixdepth()
        total_amount = amount + cjorder.txfee
        log.debug('amount, txfee, total_amount = ' + str(amount) + str(
            cjorder.txfee) + str(total_amount))

        # look for exact amount available with no change
        filtered_mix_balance = [m
                                for m in mix_balance.iteritems()
                                if m[1] == total_amount]
        if filtered_mix_balance:
            log.debug('mix depths that have the exact amount needed = ' + str(
                filtered_mix_balance))
        else:
            log.debug('no mix depths contain the exact amount needed.')
            filtered_mix_balance = [m
                                    for m in mix_balance.iteritems()
                                    if m[1] >= total_amount]
            log.debug('mix depths that have enough = ' + str(
                filtered_mix_balance))
            filtered_mix_balance = [m
                                    for m in mix_balance.iteritems()
                                    if m[1] >= total_amount + min_output_size]
            log.debug('mix depths that have enough with min_output_size, ' +
                      str(filtered_mix_balance))
            try:
                len(filtered_mix_balance) > 0
            except Exception:
                log.debug('No mix depths have enough funds to cover the ' +
                          'amount, cjfee, and min_output_size.')
                return None, None, None

        # prioritize by mixdepths sequencially
        # keep coins moving towards last mixdepth, clumps once they get there
        # makes sure coins sent to mixdepth 0 will get mixed to max mixdepth
        filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[0])

        # clumping. push all coins towards the largest mixdepth
        # the largest amount of coins are available to join with (since joins always come from a single depth)
        # the maker commands a higher fee for the larger amounts 
        # order ascending but circularly with largest last
        # note, no need to consider max_offer_size here
        #largest_mixdepth = sorted(
        #    filtered_mix_balance,
        #    key=lambda x: x[1],)[-1]  # find largest amount
        #smb = sorted(filtered_mix_balance,
        #             key=lambda x: x[0])  # seq of mixdepth num
        #next_index = smb.index(largest_mixdepth) + 1
        #mmd = self.wallet.max_mix_depth
        #filtered_mix_balance = smb[next_index % mmd:] + smb[:next_index % mmd]

        # use mix depth that has the closest amount of coins to what this transaction needs
        # keeps coins moving through mix depths more quickly
        # and its more likely to use txos of a similiar size to this transaction
        # sort smallest to largest usable amount
        #filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[1])

        # use mix depth with the most coins, 
        # creates a more even distribution across mix depths
        # and a more diverse txo selection in each depth
        # sort largest to smallest amount
        #filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[1], reverse=True)

        # use a random usable mixdepth. 
        # warning, could expose more txos to malicous taker requests
        #filtered_mix_balance = random.choice(filtered_mix_balance)

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
        if change_value <= min_output_size:
            log.debug('change value=%d below dust threshold, finding new utxos'
                      % (change_value))
            try:
                utxos = self.wallet.select_utxos(mixdepth,
                                                 total_amount + min_output_size)
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
