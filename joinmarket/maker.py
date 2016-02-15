#! /usr/bin/env python
from __future__ import absolute_import, print_function

import base64
import pprint
import sys
import threading

import bitcoin as btc
from joinmarket import IRCMessageChannel
from joinmarket.configure import get_p2pk_vbyte, load_program_config, jm_single
from joinmarket.enc_wrapper import init_keypair, as_init_encryption, init_pubkey

from joinmarket.support import get_log, calc_cj_fee, debug_dump_object
from joinmarket.taker import CoinJoinerPeer
from joinmarket.wallet import Wallet

log = get_log()


class CoinJoinOrder(object):
    def __init__(self, maker, nick, oid, amount, taker_pk):
        self.tx = None
        self.i_utxo_pubkey = None

        self.maker = maker
        self.oid = oid
        self.cj_amount = amount
        if self.cj_amount <= jm_single().DUST_THRESHOLD:
            self.maker.msgchan.send_error(nick, 'amount below dust threshold')
        # the btc pubkey of the utxo that the taker plans to use as input
        self.taker_pk = taker_pk
        # create DH keypair on the fly for this Order object
        self.kp = init_keypair()
        # the encryption channel crypto box for this Order object
        self.crypto_box = as_init_encryption(self.kp,
                                             init_pubkey(taker_pk))

        order_s = [o for o in maker.orderlist if o['oid'] == oid]
        if len(order_s) == 0:
            self.maker.msgchan.send_error(nick, 'oid not found')
        order = order_s[0]
        if amount < order['minsize'] or amount > order['maxsize']:
            self.maker.msgchan.send_error(nick, 'amount out of range')
        self.ordertype = order['ordertype']
        self.txfee = order['txfee']
        self.cjfee = order['cjfee']
        log.debug('new cjorder nick=%s oid=%d amount=%d' % (nick, oid, amount))
        self.utxos, self.cj_addr, self.change_addr = maker.oid_to_order(
                self, oid, amount)
        self.maker.wallet.update_cache_index()
        if not self.utxos:
            self.maker.msgchan.send_error(
                    nick, 'unable to fill order constrained by dust avoidance')
            # TODO make up orders offers in a way that this error cant appear
            #  check nothing has messed up with the wallet code, remove this
            # code after a while
        import pprint
        log.debug('maker utxos = ' + pprint.pformat(self.utxos))
        utxo_list = self.utxos.keys()
        utxo_data = jm_single().bc_interface.query_utxo_set(utxo_list)
        if None in utxo_data:
            log.debug('wrongly using an already spent utxo. utxo_data = ' +
                      pprint.pformat(utxo_data))
            sys.exit(0)
        for utxo, data in zip(utxo_list, utxo_data):
            if self.utxos[utxo]['value'] != data['value']:
                fmt = 'wrongly labeled utxo, expected value: {} got {}'.format
                log.debug(fmt(self.utxos[utxo]['value'], data['value']))
                sys.exit(0)

        # always a new address even if the order ends up never being
        # furfilled, you dont want someone pretending to fill all your
        # orders to find out which addresses you use
        self.maker.msgchan.send_pubkey(nick, self.kp.hex_pk())

    def auth_counterparty(self, nick, i_utxo_pubkey, btc_sig):
        self.i_utxo_pubkey = i_utxo_pubkey

        if not btc.ecdsa_verify(self.taker_pk, btc_sig, self.i_utxo_pubkey):
            print('signature didnt match pubkey and message')
            return False
        # authorisation of taker passed
        # (but input utxo pubkey is checked in verify_unsigned_tx).
        # Send auth request to taker
        # TODO the next 2 lines are a little inefficient.
        btc_key = self.maker.wallet.get_key_from_addr(self.cj_addr)
        btc_pub = btc.privtopub(btc_key)
        btc_sig = btc.ecdsa_sign(self.kp.hex_pk(), btc_key)
        self.maker.msgchan.send_ioauth(nick, self.utxos.keys(), btc_pub,
                                       self.change_addr, btc_sig)
        return True

    def recv_tx(self, nick, txhex):
        try:
            self.tx = btc.deserialize(txhex)
        except IndexError as e:
            self.maker.msgchan.send_error(nick, 'malformed txhex. ' + repr(e))
        log.debug('obtained tx\n' + pprint.pformat(self.tx))
        goodtx, errmsg = self.verify_unsigned_tx(self.tx)
        if not goodtx:
            log.debug('not a good tx, reason=' + errmsg)
            self.maker.msgchan.send_error(nick, errmsg)
        # TODO: the above 3 errors should be encrypted, but it's a bit messy.
        log.debug('goodtx')
        sigs = []
        for index, ins in enumerate(self.tx['ins']):
            utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
            if utxo not in self.utxos:
                continue
            addr = self.utxos[utxo]['address']
            txs = btc.sign(txhex, index,
                           self.maker.wallet.get_key_from_addr(addr))
            sigs.append(base64.b64encode(btc.deserialize(txs)['ins'][index][
                                             'script'].decode('hex')))
        # len(sigs) > 0 guarenteed since i did verify_unsigned_tx()

        jm_single().bc_interface.add_tx_notify(
                self.tx, self.unconfirm_callback,
                self.confirm_callback, self.cj_addr)
        log.debug('sending sigs ' + str(sigs))
        self.maker.msgchan.send_sigs(nick, sigs)
        self.maker.active_orders[nick] = None

    def unconfirm_callback(self, txd, txid):
        self.maker.wallet_unspent_lock.acquire()
        try:
            removed_utxos = self.maker.wallet.remove_old_utxos(self.tx)
        finally:
            self.maker.wallet_unspent_lock.release()
        log.debug('saw tx on network, removed_utxos=\n{}'.format(
                pprint.pformat(removed_utxos)))
        to_cancel, to_announce = self.maker.on_tx_unconfirmed(
                self, txid, removed_utxos)
        self.maker.modify_orders(to_cancel, to_announce)

    def confirm_callback(self, txd, txid, confirmations):
        self.maker.wallet_unspent_lock.acquire()
        try:
            jm_single().bc_interface.sync_unspent(self.maker.wallet)
        finally:
            self.maker.wallet_unspent_lock.release()
        log.debug('tx in a block')
        log.debug('earned = ' + str(self.real_cjfee - self.txfee))
        to_cancel, to_announce = self.maker.on_tx_confirmed(self, confirmations,
                                                            txid)
        self.maker.modify_orders(to_cancel, to_announce)

    def verify_unsigned_tx(self, txd):
        tx_utxo_set = set(ins['outpoint']['hash'] + ':' + str(
                ins['outpoint']['index']) for ins in txd['ins'])
        # complete authentication: check the tx input uses the authing pubkey
        input_utxo_data = jm_single().bc_interface.query_utxo_set(
                list(tx_utxo_set))

        if None in input_utxo_data:
            return False, 'some utxos already spent or not confirmed yet'
        input_addresses = [u['address'] for u in input_utxo_data]
        if btc.pubtoaddr(
                self.i_utxo_pubkey, get_p2pk_vbyte()) not in input_addresses:
            return False, "authenticating bitcoin address is not contained"

        my_utxo_set = set(self.utxos.keys())
        if not tx_utxo_set.issuperset(my_utxo_set):
            return False, 'my utxos are not contained'

        my_total_in = sum([va['value'] for va in self.utxos.values()])
        self.real_cjfee = calc_cj_fee(
                self.ordertype, self.cjfee, self.cj_amount)
        expected_change_value = (
            my_total_in - self.cj_amount - self.txfee + self.real_cjfee)
        log.debug('potentially earned = {}'.format(
                self.real_cjfee - self.txfee))
        log.debug('mycjaddr, mychange = {}, {}'.format(
                self.cj_addr, self.change_addr))

        times_seen_cj_addr = 0
        times_seen_change_addr = 0
        for outs in txd['outs']:
            addr = btc.script_to_address(outs['script'], get_p2pk_vbyte())
            if addr == self.cj_addr:
                times_seen_cj_addr += 1
                if outs['value'] != self.cj_amount:
                    return False, 'Wrong cj_amount. I expect ' + str(
                            self.cj_amount)
            if addr == self.change_addr:
                times_seen_change_addr += 1
                if outs['value'] != expected_change_value:
                    return False, 'wrong change, i expect ' + str(
                            expected_change_value)
        if times_seen_cj_addr != 1 or times_seen_change_addr != 1:
            fmt = ('cj or change addr not in tx '
                   'outputs once, #cjaddr={}, #chaddr={}').format
            return False, (fmt(times_seen_cj_addr, times_seen_change_addr))
        return True, None


class CJMakerOrderError(StandardError):
    pass


class Maker(CoinJoinerPeer):
    def __init__(self, msgchan, wallet):
        CoinJoinerPeer.__init__(self, msgchan)
        self.msgchan.register_channel_callbacks(self.on_welcome,
                                                self.on_set_topic, None, None,
                                                self.on_nick_leave, None)
        msgchan.register_maker_callbacks(self.on_orderbook_requested,
                                         self.on_order_fill, self.on_seen_auth,
                                         self.on_seen_tx, self.on_push_tx)
        msgchan.cjpeer = self

        self.active_orders = {}
        self.wallet = wallet
        self.nextoid = -1
        if not self.msgchan.newnyms:
            self.orderlist = self.create_my_orders()
        self.wallet_unspent_lock = threading.Lock()

    def get_crypto_box_from_nick(self, nick):
        if nick not in self.active_orders:
            log.debug(
                'wrong ordering of protocol events, no crypto object, nick=' +
                nick)
            return None
        else:
            return self.active_orders[nick].crypto_box

    def on_orderbook_requested(self, nick):
        self.msgchan.announce_orders(self.orderlist, nick)

    def on_order_fill(self, nick, oid, amount, taker_pubkey):
        if nick in self.active_orders and self.active_orders[nick] is not None:
            self.active_orders[nick] = None
            log.debug('had a partially filled order but starting over now')
        self.wallet_unspent_lock.acquire()
        try:
            self.active_orders[nick] = CoinJoinOrder(self, nick, oid, amount,
                                                     taker_pubkey)
        finally:
            self.wallet_unspent_lock.release()

    def on_seen_auth(self, nick, pubkey, sig):
        if nick not in self.active_orders or self.active_orders[nick] is None:
            self.msgchan.send_error(nick, 'No open order from this nick')
        self.active_orders[nick].auth_counterparty(nick, pubkey, sig)
        # TODO if auth_counterparty returns false, remove this order from active_orders
        # and send an error

    def on_seen_tx(self, nick, txhex):
        if nick not in self.active_orders or self.active_orders[nick] is None:
            self.msgchan.send_error(nick, 'No open order from this nick')
        self.wallet_unspent_lock.acquire()
        try:
            self.active_orders[nick].recv_tx(nick, txhex)
        finally:
            self.wallet_unspent_lock.release()

    def on_push_tx(self, nick, txhex):
        log.debug('received txhex from ' + nick + ' to push\n' + txhex)
        pushed = jm_single().bc_interface.pushtx(txhex)
        if pushed[0]:
            log.debug('pushed tx ' + str(pushed[1]))
        else:
            log.debug('failed to push tx, reason: '+str(pushed[1]))
            self.msgchan.send_error(nick, 'Unable to push tx')

    def on_welcome(self):
        if self.msgchan.newnyms:
            self.orderlist = self.create_my_orders()
        self.msgchan.announce_orders(self.orderlist)
        self.active_orders = {}

    def on_nick_leave(self, nick):
        if nick in self.active_orders:
            log.debug('nick ' + nick + ' has left')
            del self.active_orders[nick]

    def modify_orders(self, to_cancel, to_announce):
        log.debug('modifying orders. to_cancel={}\nto_announce={}'.format(
                to_cancel, to_announce))
        for oid in to_cancel:
            order = [o for o in self.orderlist if o['oid'] == oid]
            if len(order) == 0:
                fmt = 'didnt cancel order which doesnt exist, oid={}'.format
                log.debug(fmt(oid))
            self.orderlist.remove(order[0])
        if len(to_cancel) > 0:
            self.msgchan.cancel_orders(to_cancel)
        if len(to_announce) > 0:
            self.msgchan.announce_orders(to_announce)
            for ann in to_announce:
                oldorder_s = [order for order in self.orderlist
                              if order['oid'] == ann['oid']]
                if len(oldorder_s) > 0:
                    self.orderlist.remove(oldorder_s[0])
            self.orderlist += to_announce

    # these functions
    # create_my_orders()
    # oid_to_uxto()
    # on_tx_unconfirmed()
    # on_tx_confirmed()
    # define the sell-side pricing algorithm of this bot
    # still might be a bad way of doing things, we'll see
    def create_my_orders(self):
        """
		#tells the highest value possible made by combining all utxos
		#fee is 0.2% of the cj amount
		total_value = 0
		for utxo, addrvalue in self.wallet.unspent.iteritems():
			total_value += addrvalue['value']

		order = {'oid': 0, 'ordertype': 'relorder', 'minsize': 0,
			'maxsize': total_value, 'txfee': 10000, 'cjfee': '0.002'}
		return [order]
		"""

        # each utxo is a single absolute-fee order
        orderlist = []
        for utxo, addrvalue in self.wallet.unspent.iteritems():
            order = {'oid': self.get_next_oid(),
                     'ordertype': 'absorder',
                     'minsize': 12000,
                     'maxsize': addrvalue['value'],
                     'txfee': 10000,
                     'cjfee': 100000,
                     'utxo': utxo,
                     'mixdepth':
                         self.wallet.addr_cache[addrvalue['address']][0]}
            orderlist.append(order)
        # yes you can add keys there that are never used by the rest of the
        # Maker code so im adding utxo and mixdepth here
        return orderlist

        # has to return a list of utxos and mixing depth the cj address will
        # be in the change address will be in mixing_depth-1

    def oid_to_order(self, cjorder, oid, amount):
        """
		unspent = []
		for utxo, addrvalue in self.wallet.unspent.iteritems():
			unspent.append({'value': addrvalue['value'], 'utxo': utxo})
		inputs = btc.select(unspent, amount)
		#TODO this raises an exception if you dont have enough money, id rather it just returned None
		mixing_depth = 1
		return [i['utxo'] for i in inputs], mixing_depth
		"""

        order = [o for o in self.orderlist if o['oid'] == oid][0]
        cj_addr = self.wallet.get_internal_addr(order['mixdepth'] + 1)
        change_addr = self.wallet.get_internal_addr(order['mixdepth'])
        return [order['utxo']], cj_addr, change_addr

    def get_next_oid(self):
        self.nextoid += 1
        return self.nextoid

    # gets called when the tx is seen on the network
    # must return which orders to cancel or recreate
    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        return [cjorder.oid], []

    # gets called when the tx is included in a block
    # must return which orders to cancel or recreate
    # and i have to think about how that will work for both
    # the blockchain explorer api method and the bitcoid walletnotify
    def on_tx_confirmed(self, cjorder, confirmations, txid):
        to_announce = []
        for i, out in enumerate(cjorder.tx['outs']):
            addr = btc.script_to_address(out['script'], get_p2pk_vbyte())
            if addr == cjorder.change_addr:
                neworder = {'oid': self.get_next_oid(),
                            'ordertype': 'absorder',
                            'minsize': 12000,
                            'maxsize': out['value'],
                            'txfee': 10000,
                            'cjfee': 100000,
                            'utxo': txid + ':' + str(i)}
                to_announce.append(neworder)
            if addr == cjorder.cj_addr:
                neworder = {'oid': self.get_next_oid(),
                            'ordertype': 'absorder',
                            'minsize': 12000,
                            'maxsize': out['value'],
                            'txfee': 10000,
                            'cjfee': 100000,
                            'utxo': txid + ':' + str(i)}
                to_announce.append(neworder)
        return [], to_announce


def main():
    from socket import gethostname
    nickname = 'cj-maker-' + btc.sha256(gethostname())[:6]
    import sys
    seed = sys.argv[
        1
    ]  # btc.sha256('dont use brainwallets except for holding testnet coins')

    load_program_config()
    wallet = Wallet(seed, max_mix_depth=5)
    jm_single().bc_interface.sync_wallet(wallet)

    irc = IRCMessageChannel(nickname)
    maker = Maker(irc, wallet)
    try:
        print('connecting to irc')
        irc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        log.debug('wallet seed = ' + seed)
        debug_dump_object(wallet, ['addr_cache'])
        debug_dump_object(maker)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
    print('done')
