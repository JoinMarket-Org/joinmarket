#! /usr/bin/env python

from common import *
import irclib
import bitcoin as btc

import sqlite3, base64, threading, time, random


class CoinJoinTX(object):

    def __init__(self,
                 taker,
                 cj_amount,
                 counterparties,
                 oids,
                 my_utxos,
                 my_cj_addr,
                 my_change_addr,
                 my_txfee,
                 finishcallback=None):
        '''
		if my_change is None then there wont be a change address
		thats used if you want to entirely coinjoin one utxo with no change left over
		'''
        self.taker = taker
        self.cj_amount = cj_amount
        self.active_orders = dict(zip(counterparties, oids))
        self.nonrespondants = list(counterparties)
        self.my_utxos = my_utxos
        self.utxos = {taker.nick: my_utxos}
        self.finishcallback = finishcallback
        self.my_txfee = my_txfee
        self.outputs = [{'address': my_cj_addr, 'value': self.cj_amount}]
        self.my_change_addr = my_change_addr
        self.cjfee_total = 0
        self.latest_tx = None
        for c, oid in zip(counterparties, oids):
            taker.privmsg(
                c, command_prefix + 'fill ' + str(oid) + ' ' + str(cj_amount))

    def recv_addrs(self, nick, utxo_list, cj_addr, change_addr):
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
        #ret = btc.blockr_pushtx(btc.serialize(self.latest_tx), get_network())
        #print 'pushed tx ' + str(ret)
        if self.finishcallback != None:
            self.finishcallback()


class Taker(irclib.IRCClient):

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

        #self.connection.quit("Using irc.client.py")

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


def main():
    from socket import gethostname
    nickname = 'cj-taker-' + btc.sha256(gethostname())[:6]

    print 'starting irc'
    taker = Taker()
    taker.run(HOST, PORT, nickname, CHANNEL)


if __name__ == "__main__":
    main()
    print('done')
