#! /usr/bin/env python

from common import *
import enc_wrapper
import bitcoin as btc

import sqlite3, base64, threading, time, random


class CoinJoinTX(object):
    #soon the taker argument will be removed and just be replaced by wallet or some other interface
    def __init__(self,
                 msgchan,
                 taker,
                 cj_amount,
                 orders,
                 my_utxos,
                 my_cj_addr,
                 my_change_addr,
                 my_txfee,
                 finishcallback=None):
        '''
		if my_change is None then there wont be a change address
		thats used if you want to entirely coinjoin one utxo with no change left over
		orders is the orders you want to fill {'counterpartynick': oid, 'cp2': oid2}
		'''
        debug('starting cj to ' + my_cj_addr + ' with change at ' + str(
            my_change_addr))
        self.msgchan = msgchan
        self.taker = taker
        self.cj_amount = cj_amount
        self.active_orders = dict(orders)
        self.nonrespondants = list(orders.keys())
        self.my_utxos = my_utxos
        self.utxos = {None: my_utxos}  #None means they belong to me
        self.finishcallback = finishcallback
        self.my_txfee = my_txfee
        self.outputs = [{'address': my_cj_addr, 'value': self.cj_amount}]
        self.my_change_addr = my_change_addr
        self.cjfee_total = 0
        self.latest_tx = None
        #create DH keypair on the fly for this Tx object
        self.kp = enc_wrapper.init_keypair()
        self.crypto_boxes = {}
        #find the btc pubkey of the first utxo being used
        self.signing_btc_add = taker.wallet.unspent[self.my_utxos[0]]['address']
        self.signing_btc_pub = btc.privtopub(taker.wallet.get_key_from_addr(
            self.signing_btc_add))
        self.msgchan.fill_orders(orders, cj_amount, self.kp.hex_pk())

    def start_encryption(self, nick, maker_pk):
        if nick not in self.active_orders.keys():
            raise Exception("Counterparty not part of this transaction.")
        self.crypto_boxes[nick] = [maker_pk, enc_wrapper.as_init_encryption(\
                                self.kp, enc_wrapper.init_pubkey(maker_pk))]
        #send authorisation request
        my_btc_priv = self.taker.wallet.get_key_from_addr(\
                self.taker.wallet.unspent[self.my_utxos[0]]['address'])
        my_btc_pub = btc.privtopub(my_btc_priv)
        my_btc_sig = btc.ecdsa_sign(self.kp.hex_pk(), my_btc_priv)
        self.msgchan.send_auth(nick, my_btc_pub, my_btc_sig)

    def auth_counterparty(self, nick, btc_sig, cj_pub):
        '''Validate the counterpartys claim to own the btc
		address/pubkey that will be used for coinjoining 
		with an ecdsa verification.'''
        if not btc.ecdsa_verify(self.crypto_boxes[nick][0], btc_sig, cj_pub):
            print 'signature didnt match pubkey and message'
            return False
        return True

    def recv_txio(self, nick, utxo_list, cj_pub, change_addr):
        cj_addr = btc.pubtoaddr(cj_pub, get_addr_vbyte())
        if nick not in self.nonrespondants:
            debug('nick(' + nick + ') not in nonrespondants ' + str(
                self.nonrespondants))
            return
        self.utxos[nick] = utxo_list
        self.nonrespondants.remove(nick)
        order = self.taker.db.execute(
            'SELECT ordertype, txfee, cjfee FROM '
            'orderbook WHERE oid=? AND counterparty=?',
            (self.active_orders[nick], nick)).fetchone()
        total_input = calc_total_input_value(self.utxos[nick])
        real_cjfee = calc_cj_fee(order['ordertype'], order['cjfee'],
                                 self.cj_amount)
        self.outputs.append({'address': change_addr,
                             'value': total_input - self.cj_amount - order[
                                 'txfee'] + real_cjfee})
        print 'fee breakdown for %s totalin=%d cjamount=%d txfee=%d realcjfee=%d' % (
            nick, total_input, self.cj_amount, order['txfee'], real_cjfee)
        self.outputs.append({'address': cj_addr, 'value': self.cj_amount})
        self.cjfee_total += real_cjfee
        if len(self.nonrespondants) > 0:
            return
        debug('got all parts, enough to build a tx cjfeetotal=' + str(
            self.cjfee_total))

        my_total_in = 0
        for u in self.my_utxos:
            usvals = self.taker.wallet.unspent[u]
            my_total_in += int(usvals['value'])

        my_change_value = my_total_in - self.cj_amount - self.cjfee_total - self.my_txfee
        print 'fee breakdown for me totalin=%d txfee=%d cjfee_total=%d => changevalue=%d' % (
            my_total_in, self.my_txfee, self.cjfee_total, my_change_value)
        if self.my_change_addr == None:
            if my_change_value != 0 or abs(my_change_value) != 1:
                #seems you wont always get exactly zero because of integer rounding
                # so 1 satoshi extra or fewer being spent as miner fees is acceptable
                print 'WARNING CHANGE NOT BEING USED\nCHANGEVALUE = ' + str(
                    my_change_value)
        else:
            self.outputs.append({'address': self.my_change_addr,
                                 'value': my_change_value})
        utxo_tx = [dict([('output', u)]) for u in sum(self.utxos.values(), [])]
        random.shuffle(self.outputs)
        tx = btc.mktx(utxo_tx, self.outputs)
        import pprint
        debug('obtained tx\n' + pprint.pformat(btc.deserialize(tx)))
        self.msgchan.send_tx(self.active_orders.keys(), tx)

        #now sign it ourselves here
        for index, ins in enumerate(btc.deserialize(tx)['ins']):
            utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
            if utxo not in self.my_utxos:
                continue
            if utxo not in self.taker.wallet.unspent:
                continue
            addr = self.taker.wallet.unspent[utxo]['address']
            tx = btc.sign(tx, index, self.taker.wallet.get_key_from_addr(addr))
        self.latest_tx = btc.deserialize(tx)

    def add_signature(self, sigb64):
        sig = base64.b64decode(sigb64).encode('hex')
        inserted_sig = False
        tx = btc.serialize(self.latest_tx)
        for index, ins in enumerate(self.latest_tx['ins']):
            if ins['script'] != '':
                continue
            ftx = btc.blockr_fetchtx(ins['outpoint']['hash'], get_network())
            src_val = btc.deserialize(ftx)['outs'][ins['outpoint']['index']]
            sig_good = btc.verify_tx_input(tx, index, src_val['script'], *
                                           btc.deserialize_script(sig))
            if sig_good:
                debug('found good sig at index=%d' % (index))
                ins['script'] = sig
                inserted_sig = True
                break
        if not inserted_sig:
            debug('signature did not match anything in the tx')
            #TODO what if the signature doesnt match anything
            # nothing really to do except drop it, carry on and wonder why the
            # other guy sent a failed signature

        tx_signed = True
        for ins in self.latest_tx['ins']:
            if ins['script'] == '':
                tx_signed = False
        if not tx_signed:
            return
        debug('the entire tx is signed, ready to pushtx()')

        print btc.serialize(self.latest_tx)
        #ret = btc.blockr_pushtx(btc.serialize(self.latest_tx), get_network())
        #debug('pushed tx ' + str(ret))
        if self.finishcallback != None:
            self.finishcallback()


class CoinJoinerPeer(object):

    def __init__(self, msgchan):
        self.msgchan = msgchan

    def get_crypto_box_from_nick(self, nick):
        raise Exception()


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
        self.db.execute(
            "CREATE TABLE orderbook(counterparty TEXT, oid INTEGER, ordertype TEXT, "
            + "minsize INTEGER, maxsize INTEGER, txfee INTEGER, cjfee TEXT);")

    def on_order_seen(self, counterparty, oid, ordertype, minsize, maxsize,
                      txfee, cjfee):
        self.db.execute("DELETE FROM orderbook WHERE counterparty=? AND oid=?;",
                        (counterparty, oid))
        self.db.execute(
            'INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);',
            (counterparty, oid, ordertype, minsize, maxsize, txfee, cjfee))

    def on_order_cancel(self, counterparty, oid):
        self.db.execute("DELETE FROM orderbook WHERE counterparty=? AND oid=?;",
                        (counterparty, oid))

    def on_welcome(self):
        self.msgchan.request_orderbook()

    def on_nick_leave(self, nick):
        self.db.execute('DELETE FROM orderbook WHERE counterparty=?;', (nick,))

    def on_disconnect(self):
        self.db.execute('DELETE FROM orderbook;')

    def on_set_topic(self, newtopic):
        chunks = newtopic.split('|')
        if len(chunks) > 1:
            print '=' * 60
            print 'MESSAGE FROM BELCHER!'
            print chunks[1].strip()
            print '=' * 60


#assume this only has one open cj tx at a time
class Taker(OrderbookWatch):

    def __init__(self, msgchan):
        OrderbookWatch.__init__(self, msgchan)
        msgchan.register_taker_callbacks(self.on_error, self.on_pubkey,
                                         self.on_ioauth, self.on_sig)
        msgchan.cjpeer = self
        self.cjtx = None
        self.maker_pks = {}
        #TODO have a list of maker's nick we're coinjoining with, so
        # that some other guy doesnt send you confusing stuff
        #maybe a start_cj_tx() method is needed

    def get_crypto_box_from_nick(self, nick):
        return self.cjtx.crypto_boxes[nick][1]

    def on_error(self):
        pass  #TODO implement

    def on_pubkey(self, nick, maker_pubkey):
        self.cjtx.start_encryption(nick, maker_pubkey)

    def on_ioauth(self, nick, utxo_list, cj_pub, change_addr, btc_sig):
        if not self.cjtx.auth_counterparty(nick, btc_sig, cj_pub):
            print 'Authenticated encryption with counterparty: ' + nick + \
            ' not established. TODO: send rejection message'
            return
        self.cjtx.recv_txio(nick, utxo_list, cj_pub, change_addr)

    def on_sig(self, nick, sig):
        self.cjtx.add_signature(sig)


my_tx_fee = 10000


class TestTaker(Taker):

    def __init__(self, wallet):
        Taker.__init__(self)
        self.wallet = wallet

    def finish_callback(self):
        removed_utxos = self.wallet.remove_old_utxos(self.cjtx.latest_tx)
        added_utxos = self.wallet.add_new_utxos(
            self.cjtx.latest_tx, btc.txhash(btc.serialize(self.cjtx.latest_tx)))
        debug('tx published, added_utxos=\n' + pprint.pformat(added_utxos))
        debug('removed_utxos=\n' + pprint.pformat(removed_utxos))

    def on_pubmsg(self, nick, message):
        Taker.on_pubmsg(self, nick, message)
        if message[0] != COMMAND_PREFIX:
            return
        for command in message[1:].split(COMMAND_PREFIX):
            #commands starting with % are for testing and will be removed in the final version
            chunks = command.split(" ")
            if chunks[0] == '%go':
                #!%go [counterparty] [oid] [amount]
                cp = chunks[1]
                oid = chunks[2]
                amt = chunks[3]
                #this testing command implements a very dumb algorithm.
                #just take 1 utxo from anywhere and output it to a level 1
                #change address.
                utxo_dict = self.wallet.get_utxo_list_by_mixdepth()
                utxo_list = [x for v in utxo_dict.itervalues() for x in v]
                unspent = [{'utxo': utxo, 'value': self.wallet.unspent[utxo]['value']} \
                           for utxo in utxo_list]
                inputs = btc.select(unspent, amt)
                utxos = [i['utxo'] for i in inputs]
                print 'making cjtx'
                self.cjtx = CoinJoinTX(
                    self,
                    int(amt),
                    {cp: oid},
                    utxos,
                    self.wallet.get_receive_addr(mixing_depth=1),
                    self.wallet.get_change_addr(mixing_depth=0),
                    my_tx_fee,
                    self.finish_callback)
            elif chunks[0] == '%unspent':
                from pprint import pprint
                pprint(self.wallet.unspent)
            elif chunks[0] == '%fill':
                #!fill [counterparty] [oid] [amount] [utxo]
                counterparty = chunks[1]
                oid = int(chunks[2])
                amount = chunks[3]
                my_utxo = chunks[4]
                print 'making cjtx'
                self.cjtx = CoinJoinTX(
                    self,
                    int(amount),
                    {counterparty: oid},
                    [my_utxo],
                    self.wallet.get_receive_addr(mixing_depth=1),
                    self.wallet.get_change_addr(mixing_depth=0),
                    my_tx_fee,
                    self.finish_callback)
            elif chunks[0] == '%2fill':
                #!2fill [amount] [utxo] [counterparty1] [oid1] [counterparty2] [oid2]
                amount = int(chunks[1])
                my_utxo = chunks[2]
                cp1 = chunks[3]
                oid1 = int(chunks[4])
                cp2 = chunks[5]
                oid2 = int(chunks[6])
                print 'creating cjtx'
                self.cjtx = CoinJoinTX(
                    self,
                    amount,
                    {cp1: oid1,
                     cp2: oid2},
                    [my_utxo],
                    self.wallet.get_receive_addr(mixing_depth=1),
                    self.wallet.get_change_addr(mixing_depth=0),
                    my_tx_fee,
                    self.finish_callback)


def main():
    import sys
    seed = sys.argv[1]  #btc.sha256('your brainwallet goes here')
    from socket import gethostname
    nickname = 'taker-' + btc.sha256(gethostname())[:6]

    wallet = Wallet(seed, max_mix_depth=5)
    wallet.sync_wallet()

    print 'starting irc'
    taker = TestTaker(wallet)
    try:
        taker.run(HOST, PORT, nickname, CHANNEL)
    finally:
        debug('CRASHING, DUMPING EVERYTHING')
        debug('wallet seed = ' + seed)
        debug_dump_object(wallet, ['addr_cache'])
        debug_dump_object(taker)


if __name__ == "__main__":
    main()
    print('done')
