#! /usr/bin/env python
from __future__ import absolute_import, print_function

import base64
import pprint
import random
import sqlite3
import sys
import time
import threading
from decimal import InvalidOperation, Decimal

import bitcoin as btc
from joinmarket.configure import jm_single, get_p2pk_vbyte
from joinmarket.enc_wrapper import init_keypair, as_init_encryption, init_pubkey, \
     NaclError
from joinmarket.support import get_log, calc_cj_fee
from joinmarket.wallet import estimate_tx_fee
from joinmarket.irc import B_PER_SEC

log = get_log()


class CoinJoinTX(object):
    # soon the taker argument will be removed and just be replaced by wallet
    # or some other interface
    def __init__(self,
                 msgchan,
                 wallet,
                 db,
                 cj_amount,
                 orders,
                 input_utxos,
                 my_cj_addr,
                 my_change_addr,
                 total_txfee,
                 finishcallback,
                 choose_orders_recover,
                 auth_addr=None):
        """
        if my_change is None then there wont be a change address
        thats used if you want to entirely coinjoin one utxo with no change left over
        orders is the orders you want to fill {'counterpartynick': order1, 'cp2': order2}
        each order object is a dict of properties {'oid': 0, 'maxsize': 2000000, 'minsize':
            5000, 'cjfee': 10000, 'txfee': 5000}
        """
        log.debug(
            'starting cj to ' + str(my_cj_addr) + ' with change at ' + str(
                    my_change_addr))
        # parameters
        self.msgchan = msgchan
        self.wallet = wallet
        self.db = db
        self.cj_amount = cj_amount
        self.active_orders = dict(orders)
        self.input_utxos = input_utxos
        self.finishcallback = finishcallback
        self.total_txfee = total_txfee
        self.my_cj_addr = my_cj_addr
        self.my_change_addr = my_change_addr
        self.choose_orders_recover = choose_orders_recover
        self.auth_addr = auth_addr
        self.timeout_lock = threading.Condition()  # used to wait() and notify()
        # used to restrict access to certain variables across threads
        self.timeout_thread_lock = threading.Condition()
        self.end_timeout_thread = False
        self.maker_timeout_sec = jm_single().maker_timeout_sec
        CoinJoinTX.TimeoutThread(self).start()
        # state variables
        self.txid = None
        self.cjfee_total = 0
        self.maker_txfee_contributions = 0
        self.nonrespondants = list(self.active_orders.keys())
        self.all_responded = False
        self.latest_tx = None
        self.current_max_inputs = 2
        self.tries_fewer_maker_inputs = 0
        # None means they belong to me
        self.utxos = {None: self.input_utxos.keys()}
        self.outputs = []
        # create DH keypair on the fly for this Tx object
        self.kp = init_keypair()
        self.crypto_boxes = {}
        self.msgchan.fill_orders(self.active_orders, self.cj_amount,
                                 self.kp.hex_pk())

    def start_encryption(self, nick, maker_pk):
        if nick not in self.active_orders.keys():
            log.debug("Counterparty not part of this transaction. Ignoring")
            return
        try:
            self.crypto_boxes[nick] = [maker_pk, as_init_encryption(
                self.kp, init_pubkey(maker_pk))]
        except NaclError as e:
            log.debug("Unable to setup crypto box with " + nick + ": " + repr(e))
            self.msgchan.send_error(nick, "invalid nacl pubkey: " + maker_pk)
            return
        # send authorisation request
        if self.auth_addr:
            my_btc_addr = self.auth_addr
        else:
            my_btc_addr = self.input_utxos.itervalues().next()['address']
        my_btc_priv = self.wallet.get_key_from_addr(my_btc_addr)
        my_btc_pub = btc.privtopub(my_btc_priv)
        my_btc_sig = btc.ecdsa_sign(self.kp.hex_pk(), my_btc_priv)
        self.msgchan.send_auth(nick, my_btc_pub, my_btc_sig)

    def auth_counterparty(self, nick, btc_sig, cj_pub):
        """Validate the counterpartys claim to own the btc
        address/pubkey that will be used for coinjoining
        with an ecdsa verification."""
        # crypto_boxes[nick][0] = maker_pubkey
        if not btc.ecdsa_verify(self.crypto_boxes[nick][0], btc_sig, cj_pub):
            log.debug('signature didnt match pubkey and message')
            return False
        return True

    def recv_txio(self, nick, utxo_list, cj_pub, change_addr):
        if nick not in self.nonrespondants:
            log.debug(('recv_txio => nick={} not in '
                       'nonrespondants {}').format(nick, self.nonrespondants))
            return
        self.utxos[nick] = utxo_list
        utxo_data = jm_single().bc_interface.query_utxo_set(self.utxos[nick])
        if None in utxo_data:
            log.debug(('ERROR outputs unconfirmed or already spent. '
                       'utxo_data={}').format(pprint.pformat(utxo_data)))
            # when internal reviewing of makers is created, add it here to
            # immediately quit; currently, the timeout thread suffices.
            return

        # check for too many maker inputs, which might create absurd tx fees
        # and could crash this script later otherwise
        if len(utxo_data) > self.current_max_inputs:
            # Every maker creates 1 inputs and 2 ouputs, which
            # are agreed to be paid by the taker implicity.
            # If there are more, check if they are paid for by the maker
            additional_cost_maker = estimate_tx_fee(len(utxo_data)-self.current_max_inputs, 0)
            if (additional_cost_maker > self.active_orders[nick]['txfee']):
                log.debug('Too many inputs (' + str(len(utxo_data)) + ') from ' + nick
                    + '. This would increase transaction costs for the taker. These additinal '
                    + 'transaction costs are not covered by the maker either'
                    + ' (estimated add. fee: ' + str(additional_cost_maker) + ', paid for by maker: '
                    + str(self.active_orders[nick]['txfee']) + '). '
                    + 'Ignoring. Will select another maker shortly.')
                return                      # timeout marks this maker nonresponsive

        total_input = sum([d['value'] for d in utxo_data])
        real_cjfee = calc_cj_fee(self.active_orders[nick]['ordertype'],
                       self.active_orders[nick]['cjfee'], self.cj_amount)
        change_amount = (total_input - self.cj_amount -
            self.active_orders[nick]['txfee'] + real_cjfee)

        # certain malicious and/or incompetent liquidity providers send
        # inputs totalling less than the coinjoin amount! this leads to
        # a change output of zero satoshis, so the invalid transaction
        # fails harmlessly; let's fail earlier, with a clear message.
        if change_amount < jm_single().DUST_THRESHOLD:
            fmt = ('ERROR counterparty requires sub-dust change. nick={}'
                   'totalin={:d} cjamount={:d} change={:d}').format
            log.debug(fmt(nick, total_input, self.cj_amount, change_amount))
            return              # timeout marks this maker as nonresponsive

        self.outputs.append({'address': change_addr, 'value': change_amount})
        fmt = ('fee breakdown for {} totalin={:d} '
               'cjamount={:d} txfee={:d} realcjfee={:d}').format
        log.debug(fmt(nick, total_input, self.cj_amount,
            self.active_orders[nick]['txfee'], real_cjfee))
        cj_addr = btc.pubtoaddr(cj_pub, get_p2pk_vbyte())
        self.outputs.append({'address': cj_addr, 'value': self.cj_amount})
        self.cjfee_total += real_cjfee
        self.maker_txfee_contributions += self.active_orders[nick]['txfee']
        self.nonrespondants.remove(nick)
        if len(self.nonrespondants) > 0:
            log.debug('nonrespondants = ' + str(self.nonrespondants))
            return
        log.debug('got all parts, enough to build a tx')
        self.nonrespondants = list(self.active_orders.keys())

        my_total_in = sum([va['value'] for u, va in
                           self.input_utxos.iteritems()])
        if self.my_change_addr:
            #Estimate fee per choice of next/3/6 blocks targetting.
            estimated_fee = estimate_tx_fee(len(sum(
                self.utxos.values(),[])), len(self.outputs)+2)
            log.debug("Based on initial guess: "+str(
                self.total_txfee)+", we estimated a fee of: "+str(estimated_fee))
            #reset total
            self.total_txfee = estimated_fee
        my_txfee = max(self.total_txfee - self.maker_txfee_contributions, 0)
        my_change_value = (
            my_total_in - self.cj_amount - self.cjfee_total - my_txfee)
        #Since we could not predict the maker's inputs, we may end up needing
        #too much such that the change value is negative or small. Note that 
        #we have tried to avoid this based on over-estimating the needed amount
        #in SendPayment.create_tx(), but it is still a possibility if one maker
        #uses a *lot* of inputs.
        if self.my_change_addr and my_change_value <= 0:
            raise ValueError("Calculated transaction fee of: "+str(
                self.total_txfee)+" is too large for our inputs;Please try again.")
        elif self.my_change_addr and my_change_value <= jm_single().DUST_THRESHOLD:
            log.debug("Dynamically calculated change lower than dust: "+str(
                my_change_value)+"; dropping.")
            self.my_change_addr = None
            my_change_value = 0
        log.debug('fee breakdown for me totalin=%d my_txfee=%d makers_txfee=%d cjfee_total=%d => changevalue=%d'
                  % (my_total_in, my_txfee, self.maker_txfee_contributions,            
                  self.cjfee_total, my_change_value))
        if self.my_change_addr is None:
            if my_change_value != 0 and abs(my_change_value) != 1:
                # seems you wont always get exactly zero because of integer
                # rounding so 1 satoshi extra or fewer being spent as miner
                # fees is acceptable
                log.debug(('WARNING CHANGE NOT BEING '
                           'USED\nCHANGEVALUE = {}').format(my_change_value))
        else:
            self.outputs.append({'address': self.my_change_addr,
                                 'value': my_change_value})
        self.utxo_tx = [dict([('output', u)])
                        for u in sum(self.utxos.values(), [])]
        self.outputs.append({'address': self.coinjoin_address(),
                             'value': self.cj_amount})
        random.shuffle(self.utxo_tx)
        random.shuffle(self.outputs)
        tx = btc.mktx(self.utxo_tx, self.outputs)
        log.debug('obtained tx\n' + pprint.pformat(btc.deserialize(tx)))
        #Re-calculate a sensible timeout wait based on the throttling
        #settings and the tx size.
        #Calculation: Let tx size be S; tx undergoes two b64 expansions, 1.8*S
        #So we're sending N*1.8*S over the wire, and the
        #maximum bytes/sec = B, means we need (1.8*N*S/B) seconds,
        #and need to add some leeway for network delays, we just add the
        #contents of jm_single().maker_timeout_sec (the user configured value)
        self.maker_timeout_sec = (len(tx) * 1.8 * len(
            self.active_orders.keys()))/(B_PER_SEC) + jm_single().maker_timeout_sec
        log.debug("Based on transaction size: " + str(
            len(tx)) + ", calculated time to wait for replies: " + str(
            self.maker_timeout_sec))
        self.all_responded = True
        with self.timeout_lock:
            self.timeout_lock.notify()
        self.msgchan.send_tx(self.active_orders.keys(), tx)

        self.latest_tx = btc.deserialize(tx)
        for index, ins in enumerate(self.latest_tx['ins']):
            utxo = ins['outpoint']['hash'] + ':' + str(
                    ins['outpoint']['index'])
            if utxo not in self.input_utxos.keys():
                continue
            # placeholders required
            ins['script'] = 'deadbeef'

    def add_signature(self, nick, sigb64):
        if nick not in self.nonrespondants:
            log.debug(('add_signature => nick={} '
                       'not in nonrespondants {}').format(
                    nick, self.nonrespondants))
            return
        sig = base64.b64decode(sigb64).encode('hex')
        inserted_sig = False
        txhex = btc.serialize(self.latest_tx)

        # batch retrieval of utxo data
        utxo = {}
        ctr = 0
        for index, ins in enumerate(self.latest_tx['ins']):
            utxo_for_checking = ins['outpoint']['hash'] + ':' + str(
                    ins['outpoint']['index'])
            if (ins['script'] != '' or
                        utxo_for_checking in self.input_utxos.keys()):
                continue
            utxo[ctr] = [index, utxo_for_checking]
            ctr += 1
        utxo_data = jm_single().bc_interface.query_utxo_set(
                [x[1] for x in utxo.values()])

        # insert signatures
        for i, u in utxo.iteritems():
            if utxo_data[i] is None:
                continue
            sig_good = btc.verify_tx_input(
                    txhex, u[0], utxo_data[i]['script'],
                    *btc.deserialize_script(sig))
            if sig_good:
                log.debug('found good sig at index=%d' % (u[0]))
                self.latest_tx['ins'][u[0]]['script'] = sig
                inserted_sig = True
                # check if maker has sent everything possible
                self.utxos[nick].remove(u[1])
                if len(self.utxos[nick]) == 0:
                    log.debug(('nick = {} sent all sigs, removing from '
                               'nonrespondant list').format(nick))
                    self.nonrespondants.remove(nick)
                break
        if not inserted_sig:
            log.debug('signature did not match anything in the tx')
            # TODO what if the signature doesnt match anything
            # nothing really to do except drop it, carry on and wonder why the
            # other guy sent a failed signature

        tx_signed = True
        for ins in self.latest_tx['ins']:
            if ins['script'] == '':
                tx_signed = False
        if not tx_signed:
            return
        self.end_timeout_thread = True
        self.all_responded = True
        with self.timeout_lock:
            self.timeout_lock.notify()
        log.debug('all makers have sent their signatures')
        for index, ins in enumerate(self.latest_tx['ins']):
            # remove placeholders
            if ins['script'] == 'deadbeef':
                ins['script'] = ''
        if self.finishcallback is not None:
            self.finishcallback(self)

    def coinjoin_address(self):
        if self.my_cj_addr:
            return self.my_cj_addr
        else:
            return donation_address(self)

    def sign_tx(self, tx, i, priv):
        if self.my_cj_addr:
            return btc.sign(tx, i, priv)
        else:
            return sign_donation_tx(tx, i, priv)

    def self_sign(self):
        # now sign it ourselves
        tx = btc.serialize(self.latest_tx)
        for index, ins in enumerate(self.latest_tx['ins']):
            utxo = ins['outpoint']['hash'] + ':' + str(
                    ins['outpoint']['index'])
            if utxo not in self.input_utxos.keys():
                continue
            addr = self.input_utxos[utxo]['address']
            tx = self.sign_tx(tx, index, self.wallet.get_key_from_addr(addr))
        self.latest_tx = btc.deserialize(tx)

    def push(self):
        tx = btc.serialize(self.latest_tx)
        log.debug('\n' + tx)
        self.txid = btc.txhash(tx)
        log.debug('txid = ' + self.txid)
        
        tx_broadcast = jm_single().config.get('POLICY', 'tx_broadcast')
        if tx_broadcast == 'self':
            pushed = jm_single().bc_interface.pushtx(tx)
        elif tx_broadcast in ['random-peer', 'not-self']:
            n = len(self.active_orders)
            if tx_broadcast == 'random-peer':
                i = random.randrange(n + 1)
            else:
                i = random.randrange(n)
            if i == n:
                pushed = jm_single().bc_interface.pushtx(tx)
            else:
                self.msgchan.push_tx(self.active_orders.keys()[i], tx)
                pushed = True
        elif tx_broadcast == 'random-maker':
            crow = self.db.execute(
                'SELECT DISTINCT counterparty FROM orderbook ORDER BY ' +
                'RANDOM() LIMIT 1;'
            ).fetchone()
            counterparty = crow['counterparty']
            log.debug('pushing tx to ' + counterparty)
            self.msgchan.push_tx(counterparty, tx)
            pushed = True

        if not pushed:
            log.debug('unable to pushtx')
        return pushed

    def self_sign_and_push(self):
        self.self_sign()
        return self.push()

    def recover_from_nonrespondants(self):
        log.debug('nonresponding makers = ' + str(self.nonrespondants))
        # if there is no choose_orders_recover then end and call finishcallback
        # so the caller can handle it in their own way, notable for sweeping
        # where simply replacing the makers wont work
        if not self.choose_orders_recover:
            self.end_timeout_thread = True
            if self.finishcallback is not None:
                self.finishcallback(self)
            return

        # relax number of allowed maker inputs after 4 unsuccessful tries
        self.tries_fewer_maker_inputs += 1
        if self.tries_fewer_maker_inputs >= 4:
            self.current_max_inputs += 1
            self.nonrespondants = list(self.active_orders.keys())
            log.debug('Could not find enough makers with low input count to fill order. Increasing allowed inputs per maker to ' + str(self.current_max_inputs))
            log.debug('self.nonrespondants: ' + str(self.nonrespondants))

        if self.latest_tx is None:
            # nonresponding to !fill, recover by finding another maker
            log.debug('nonresponse to !fill')
            for nr in self.nonrespondants:
                del self.active_orders[nr]
            new_orders, new_makers_fee = self.choose_orders_recover(
                    self.cj_amount, len(self.nonrespondants),
                    self.nonrespondants,
                    self.active_orders.keys())
            for nick, order in new_orders.iteritems():
                self.active_orders[nick] = order
            self.nonrespondants = list(new_orders.keys())
            log.debug(('new active_orders = {} \nnew nonrespondants = '
                       '{}').format(
                    pprint.pformat(self.active_orders),
                    pprint.pformat(self.nonrespondants)))

            self.msgchan.fill_orders(new_orders, self.cj_amount,
                                     self.kp.hex_pk())
        else:
            log.debug('nonresponse to !tx')
            # nonresponding to !tx, have to restart tx from the beginning
            self.end_timeout_thread = True
            if self.finishcallback is not None:
                self.finishcallback(self)
                # finishcallback will check if self.all_responded is True and will know it came from here

    class TimeoutThread(threading.Thread):

        def __init__(self, cjtx):
            threading.Thread.__init__(self, name='TimeoutThread')
            self.cjtx = cjtx

        def run(self):
            log.debug(('started timeout thread for coinjoin of amount {} to '
                       'addr {}').format(self.cjtx.cj_amount,
                                         self.cjtx.my_cj_addr))

            # how the threading to check for nonresponding makers works like this
            # there is a Condition object
            # in a loop, call cond.wait(timeout)
            # after it returns, check a boolean
            # to see if if the messages have arrived
            while not self.cjtx.end_timeout_thread:
                log.debug('waiting for all replies.. timeout=' + str(
                        self.cjtx.maker_timeout_sec))
                with self.cjtx.timeout_lock:
                    self.cjtx.timeout_lock.wait(self.cjtx.maker_timeout_sec)
                with self.cjtx.timeout_thread_lock:
                    if self.cjtx.all_responded:
                        log.debug(('timeout thread woken by notify(), '
                                   'makers responded in time'))
                        self.cjtx.all_responded = False
                    else:
                        log.debug('timeout thread woken by timeout, '
                                  'makers didnt respond')
                        self.cjtx.recover_from_nonrespondants()


class CoinJoinerPeer(object):
    def __init__(self, msgchan):
        self.msgchan = msgchan

    def get_crypto_box_from_nick(self, nick):
        raise Exception()

    @staticmethod
    def on_set_topic(newtopic):
        chunks = newtopic.split('|')
        for msg in chunks[1:]:
            try:
                msg = msg.strip()
                params = msg.split(' ')
                min_version = int(params[0])
                max_version = int(params[1])
                alert = msg[msg.index(params[1]) + len(params[1]):].strip()
            except ValueError, IndexError:
                continue
            if min_version < jm_single().JM_VERSION < max_version:
                print('=' * 60)
                print('JOINMARKET ALERT')
                print(alert)
                print('=' * 60)
                jm_single().joinmarket_alert[0] = alert


class OrderbookWatch(CoinJoinerPeer):
    def __init__(self, msgchan):
        CoinJoinerPeer.__init__(self, msgchan)
        self.msgchan.register_orderbookwatch_callbacks(self.on_order_seen,
                                                       self.on_order_cancel)
        self.msgchan.register_channel_callbacks(
                self.on_welcome, self.on_set_topic, None, self.on_disconnect,
                self.on_nick_leave, None)

        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        self.db = con.cursor()
        self.db.execute("CREATE TABLE orderbook(counterparty TEXT, "
                        "oid INTEGER, ordertype TEXT, minsize INTEGER, "
                        "maxsize INTEGER, txfee INTEGER, cjfee TEXT);")

    def on_order_seen(self, counterparty, oid, ordertype, minsize, maxsize,
                      txfee, cjfee):
        try:
            if int(oid) < 0 or int(oid) > sys.maxint:
                log.debug(
                    "Got invalid order ID: " + oid + " from " + counterparty)
                return
            # delete orders eagerly, so in case a buggy maker sends an
            # invalid offer, we won't accidentally !fill based on the ghost
            # of its previous message.
            self.db.execute(("DELETE FROM orderbook WHERE counterparty=? "
                             "AND oid=?;"), (counterparty, oid))
            # now validate the remaining fields
            if int(minsize) < 0 or int(minsize) > 21 * 10 ** 14:
                log.debug("Got invalid minsize: {} from {}".format(
                        minsize, counterparty))
                return
            if int(minsize) < jm_single().DUST_THRESHOLD:
                minsize = jm_single().DUST_THRESHOLD
                log.debug("{} has dusty minsize, capping at {}".format(
                        counterparty, minsize))
                # do not pass return, go not drop this otherwise fine offer
            if int(maxsize) < 0 or int(maxsize) > 21 * 10 ** 14:
                log.debug("Got invalid maxsize: " + maxsize + " from " +
                          counterparty)
                return
            if int(txfee) < 0:
                log.debug("Got invalid txfee: {} from {}".format(
                        txfee, counterparty))
                return
            if int(minsize) > int(maxsize):

                fmt = ("Got minsize bigger than maxsize: {} - {} "
                       "from {}").format
                log.debug(fmt(minsize, maxsize, counterparty))
                return
            if ordertype == 'absorder' and not isinstance(cjfee, int):
                try:
                    cjfee = int(cjfee)
                except ValueError:
                    log.debug("Got non integer coinjoin fee: " + str(cjfee) +
                            " for an absorder from " + counterparty)
                    return
            self.db.execute(
                    'INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);',
                    (counterparty, oid, ordertype, minsize, maxsize, txfee,
                     str(Decimal(
                         cjfee))))  # any parseable Decimal is a valid cjfee
        except InvalidOperation:
            log.debug("Got invalid cjfee: " + cjfee + " from " + counterparty)
        except:
            log.debug("Error parsing order " + oid + " from " + counterparty)

    def on_order_cancel(self, counterparty, oid):
        self.db.execute(("DELETE FROM orderbook WHERE "
                         "counterparty=? AND oid=?;"), (counterparty, oid))

    def on_welcome(self):
        self.msgchan.request_orderbook()

    def on_nick_leave(self, nick):
        self.db.execute('DELETE FROM orderbook WHERE counterparty=?;', (nick,))

    def on_disconnect(self):
        self.db.execute('DELETE FROM orderbook;')


# assume this only has one open cj tx at a time
class Taker(OrderbookWatch):
    def __init__(self, msgchan):
        OrderbookWatch.__init__(self, msgchan)
        msgchan.register_taker_callbacks(self.on_error, self.on_pubkey,
                                         self.on_ioauth, self.on_sig)
        msgchan.cjpeer = self
        self.cjtx = None
        self.maker_pks = {}
        # TODO have a list of maker's nick we're coinjoining with, so
        # that some other guy doesnt send you confusing stuff

    def get_crypto_box_from_nick(self, nick):
        if nick in self.cjtx.crypto_boxes:
            return self.cjtx.crypto_boxes[nick][
                1]  # libsodium encryption object
        else:
            log.debug('something wrong, no crypto object, nick=' + nick +
                      ', message will be dropped')
            return None

    def start_cj(self,
                 wallet,
                 cj_amount,
                 orders,
                 input_utxos,
                 my_cj_addr,
                 my_change_addr,
                 total_txfee,
                 finishcallback=None,
                 choose_orders_recover=None,
                 auth_addr=None):
        self.cjtx = None
        self.cjtx = CoinJoinTX(
                self.msgchan, wallet, self.db, cj_amount, orders,
                input_utxos, my_cj_addr, my_change_addr,
                total_txfee, finishcallback,
                choose_orders_recover, auth_addr)

    def on_error(self):
        pass  # TODO implement

    def on_pubkey(self, nick, maker_pubkey):
        #It's possible that the CoinJoinTX object is
        #not yet created (__init__ call not finished).
        while not self.cjtx:
            time.sleep(0.5)
        self.cjtx.start_encryption(nick, maker_pubkey)

    def on_ioauth(self, nick, utxo_list, cj_pub, change_addr, btc_sig):
        if not self.cjtx.auth_counterparty(nick, btc_sig, cj_pub):
            fmt = ('Authenticated encryption with counterparty: {}'
                    ' not established. TODO: send rejection message').format
            log.debug(fmt(nick))
            return
        with self.cjtx.timeout_thread_lock:
            self.cjtx.recv_txio(nick, utxo_list, cj_pub, change_addr)

    def on_sig(self, nick, sig):
        with self.cjtx.timeout_thread_lock:
            self.cjtx.add_signature(nick, sig)


# this stuff copied and slightly modified from pybitcointools
def donation_address(cjtx):
    from bitcoin.main import multiply, G, deterministic_generate_k, add_pubkeys
    reusable_donation_pubkey = ('02be838257fbfddabaea03afbb9f16e852'
                                '9dfe2de921260a5c46036d97b5eacf2a')

    donation_utxo_data = cjtx.input_utxos.iteritems().next()
    global donation_utxo
    donation_utxo = donation_utxo_data[0]
    privkey = cjtx.wallet.get_key_from_addr(donation_utxo_data[1]['address'])
    # tx without our inputs and outputs
    tx = btc.mktx(cjtx.utxo_tx, cjtx.outputs)
    msghash = btc.bin_txhash(tx, btc.SIGHASH_ALL)
    # generate unpredictable k
    global sign_k
    sign_k = deterministic_generate_k(msghash, privkey)
    c = btc.sha256(multiply(reusable_donation_pubkey, sign_k))
    sender_pubkey = add_pubkeys(
            reusable_donation_pubkey, multiply(
                    G, c))
    sender_address = btc.pubtoaddr(sender_pubkey, get_p2pk_vbyte())
    log.debug('sending coins to ' + sender_address)
    return sender_address


def sign_donation_tx(tx, i, priv):
    from bitcoin.main import fast_multiply, decode_privkey, G, inv, N
    from bitcoin.transaction import der_encode_sig
    k = sign_k
    hashcode = btc.SIGHASH_ALL
    i = int(i)
    if len(priv) <= 33:
        priv = btc.safe_hexlify(priv)
    pub = btc.privkey_to_pubkey(priv)
    address = btc.pubkey_to_address(pub)
    signing_tx = btc.signature_form(
            tx, i, btc.mk_pubkey_script(address), hashcode)

    msghash = btc.bin_txhash(signing_tx, hashcode)
    z = btc.hash_to_int(msghash)
    # k = deterministic_generate_k(msghash, priv)
    r, y = fast_multiply(G, k)
    s = inv(k, N) * (z + r * decode_privkey(priv)) % N
    rawsig = 27 + (y % 2), r, s

    sig = der_encode_sig(*rawsig) + btc.encode(hashcode, 16, 2)
    # sig = ecdsa_tx_sign(signing_tx, priv, hashcode)
    txobj = btc.deserialize(tx)
    txobj["ins"][i]["script"] = btc.serialize_script([sig, pub])
    return btc.serialize(txobj)
