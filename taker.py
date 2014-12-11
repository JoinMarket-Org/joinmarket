#! /usr/bin/env python

from common import *
import irclib
import bitcoin as btc

import sqlite3, sys, base64
import threading, time

from socket import gethostname
nickname = 'cj-taker-' + btc.sha256(gethostname())[:6]
seed = sys.argv[1]  #btc.sha256('your brainwallet goes here')
my_utxo = '5cf68d4c42132f8f0bef8573454036953ddb3ba77a3bf3797d9862b7102d65cd:0'

my_tx_fee = 10000


class CoinJoinTX(object):

    def __init__(self,
                 irc,
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
        self.cj_amount = cj_amount
        self.active_orders = dict(zip(counterparties, oids))
        self.nonrespondants = list(counterparties)
        self.my_utxos = my_utxos
        self.utxos = {irc.nick: my_utxos}
        self.finishcallback = finishcallback
        self.my_txfee = my_txfee
        self.outputs = [{'address': my_cj_addr, 'value': self.cj_amount}]
        self.my_change_addr = my_change_addr
        self.cjfee_total = 0
        self.latest_tx = None
        for c, oid in zip(counterparties, oids):
            irc.privmsg(
                c, command_prefix + 'fill ' + str(oid) + ' ' + str(cj_amount))

    def recv_tx_parts(self, irc, nick, utxo_list, cj_addr, change_addr):
        if nick not in self.nonrespondants:
            debug('nick(' + nick + ') not in nonrespondants ' + str(
                self.nonrespondants))
            return
        self.utxos[nick] = utxo_list
        self.nonrespondants.remove(nick)
        order = db.execute('SELECT ordertype, txfee, cjfee FROM '
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
            usvals = wallet.unspent[u]
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
        tx = btc.mktx(utxo_tx, self.outputs)
        txb64 = base64.b64encode(tx.decode('hex'))
        n = MAX_PRIVMSG_LEN
        txparts = [txb64[i:i + n] for i in range(0, len(txb64), n)]
        for p in txparts[:-1]:
            for nickk in self.active_orders.keys():
                irc.privmsg(nickk, command_prefix + 'txpart' + p)
        for nickk in self.active_orders.keys():
            irc.privmsg(nickk, command_prefix + 'tx ' + txparts[-1])
        #now sign it ourselves here

        for index, ins in enumerate(btc.deserialize(tx)['ins']):
            utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
            if utxo not in self.my_utxos:
                continue
            if utxo not in wallet.unspent:
                continue
            addr = wallet.unspent[utxo]['address']
            tx = btc.sign(tx, index, wallet.get_key_from_addr(addr))
        self.latest_tx = btc.deserialize(tx)

    def add_signature(self, sigb64):
        sig = base64.b64decode(sigb64).encode('hex')

        inserted_sig = False
        tx = btc.serialize(self.latest_tx)
        for index, ins in enumerate(self.latest_tx['ins']):
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


wallet = Wallet(seed)
cjtx = None

algo_thread = None

#how long to wait for all the orders to arrive before starting to do coinjoins
ORDER_ARRIVAL_WAIT_TIME = 2


def choose_order(cj_amount):

    sqlorders = db.execute('SELECT * FROM orderbook;').fetchall()
    orders = [(o['counterparty'], o['oid'], calc_cj_fee(o['ordertype'],
                                                        o['cjfee'], cj_amount))
              for o in sqlorders
              if cj_amount >= o['minsize'] or cj_amount <= o['maxsize']]
    orders = sorted(orders, key=lambda k: k[2])
    print 'orders = ' + str(orders)
    return orders[0
                 ]  #choose the cheapest, later this will be chosen differently


def choose_sweep_order(my_total_input, my_tx_fee):
    '''
	choose an order given that we want to be left with no change
	i.e. sweep an entire group of utxos

	solve for mychange = 0
	ABS FEE
	mychange = totalin - cjamount - mytxfee - absfee
	=> cjamount = totalin - mytxfee - absfee
	REL FEE
	mychange = totalin - cjamount - mytxfee - relfee*cjamount
	=> 0 = totalin - mytxfee - cjamount*(1 + relfee)
	=> cjamount = (totalin - mytxfee) / (1 + relfee)
	'''

    def calc_zero_change_cj_amount(ordertype, cjfee):
        cj_amount = None
        if ordertype == 'absorder':
            cj_amount = my_total_input - my_tx_fee - cjfee
        elif ordertype == 'relorder':
            cj_amount = (my_total_input - my_tx_fee) / (Decimal(cjfee) + 1)
            cj_amount = int(cj_amount.quantize(Decimal(1)))
        else:
            raise RuntimeError('unknown order type: ' + str(ordertype))
        return cj_amount

    sqlorders = db.execute('SELECT * FROM orderbook;').fetchall()
    orders = [(o['counterparty'], o['oid'],
               calc_zero_change_cj_amount(o['ordertype'], o['cjfee']),
               o['minsize'], o['maxsize']) for o in sqlorders]
    #filter cj_amounts that are not in range
    orders = [o[:3] for o in orders if o[2] >= o[3] and o[2] <= o[4]]
    orders = sorted(orders, key=lambda k: k[2])
    print 'sweep orders = ' + str(orders)
    return orders[
        -1
    ]  #choose one with the highest cj_amount, most left over after paying everything else


#thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class AlgoThread(threading.Thread):

    def __init__(self, irc, initial_unspents):
        threading.Thread.__init__(self)
        self.daemon = True
        self.irc = irc
        self.initial_unspents = initial_unspents
        self.finished_cj = False

    def finished_cj_callback(self):
        self.finished_cj = True
        print 'finished cj'

    def run(self):
        global cjtx
        time.sleep(ORDER_ARRIVAL_WAIT_TIME)
        #while True:
        if 1:
            #wait for orders to arrive
            #TODO just make this do one tx and then stop
            if len(self.initial_unspents) == 0:
                print 'finished mixing, closing...'
                self.irc.shutdown()
                #break

                #utxo, addrvalue = self.initial_unspents.popitem()
            utxo, addrvalue = [(k, v)
                               for k, v in self.initial_unspents.iteritems()
                               if v['value'] == 200000000][0]
            counterparty, oid, cj_amount = choose_sweep_order(
                addrvalue['value'], my_tx_fee)
            self.finished_cj = False
            cjtx = CoinJoinTX(self.irc,
                              cj_amount,
                              [counterparty],
                              [int(oid)],
                              [utxo],
                              wallet.get_receive_addr(mixing_depth=1),
                              None,
                              my_tx_fee,
                              self.finished_cj_callback)
            #algorithm for making
            '''
			single_cj_amount = 112000000
			unspent = []
			for utxo, addrvalue in self.initial_unspents.iteritems():
				unspent.append({'value': addrvalue['value'], 'utxo': utxo})
			inputs = btc.select(unspent, single_cj_amount)
			my_utxos = [i['utxo'] for i in inputs]
			counterparty, oid = choose_order(single_cj_amount)
			cjtx = CoinJoinTX(self.irc, int(single_cj_amount), [counterparty], [int(oid)],
				my_utxos, wallet.get_receive_addr(mixing_depth=1), wallet.get_change_addr(mixing_depth=0))
			'''
            while not self.finished_cj:
                time.sleep(5)
            print 'woken algo thread'


def add_order(nick, chunks):
    db.execute('INSERT INTO orderbook VALUES(?, ?, ?, ?, ?, ?, ?);', (
        nick, chunks[1], chunks[0], chunks[2], chunks[3], chunks[4], chunks[5]))


def on_privmsg(irc, nick, message):
    #debug("privmsg nick=%s message=%s" % (nick, message))
    if message[0] != command_prefix:
        return

    for command in message[1:].split(command_prefix):
        chunks = command.split(" ")
        if chunks[0] in ordername_list:
            add_order(nick, chunks)
        elif chunks[0] == 'myparts':
            utxo_list = chunks[1].split(',')
            cj_addr = chunks[2]
            change_addr = chunks[3]
            cjtx.recv_tx_parts(irc, nick, utxo_list, cj_addr, change_addr)
        elif chunks[0] == 'sig':
            sig = chunks[1]
            cjtx.add_signature(sig)


#each order has an id for referencing to and looking up
# using the same id again overwrites it, they'll be plenty of times when an order
# has to be modified and its better to just have !order rather than !cancelorder then !order
def on_pubmsg(irc, nick, message):
    global cjtx
    print("pubmsg nick=%s message=%s" % (nick, message))
    if message[0] != command_prefix:
        return

    for command in message[1:].split(command_prefix):
        #commands starting with % are for testing and will be removed in the final version
        chunks = command.split(" ")
        if chunks[0] == '%quit' or chunks[0] == '%takerquit':
            irc.shutdown()
        elif chunks[0] == 'cancel':
            #!cancel [oid]
            try:
                oid = int(chunks[1])
                db.execute(
                    "DELETE FROM orderbook WHERE counterparty=? AND oid=?;",
                    (nick, oid))
            except ValueError as e:
                debug("!cancel " + repr(e))
                return
        elif chunks[0] in ordername_list:
            add_order(nick, chunks)
        elif chunks[0] == '%showob':
            print('printing orderbook')
            for o in db.execute('SELECT * FROM orderbook;').fetchall():
                print '(%s %s %d %d-%d %d %s)' % (
                    o['counterparty'], o['ordertype'], o['oid'], o['minsize'],
                    o['maxsize'], o['txfee'], o['cjfee'])
            print('done')
        elif chunks[0] == '%fill':
            counterparty = chunks[1]
            oid = chunks[2]
            amount = chunks[3]
            #!fill [counterparty] [oid] [amount]
            cjtx = CoinJoinTX(irc,
                              int(amount),
                              [counterparty],
                              [int(oid)],
                              [my_utxo],
                              wallet.get_receive_addr(mixing_depth=1),
                              wallet.get_change_addr(mixing_depth=0),
                              my_tx_fee)

    #self.connection.quit("Using irc.client.py")


def on_welcome(irc):
    global algo_thread
    irc.pubmsg(command_prefix + 'orderbook')
    algo_thread = AlgoThread(irc, wallet.unspent.copy())
    #algo_thread.start()


def on_set_topic(irc, newtopic):
    chunks = newtopic.split('|')
    try:
        print chunks[1]
        print chunks[2]
    except IndexError:
        pass


'''
for m in range(2):
	print 'mixing depth ' + str(m)
	for forchange in range(2):
		print ' forchange=' + str(forchange)
		for n in range(3):
			#print '   ' + str(n) + ' ' + btc.privtoaddr(wallet.get_key(m, forchange, n), 0x6f)
'''


def main():
    global db
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    db = con.cursor()
    db.execute(
        "CREATE TABLE orderbook(counterparty TEXT, oid INTEGER, ordertype TEXT, "
        + "minsize INTEGER, maxsize INTEGER, txfee INTEGER, cjfee TEXT);")
    wallet.download_wallet_history()
    wallet.find_unspent_addresses()

    print 'starting irc'
    irc = irclib.IRCClient()
    irc.on_privmsg = on_privmsg
    irc.on_pubmsg = on_pubmsg
    irc.on_welcome = on_welcome
    irc.on_set_topic = on_set_topic
    irc.run(server, port, nickname, channel)


if __name__ == "__main__":
    main()
    print('done')
