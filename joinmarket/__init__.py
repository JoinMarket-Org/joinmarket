from __future__ import absolute_import

import datetime
import io
import logging
import threading
from math import exp

from ConfigParser import SafeConfigParser
from configparser import NoOptionError

# Set default logging handler to avoid "No handler found" warnings.
from joinmarket.wallet import AbstractWallet

try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

logging.getLogger(__name__).addHandler(NullHandler())

log = logging.getLogger('gitreformat')
log.addHandler(logging.NullHandler())


def get_log():
    return log


JM_VERSION = 2
nickname = None
DUST_THRESHOLD = 2730
bc_interface = None
ordername_list = ["absorder", "relorder"]
maker_timeout_sec = 30

debug_file_lock = threading.Lock()
debug_file_handle = None
core_alert = None
joinmarket_alert = None
debug_silence = False

config = SafeConfigParser()
config_location = 'joinmarket.cfg'


# todo: we need a class or something to manage this global state

def set_nickname(nick):
    global nickname
    nickname = nick


def set_debug_silence(state):
    global debug_silence
    debug_silence = state


# FIXME: Add rpc_* options here in the future!
required_options = {'BLOCKCHAIN': ['blockchain_source', 'network'],
                    'MESSAGING': ['host', 'channel', 'port']}

defaultconfig = \
    """
    [BLOCKCHAIN]
    blockchain_source = blockr
    #options: blockr, bitcoin-rpc, json-rpc, regtest
    #for instructions on bitcoin-rpc read https://github.com/chris-belcher/joinmarket/wiki/Running-JoinMarket-with-Bitcoin-Core-full-node
    network = mainnet
    rpc_host = localhost
    rpc_port = 8332
    rpc_user = bitcoin
    rpc_password = password

    [MESSAGING]
    host = irc.cyberguerrilla.org
    channel = joinmarket-pit
    port = 6697
    usessl = true
    socks5 = false
    socks5_host = localhost
    socks5_port = 9050
    #for tor
    #host = 6dvj6v5imhny3anf.onion
    #port = 6697
    #usessl = true
    #socks5 = true
    maker_timeout_sec = 30

    [POLICY]
    # for dust sweeping, try merge_algorithm = gradual
    # for more rapid dust sweeping, try merge_algorithm = greedy
    # for most rapid dust sweeping, try merge_algorithm = greediest
    # but don't forget to bump your miner fees!
    merge_algorithm = default
    """


def get_config_irc_channel():
    channel = '#' + config.get("MESSAGING", "channel")
    if get_network() == 'testnet':
        channel += '-test'
    return channel


# todo: oh wow, I thought all those debug statements were logging.debug
# suggestions?  obviously rewritten to use logging module but what is
# the strategy being employed in the below?

def dontuse_debug(msg):
    global debug_file_handle
    with debug_file_lock:
        if nickname and not debug_file_handle:
            debug_file_handle = open(
                    os.path.join('logs', nickname + '.log'), 'ab', 1)
        outmsg = datetime.datetime.now().strftime("[%Y/%m/%d %H:%M:%S] ") + msg
        if not debug_silence:
            if core_alert:
                print 'Core Alert Message: ' + core_alert
            if joinmarket_alert:
                print 'JoinMarket Alert Message: ' + joinmarket_alert
            print outmsg
        if nickname:  # debugs before creating bot nick won't be handled like this
            debug_file_handle.write(outmsg + '\r\n')


# Random functions - replacing some NumPy features
# NOTE THESE ARE NEITHER CRYPTOGRAPHICALLY SECURE
# NOR PERFORMANT NOR HIGH PRECISION!
# Only for sampling purposes


def rand_norm_array(mu, sigma, n):
    # use normalvariate instead of gauss for thread safety
    return [random.normalvariate(mu, sigma) for i in range(n)]


def rand_exp_array(lamda, n):
    # 'lambda' is reserved (in case you are triggered by spelling errors)
    return [random.expovariate(1.0 / lamda) for i in range(n)]


def rand_pow_array(power, n):
    # rather crude in that uses a uniform sample which is a multiple of 1e-4
    # for basis of formula, see: http://mathworld.wolfram.com/RandomNumber.html
    return [y ** (1.0 / power)
            for y in [x * 0.0001 for x in random.sample(
                xrange(10000), n)]]


def rand_weighted_choice(n, p_arr):
    """
    Choose a value in 0..n-1
	with the choice weighted by the probabilities
	in the list p_arr. Note that there will be some
	floating point rounding errors, but see the note
	at the top of this section.
	"""
    if abs(sum(p_arr) - 1.0) > 1e-4:
        raise ValueError("Sum of probabilities must be 1")
    if len(p_arr) != n:
        raise ValueError("Need: " + str(n) + " probabilities.")
    cum_pr = [sum(p_arr[:i + 1]) for i in xrange(len(p_arr))]
    r = random.random()
    return sorted(cum_pr + [r]).index(r)


# End random functions


def chunks(d, n):
    return [d[x:x + n] for x in xrange(0, len(d), n)]


def get_network():
    """Returns network name"""
    return config.get("BLOCKCHAIN", "network")


def get_p2sh_vbyte():
    if get_network() == 'testnet':
        return 0xc4
    else:
        return 0x05


def get_p2pk_vbyte():
    if get_network() == 'testnet':
        return 0x6f
    else:
        return 0x00


def validate_address(addr):
    try:
        ver = btc.get_version_byte(addr)
    except AssertionError:
        return False, 'Checksum wrong. Typo in address?'
    if ver != get_p2pk_vbyte() and ver != get_p2sh_vbyte():
        return False, 'Wrong address version. Testnet/mainnet confused?'
    return True, 'address validated'


def debug_dump_object(obj, skip_fields=None):
    if skip_fields is None:
        skip_fields = []
    log.debug('Class debug dump, name:' + obj.__class__.__name__)
    for k, v in obj.__dict__.iteritems():
        if k in skip_fields:
            continue
        if k == 'password' or k == 'given_password':
            continue
        log.debug('key=' + k)
        if isinstance(v, str):
            log.debug('string: len:' + str(len(v)))
            log.debug(v)
        elif isinstance(v, dict) or isinstance(v, list):
            log.debug(pprint.pformat(v))
        else:
            log.debug(str(v))


def select_gradual(unspent, value):
    """
	UTXO selection algorithm for gradual dust reduction
	If possible, combines outputs, picking as few as possible of the largest
	utxos less than the target value; if the target value is larger than the
	sum of all smaller utxos, uses the smallest utxo larger than the value.
	"""
    value, key = int(value), lambda u: u["value"]
    high = sorted([u for u in unspent if key(u) >= value], key=key)
    low = sorted([u for u in unspent if key(u) < value], key=key)
    lowsum = reduce(lambda x, y: x + y, map(key, low), 0)
    if value > lowsum:
        if len(high) == 0:
            raise Exception('Not enough funds')
        else:
            return [high[0]]
    else:
        start, end, total = 0, 0, 0
        while total < value:
            total += low[end]['value']
            end += 1
        while total >= value + low[start]['value']:
            total -= low[start]['value']
            start += 1
        return low[start:end]


def select_greedy(unspent, value):
    """
	UTXO selection algorithm for greedy dust reduction, but leaves out
	extraneous utxos, preferring to keep multiple small ones.
	"""
    value, key, cursor = int(value), lambda u: u['value'], 0
    utxos, picked = sorted(unspent, key=key), []
    for utxo in utxos:  # find the smallest consecutive sum >= value
        value -= key(utxo)
        if value == 0:  # perfect match! (skip dilution stage)
            return utxos[0:cursor + 1]  # end is non-inclusive
        elif value < 0:  # overshot
            picked += [utxo]  # definitely need this utxo
            break  # proceed to dilution
        cursor += 1
    for utxo in utxos[cursor - 1::-1]:  # dilution loop
        value += key(utxo)  # see if we can skip this one
        if value > 0:  # no, that drops us below the target
            picked += [utxo]  # so we need this one too
            value -= key(utxo)  # 'backtrack' the counter
    if len(picked) > 0:
        return picked
    raise Exception('Not enough funds')  # if all else fails, we do too


def select_greediest(unspent, value):
    """
	UTXO selection algorithm for speediest dust reduction
	Combines the shortest run of utxos (sorted by size, from smallest) which
	exceeds the target value; if the target value is larger than the sum of
	all smaller utxos, uses the smallest utxo larger than the target value.
	"""
    value, key = int(value), lambda u: u["value"]
    high = sorted([u for u in unspent if key(u) >= value], key=key)
    low = sorted([u for u in unspent if key(u) < value], key=key)
    lowsum = reduce(lambda x, y: x + y, map(key, low), 0)
    if value > lowsum:
        if len(high) == 0:
            raise Exception('Not enough funds')
        else:
            return [high[0]]
    else:
        end, total = 0, 0
        while total < value:
            total += low[end]['value']
            end += 1
        return low[0:end]


def calc_cj_fee(ordertype, cjfee, cj_amount):
    real_cjfee = None
    if ordertype == 'absorder':
        real_cjfee = int(cjfee)
    elif ordertype == 'relorder':
        real_cjfee = int((Decimal(cjfee) * Decimal(cj_amount)).quantize(Decimal(
                1)))
    else:
        raise RuntimeError('unknown order type: ' + str(ordertype))
    return real_cjfee


def weighted_order_choose(orders, n, feekey):
    """
	Algorithm for choosing the weighting function
	it is an exponential
	P(f) = exp(-(f - fmin) / phi)
	P(f) - probability of order being chosen
	f - order fee
	fmin - minimum fee in the order book
	phi - scaling parameter, 63% of the distribution is within

	define number M, related to the number of counterparties in this coinjoin
	phi has a value such that it contains up to the Mth order
	unless M < orderbook size, then phi goes up to the last order
	"""
    minfee = feekey(orders[0])
    M = int(3 * n)
    if len(orders) > M:
        phi = feekey(orders[M]) - minfee
    else:
        phi = feekey(orders[-1]) - minfee
    fee = [feekey(o) for o in orders]
    if phi > 0:
        weight = [exp(-(1.0 * f - minfee) / phi) for f in fee]
    else:
        weight = [1.0] * len(fee)
    weight = [x / sum(weight) for x in weight]
    log.debug('phi=' + str(phi) + ' weights = ' + str(weight))
    chosen_order_index = rand_weighted_choice(len(orders), weight)
    return orders[chosen_order_index]


def cheapest_order_choose(orders, n, feekey):
    """
	Return the cheapest order from the orders.
	"""
    return sorted(orders, key=feekey)[0]


def pick_order(orders, n, feekey):
    i = -1
    print("Considered orders:")
    for o in orders:
        i += 1
        print("    %2d. %20s, CJ fee: %6d, tx fee: %6d" % (i, o[0], o[2], o[3]))
    pickedOrderIndex = -1
    if i == 0:
        print("Only one possible pick, picking it.")
        return orders[0]
    while pickedOrderIndex == -1:
        try:
            pickedOrderIndex = int(raw_input('Pick an order between 0 and ' +
                                             str(i) + ': '))
        except ValueError:
            pickedOrderIndex = -1
            continue

        if 0 <= pickedOrderIndex < len(orders):
            return orders[pickedOrderIndex]
        pickedOrderIndex = -1


def choose_orders(db, cj_amount, n, chooseOrdersBy, ignored_makers=None):
    if ignored_makers is None:
        ignored_makers = []
    sqlorders = db.execute('SELECT * FROM orderbook;').fetchall()
    orders = [(o['counterparty'], o['oid'], calc_cj_fee(
            o['ordertype'], o['cjfee'], cj_amount), o['txfee'])
              for o in sqlorders
              if o['minsize'] <= cj_amount <= o['maxsize'] and o[
                  'counterparty'] not in ignored_makers]
    feekey = lambda o: o[2] - o[
        3]  # function that returns the fee for a given order
    counterparties = set([o[0] for o in orders])
    if n > len(counterparties):
        log.debug(
                'ERROR not enough liquidity in the orderbook n=%d suitable-counterparties=%d amount=%d totalorders=%d'
                % (n, len(counterparties), cj_amount, len(orders)))
        return None, 0  # TODO handle not enough liquidity better, maybe an Exception
    # restrict to one order per counterparty, choose the one with the lowest cjfee
    # this is done in advance of the order selection algo, so applies to all of them.
    # however, if orders are picked manually, allow duplicates.
    if chooseOrdersBy != pick_order:
        orders = sorted(
                dict((v[0], v) for v in sorted(orders,
                                               key=feekey,
                                               reverse=True)).values(),
                key=feekey)
    else:
        orders = sorted(orders,
                        key=feekey)  # sort from smallest to biggest cj fee

    log.debug('considered orders = \n' + '\n'.join([str(o) for o in orders]))
    total_cj_fee = 0
    chosen_orders = []
    for i in range(n):
        chosen_order = chooseOrdersBy(orders, n, feekey)
        orders = [o for o in orders if o[0] != chosen_order[0]
                  ]  # remove all orders from that same counterparty
        chosen_orders.append(chosen_order)
        total_cj_fee += chosen_order[2]
    log.debug('chosen orders = \n' + '\n'.join([str(o) for o in chosen_orders]))
    chosen_orders = [o[:2] for o in chosen_orders]
    return dict(chosen_orders), total_cj_fee


def choose_sweep_orders(db,
                        total_input_value,
                        total_txfee,
                        n,
                        chooseOrdersBy,
                        ignored_makers=None):
    """
	choose an order given that we want to be left with no change
	i.e. sweep an entire group of utxos

	solve for cjamount when mychange = 0
	for an order with many makers, a mixture of absorder and relorder
	mychange = totalin - cjamount - total_txfee - sum(absfee) - sum(relfee*cjamount)
	=> 0 = totalin - mytxfee - sum(absfee) - cjamount*(1 + sum(relfee))
	=> cjamount = (totalin - mytxfee - sum(absfee)) / (1 + sum(relfee))
	"""

    if ignored_makers is None:
        ignored_makers = []

    def calc_zero_change_cj_amount(ordercombo):
        sumabsfee = 0
        sumrelfee = Decimal('0')
        sumtxfee_contribution = 0
        for order in ordercombo:
            sumtxfee_contribution += order[0]['txfee']
            if order[0]['ordertype'] == 'absorder':
                sumabsfee += int(order[0]['cjfee'])
            elif order[0]['ordertype'] == 'relorder':
                sumrelfee += Decimal(order[0]['cjfee'])
            else:
                raise RuntimeError('unknown order type: {}'.format(
                        order[0]['ordertype']))

        my_txfee = max(total_txfee - sumtxfee_contribution, 0)
        cjamount = (total_input_value - my_txfee - sumabsfee) / (1 + sumrelfee)
        cjamount = int(cjamount.quantize(Decimal(1)))
        return cjamount, int(sumabsfee + sumrelfee * cjamount)

    log.debug('choosing sweep orders for total_input_value = ' + str(
            total_input_value))
    sqlorders = db.execute('SELECT * FROM orderbook WHERE minsize <= ?;',
                           (total_input_value,)).fetchall()
    orderkeys = ['counterparty', 'oid', 'ordertype', 'minsize', 'maxsize',
                 'txfee', 'cjfee']
    orderlist = [dict([(k, o[k]) for k in orderkeys])
                 for o in sqlorders if o['counterparty'] not in ignored_makers]
    # orderlist = sqlorders #uncomment this and comment previous two lines for faster runtime but less readable output
    log.debug('orderlist = \n' + '\n'.join([str(o) for o in orderlist]))

    # choose N amount of orders
    available_orders = [(o, calc_cj_fee(o['ordertype'], o['cjfee'],
                                        total_input_value), o['txfee'])
                        for o in orderlist]
    feekey = lambda o: o[1] - o[
        2]  # function that returns the fee for a given order
    available_orders = sorted(available_orders,
                              key=feekey)  # sort from smallest to biggest cj fee
    chosen_orders = []
    while len(chosen_orders) < n:
        if len(available_orders) < n - len(chosen_orders):
            log.debug('ERROR not enough liquidity in the orderbook')
            return None, 0  # TODO handle not enough liquidity better, maybe an Exception
        for i in range(n - len(chosen_orders)):
            chosen_order = chooseOrdersBy(available_orders, n, feekey)
            log.debug('chosen = ' + str(chosen_order))
            # remove all orders from that same counterparty
            available_orders = [
                o
                for o in available_orders
                if o[0]['counterparty'] != chosen_order[0]['counterparty']
                ]
            chosen_orders.append(chosen_order)
        # calc cj_amount and check its in range
        cj_amount, total_fee = calc_zero_change_cj_amount(chosen_orders)
        for c in list(chosen_orders):
            minsize = c[0]['minsize']
            maxsize = c[0]['maxsize']
            if cj_amount > maxsize or cj_amount < minsize:
                chosen_orders.remove(c)
    log.debug('chosen orders = \n' + '\n'.join([str(o) for o in chosen_orders]))
    result = dict([(o[0]['counterparty'], o[0]['oid']) for o in chosen_orders])
    log.debug('cj amount = ' + str(cj_amount))
    return result, cj_amount


from .slowaes import *
from .message_channel import *
from .socks import *
from .message_channel import *
from .old_mnemonic import *
from .jsonrpc import *
from .wallet import *
from .enc_wrapper import *

from .irc import *
from .taker import *

from joinmarket.blockchaininterface import *


def load_program_config():
    loadedFiles = config.read([config_location])
    # Create default config file if not found
    if len(loadedFiles) != 1:
        config.readfp(io.BytesIO(defaultconfig))
        with open(config_location, "w") as configfile:
            configfile.write(defaultconfig)

    # check for sections
    for s in required_options:
        if s not in config.sections():
            raise Exception(
                    "Config file does not contain the required section: " + s)
    # then check for specific options
    for k, v in required_options.iteritems():
        for o in v:
            if o not in config.options(k):
                raise Exception(
                        "Config file does not contain the required option: " + o)

    try:
        global maker_timeout_sec
        maker_timeout_sec = config.getint('MESSAGING', 'maker_timeout_sec')
    except NoOptionError:
        log.debug(
                'maker_timeout_sec not found in .cfg file, using default value')

    # configure the interface to the blockchain on startup
    global bc_interface
    bc_interface = get_blockchain_interface_instance(config)


from .maker import *
