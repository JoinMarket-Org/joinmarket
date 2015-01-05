#! /usr/bin/env python

from common import *
import irclib
import bitcoin as btc

import sqlite3, base64, threading, time, random


class CoinJoinTX(object):

    def __init__(self,
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
        self.taker = taker
        self.cj_amount = cj_amount
        self.active_orders = dict(orders)
        self.nonrespondants = list(orders.keys())
        self.my_utxos = my_utxos
        self.utxos = {taker.nick: my_utxos}
        self.finishcallback = finishcallback
        self.my_txfee = my_txfee
        self.outputs = [{'address': my_cj_addr, 'value': self.cj_amount}]
        self.my_change_addr = my_change_addr
        self.cjfee_total = 0
        self.latest_tx = None
        #find the btc pubkey of the first utxo being used
        self.signing_btc_add = taker.wallet.unspent[self.my_utxos[0]]['address']
        self.signing_btc_pub = btc.privtopub(taker.wallet.get_key_from_addr(
            self.signing_btc_add))
        for c, oid in orders.iteritems():
            taker.privmsg(c, command_prefix + 'fill ' + \
            str(oid) + ' ' + str(cj_amount) + ' ' + self.signing_btc_pub)

    def recv_txio(self, nick, utxo_list, cj_addr, change_addr):
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
        print 'fee breakdown for me totalin=%d txfee=%d cjfee_total=%d' % (
            my_total_in, self.my_txfee, self.cjfee_total)
        if self.my_change_addr == None:
            if my_change_value != 0:
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
        txb64 = base64.b64encode(tx.decode('hex'))
        n = MAX_PRIVMSG_LEN
        txparts = [txb64[i:i + n] for i in range(0, len(txb64), n)]
        for p in txparts[:-1]:
            for nickk in self.active_orders.keys():
                self.taker.privmsg(nickk, command_prefix + 'txpart ' + p)
        for nickk in self.active_orders.keys():
            self.taker.privmsg(nickk, command_prefix + 'tx ' + txparts[-1])

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
        ret = btc.blockr_pushtx(btc.serialize(self.latest_tx), get_network())
        debug('pushed tx ' + str(ret))
        if self.finishcallback != None:
            self.finishcallback()


class OrderbookWatch(irclib.IRCClient):

    def __init__(self):
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.row_factory = sqlite3.Row
        self.db = con.cursor()
        self.db.execute(
            "CREATE TABLE orderbook(counterparty TEXT, oid INTEGER, ordertype TEXT, "
            + "minsize INTEGER, maxsize INTEGER, txfee INTEGER, cjfee TEXT);")

    def add_order(self, nick, chunks):
        self.db.execute('INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);',
                        (nick, chunks[1], chunks[0], chunks[2], chunks[3],
                         chunks[4], chunks[5]))

    def on_privmsg(self, nick, message):
        debug("privmsg nick=%s message=%s" % (nick, message))
        if message[0] != command_prefix:
            return

        for command in message[1:].split(command_prefix):
            chunks = command.split(" ")
            if chunks[0] in ordername_list:
                self.add_order(nick, chunks)

    #each order has an id for referencing to and looking up
    # using the same id again overwrites it, they'll be plenty of times when an order
    # has to be modified and its better to just have !order rather than !cancelorder then !order
    def on_pubmsg(self, nick, message):
        debug("pubmsg nick=%s message=%s" % (nick, message))
        if message[0] != command_prefix:
            return
        for command in message[1:].split(command_prefix):
            #commands starting with % are for testing and will be removed in the final version
            chunks = command.split(" ")
            if chunks[0] == '%quit' or chunks[0] == '%takerquit':
                self.shutdown()
            elif chunks[0] == 'cancel':
                #!cancel [oid]
                try:
                    oid = int(chunks[1])
                    self.db.execute(
                        "DELETE FROM orderbook WHERE counterparty=? AND oid=?;",
                        (nick, oid))
                except ValueError as e:
                    debug("!cancel " + repr(e))
                    return
            elif chunks[0] in ordername_list:
                self.add_order(nick, chunks)

    def on_welcome(self):
        self.pubmsg(command_prefix + 'orderbook')

    def on_set_topic(self, newtopic):
        chunks = newtopic.split('|')
        try:
            print chunks[1].strip()
            print chunks[2].strip()
        except IndexError:
            pass

    def on_leave(self, nick):
        self.db.execute('DELETE FROM orderbook WHERE counterparty=?;', (nick,))

    def on_disconnect(self):
        self.db.execute('DELETE FROM orderbook;')


#assume this only has one open cj tx at a time
class Taker(OrderbookWatch):

    def __init__(self, keyfile):
        OrderbookWatch.__init__(self)
        self.cjtx = None
        #TODO have a list of maker's nick we're coinjoining with, so
        # that some other guy doesnt send you confusing stuff
        #maybe a start_cj_tx() method is needed
        self.init_encryption(keyfile)

    def auth_counterparty(self, nick, btc_pub, btc_sig, cj_addr, enc_pk,
                          signing_add):
        if not cj_addr == btc.pubtoaddr(btc_pub, magicbyte=get_addr_vbyte()):
            print 'coinjoin address and pubkey didnt match'
            return False
        if not btc.ecdsa_verify(enc_pk, btc_sig, btc_pub):
            print 'signature didnt match pubkey and message'
            return False
        #send authorisation response
        my_btc_sig = btc.ecdsa_sign(self.enc_kp.hex_pk(),\
                                    self.wallet.get_key_from_addr(signing_add))
        message = '!auth ' + self.enc_kp.hex_pk() + ' ' + my_btc_sig
        self.privmsg(nick, message
                    )  #note: we do this *before* starting encryption
        #TODO: should both sides send acks to acknowledge successful handshake?
        #authorisation passed: initiate encryption for future
        #messages
        self.start_encryption(nick, enc_pk)
        return True

    def on_privmsg(self, nick, message):
        OrderbookWatch.on_privmsg(self, nick, message)
        #debug("privmsg nick=%s message=%s" % (nick, message))
        if message[0] != command_prefix:
            return
        for command in message[1:].split(command_prefix):
            chunks = command.split(" ")
            if chunks[0] == 'io':
                utxo_list = chunks[1].split(',')
                cj_addr = chunks[2]
                change_addr = chunks[3]
                btc_pub = chunks[4]
                btc_sig = chunks[5]
                enc_pk = chunks[6]
                if not self.auth_counterparty(nick,btc_pub,btc_sig,cj_addr,enc_pk,\
                        self.cjtx.signing_btc_add):
                    print 'Authenticated encryption with counterparty: ' + nick + \
                    ' not established. TODO: send rejection message'
                    continue
                self.cjtx.recv_txio(nick, utxo_list, cj_addr, change_addr)
            elif chunks[0] == 'sig':
                sig = chunks[1]
                self.cjtx.add_signature(sig)


my_tx_fee = 10000


class TestTaker(Taker):

    def __init__(self, wallet, keyfile):
        Taker.__init__(self, keyfile)
        self.wallet = wallet

    def on_pubmsg(self, nick, message):
        Taker.on_pubmsg(self, nick, message)
        if message[0] != command_prefix:
            return
        for command in message[1:].split(command_prefix):
            #commands starting with % are for testing and will be removed in the final version
            chunks = command.split(" ")
            if chunks[0] == '%go':
                #!%go [counterparty] [oid] [amount]
                cp = chunks[1]
                oid = chunks[2]
                amt = chunks[3]
                utxo_list = self.wallet.get_mix_utxo_list()[
                    0
                ]  #only spend from the unmixed funds
                unspent = [{'utxo': utxo, 'value': self.wallet.unspent[utxo]['value']} \
                           for utxo in utxo_list]
                inputs = btc.select(unspent, amt)
                utxos = [i['utxo'] for i in inputs]
                print 'making cjtx'
                self.cjtx = CoinJoinTX(
                    self,
                    int(amt),
                    {cp: oid},
                    [utxos[0]],
                    self.wallet.get_receive_addr(mixing_depth=1),
                    self.wallet.get_change_addr(mixing_depth=0),
                    my_tx_fee)

            if chunks[0] == '%showob':
                print('printing orderbook')
                for o in self.db.execute('SELECT * FROM orderbook;').fetchall():
                    print '(%s %s %d %d-%d %d %s)' % (
                        o['counterparty'], o['ordertype'], o['oid'],
                        o['minsize'], o['maxsize'], o['txfee'], o['cjfee'])
                print('done')
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
                    my_tx_fee)
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
                    my_tx_fee)


def main():
    import sys
    seed = sys.argv[1]  #btc.sha256('your brainwallet goes here')
    keyfile = sys.argv[2]
    from socket import gethostname
    nickname = 'taker-' + btc.sha256(gethostname())[:6]

    print 'downloading wallet history'
    wallet = Wallet(seed, max_mix_depth=5)
    wallet.download_wallet_history()
    wallet.find_unspent_addresses()

    print 'starting irc'
    taker = TestTaker(wallet, keyfile)
    taker.run(HOST, PORT, nickname, CHANNEL)


if __name__ == "__main__":
    main()
    print('done')
