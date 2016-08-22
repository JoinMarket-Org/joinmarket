#! /usr/bin/env python
from __future__ import absolute_import, print_function

import base64
import pprint
import random
import sqlite3
import sys
import time
import threading
import json
from decimal import InvalidOperation, Decimal

import bitcoin as btc
from joinmarket.configure import jm_single, get_p2pk_vbyte, donation_address
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
                 commitment_creator
                 ):
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
        self.commitment_creator = commitment_creator
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
        # None means they belong to me
        self.utxos = {None: self.input_utxos.keys()}
        self.outputs = []
        # create DH keypair on the fly for this Tx object
        self.kp = init_keypair()
        self.crypto_boxes = {}
        self.get_commitment(input_utxos, self.cj_amount)
        self.msgchan.fill_orders(self.active_orders, self.cj_amount,
                                 self.kp.hex_pk(), self.commitment)

    def get_commitment(self, utxos, amount):
        """Create commitment to fulfil anti-DOS requirement of makers,
        storing the corresponding reveal/proof data for next step.
        """
        while True:
            self.commitment, self.reveal_commitment = self.commitment_creator(
                self.wallet, utxos, amount)
            if (self.commitment) or (jm_single().wait_for_commitments == 0):
                break
            log.debug("Failed to source commitments, waiting 3 minutes")
            time.sleep(3 * 60)
        if not self.commitment:
            log.debug("Cannot construct transaction, failed to generate "
                    "commitment, shutting down. Please read commitments_debug.txt "
                      "for some information on why this is, and what can be "
                      "done to remedy it.")
            #TODO: would like to raw_input here to show the user, but
            #interactivity is undesirable here.
            #Test only:
            if jm_single().config.get(
                "BLOCKCHAIN", "blockchain_source") == 'regtest':
                raise btc.PoDLEError("For testing raising podle exception")
            #The timeout/recovery code is designed to handle non-responsive
            #counterparties, but this condition means that the current bot
            #is not able to create transactions following its *own* rules,
            #so shutting down is appropriate no matter what style
            #of bot this is.
            #These two settings shut down the timeout thread and avoid recovery.
            self.all_responded = True
            self.end_timeout_thread = True
            self.msgchan.shutdown()

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

        self.msgchan.send_auth(nick, self.reveal_commitment)

    def auth_counterparty(self, nick, btc_sig, auth_pub):
        """Validate the counterpartys claim to own the btc
        address/pubkey that will be used for coinjoining
        with an ecdsa verification.
        Note that this is only a first-step
        authorisation; it checks the btc signature, but
        the authorising pubkey is checked to be part of the
        transactoin in recv_txio.
        """
        if not btc.ecdsa_verify(self.crypto_boxes[nick][0], btc_sig, auth_pub):
            log.debug('signature didnt match pubkey and message')
            return False
        return True

    def recv_txio(self, nick, utxo_list, auth_pub, cj_addr, change_addr):
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
        #Complete maker authorization:
        #Extract the address fields from the utxos
        #Construct the Bitcoin address for the auth_pub field
        #Ensure that at least one address from utxos corresponds.
        input_addresses = [d['address'] for d in utxo_data]
        auth_address = btc.pubkey_to_address(auth_pub, get_p2pk_vbyte())
        if not auth_address in input_addresses:
            log.debug("ERROR maker's authorising pubkey is not included "
                      "in the transaction: " + str(auth_address))
            return

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
            addr, self.sign_k = donation_address()
            return addr

    def sign_tx(self, tx, i, priv):
        if self.my_cj_addr:
            return btc.sign(tx, i, priv)
        else:
            return btc.sign(tx, i, priv, usenonce=btc.safe_from_hex(self.sign_k))

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
            #Re-source commitment; previous attempt will have been blacklisted
            self.get_commitment(self.input_utxos, self.cj_amount)
            self.msgchan.fill_orders(new_orders, self.cj_amount,
                                     self.kp.hex_pk(), self.commitment)
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
        self.dblock = threading.Lock()
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        self.db = con.cursor()
        self.db.execute("CREATE TABLE orderbook(counterparty TEXT, "
                        "oid INTEGER, ordertype TEXT, minsize INTEGER, "
                        "maxsize INTEGER, txfee INTEGER, cjfee TEXT);")

    def on_order_seen(self, counterparty, oid, ordertype, minsize, maxsize,
                      txfee, cjfee):
        try:
            self.dblock.acquire(True)
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
            if ordertype == 'absoffer' and not isinstance(cjfee, int):
                try:
                    cjfee = int(cjfee)
                except ValueError:
                    log.debug("Got non integer coinjoin fee: " + str(cjfee) +
                            " for an absoffer from " + counterparty)
                    return
            self.db.execute(
                    'INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);',
                    (counterparty, oid, ordertype, minsize, maxsize, txfee,
                     str(Decimal(
                         cjfee))))  # any parseable Decimal is a valid cjfee
        except InvalidOperation:
            log.debug("Got invalid cjfee: " + cjfee + " from " + counterparty)
        except Exception as e:
            log.debug("Error parsing order " + oid + " from " + counterparty)
            log.debug("Exception was: " + repr(e))
        finally:
            self.dblock.release()

    def on_order_cancel(self, counterparty, oid):
        with self.dblock:
            self.db.execute(("DELETE FROM orderbook WHERE "
                         "counterparty=? AND oid=?;"), (counterparty, oid))

    def on_welcome(self):
        self.msgchan.request_orderbook()

    def on_nick_leave(self, nick):
        with self.dblock:
            self.db.execute('DELETE FROM orderbook WHERE counterparty=?;', (nick,))

    def on_disconnect(self):
        with self.dblock:
            self.db.execute('DELETE FROM orderbook;')


# assume this only has one open cj tx at a time
class Taker(OrderbookWatch):
    def __init__(self, msgchan):
        OrderbookWatch.__init__(self, msgchan)
        msgchan.register_taker_callbacks(self.on_error, self.on_pubkey,
                                         self.on_ioauth, self.on_sig)
        msgchan.set_cjpeer(self)
        self.cjtx = None
        self.maker_pks = {}
        # TODO have a list of maker's nick we're coinjoining with, so
        # that some other guy doesnt send you confusing stuff

    def get_crypto_box_from_nick(self, nick):
        if nick in self.cjtx.crypto_boxes and self.cjtx.crypto_boxes[nick] != None:
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
                 choose_orders_recover=None
                 ):
        self.cjtx = None
        #needed during commitment preparation, self.cjtx.cj_amount
        #will be the amount after CoinJoinTx.__init__() completes.
        #(and same for self.cjtx.wallet)
        self.proposed_cj_amount = cj_amount
        self.proposed_wallet = wallet
        self.cjtx = CoinJoinTX(
                self.msgchan, wallet, self.db, cj_amount, orders,
                input_utxos, my_cj_addr, my_change_addr,
                total_txfee, finishcallback,
                choose_orders_recover, self.make_commitment)

    def on_error(self):
        pass  # TODO implement

    def on_pubkey(self, nick, maker_pubkey):
        #It's possible that the CoinJoinTX object is
        #not yet created (__init__ call not finished).
        while not self.cjtx:
            time.sleep(0.5)
        self.cjtx.start_encryption(nick, maker_pubkey)

    def on_ioauth(self, nick, utxo_list, auth_pub, cj_addr, change_addr, btc_sig):
        if not self.cjtx.auth_counterparty(nick, btc_sig, auth_pub):
            fmt = ('Authenticated encryption with counterparty: {}'
                    ' not established. TODO: send rejection message').format
            log.debug(fmt(nick))
            return
        with self.cjtx.timeout_thread_lock:
            self.cjtx.recv_txio(nick, utxo_list, auth_pub, cj_addr, change_addr)

    def on_sig(self, nick, sig):
        with self.cjtx.timeout_thread_lock:
            self.cjtx.add_signature(nick, sig)

    def make_commitment(self, wallet, input_utxos, cjamount):
        """The Taker default commitment function, which uses PoDLE.
        Alternative commitment types should use a different commit type byte.
        This will allow future upgrades to provide different style commitments
        by subclassing Taker and changing the commit_type_byte; existing makers
        will simply not accept this new type of commitment.
        In case of success, return the commitment and its opening.
        In case of failure returns (None, None) and constructs a detailed
        log for the user to read and discern the reason.
        """

        def filter_by_coin_age_amt(utxos, age, amt):
            results = jm_single().bc_interface.query_utxo_set(utxos,
                                                              includeconf=True)
            newresults = []
            too_old = []
            too_small = []
            for i, r in enumerate(results):
                #results return "None" if txo is spent; drop this
                if not r:
                    continue
                valid_age = r['confirms'] >= age
                valid_amt = r['value'] >= amt
                if not valid_age:
                    too_old.append(utxos[i])
                if not valid_amt:
                    too_small.append(utxos[i])
                if valid_age and valid_amt:
                    newresults.append(utxos[i])

            return newresults, too_old, too_small

        def priv_utxo_pairs_from_utxos(utxos, age, amt):
            #returns pairs list of (priv, utxo) for each valid utxo;
            #also returns lists "too_old" and "too_small" for any
            #utxos that did not satisfy the criteria for debugging.
            priv_utxo_pairs = []
            new_utxos, too_old, too_small = filter_by_coin_age_amt(
                utxos.keys(), age, amt)
            new_utxos_dict = {k: v for k, v in utxos.items() if k in new_utxos}
            for k, v in new_utxos_dict.iteritems():
                addr = v['address']
                priv = wallet.get_key_from_addr(addr)
                if priv: #can be null from create-unsigned
                    priv_utxo_pairs.append((priv, k))
            return priv_utxo_pairs, too_old, too_small

        commit_type_byte = "P"
        podle_data = None
        tries = jm_single().config.getint("POLICY", "taker_utxo_retries")
        age = jm_single().config.getint("POLICY", "taker_utxo_age")
        #Minor rounding errors don't matter here
        amt = int(cjamount * jm_single().config.getint(
            "POLICY", "taker_utxo_amtpercent") / 100.0)
        priv_utxo_pairs, to, ts = priv_utxo_pairs_from_utxos(input_utxos, age, amt)
        #Note that we ignore the "too old" and "too small" lists in the first
        #pass through, because the same utxos appear in the whole-wallet check.

        #For podle data format see: btc.podle.PoDLE.reveal()
        #In first round try, don't use external commitments
        podle_data = btc.generate_podle(priv_utxo_pairs, tries)
        if not podle_data:
            #We defer to a second round to try *all* utxos in wallet;
            #this is because it's much cleaner to use the utxos involved
            #in the transaction, about to be consumed, rather than use
            #random utxos that will persist after. At this step we also
            #allow use of external utxos in the json file.
            if wallet.unspent:
                priv_utxo_pairs, to, ts = priv_utxo_pairs_from_utxos(
                    wallet.unspent, age, amt)
            #Pre-filter the set of external commitments that work for this
            #transaction according to its size and age.
            dummy, extdict = btc.get_podle_commitments()
            ext_valid, ext_to, ext_ts = filter_by_coin_age_amt(extdict.keys(),
                                                               age, amt)
            podle_data = btc.generate_podle(priv_utxo_pairs, tries, ext_valid)
        if podle_data:
            log.debug("Generated PoDLE: " + pprint.pformat(podle_data))
            revelation = btc.PoDLE(u=podle_data['utxo'],P=podle_data['P'],
                                   P2=podle_data['P2'],s=podle_data['sig'],
                                   e=podle_data['e']).serialize_revelation()
            return (commit_type_byte + podle_data["commit"], revelation)
        else:
            #we know that priv_utxo_pairs all passed age and size tests, so
            #they must have failed the retries test. Summarize this info
            #and publish to commitments_debug.txt
            with open("commitments_debug.txt", "wb") as f:
                f.write("THIS IS A TEMPORARY FILE FOR DEBUGGING; "
                            "IT CAN BE SAFELY DELETED ANY TIME.\n")
                f.write("***\n")
                f.write("1: Utxos that passed age and size limits, but have "
                            "been used too many times (see taker_utxo_retries "
                            "in the config):\n")
                if len(priv_utxo_pairs) == 0:
                    f.write("None\n")
                else:
                    for p, u in priv_utxo_pairs:
                        f.write(str(u) + "\n")
                f.write("2: Utxos that have less than " + jm_single().config.get(
                    "POLICY", "taker_utxo_age") + " confirmations:\n")
                if len(to) == 0:
                    f.write("None\n")
                else:
                    for t in to:
                        f.write(str(t) + "\n")
                f.write("3: Utxos that were not at least " + \
                        jm_single().config.get(
                            "POLICY", "taker_utxo_amtpercent") + "% of the "
                        "size of the coinjoin amount " + str(
                            self.proposed_cj_amount) + "\n")
                if len(ts) == 0:
                    f.write("None\n")
                else:
                    for t in ts:
                        f.write(str(t) + "\n")
                f.write('***\n')
                f.write("Utxos that appeared in item 1 cannot be used again.\n")
                f.write("Utxos only in item 2 can be used by waiting for more "
                        "confirmations, (set by the value of taker_utxo_age).\n")
                f.write("Utxos only in item 3 are not big enough for this "
                        "coinjoin transaction, set by the value "
                        "of taker_utxo_amtpercent.\n")
                f.write("If you cannot source a utxo from your wallet according "
                        "to these rules, use the tool add-utxo.py to source a "
                        "utxo external to your joinmarket wallet. Read the help "
                        "with 'python add-utxo.py --help'\n\n")
                f.write("You can also reset the rules in the joinmarket.cfg "
                        "file, but this is generally inadvisable.\n")
                f.write("***\nFor reference, here are the utxos in your wallet:\n")
                f.write("\n" + str(self.proposed_wallet.unspent))

            return (None, None)


