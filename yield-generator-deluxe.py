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

# --- global config

offer_low = None  # when None, output_size_min will be used
offer_high = None  # when None, size of largest mix depth will be used
#offer_low = random.randrange(1e6, 4e6)  #random
#offer_high = random.randrange(20 * 1e8, 30 * 1e8)

# If you want to be part of more joins, set a lower required profit.
# Negative is valid to outbid others for a small cost.

#profit_req_per_transaction = None  # disabled
#profit_req_per_btc = None  # disabled
profit_req_per_transaction = 0
profit_req_per_btc = 1
#profit_req_per_transaction = random.randrange(0, 5)
#profit_req_per_btc = random.randrange(0, 10)
#profit_req_per_transaction = random.randrange(-5000, 5000)
#profit_req_per_btc = random.randrange(-10, 10)  # negative means net loss okay

output_size_min = random.randrange(2e5, 3e5)
#output_size_min = jm_single().DUST_THRESHOLD # 546 satoshis

# ---

# Creates a spread of offers defined by the settings below.

spread_offers_enabled = True

num_offers = random.randrange(1, 12)
cjfee_spread_type = random.choice(('absolute', 'relative'))
abs_cjfee_low = random.randrange(0, 10)
abs_cjfee_high = random.randrange(5000, 10000)
rel_cjfee_low = random.uniform(1e-8, 1e-5)
rel_cjfee_high = random.uniform(1e-4, 1e-3)
txfee_low = random.randrange(0, 250)
txfee_high = random.randrange(4000, 6000)
cjfee_spread = random.choice(('fibonacci', 'evenly', 'random'))
offer_spread = random.choice(('fibonacci', 'evenly', 'random'))
txfee_spread = random.choice(('fibonacci', 'evenly', 'random'))

# -- simple static example --
#num_offers = 7
#cjfee_spread_type = 'relative'
#abs_cjfee_low = 100
#abs_cjfee_high = 10000
#rel_cjfee_low = 1e-6
#rel_cjfee_high = 1e-4
#txfee_low = 0
#txfee_high = 5000

# -- bymixdepth example -- was "new-yieldgen-algo"
#num_offers = mix_levels
#abs_cjfee_low = 100
#abs_cjfee_high = 10000
#rel_cjfee_low = 1e-6
#rel_cjfee_high = 1e-4
#txfee_low = 0
#txfee_high = 5000
#cjfee_spread = 'fibonacci'
#offer_spread = 'bymixdepth'
#txfee_spread = 'fibonacci'

# -- single offer example --
#num_offers = 1
#abs_cjfee_low = 100
#rel_cjfee_low = 1e-5
#txfee_low = 0
#abs_cjfee_high = abs_cjfee_low
#rel_cjfee_high = rel_cjfee_low
#txfee_high = txfee_low
#cjfee_spread = ''
#offer_spread = ''
#txfee_spread = ''

# -- broad possibilities testing example --
#num_offers = random.randrange(1, 12)
#abs_cjfee_low = random.randrange(-50, 50)
#abs_cjfee_high = random.randrange(-25000, 25000)
#rel_cjfee_low = random.uniform(-0.00001, 0.00001)
#rel_cjfee_high = random.uniform(-0.005, 0.005)
#txfee_low = random.randrange(0, 222)
#txfee_high = random.randrange(5555, 11111)
#cjfee_spread = random.choice(('fibonacci', 'evenly', 'random', 'custom'))
#offer_spread = random.choice(('fibonacci', 'evenly', 'random', 'custom', 'bymixdepth'))
#txfee_spread = random.choice(('fibonacci', 'evenly', 'random', 'custom'))

custom_offers = []
custom_abs_cjfees = []
custom_rel_cjfees = []
custom_txfees = []

#custom_offers = [ 1.01 * 1e8, 112345657, 1 * 1e8, 10 * 1e8, 100 * 1e8 ]
#custom_abs_cjfees = [ 1, 10, 100, 200, 500 ]
#custom_rel_cjfees = [ 0.01, 0.0123, 0.013, 0.014, 0.015 ]
#custom_txfees = [ 250, 500, 1000, 2000, 5000 ]

# ---

# Create no fee offers for sizes of ten. 1, 10, 100
powers_of_ten_offers_enabled = False

# ---

user_defined_offers_enabled = False
"""
user_defined_offers = [
    {'ordertype': 'absorder', 'oid': 0, 'minsize': 0,     'maxsize': 100000000,   'cjfee': 0,      'txfee': 0}, 
    {'ordertype': 'absorder', 'oid': 1, 'minsize': 0,     'maxsize': 1500000000,  'cjfee': 300000, 'txfee': 0}, 
    {'ordertype': 'relorder', 'oid': 2, 'minsize': 15000, 'maxsize': 100000000,   'cjfee': 0.0001, 'txfee': 0},
    {'ordertype': 'relorder', 'oid': 3, 'minsize': 15000, 'maxsize': 1000000000,  'cjfee': 0.0002, 'txfee': 0},
    {'ordertype': 'relorder', 'oid': 4, 'minsize': 15000, 'maxsize': 2500000000,  'cjfee': 0.0003, 'txfee': 0},
    ]
"""

# ---

#END CONFIGURATION

if offer_spread == 'bymixdepth':
    num_offers = mix_levels
elif offer_spread == 'custom':
    num_offers = len(custom_offers)

log = get_log()
log.debug('*GLOBAL SETTINGS')
if offer_low:
    log.debug('offer_low = ' + str(offer_low) + " (" + str(offer_low / 1e8) +
              " btc)")
if offer_high:
    log.debug('offer_high = ' + str(offer_high) + " (" + str(offer_high / 1e8) +
              " btc)")
log.debug('profit_req_per_transaction = ' + str(profit_req_per_transaction))
log.debug('profit_req_per_btc = ' + str(profit_req_per_btc))
log.debug('output_size_min = ' + str(output_size_min) + " (" + str(
    output_size_min / 1e8) + " btc)")

output_size_min = int(output_size_min)

if powers_of_ten_offers_enabled:
    log.debug('')
    log.debug('*POWERS OF TEN OFFERS enabled')
if user_defined_offers_enabled:
    log.debug('')
    log.debug('*USER DEFINED OFFERS enabled')
if spread_offers_enabled:
    log.debug('')
    log.debug('*SPREAD OFFERS enabled')
    assert num_offers > 0
    log.debug('num_offers = ' + str(num_offers))
    log.debug('cjfee_spread_type = ' + str(cjfee_spread_type))
    if cjfee_spread_type == 'absolute':
        log.debug('abs_cjfee_low  = ' + str(abs_cjfee_low))
        log.debug('abs_cjfee_high = ' + str(abs_cjfee_high))
        log.debug('cjfee_spread = ' + str(cjfee_spread))
    elif cjfee_spread_type == 'relative':
        rel_cjfee_low = float("{0:.8f}".format(rel_cjfee_low))
        rel_cjfee_high = float("{0:.8f}".format(rel_cjfee_high))
        log.debug('rel_cjfee_low  = ' + str('%.8f' % rel_cjfee_low))
        log.debug('rel_cjfee_high = ' + str('%.8f' % rel_cjfee_high))
        log.debug('cjfee_spread = ' + str(cjfee_spread))
    log.debug('offer_spread = ' + str(offer_spread))
    log.debug('txfee_spread = ' + str(txfee_spread))
    log.debug('txfee_low = ' + str(txfee_low))
    log.debug('txfee_high = ' + str(txfee_high))


def get_profit_reqx(size):
    if profit_req_per_btc == None and profit_req_per_transaction == None:
        return -50000  # last resort safe limit
    elif profit_req_per_btc == None:
        return profit_req_per_transaction
    else:
        return max(profit_req_per_transaction,
                   int(profit_req_per_btc / 1e8 * size))


def calc_est_cost(offer):
    if offer['ordertype'] == 'absorder':
        profit = offer['cjfee']
    elif offer['ordertype'] == 'relorder':
        if offer['cjfee'] == 0:
            profit = 0
        elif offer['cjfee'] > 0:
            profit = (float(offer['cjfee']) * offer['minsize'])
        elif offer['cjfee'] < 0:
            profit = (float(offer['cjfee']) * offer['maxsize'])
    profit = int(profit)
    profit -= offer['txfee']
    return profit


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
    #log.debug("fib_sec: " + str(fib_sec))
    for y in range(2, (num + 1)):
        x.append(low + (fib_sec * fib(y)))
        #log.debug("y: " + str(y))
        #log.debug("fib(y): " + str(fib(y)))
        #log.debug("new: " + str(x[-1:]))
    return x


# range function for decimals
def drange(start, stop, step):
    r = start
    while r < stop:
        yield r
        r += step
    yield stop


def offer_data_chart(offers):
    offer_display = []
    header = 'oid'.rjust(4)
    header += 'type'.rjust(5)
    header += 'cjfee'.rjust(12)
    header += 'minsize btc'.rjust(15)
    header += 'maxsize btc'.rjust(15)
    header += 'txfee'.rjust(7)
    header += 'minrev'.rjust(11)
    header += 'maxrev'.rjust(11)
    header += 'minprof'.rjust(11)
    header += 'maxprof'.rjust(11)
    header += 'minreqprof'.rjust(11)
    header += 'maxreqprof'.rjust(11)
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
            minreqprof = '-'
            maxreqprof = get_profit_reqx(offer['maxsize'])
        elif offer['ordertype'] == 'relorder':
            ot = 'rel'
            cjfee = str('%.8f' % (offer['cjfee'] * 100))
            offer['cjfee'] = float(offer['cjfee'])  # are these type
            offer['minsize'] = int(offer['minsize'])  # conversions
            offer['maxsize'] = int(offer['maxsize'])  # necessary?
            minrev = str(int(offer['cjfee'] * offer['minsize']))
            maxrev = str(int(offer['cjfee'] * offer['maxsize']))
            minprof = int(minrev) - offer['txfee']
            maxprof = int(maxrev) - offer['txfee']
            minreqprof = get_profit_reqx(offer['minsize'])
            maxreqprof = get_profit_reqx(offer['maxsize'])
        if oid == 'exempt':
            line = ''.rjust(4)
        else:
            line = oid.rjust(4)
        line += ot.rjust(5)
        line += cjfee.rjust(12)
        line += str('%.8f' % (offer['minsize'] / 1e8)).rjust(15)
        line += str('%.8f' % (offer['maxsize'] / 1e8)).rjust(15)
        line += str(offer['txfee']).rjust(7)
        line += str(minrev).rjust(11)
        line += str(maxrev).rjust(11)
        line += str(minprof).rjust(11)  # minprof
        line += str(maxprof).rjust(11)  # maxprof
        if oid == 'exempt':
            line += '-'.rjust(11)
            line += '-'.rjust(11)
        else:
            line += str(minreqprof).rjust(11)  # minreqprof
            line += str(maxreqprof).rjust(11)  # maxreqprof
        offer_display.append(line)
    return offer_display


def sanity_check(offers, dust=False):
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
        assert isinstance(offer['minsize'], int)
        assert isinstance(offer['maxsize'], int)
        assert isinstance(offer['txfee'], int)
        if not dust:
            assert offer['minsize'] >= offer_low
            try:
                if offer['ordertype'] == 'absorder':
                    profit_min = '-'
                    profit_max = offer['cjfee'] - offer['txfee']
                    profit_req_min = '-'
                    profit_req_max = get_profit_reqx(offer['maxsize'])
                    assert profit_max >= profit_req_max
                elif offer['ordertype'] == 'relorder':
                    profit_min = int(float(offer['cjfee']) *
                                     offer['minsize']) - offer['txfee']
                    profit_max = int(float(offer['cjfee']) *
                                     offer['maxsize']) - offer['txfee']
                    profit_req_min = get_profit_reqx(offer['minsize'])
                    profit_req_max = get_profit_reqx(offer['maxsize'])
                    assert profit_min >= profit_req_min
                    assert profit_max >= profit_req_max
            except:
                log.debug('offer was ' + str(offer))
                log.debug('profit_min ' + str(profit_min))
                log.debug('profit_max ' + str(profit_max))
                log.debug('profit_req_min ' + str(profit_req_min))
                log.debug('profit_req_max ' + str(profit_req_max))
                sys.exit()


def create_user_defined_offers():
    for offer in user_defined_offers:
        if offer['minsize'] < offer_low:
            print("minsize below offer_low for user defined offer")
            print(str(offer))
            sys.exit()

    log.debug('user defined offers = \n' + '\n'.join([str(
        o) for o in user_defined_offers]))
    return user_defined_offers


def create_powers_of_ten_offers():
    offers = []
    count = 1
    while (count <= 15):
        size = 10**count
        if size >= offer_low and size <= offer_high:
            offers.append({'ordertype': 'absorder',
                           'oid': 'exempt',
                           'minsize': int(size),
                           'maxsize': int(size),
                           'cjfee': 0,
                           'txfee': 0,})
        count = count + 1

    log.debug('powers of ten offers = \n' + '\n'.join([str(o) for o in offers]))
    return offers


def create_spread_offers(largest_mixdepth_size, sorted_mix_balance):
    if largest_mixdepth_size <= output_size_min:
        print("ALERT: not enough funds available in wallet")
        return []

    offer_lowx = max(offer_low, output_size_min)
    if offer_high:
        offer_highx = min(offer_high, largest_mixdepth_size - output_size_min)
    else:
        offer_highx = largest_mixdepth_size - output_size_min

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
            offer_highx - first_upper_bound) / max(1, (num_offers - 1))))
        offer_levels = offer_levels[0:(num_offers - 1)] + [offer_highx]
    elif offer_spread == 'random' or offer_spread == '':
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
                continue
            elif m[1] > offer_highx:
                offer_levels += [offer_highx]
                break
            else:
                offer_levels += [m[1]]
        # note, offer_levels len can be less then num_offers here
    elif offer_spread == 'custom':
        offer_levels = [
            int((decimal.Decimal(str(x))).quantize(0))
            for x in sorted(custom_offers)
        ]
        if offer_levels[-1] > offer_highx:
            log.debug('ALERT: Your custom offers exceeds you max offer size.')
            log.debug('offer = ' + str(offer_levels[-1]) + ' offer_highx = ' +
                      str(offer_highx))
            sys.exit(0)
    else:
        log.debug('invalid offer_spread = ' + str(offer_spread))
        sys.exit(0)
    log.debug('offer_levels = ' + str(offer_levels))

    # CJFees
    if cjfee_spread_type == 'absolute':
        cjfee_lowx = abs_cjfee_low
        cjfee_highx = abs_cjfee_high
        if cjfee_lowx == cjfee_highx:
            cjfee_levels = [cjfee_lowx for n in range(num_offers)]
        elif cjfee_spread == 'fibonacci':
            cjfee_levels = fib_seq(cjfee_lowx, cjfee_highx, num_offers)
            cjfee_levels = [int(round(x)) for x in cjfee_levels]
        elif cjfee_spread == 'evenly':
            cjfee_levels = list(range(cjfee_lowx, cjfee_highx, (
                cjfee_highx - cjfee_lowx) / max(1, (num_offers - 1))))
            cjfee_levels = cjfee_levels[0:(num_offers - 1)] + [cjfee_highx]
        elif cjfee_spread == 'random' or cjfee_spread == '':
            if cjfee_lowx < cjfee_highx:
                cjfee_levels = sorted([random.randrange(cjfee_lowx, cjfee_highx)
                                       for n in range(num_offers)])
            elif cjfee_lowx > cjfee_highx:
                cjfee_levels = sorted(
                    [random.randrange(cjfee_highx, cjfee_lowx)
                     for n in range(num_offers)],
                    reverse=True)
        elif cjfee_spread == 'custom':
            cjfee_levels = custom_abs_cjfees
            if len(cjfee_levels) == num_offers:
                pass
            elif len(cjfee_levels) < num_offers:
                leftout = num_offers - len(cjfee_levels)
                while leftout > 0:
                    log.debug('cjfee_custom has too few items, appending')
                    log.debug('cjfee_levels: ' + str(cjfee_levels))
                    cjfee_levels.append(cjfee_levels[-1])
                    leftout -= 1
            elif len(cjfee_levels) > num_offers:
                cjfee_levels = cjfee_levels[-num_offers:]
        else:
            log.debug('invalid cjfee_spread = ' + str(cjfee_spread))
            sys.exit(0)
    elif cjfee_spread_type == 'relative':
        cjfee_lowx = decimal.Decimal(str(rel_cjfee_low)) / 100
        cjfee_highx = decimal.Decimal(str(rel_cjfee_high)) / 100
        if cjfee_lowx == cjfee_highx:
            cjfee_levels = [cjfee_lowx for n in range(num_offers)]
        elif cjfee_spread == 'fibonacci':
            cjfee_levels = fib_seq(cjfee_lowx, cjfee_highx, num_offers)
        elif cjfee_spread == 'evenly':
            cjfee_levels = drange(cjfee_lowx, cjfee_highx, (
                cjfee_highx - cjfee_lowx) / max(1, (num_offers - 1)))
        elif cjfee_spread == 'random' or cjfee_spread == '':
            if cjfee_lowx < cjfee_highx:
                cjfee_levels = sorted([random.uniform(
                    float(cjfee_lowx), float(cjfee_highx))
                                       for n in range(num_offers)])
            elif cjfee_lowx > cjfee_highx:
                cjfee_levels = sorted(
                    [random.uniform(
                        float(cjfee_lowx), float(cjfee_highx))
                     for n in range(num_offers)],
                    reverse=True)
        elif cjfee_spread == 'custom':
            cjfee_levels = [float(decimal.Decimal(str(x)) / 100)
                            for x in custom_rel_cjfees]
            if len(cjfee_levels) == num_offers:
                pass
            elif len(cjfee_levels) < num_offers:
                leftout = num_offers - len(cjfee_levels)
                while leftout > 0:
                    log.debug('cjfee_custom has too few items, appending')
                    log.debug('cjfee_levels: ' + str(cjfee_levels))
                    cjfee_levels.append(cjfee_levels[-1])
                    leftout -= 1
            elif len(cjfee_levels) > num_offers:
                cjfee_levels = cjfee_levels[-num_offers:]
        else:
            log.debug('invalid cjfee_spread = ' + str(cjfee_spread))
            sys.exit(0)
        cjfee_levels = ["%0.10f" % x for x in cjfee_levels]
        cjfee_levels = [float(x) for x in cjfee_levels]
    log.debug('cjfee_levels = ' + str(cjfee_levels))

    # TXFees
    if txfee_low == txfee_high:
        txfee_levels = [txfee_low for n in range(num_offers)]
    elif txfee_spread == 'fibonacci':
        txfee_levels = fib_seq(txfee_low, txfee_high, num_offers)
        txfee_levels = [int(round(x)) for x in txfee_levels]
    elif txfee_spread == 'evenly':
        txfee_levels = list(range(txfee_low, txfee_high, (
            txfee_high - txfee_low) / max(1, (num_offers - 1))))
        txfee_levels = txfee_levels[0:(num_offers - 1)] + [txfee_high]
    elif txfee_spread == 'random' or txfee_spread == '':
        if txfee_low < txfee_high:
            txfee_levels = sorted([random.randrange(txfee_low, txfee_high)
                                   for n in range(num_offers - 1)] +
                                  [random.randrange(txfee_high - (
                                      txfee_high / num_offers), txfee_high)])
        elif txfee_low > txfee_high:
            txfee_levels = sorted(
                [random.randrange(txfee_low, txfee_high)
                 for n in range(num_offers - 1)] + [random.randrange(
                     txfee_high - (txfee_high / num_offers), txfee_high)],
                reverse=True)
    elif txfee_spread == 'custom':
        txfee_levels = [x for x in custom_txfees]
        if len(txfee_levels) == num_offers:
            pass
        elif len(txfee_levels) < num_offers:
            leftout = num_offers - len(txfee_levels)
            while leftout > 0:
                log.debug('txfee_custom has too few items, appending')
                log.debug('txfee_levels: ' + str(txfee_levels))
                txfee_levels.append(txfee_levels[-1])
                leftout -= 1
        elif len(txfee_levels) > num_offers:
            txfee_levels = txfee_levels[-num_offers:]
    else:
        log.debug('invalid txfee_spread = ' + str(txfee_spread))
        sys.exit(0)
    log.debug('txfee_levels = ' + str(txfee_levels))

    lower_bound_balances = [offer_lowx] + [x for x in offer_levels[:-1]]
    if offer_spread == 'bymixdepth':
        cjfee_levels = cjfee_levels[-len(offer_levels):]
        txfee_levels = txfee_levels[-len(offer_levels):]
    offer_ranges = zip(offer_levels, lower_bound_balances, cjfee_levels,
                       txfee_levels)
    log.debug('offer_ranges = ' + str(offer_ranges))
    offers = []
    oid = 0
    for upper, lower, cjfee, txfee in offer_ranges:
        if cjfee_spread_type == 'absolute':
            ordertype = 'absorder'
            profit = cjfee - txfee
            profit_reqx = get_profit_reqx(upper)
            if profit < profit_reqx:
                log.debug('oid ' + str(oid) + ' below profit_req ' + str(
                    profit_reqx))
                if txfee > 0:
                    log.debug('reducing txfee from ' + str(txfee))
                    txfee = -(profit_reqx - cjfee)
                    if txfee < 0:
                        log.debug('cant make txfee ' + str(txfee))
                        txfee = 0
                    log.debug('reduced txfee to ' + str(txfee))
                if cjfee - txfee < profit_reqx:
                    log.debug('changing cjfee from ' + str(cjfee))
                    cjfee = profit_reqx
                    log.debug('changed cjfee to ' + str(cjfee))
        elif cjfee_spread_type == 'relative':
            ordertype = 'relorder'
            for size in (lower, upper):
                profit = int(cjfee * size) - txfee
                profit_reqx = get_profit_reqx(size)
                if profit < profit_reqx:
                    log.debug('oid ' + str(oid) + ' below profit_req ' + str(
                        profit_reqx))
                    if txfee > 0:
                        log.debug('reducing txfee from ' + str(txfee))
                        txfee = -(profit_reqx - int(cjfee * size))
                        if txfee < 0:
                            log.debug('cant make txfee ' + str(txfee))
                            txfee = 0
                        log.debug('reduced txfee to ' + str(txfee))
                    if (cjfee * size) - txfee < profit_reqx:
                        log.debug('changing cjfee from ' + str('%.8f' % (cjfee *
                                                                         100)))
                        cjfee = (profit_reqx + txfee + 1) / float(size)
                        cjfee = float("%0.10f" % cjfee)
                        log.debug('changed cjfee to    ' + str('%.8f' % (cjfee *
                                                                         100)))
        offer = {'oid': oid,
                 'ordertype': ordertype,
                 'minsize': lower,
                 'maxsize': upper,
                 'txfee': txfee,
                 'cjfee': cjfee}
        oid += 1
        offers.append(offer)
    log.debug('spread offers = \n' + '\n'.join([str(o) for o in offers]))
    return offers


class YieldGenerator(Maker):
    statement_file = os.path.join('logs', 'yigen-statement.csv')

    def __init__(self, msgchan, wallet):
        Maker.__init__(self, msgchan, wallet)
        self.msgchan.register_channel_callbacks(self.on_welcome,
                                                self.on_set_topic, None, None,
                                                self.on_nick_leave, None)
        self.tx_unconfirm_timestamp = {}
        self.last_offer_update = None

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
        if largest_mixdepth_size == 0:
            print("ALERT: not enough funds available in wallet")
            return []

        spread_offers = []
        powers_of_ten_offers = []
        user_defined_offers = []
        if user_defined_offers_enabled:
            user_defined_offers = create_user_defined_offers()
        if powers_of_ten_offers_enabled:
            powers_of_ten_offers = create_powers_of_ten_offers()
        if spread_offers_enabled:
            spread_offers = create_spread_offers(largest_mixdepth_size,
                                                 sorted_mix_balance)

        offers = user_defined_offers + powers_of_ten_offers + spread_offers
        log.debug('offer_data_chart = \n' + '\n'.join([str(
            x) for x in offer_data_chart(offers)]))

        sanity_check(powers_of_ten_offers, dust=True)
        sanity_check(user_defined_offers + spread_offers)

        count = 0
        for offer in offers:
            offer['oid'] = count
            count += 1

        log.debug('offers len = ' + str(len(offers)))
        log.debug('generated offers = \n' + '\n'.join([str(o) for o in offers]))
        if len(offers) > 50:  # safe guard
            log.debug('too many offers. truncating')
            offers = offers[-10:]
            log.debug('truncated offers = \n' + '\n'.join([str(o) for o in
                                                           offers]))
        return offers

    def oid_to_order(self, cjorder, oid, amount):
        '''Coins rotate circularly from max mixdepth back to mixdepth 0'''
        mix_balance = self.wallet.get_balance_by_mixdepth()
        total_amount = amount + cjorder.txfee
        log.debug('amount, txfee, total_amount = ' + str(amount) + str(
            cjorder.txfee) + str(total_amount))

        # look for exact amount available with no change
        # not supported because change output required
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

        if offer_spread == 'bymixdepth':
            # use mix depth that has the closest amount of coins to what this transaction needs
            # keeps coins moving through mix depths more quickly
            # and its more likely to use txos of a similiar size to this transaction
            filtered_mix_balance = sorted(
                filtered_mix_balance,
                key=lambda x: x[1])  #sort smallest to largest usable amount
        else:
            # prioritize by mixdepths ascending
            # keep coins moving towards last mixdepth, clumps once they get there
            # makes sure coins sent to mixdepth 0 will get mixed to mixdepth 5
            filtered_mix_balance = sorted(filtered_mix_balance,
                                          key=lambda x: x[0])

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
    try:
        seed = sys.argv[1]
    except:
        sys.exit("You forgot to specify the wallet file.")
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
