from __future__ import absolute_import, print_function

import copy
import sys
import threading

# data_dir = os.path.dirname(os.path.realpath(__file__))
# sys.path.insert(0, os.path.join(data_dir, 'joinmarket'))

import time
from optparse import OptionParser
from pprint import pprint

from joinmarket import jm_single, Taker, load_program_config, \
    IRCMessageChannel, MessageChannelCollection
from joinmarket import validate_address
from joinmarket import random_nick
from joinmarket import get_log, rand_norm_array, rand_pow_array, \
    rand_exp_array, choose_orders, weighted_order_choose, choose_sweep_orders, \
    debug_dump_object, get_irc_mchannels
from joinmarket import Wallet
from joinmarket.wallet import estimate_tx_fee

log = get_log()


def lower_bounded_int(thelist, lowerbound):
    return [int(l) if int(l) >= lowerbound else lowerbound for l in thelist]


def generate_tumbler_tx(destaddrs, options):
    # sends the coins up through a few mixing depths
    # send to the destination addresses from different mixing depths

    # simple algo, move coins completely from one mixing depth to the next
    # until you get to the end, then send to destaddrs

    # txcounts for going completely from one mixdepth to the next
    # follows a normal distribution
    txcounts = rand_norm_array(options['txcountparams'][0],
                               options['txcountparams'][1], options['mixdepthcount'])
    txcounts = lower_bounded_int(txcounts, options['mintxcount'])
    tx_list = []
    for m, txcount in enumerate(txcounts):
        if options['mixdepthcount'] - options['addrcount'] <= m and m < \
                options['mixdepthcount'] - 1:
            #these mixdepths send to a destination address, so their
            # amount_fraction cant be 1.0, some coins must be left over
            if txcount == 1:
                txcount = 2
        # assume that the sizes of outputs will follow a power law
        amount_fractions = rand_pow_array(options['amountpower'], txcount)
        amount_fractions = [1.0 - x for x in amount_fractions]
        amount_fractions = [x / sum(amount_fractions) for x in amount_fractions]
        # transaction times are uncorrelated
        # time between events in a poisson process followed exp
        waits = rand_exp_array(options['timelambda'], txcount)
        # number of makers to use follows a normal distribution
        makercounts = rand_norm_array(options['makercountrange'][0],
                                      options['makercountrange'][1], txcount)
        makercounts = lower_bounded_int(makercounts, options['minmakercount'])
        if m == options['mixdepthcount'] - options['addrcount'] and \
                options['donateamount']:
            tx_list.append({'amount_fraction': 0,
                            'wait': round(waits[0], 2),
                            'srcmixdepth': m + options['mixdepthsrc'],
                            'makercount': makercounts[0],
                            'destination': 'internal'})
        for amount_fraction, wait, makercount in zip(amount_fractions, waits,
                                                     makercounts):
            tx = {'amount_fraction': amount_fraction,
                  'wait': round(wait, 2),
                  'srcmixdepth': m + options['mixdepthsrc'],
                  'makercount': makercount,
                  'destination': 'internal'}
            tx_list.append(tx)

    addrask = options['addrcount'] - len(destaddrs)
    external_dest_addrs = ['addrask'] * addrask + destaddrs
    for mix_offset in range(options['addrcount']):
        srcmix = (options['mixdepthsrc'] + options['mixdepthcount'] - 
            mix_offset - 1)
        for tx in reversed(tx_list):
            if tx['srcmixdepth'] == srcmix:
                tx['destination'] = external_dest_addrs[mix_offset]
                break
        if mix_offset == 0:
            # setting last mixdepth to send all to dest
            tx_list_remove = []
            for tx in tx_list:
                if tx['srcmixdepth'] == srcmix:
                    if tx['destination'] == 'internal':
                        tx_list_remove.append(tx)
                    else:
                        tx['amount_fraction'] = 1.0
            [tx_list.remove(t) for t in tx_list_remove]
    return tx_list


# thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class TumblerThread(threading.Thread):
    def __init__(self, taker):
        threading.Thread.__init__(self, name='TumblerThread')
        self.daemon = True
        self.taker = taker
        self.ignored_makers = []
        self.sweep = False
        self.broadcast_attempts = 0
        self.create_tx_attempts = 0

    def unconfirm_callback(self, txd, txid):
        log.debug('that was %d tx out of %d, waiting for confirmation' %
                  (self.current_tx + 1, len(self.taker.tx_list)))

    def confirm_callback(self, txd, txid, confirmations):
        self.taker.wallet.remove_old_utxos(txd)
        self.taker.wallet.add_new_utxos(txd, txid)
        with self.lockcond:
            self.lockcond.notify()

    def timeout_callback(self, confirmed):
        if not confirmed:
            #try rebroadcasting a few times, then create again
            if self.broadcast_attempts == 0:
                log.debug('timed out for unconfirmed tx, recreating')
                self.create_tx()
                #need a countdown here and other places, maybe inside
                #create_tx in case theres some long-running problem
                return
            self.broadcast_attempts -= 1
            log.debug('timed out for unconfirmed tx, rebroadcasting')
            pushed = self.pushtx()
            if not pushed:
                log.debug("Failed to push transaction, recreating")
                self.create_tx()
        else:
            log.debug('timed out waiting for confirmation')

    def pushtx(self):
        push_attempts = 3
        while True:
            ret = self.taker.cjtx.push()
            if ret:
                break
            if push_attempts == 0:
                break
            push_attempts -= 1
            time.sleep(10)
        if ret:
            jm_single().bc_interface.add_tx_notify(
                self.taker.cjtx.latest_tx, self.unconfirm_callback,
                self.confirm_callback, self.taker.cjtx.my_cj_addr,
                self.timeout_callback)
        return ret

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            self.broadcast_attempts = self.taker.options['maxbroadcasts']
            coinjointx.self_sign()
            pushed = self.pushtx()
            if not pushed:
                log.debug("Failed to push transaction, recreating")
                self.create_tx()
        else:
            self.ignored_makers += coinjointx.nonrespondants
            log.debug('recreating the tx, ignored_makers=' + str(
                    self.ignored_makers))
            self.create_tx_attempts += 1 #nonrespondants dont count for timeout
            self.create_tx()

    def tumbler_choose_orders(self,
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
                    self.taker.db, cj_amount, makercount, weighted_order_choose,
                    self.ignored_makers + active_nicks)
            abs_cj_fee = 1.0 * total_cj_fee / makercount
            rel_cj_fee = abs_cj_fee / cj_amount
            log.debug('rel/abs average fee = ' + str(rel_cj_fee) + ' / ' + str(
                    abs_cj_fee))

            if rel_cj_fee > self.taker.options['maxcjfee'][
                0] and abs_cj_fee > self.taker.options['maxcjfee'][1]:
                log.debug('cj fee higher than maxcjfee, waiting ' + str(
                        self.taker.options['liquiditywait']) + ' seconds')
                time.sleep(self.taker.options['liquiditywait'])
                continue
            if orders is None:
                log.debug('waiting for liquidity ' + str(
                        self.taker.options['liquiditywait']) +
                          'secs, hopefully more orders should come in')
                time.sleep(self.taker.options['liquiditywait'])
                continue
            break
        log.debug('chosen orders to fill ' + str(orders) + ' totalcjfee=' + str(
                total_cj_fee))
        return orders, total_cj_fee

    def create_tx(self):
        if self.create_tx_attempts == 0:
             log.debug('reached limit of number of attempts to create tx, quitting')
             self.taker.msgchan.shutdown()
             return
        jm_single().bc_interface.sync_unspent(self.taker.wallet)
        self.create_tx_attempts -= 1
        orders = None
        cj_amount = 0
        change_addr = None
        choose_orders_recover = None
        if self.sweep:
            log.debug('sweeping')
            utxos = self.taker.wallet.get_utxos_by_mixdepth()[self.tx[
                'srcmixdepth']]
            #do our best to estimate the fee based on the number of
            #our own utxos; this estimate may be significantly higher
            #than the default set in option.txfee * makercount, where
            #we have a large number of utxos to spend. If it is smaller,
            #we'll be conservative and retain the original estimate.
            est_ins = len(utxos)+3*self.tx['makercount']
            log.debug("Estimated ins: "+str(est_ins))
            est_outs = 2*self.tx['makercount'] + 1
            log.debug("Estimated outs: "+str(est_outs))
            estimated_fee = estimate_tx_fee(est_ins, est_outs)
            log.debug("We have a fee estimate: "+str(estimated_fee))
            log.debug("And a requested fee of: "+str(
                self.taker.options['txfee'] * self.tx['makercount']))
            fee_for_tx = max([estimated_fee,
                              self.tx['makercount'] * self.taker.options['txfee']])
            fee_for_tx = int(fee_for_tx / self.tx['makercount'])
            total_value = sum([addrval['value'] for addrval in utxos.values()])
            while True:
                orders, cj_amount, total_cj_fee = choose_sweep_orders(
                    self.taker.db, total_value, fee_for_tx,
                        self.tx['makercount'], weighted_order_choose,
                        self.ignored_makers)
                if orders is None:
                    log.debug('waiting for liquidity ' + str(
                            self.taker.options['liquiditywait']) +
                              'secs, hopefully more orders should come in')
                    time.sleep(self.taker.options['liquiditywait'])
                    continue
                abs_cj_fee = 1.0 * total_cj_fee / self.tx['makercount']
                rel_cj_fee = abs_cj_fee / cj_amount
                log.debug(
                    'rel/abs average fee = ' + str(rel_cj_fee) + ' / ' + str(
                            abs_cj_fee))
                if rel_cj_fee > self.taker.options['maxcjfee'][0] \
                        and abs_cj_fee > self.taker.options['maxcjfee'][1]:
                    log.debug('cj fee higher than maxcjfee, waiting ' + str(
                            self.taker.options['liquiditywait']) + ' seconds')
                    time.sleep(self.taker.options['liquiditywait'])
                    continue
                break
        else:
            if self.tx['amount_fraction'] == 0:
                cj_amount = int(self.balance *
                    self.taker.options['donateamount'] / 100.0)
                self.destaddr = None
            else:
                cj_amount = int(self.tx['amount_fraction'] * self.balance)
            if cj_amount < self.taker.options['mincjamount']:
                log.debug('cj amount too low, bringing up')
                cj_amount = self.taker.options['mincjamount']
            change_addr = self.taker.wallet.get_internal_addr(
                self.tx['srcmixdepth'])
            log.debug('coinjoining ' + str(cj_amount) + ' satoshi')
            orders, total_cj_fee = self.tumbler_choose_orders(
                    cj_amount, self.tx['makercount'])
            total_amount = cj_amount + total_cj_fee + \
                self.taker.options['txfee']*self.tx['makercount']
            log.debug('total estimated amount spent = ' + str(total_amount))
            #adjust the required amount upwards to anticipate an increase of the
            #transaction fee after re-estimation; this is sufficiently conservative
            #to make failures unlikely while keeping the occurence of failure to
            #find sufficient utxos extremely rare. Indeed, a doubling of 'normal'
            #txfee indicates undesirable behaviour on maker side anyway.
            try:
                utxos = self.taker.wallet.select_utxos(self.tx['srcmixdepth'],
                total_amount+self.taker.options['txfee']*self.tx['makercount'])
            except Exception as e:
                #we cannot afford to just throw not enough funds; better to
                #try with a smaller request; it could still fail within
                #CoinJoinTX.recv_txio, but make every effort to avoid stopping.
                if str(e) == "Not enough funds":
                    log.debug("Failed to select total amount + twice txfee from" +
                          "wallet; trying to select just total amount.")
                    utxos = self.taker.wallet.select_utxos(self.tx['srcmixdepth'],
                            total_amount)
                else:
                    raise
            fee_for_tx = self.taker.options['txfee']
            choose_orders_recover = self.tumbler_choose_orders

        self.taker.start_cj(self.taker.wallet, cj_amount, orders, utxos,
                            self.destaddr, change_addr,
                            fee_for_tx*self.tx['makercount'],
                            self.finishcallback, choose_orders_recover)

    def init_tx(self, tx, balance, sweep):
        destaddr = None
        if tx['destination'] == 'internal':
            destaddr = self.taker.wallet.get_internal_addr(tx['srcmixdepth'] + 1)
        elif tx['destination'] == 'addrask':
            jm_single().debug_silence[0] = True
            print('\n'.join(['=' * 60] * 3))
            print('Tumbler requires more addresses to stop amount correlation')
            print('Obtain a new destination address from your bitcoin recipient')
            print(' for example click the button that gives a new deposit address')
            print('\n'.join(['=' * 60] * 1))
            while True:
                destaddr = raw_input('insert new address: ')
                addr_valid, errormsg = validate_address(destaddr)
                if addr_valid:
                    break
                print(
                'Address ' + destaddr + ' invalid. ' + errormsg + ' try again')
            jm_single().debug_silence[0] = False
        else:
            destaddr = tx['destination']
        self.taker.wallet.update_cache_index()
        self.sweep = sweep
        self.balance = balance
        self.tx = tx
        self.destaddr = destaddr
        self.create_tx_attempts = self.taker.options['maxcreatetx']
        self.create_tx()
        with self.lockcond:
            self.lockcond.wait()
        log.debug('tx confirmed, waiting for ' + str(tx['wait']) + ' minutes')
        time.sleep(tx['wait'] * 60)
        log.debug('woken')

    def run(self):
        log.debug('waiting for all orders to certainly arrive')
        time.sleep(self.taker.options['waittime'])

        sqlorders = self.taker.db.execute(
                'SELECT cjfee, ordertype FROM orderbook;').fetchall()
        orders = [o['cjfee'] for o in sqlorders if o['ordertype'] == 'reloffer']
        orders = sorted(orders)
        if len(orders) == 0:
            log.debug('There are no orders at all in the orderbook! '
                      'Is the bot connecting to the right server?')
            return
        relorder_fee = float(orders[0])
        log.debug('reloffer fee = ' + str(relorder_fee))
        maker_count = sum([tx['makercount'] for tx in self.taker.tx_list])
        log.debug('uses ' + str(maker_count) + ' makers, at ' + str(
                relorder_fee * 100) + '% per maker, estimated total cost ' + str(
                round((1 - (1 - relorder_fee) ** maker_count) * 100, 3)) + '%')
        log.debug('starting')
        self.lockcond = threading.Condition()

        self.balance_by_mixdepth = {}
        for i, tx in enumerate(self.taker.tx_list):
            if tx['srcmixdepth'] not in self.balance_by_mixdepth:
                self.balance_by_mixdepth[tx[
                    'srcmixdepth']] = self.taker.wallet.get_balance_by_mixdepth(
                )[tx['srcmixdepth']]
            sweep = True
            for later_tx in self.taker.tx_list[i + 1:]:
                if later_tx['srcmixdepth'] == tx['srcmixdepth']:
                    sweep = False
            self.current_tx = i
            self.init_tx(tx, self.balance_by_mixdepth[tx['srcmixdepth']], sweep)

        log.debug('total finished')
        self.taker.msgchan.shutdown()

class Tumbler(Taker):
    def __init__(self, msgchan, wallet, tx_list, options):
        Taker.__init__(self, msgchan)
        self.wallet = wallet
        self.tx_list = tx_list
        self.options = options
        self.tumbler_thread = None

    def on_welcome(self):
        Taker.on_welcome(self)
        if not self.tumbler_thread:
            self.tumbler_thread = TumblerThread(self)
            self.tumbler_thread.start()


def main():
    parser = OptionParser(
            usage='usage: %prog [options] [wallet file] [destaddr(s)...]',
            description=
            'Sends bitcoins to many different addresses using coinjoin in'
            ' an attempt to break the link between them. Sending to multiple '
            ' addresses is highly recommended for privacy. This tumbler can'
            ' be configured to ask for more address mid-run, giving the user'
            ' a chance to click `Generate New Deposit Address` on whatever service'
            ' they are using.')
    parser.add_option(
            '-m',
            '--mixdepthsource',
            type='int',
            dest='mixdepthsrc',
            help=
            'Mixing depth to spend from. Useful if a previous tumbler run prematurely ended with '
            +
            'coins being left in higher mixing levels, this option can be used to resume without needing'
            + ' to send to another address. default=0',
            default=0)
    parser.add_option(
            '-f',
        '--txfee',
        action='store',
        type='int',
        dest='txfee',
        default=-1,
        help='number of satoshis per participant to use as the initial estimate '+
        'for the total transaction fee, default=dynamically estimated, note that this is adjusted '+
        'based on the estimated fee calculated after tx construction, based on '+
        'policy set in joinmarket.cfg.')
    parser.add_option(
            '-a',
            '--addrcount',
            type='int',
            dest='addrcount',
            default=3,
            help=
            'How many destination addresses in total should be used. If not enough are given'
            ' as command line arguments, the script will ask for more. This parameter is required'
            ' to stop amount correlation. default=3')
    parser.add_option(
            '-x',
            '--maxcjfee',
            type='float',
            dest='maxcjfee',
            nargs=2,
            default=(0.01, 10000),
            help='maximum coinjoin fee and bitcoin value the tumbler is '
                 'willing to pay to a single market maker. Both values need to be exceeded, so if '
                 'the fee is 30% but only 500satoshi is paid the tx will go ahead. default=0.01, 10000 (1%, 10000satoshi)')
    parser.add_option(
            '-N',
            '--makercountrange',
            type='float',
            nargs=2,
            action='store',
            dest='makercountrange',
            help=
            'Input the mean and spread of number of makers to use. e.g. 5 1.5 will be a normal distribution '
            'with mean 5 and standard deveation 1.5 inclusive, default=5 1.5',
            default=(5, 1.5))
    parser.add_option(
            '--minmakercount',
            type='int',
            dest='minmakercount',
            default=3,
            help=
            'The minimum maker count in a transaction, random values below this are clamped at this number. default=3')
    parser.add_option(
            '-M',
            '--mixdepthcount',
            type='int',
            dest='mixdepthcount',
            help='How many mixing depths to mix through',
            default=4)
    parser.add_option(
            '-c',
            '--txcountparams',
            type='float',
            nargs=2,
            dest='txcountparams',
            default=(4, 1),
            help=
            'The number of transactions to take coins from one mixing depth to the next, it is'
            ' randomly chosen following a normal distribution. Should be similar to --addrask. '
            'This option controls the parameters of the normal distribution curve. (mean, standard deviation). default=(4, 1)')
    parser.add_option(
            '--mintxcount',
            type='int',
            dest='mintxcount',
            default=1,
            help='The minimum transaction count per mixing level, default=1')
    parser.add_option(
            '--donateamount',
            type='float',
            dest='donateamount',
            default=0,
            help=
            'percent of funds to donate to joinmarket development, or zero to opt out (default=0%)')
    parser.add_option(
            '--amountpower',
            type='float',
            dest='amountpower',
            default=100.0,
            help=
            'The output amounts follow a power law distribution, this is the power, default=100.0')
    parser.add_option(
            '-l',
            '--timelambda',
            type='float',
            dest='timelambda',
            default=30,
            help=
            'Average the number of minutes to wait between transactions. Randomly chosen '
            ' following an exponential distribution, which describes the time between uncorrelated'
            ' events. default=30')
    parser.add_option(
            '-w',
            '--wait-time',
            action='store',
            type='float',
            dest='waittime',
            help='wait time in seconds to allow orders to arrive, default=20',
            default=20)
    parser.add_option(
            '-s',
            '--mincjamount',
            type='int',
            dest='mincjamount',
            default=100000,
            help='minimum coinjoin amount in transaction in satoshi, default 100k')
    parser.add_option(
            '-q',
            '--liquiditywait',
            type='int',
            dest='liquiditywait',
            default=60,
            help=
            'amount of seconds to wait after failing to choose suitable orders before trying again, default 60')
    parser.add_option(
            '--maxbroadcasts',
            type='int',
            dest='maxbroadcasts',
            default=4,
            help=
            'maximum amount of times to broadcast a transaction before giving up and re-creating it, default 4')
    parser.add_option(
            '--maxcreatetx',
            type='int',
            dest='maxcreatetx',
            default=9,
            help=
            'maximum amount of times to re-create a transaction before giving up, default 9')
    (options, args) = parser.parse_args()
    options = vars(options)

    if len(args) < 1:
        parser.error('Needs a wallet file')
        sys.exit(0)
    wallet_file = args[0]
    destaddrs = args[1:]
    print(destaddrs)

    load_program_config()
    for addr in destaddrs:
        addr_valid, errormsg = validate_address(addr)
        if not addr_valid:
            print('ERROR: Address ' + addr + ' invalid. ' + errormsg)
            return

    # Dynamically estimate a realistic fee if it currently is the default value.
    # At this point we do not know even the number of our own inputs, so
    # we guess conservatively with 2 inputs and 2 outputs each
    if options['txfee'] == -1:
        options['txfee'] = max(options['txfee'], estimate_tx_fee(2, 2))
        log.debug("Estimated miner/tx fee for each cj participant: "+str(options['txfee']))
    assert(options['txfee'] >= 0)

    if len(destaddrs) > options['addrcount']:
        options['addrcount'] = len(destaddrs)
    if options['addrcount'] + 1 > options['mixdepthcount']:
        print('not enough mixing depths to pay to all destination addresses, '
              'increasing mixdepthcount')
        options['mixdepthcount'] = options['addrcount'] + 1
    if options['donateamount'] > 10.0:
        # fat finger probably, or misunderstanding
        options['donateamount'] = 0.9

    print(str(options))
    tx_list = generate_tumbler_tx(destaddrs, options)
    if not tx_list:
        return

    tx_list2 = copy.deepcopy(tx_list)
    tx_dict = {}
    for tx in tx_list2:
        srcmixdepth = tx['srcmixdepth']
        tx.pop('srcmixdepth')
        if srcmixdepth not in tx_dict:
            tx_dict[srcmixdepth] = []
        tx_dict[srcmixdepth].append(tx)
    dbg_tx_list = []
    for srcmixdepth, txlist in tx_dict.iteritems():
        dbg_tx_list.append({'srcmixdepth': srcmixdepth, 'tx': txlist})
    log.debug('tumbler transaction list')
    pprint(dbg_tx_list)

    total_wait = sum([tx['wait'] for tx in tx_list])
    print('creates ' + str(len(tx_list)) + ' transactions in total')
    print('waits in total for ' + str(len(tx_list)) + ' blocks and ' + str(
            total_wait) + ' minutes')
    total_block_and_wait = len(tx_list) * 10 + total_wait
    print('estimated time taken ' + str(total_block_and_wait) + ' minutes or ' +
          str(round(total_block_and_wait / 60.0, 2)) + ' hours')
    if options['addrcount'] <= 1:
        print('=' * 50)
        print('WARNING: You are only using one destination address')
        print('this is very bad for privacy')
        print('=' * 50)

    ret = raw_input('tumble with these tx? (y/n):')
    if ret[0] != 'y':
        return

    # NOTE: possibly out of date documentation
    # a couple of modes
    # im-running-from-the-nsa, takes about 80 hours, costs a lot
    # python tumbler.py -a 10 -N 10 5 -c 10 5 -l 50 -M 10 wallet_file 1xxx
    #
    # quick and cheap, takes about 90 minutes
    # python tumbler.py -N 2 1 -c 3 0.001 -l 10 -M 3 -a 1 wallet_file 1xxx
    #
    # default, good enough for most, takes about 5 hours
    # python tumbler.py wallet_file 1xxx
    #
    # for quick testing
    # python tumbler.py -N 2 1 -c 3 0.001 -l 0.1 -M 3 -a 0 wallet_file 1xxx 1yyy
    wallet = Wallet(wallet_file,
                    max_mix_depth=options['mixdepthsrc'] + options['mixdepthcount'])
    jm_single().bc_interface.sync_wallet(wallet)
    jm_single().wait_for_commitments = 1
    log.debug('starting tumbler')
    mcs = [IRCMessageChannel(c) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    tumbler = Tumbler(mcc, wallet, tx_list, options)
    try:
        log.debug('connecting to message channels')
        mcc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(wallet, ['addr_cache', 'keys', 'seed'])
        debug_dump_object(tumbler)
        debug_dump_object(tumbler.cjtx)
        import traceback
        log.debug(traceback.format_exc())


if __name__ == "__main__":
    main()
    print('done')
