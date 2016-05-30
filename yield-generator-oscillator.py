#! /usr/bin/env python
from __future__ import absolute_import, print_function

import os
import sys
import datetime
import time
import random
import decimal
import ConfigParser
import csv
import threading
import copy

from joinmarket import Maker, IRCMessageChannel, OrderbookWatch
from joinmarket import blockchaininterface, BlockrInterface
from joinmarket import jm_single, get_network, load_program_config
from joinmarket import random_nick
from joinmarket import get_log, calc_cj_fee, debug_dump_object
from joinmarket import Wallet

config = ConfigParser.RawConfigParser()
config.read('joinmarket.cfg')
mix_levels = 5
nickname = random_nick()
nickserv_password = ''

# EXPLANATION
# It watches your own transaction volume, and raises or lowers prices based
# on how many transactions you are getting.
# Price ranges that arent getting used will stay cheap,
# while frequently used price ranges will raise themselves in price.
# 
# CONFIGURATION
# starting size: offer amount in btc
# price floor: cjfee in satoshis
# price increment: increase your cjfee by this much per tranaction 
# time frame: Transaction count is within this window. This is how long it 
#             takes to drop to the price floor if there have been no 
#             transactions.  A short window is more aggressive at dropping
#             fees, while a large window holds prices up longer. 
# type: absolute or relative

offer_levels = (
    {'starting_size': 0,
     'type': 'absolute',
     'price_floor': 2000,
     'price_increment': 1000,  # satoshis
     'price_ceiling': None,
     'time_frame': 7 * 24,
    },
    {'starting_size': 1,
     'type': 'absolute',
     'price_floor': 3000,
     'price_increment': 1.25,  # 25%
     'price_ceiling': None,
     'time_frame': 7 * 24,
    },
    {'starting_size': 10,
     'type': 'relative',
     'price_floor': 5000,  # type is relative, so 0.00005000
     'price_increment': 1.618,  # 61.8% is the fibonacci sequence/golden ratio
     'price_ceiling': None,
     'time_frame': 7 * 24,
    },
)

# Here are randomizers you can use in your offers.
#'starting_size': random.uniform(0.9, 1),
#'starting_size': random.uniform(9, 10),
#'price_floor': random.randrange(1900, 2100),
#'price_floor': int(1000 * random.uniform(0.9, 1.1)),
#'price_increment': int(1000 * random.uniform(0.9, 1.1)),
#'type': random.choice(['absolute','relative']),
#'time_frame': random.randrange(6, 10) * 24,

# tip: you can create a file called myoscoffers.py with your offer_levels in it.
# tip: view your csv file in unix with 'column -s, -t < yigen-statement-myfile.csv'

# optional, for use in your joinmarket.cfg
"""
[YIELDGEN]
# Make your offer size never go above or below an amount
# offer low, default is output_size_min
# offer high, default is largest mix depth
# minimum output size, default is dust threshold 2730 satoshis
# multiple values means set randomly within that range
offer_low = 25000, 65000
offer_high = 10e8, 14e8  
output_size_min = 10000
"""

#END CONFIGURATION

try:
    wallet_file = sys.argv[1]
    statement_file = os.path.join(
        'logs', 'yigen-statement-' + wallet_file[:-5] + '.csv')
except:
    sys.exit("You forgot to specify the wallet file.")

try:
    from myoscoffers import offer_levels
except:
    pass

try:
    x = config.get('YIELDGEN', 'offer_low')
    x = [r for r in csv.reader([x], skipinitialspace=True)][0]
    if len(x) == 1:
        offer_low = int(float(x[0]))
    elif len(x) == 2:
        offer_low = random.randrange(
            int(float(x[0])), int(float(x[1])))  #random
    elif len(x) > 2:
        assert False
except (ConfigParser.NoOptionError, ConfigParser.NoSectionError) as e:
    offer_low = None  # will use output_min_size

try:
    x = config.get('YIELDGEN', 'offer_high')
    x = [r for r in csv.reader([x], skipinitialspace=True)][0]
    if len(x) == 1:
        offer_high = int(float(x[0]))
    elif len(x) == 2:
        offer_high = random.randrange(
            int(float(x[0])), int(float(x[1])))  #random
    elif len(x) > 2:
        assert False
except (ConfigParser.NoOptionError, ConfigParser.NoSectionError) as e:
    offer_high = None  # max mix depth will be used

try:
    x = config.get('YIELDGEN', 'output_size_min')
    x = [r for r in csv.reader([x], skipinitialspace=True)][0]
    if len(x) == 1:
        output_size_min = int(float(x[0]))
    elif len(x) == 2:
        output_size_min = random.randrange(
            int(float(x[0])), int(float(x[1])))  #random
    elif len(x) > 2:
        assert False
except (ConfigParser.NoOptionError, ConfigParser.NoSectionError) as e:
    output_size_min = jm_single().DUST_THRESHOLD

# the above config parser code could be moved into a library for reuse

log = get_log()
log.debug("  ____           _ _ _       _             ")
log.debug(" / __ \         (_) | |     | |            ")
log.debug("| |  | |___  ___ _| | | __ _| |_ ___  _ __ ")
log.debug("| |  | / __|/ __| | | |/ _` | __/ _ \| '__|")
log.debug("| |__| \__ \ (__| | | | (_| | || (_) | |   ")
log.debug(" \____/|___/\___|_|_|_|\__,_|\__\___/|_|   ")
log.debug(random.choice(["     yield generator for the civilized",
                         "     the best yield generator there is",
                         "     oscillator oscillator up and down"]))
if offer_low:
    log.debug('offer_low = ' + str(offer_low) + " (" + str(offer_low / 1e8) +
              " btc)")
if offer_high:
    log.debug('offer_high = ' + str(offer_high) + " (" + str(offer_high / 1e8) +
              " btc)")
else:
    log.debug('offer_high = Max Mix Depth')
if output_size_min != jm_single().DUST_THRESHOLD:
    log.debug('output_size_min = ' + str(output_size_min) + " (" + str(
        output_size_min / 1e8) + " btc)")


def sanity_check(offers):
    for offer in offers:
        if offer['ordertype'] == 'absorder':
            assert isinstance(offer['cjfee'], int)
        elif offer['ordertype'] == 'relorder':
            assert isinstance(offer['cjfee'], int) or isinstance(offer['cjfee'],
                                                                 float)
        assert offer['maxsize'] > 0
        assert offer['minsize'] > 0
        assert offer['minsize'] <= offer['maxsize']
        assert offer['txfee'] >= 0
        if offer_high:
            assert offer['maxsize'] <= offer_high
        assert (isinstance(offer['minsize'], int) or isinstance(offer['minsize'], long))
        assert (isinstance(offer['maxsize'], int) or isinstance(offer['maxsize'], long))
        assert isinstance(offer['txfee'], int)
        assert offer['minsize'] >= offer_low
        if offer['ordertype'] == 'absorder':
            profit_max = offer['cjfee'] - offer['txfee']
        elif offer['ordertype'] == 'relorder':
            profit_min = int(float(offer['cjfee']) *
                             offer['minsize']) - offer['txfee']
            profit_max = int(float(offer['cjfee']) *
                             offer['maxsize']) - offer['txfee']
            assert profit_min >= 0
        assert profit_max >= 0


def offer_data_chart(offers):
    has_rel = False
    for offer in offers:
        if offer['ordertype'] == 'relorder':
            has_rel = True
    offer_display = []
    header = 'oid'.rjust(4)
    header += 'type'.rjust(5)
    header += 'cjfee'.rjust(12)
    header += 'minsize btc'.rjust(15)
    header += 'maxsize btc'.rjust(15)
    header += 'txfee'.rjust(7)
    if has_rel:
        header += 'minrev'.rjust(11)
        header += 'maxrev'.rjust(11)
        header += 'minprof'.rjust(11)
        header += 'maxprof'.rjust(11)
    else:
        header += 'rev'.rjust(11)
        header += 'prof'.rjust(11)
    offer_display.append(header)
    for offer in offers:
        oid = str(offer['oid'])
        if offer['ordertype'] == 'absorder':
            ot = 'abs'
            cjfee = str(offer['cjfee'])
            minrev = '-'
            maxrev = offer['cjfee']
            minprof = '-'
            maxprof = int(maxrev - offer['txfee'])
        elif offer['ordertype'] == 'relorder':
            ot = 'rel'
            cjfee = str('%.8f' % (offer['cjfee'] * 100))
            minrev = str(int(offer['cjfee'] * offer['minsize']))
            maxrev = str(int(offer['cjfee'] * offer['maxsize']))
            minprof = int(minrev) - offer['txfee']
            maxprof = int(maxrev) - offer['txfee']
        line = oid.rjust(4)
        line += ot.rjust(5)
        line += cjfee.rjust(12)
        line += str('%.8f' % (offer['minsize'] / 1e8)).rjust(15)
        line += str('%.8f' % (offer['maxsize'] / 1e8)).rjust(15)
        line += str(offer['txfee']).rjust(7)
        if has_rel:
            line += str(minrev).rjust(11)
            line += str(maxrev).rjust(11)
            line += str(minprof).rjust(11)  # minprof
            line += str(maxprof).rjust(11)  # maxprof
        else:
            line += str(maxrev).rjust(11)
            line += str(maxprof).rjust(11)  # maxprof
        offer_display.append(line)
    return offer_display


def get_recent_transactions(time_frame, show=False):
    if not os.path.isfile(statement_file):
        return []
    reader = csv.reader(open(statement_file, 'r'))
    rows = []
    for row in reader:
        rows.append(row)
    rows = rows[1:]  # remove heading
    rows.reverse()
    rows = sorted(rows, reverse=True)  # just to be sure
    xrows = []
    display_lines = []
    amount_total, earned_total = 0, 0
    for row in rows:
        try:
            timestamp = datetime.datetime.strptime(row[0], '%Y/%m/%d %H:%M:%S')
            if timestamp < (datetime.datetime.now() - datetime.timedelta(
                    hours=time_frame)):
                break
            amount = int(row[1])
            my_input_count = int(row[2])
            my_input_value = int(row[3])
            cjfee = int(row[4])  # before txfee contrib
            cjfee_earned = int(row[5])
            confirm_time = float(row[6])
        except ValueError:
            continue
        effective_rate = float('%.10f' % (cjfee_earned / float(amount)))  # /0?
        amount_total += amount
        earned_total += cjfee_earned
        xrows.append({'timestamp': timestamp,
                      'amount': amount,
                      'cjfee_earned': cjfee_earned,
                      'confirm_time': confirm_time,})
        display_str = ' ' + timestamp.strftime("%Y-%m-%d %I:%M:%S %p")
        display_str += str(float(confirm_time)).rjust(13)
        display_str += str('%.8f' % (int(amount) / 1e8)).rjust(14)
        display_str += str(int(cjfee_earned)).rjust(13)
        display_str += str(('%.8f' % effective_rate) + ' %').rjust(16)
        display_lines.append(display_str)

    if show and display_lines:
        display = [
            ' datetime                confirm min    amount btc   earned sat   effectiverate'
        ]
        display = display + display_lines
        display.append('-------------------------------------------'.rjust(79))
        total_effective_rate = float('%.10f' %
                                     (earned_total / float(amount_total)))
        ter_str = str(('%.8f' % total_effective_rate) + ' %').rjust(16)
        display.append('Totals:'.rjust(36) + str('%.8f' % (
            amount_total / 1e8)).rjust(14) + str(earned_total).rjust(13) +
                       ter_str)
        time_frame_days = time_frame / 24.0
        log.debug(str(len(xrows)) + ' transactions in the last ' + str(
            time_frame) + ' hours: \n' + '\n'.join([str(x) for x in display]))
        #log.debug(str(len(xrows)) + ' transactions in the last ' + str(
        #    time_frame) + ' hours (' + str(time_frame_days) + ' days) = \n' +
        #          '\n'.join([str(x) for x in display]))
    elif show:
        log.debug('No transactions in the last ' + str(time_frame) + ' hours.')
    return xrows


def create_oscillator_offers(largest_mixdepth_size, sorted_mix_balance):
    offer_lowx = max(offer_low, output_size_min)
    if offer_high:
        offer_highx = min(offer_high, largest_mixdepth_size - output_size_min)
    else:
        offer_highx = largest_mixdepth_size - output_size_min
    offers = []
    display_lines = []
    oid = 0
    count = 0
    for offer in offer_levels:
        count += 1
        lower = int(offer['starting_size'] * 1e8)
        if lower < offer_lowx:
            lower = offer_lowx
        if count <= len(offer_levels) - 1:
            upper = int((offer_levels[count]['starting_size'] * 1e8) - 1)
            if upper > offer_highx:
                upper = offer_highx
        else:
            upper = offer_highx
        if lower > upper:
            continue
        fit_txs = []
        for tx in get_recent_transactions(offer['time_frame'], show=False):
            if tx['amount'] >= lower and tx['amount'] <= upper:
                fit_txs.append(tx)
        amounts, earnings = [], []
        size_avg, earn_avg, effective_rate = 0, 0, 0
        if fit_txs:
            amounts = [x['amount'] for x in fit_txs]
            earnings = [x['cjfee_earned'] for x in fit_txs]
            size_avg = sum(amounts) / len(amounts)
            earn_avg = sum(earnings) / len(earnings)
            effective_rate = float('%.10f' %
                                   (sum(earnings) / float(sum(amounts))))  # /0?
        if isinstance(offer['price_increment'], int):
            tpi = offer['price_increment'] * len(fit_txs)
            cjfee = offer['price_floor'] + tpi
        elif isinstance(offer['price_increment'], float):
            tpi = offer['price_increment']**len(fit_txs)
            cjfee = int(round(offer['price_floor'] * tpi))
        else:
            sys.exit('bad price_increment: ' + str(offer['price_increment']))
        if offer['price_ceiling'] and cjfee > offer['price_ceiling']:
            cjfee = offer['price_ceiling']
        assert offer['type'] in ('absolute', 'relative')
        if offer['type'] == 'absolute':
            ordertype = 'absorder'
        elif offer['type'] == 'relative':
            ordertype = 'relorder'
            cjfee = float('%.10f' % (cjfee / 1e10))
        oid += 1
        offerx = {'oid': oid,
                  'ordertype': ordertype,
                  'minsize': lower,
                  'maxsize': upper,
                  'txfee': 0,
                  'cjfee': cjfee}
        offers.append(offerx)
        display_line = ''
        display_line += str('%.8f' % (lower / 1e8)).rjust(15)
        display_line += str('%.8f' % (upper / 1e8)).rjust(15)
        display_line += str(offer['time_frame']).rjust(8)
        display_line += str(len(fit_txs)).rjust(8)
        display_line += str('%.8f' % (size_avg / 1e8)).rjust(15)
        display_line += str(earn_avg).rjust(10)
        display_line += str('%.8f' % (sum(amounts) / 1e8)).rjust(15)
        display_line += str(sum(earnings)).rjust(10)
        display_line += str('%.8f' % effective_rate).rjust(13) + ' %'
        display_lines.append(display_line)
    newoffers = []
    for offer in offers:
        if not newoffers:
            newoffers.append(offer)
            continue
        last_offer = copy.deepcopy(newoffers[-1])
        if (offer['minsize'] == last_offer['maxsize'] or \
            offer['minsize'] == last_offer['maxsize'] + 1) and \
            offer['cjfee'] == last_offer['cjfee']:
            assert offer['txfee'] == last_offer['txfee']
            newoffers = newoffers[:-1]
            last_offer['maxsize'] = offer['maxsize']
            newoffers.append(last_offer)
        else:
            newoffers.append(offer)
    get_recent_transactions(24, show=True)
    display = ['-------averages-------   --------totals--------'.rjust(93)]
    display.append(
        '    minsize btc    maxsize btc   hours     txs       size btc  ' +
        'earn sat       size btc  earn sat  effectiverate')
    log.debug('range summaries: \n' + '\n'.join([str(
        x) for x in display + display_lines]))
    log.debug('offer data chart: \n' + '\n'.join([str(
        x) for x in offer_data_chart(offers)]))
    if offers != newoffers:
        #oid = 1
        #for offer in newoffers:
        #    offer['oid'] = oid
        #    oid += 1
        log.debug('final compressed offer data chart: \n' + '\n'.join([str(
            x) for x in offer_data_chart(newoffers)]))
    #log.debug('oscillator offers = \n' + '\n'.join([str(x) for x in offers]))
    #log.debug('oscillator offers compressed = \n' + '\n'.join([str(
    #    o) for o in newoffers]))
    return newoffers


class YieldGenerator(Maker, OrderbookWatch):

    def __init__(self, msgchan, wallet):
        Maker.__init__(self, msgchan, wallet)
        self.msgchan.register_channel_callbacks(self.on_welcome,
                                                self.on_set_topic, None, None,
                                                self.on_nick_leave, None)
        self.tx_unconfirm_timestamp = {}

    def on_welcome(self):
        Maker.on_welcome(self)
        if not os.path.isfile(statement_file):
            log.debug('Creating ' + str(statement_file))
            self.log_statement(
                ['timestamp', 'cj amount/satoshi', 'my input count',
                 'my input value/satoshi', 'cjfee/satoshi', 'earned/satoshi',
                 'confirm time/min', 'notes'])
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.log_statement([timestamp, '', '', '', '', '', '', 'Connected'])

    def create_my_orders(self):
        mix_balance = self.wallet.get_balance_by_mixdepth()
        log.debug('mix_balance = ' + str(mix_balance))
        total_balance = 0
        for num, amount in mix_balance.iteritems():
            log.debug('for mixdepth=%d balance=%.8fbtc' % (num, amount / 1e8))
            total_balance += amount
        log.debug('total balance = %.8fbtc' % (total_balance / 1e8))
        sorted_mix_balance = sorted(
            list(mix_balance.iteritems()),
            key=lambda a: a[1])  #sort by size
        largest_mixdepth_size = sorted_mix_balance[-1][1]
        if largest_mixdepth_size == 0:
            print("ALERT: not enough funds available in wallet")
            return []
        offers = create_oscillator_offers(largest_mixdepth_size,
                                          sorted_mix_balance)
        #log.debug('offer_data_chart = \n' + '\n'.join([str(
        #    x) for x in offer_data_chart(offers)]))
        sanity_check(offers)
        #log.debug('offers len = ' + str(len(offers)))
        #log.debug('generated offers = \n' + '\n'.join([str(o) for o in offers]))
        return offers

    def oid_to_order(self, cjorder, oid, amount):
        '''Coins rotate circularly from max mixdepth back to mixdepth 0'''
        mix_balance = self.wallet.get_balance_by_mixdepth()
        total_amount = amount + cjorder.txfee
        log.debug('amount, txfee, total_amount = ' + str(amount) + str(
            cjorder.txfee) + str(total_amount))

        # look for exact amount available with no change
        # not supported because change output required
        # needs this fixed https://github.com/JoinMarket-Org/joinmarket/issues/418
        #filtered_mix_balance = [m
        #                        for m in mix_balance.iteritems()
        #                        if m[1] == total_amount]
        #if filtered_mix_balance:
        #    log.debug('mix depths that have the exact amount needed = ' + str(
        #        filtered_mix_balance))
        #else:
        #    log.debug('no mix depths contain the exact amount needed.')

        filtered_mix_balance = [m
                                for m in mix_balance.iteritems()
                                if m[1] >= (total_amount)]
        log.debug('mix depths that have enough = ' + str(filtered_mix_balance))
        filtered_mix_balance = [m
                                for m in mix_balance.iteritems()
                                if m[1] >= total_amount + output_size_min]
        log.debug('mix depths that have enough with output_size_min, ' + str(
            filtered_mix_balance))
        try:
            len(filtered_mix_balance) > 0
        except Exception:
            log.debug('No mix depths have enough funds to cover the ' +
                      'amount, cjfee, and output_size_min.')
            return None, None, None

        # slinky clumping: push all coins towards the largest mixdepth,
        # then spend from the largest mixdepth into the next mixdepth.
        # the coins stay in the next mixdepth until they are all there,
        # and then get spent into the next mixdepth, ad infinitum.
        lmd = sorted(filtered_mix_balance, key=lambda x: x[1],)[-1]
        smb = sorted(filtered_mix_balance, key=lambda x: x[0])  # seq of md num
        mmd = self.wallet.max_mix_depth
        nmd = (lmd[0] + 1) % mmd
        if nmd not in [x[0] for x in smb]:  # use all usable
            next_si = (smb.index(lmd) + 1) % len(smb)
            filtered_mix_balance = smb[next_si:] + smb[:next_si]
        else:
            nmd = [x for x in smb if x[0] == nmd][0]
            others = [x for x in smb if x != nmd and x != lmd]
            if not others:  # just these two remain, prioritize largest
                filtered_mix_balance = [lmd, nmd]
            else:  # use all usable
                if [x for x in others if x[1] >= nmd[1]]:
                    next_si = (smb.index(lmd) + 1) % len(smb)
                    filtered_mix_balance = smb[next_si:] + smb[:next_si]
                else:  # others are not large, dont use nmd
                    next_si = (smb.index(lmd) + 2) % len(smb)
                    filtered_mix_balance = smb[next_si:] + smb[:next_si]

        # prioritize by mixdepths ascending
        # keep coins moving towards last mixdepth, clumps there.
        # makes sure coins sent to mixdepth 0 will get mixed to mixdepth 5
        #filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[0])

        # use mix depth with the most coins, 
        # creates a more even distribution across mix depths
        # and a more diverse txo selection in each depth
        # sort largest to smallest amount
        #filtered_mix_balance = sorted(filtered_mix_balance, key=lambda x: x[1], reverse=True)

        # use a random usable mixdepth. 
        # warning, could expose more txos to malicous taker requests
        #filtered_mix_balance = [random.choice(filtered_mix_balance)]

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
        if change_value <= output_size_min:
            log.debug('change value=%d below dust threshold, finding new utxos'
                      % (change_value))
            try:
                utxos = self.wallet.select_utxos(mixdepth,
                                                 total_amount + output_size_min)
            except Exception:
                log.debug(
                    'dont have the required UTXOs to make a output above the dust threshold, quitting')
                return None, None, None
        return utxos, cj_addr, change_addr

    def refresh_offers(self):
        cancel_orders, ann_orders = self.get_offer_diff()
        self.modify_orders(cancel_orders, ann_orders)

    def get_offer_diff(self):
        neworders = self.create_my_orders()
        oldorders = self.orderlist
        new_setdiff_old = [o for o in neworders if o not in oldorders]
        old_setdiff_new = [o for o in oldorders if o not in neworders]
        neworders = sorted(neworders, key=lambda x: x['oid'])
        oldorders = sorted(oldorders, key=lambda x: x['oid'])
        if neworders == oldorders:
            log.debug('No orders modified for ' + nickname)
            return ([], [])
        """
        if neworders:
            log.debug('neworders = \n' + '\n'.join([str(o) for o in neworders]))
        if oldorders:
            log.debug('oldorders = \n' + '\n'.join([str(o) for o in oldorders]))
        if new_setdiff_old:
            log.debug('new_setdiff_old = \n' + '\n'.join([str(
                o) for o in new_setdiff_old]))
        if old_setdiff_new:
            log.debug('old_setdiff_new = \n' + '\n'.join([str(
                o) for o in old_setdiff_new]))
        """
        ann_orders = new_setdiff_old
        ann_oids = [o['oid'] for o in ann_orders]
        cancel_orders = [o['oid']
                         for o in old_setdiff_new if o['oid'] not in ann_oids]
        """
        if cancel_orders:
            log.debug('can_orders = \n' + '\n'.join([str(o) for o in
                                                     cancel_orders]))
        if ann_orders:
            log.debug('ann_orders = \n' + '\n'.join([str(o) for o in ann_orders
                                                    ]))
        """
        return (cancel_orders, ann_orders)

    def log_statement(self, data):
        if get_network() == 'testnet':
            return
        data = [str(d) for d in data]
        log.debug('Logging to ' + str(statement_file) + ': ' + str(data))
        assert len(data) == 8
        if data[7] == 'unconfirmed':  # workaround
            # on_tx_unconfirmed is being called by on_tx_confirmed
            for row in csv.reader(open(statement_file, 'r')):
                lastrow = row
            if lastrow[1:6] == data[1:6]:
                log.debug('Skipping double csv entry, workaround.')
                pass
            else:
                fp = open(statement_file, 'a')
                fp.write(','.join(data) + '\n')
                fp.close()
        elif data[7] != '':  # 'Connected', 'notes'
            fp = open(statement_file, 'a')
            fp.write(','.join(data) + '\n')
            fp.close()
        else:  # ''
            rows = []
            for row in csv.reader(open(statement_file, 'r')):
                rows.append(row)
            fp = open(statement_file, 'w')
            for row in rows:
                if row[1:] == data[1:6] + ['0', 'unconfirmed']:
                    fp.write(','.join(data) + '\n')
                    log.debug('Found unconfirmed row, replacing.')
                else:
                    fp.write(','.join(row) + '\n')
            fp.close()

    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        my_input_value = sum([av['value'] for av in cjorder.utxos.values()])
        earned = cjorder.real_cjfee - cjorder.txfee
        self.log_statement([timestamp, cjorder.cj_amount, len(
            cjorder.utxos), my_input_value, cjorder.real_cjfee, earned, '0',
                            'unconfirmed'])
        self.refresh_offers()  # for oscillator
        return self.get_offer_diff()

    def on_tx_confirmed(self, cjorder, confirmations, txid):
        if cjorder.cj_addr in self.tx_unconfirm_timestamp:
            confirm_time = int(time.time()) - self.tx_unconfirm_timestamp[
                cjorder.cj_addr]
            confirm_time = round(confirm_time / 60.0, 2)
            del self.tx_unconfirm_timestamp[cjorder.cj_addr]
        else:
            confirm_time = 0
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        my_input_value = sum([av['value'] for av in cjorder.utxos.values()])
        earned = cjorder.real_cjfee - cjorder.txfee
        self.log_statement([timestamp, cjorder.cj_amount, len(
            cjorder.utxos), my_input_value, cjorder.real_cjfee, earned,
                            confirm_time, ''])
        return self.on_tx_unconfirmed(cjorder, txid, None)


def main():
    load_program_config()
    if isinstance(jm_single().bc_interface,
                  blockchaininterface.BlockrInterface):
        print('You are using the blockr.io website')
        print('You should setup JoinMarket with Bitcoin Core.')
        ret = raw_input('\nContinue Anyways? (y/n):')
        if ret[0] != 'y':
            return
    wallet = Wallet(wallet_file, max_mix_depth=mix_levels)
    jm_single().bc_interface.sync_wallet(wallet)
    jm_single().nickname = nickname
    log.debug('starting yield generator')
    irc = IRCMessageChannel(jm_single().nickname,
                            realname='btcint=' + jm_single().config.get(
                                "BLOCKCHAIN", "blockchain_source"),
                            password=nickserv_password)
    maker = YieldGenerator(irc, wallet)

    def timer_loop(startup=False):  # for oscillator
        if not startup:
            maker.refresh_offers()
        poss_refresh = []
        for x in offer_levels:
            recent_transactions = get_recent_transactions(x['time_frame'])
            if recent_transactions:
                oldest_transaction_time = recent_transactions[-1]['timestamp']
            else:
                oldest_transaction_time = datetime.datetime.now()
            next_refresh = oldest_transaction_time + datetime.timedelta(
                hours=x['time_frame'],
                seconds=1)
            poss_refresh.append(next_refresh)
        next_refresh = sorted(poss_refresh, key=lambda x: x)[0]
        td = next_refresh - datetime.datetime.now()
        seconds_till = (td.days * 24 * 60 * 60) + td.seconds
        log.debug('Next offer refresh for ' + nickname + ' at ' +
                  next_refresh.strftime("%Y-%m-%d %I:%M:%S %p"))
        log.debug('...or after a new transaction shows up.')
        t = threading.Timer(seconds_till, timer_loop)
        t.daemon = True
        t.start()

    timer_loop(startup=True)
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
