#! /usr/bin/env python

from common import *
import irclib
import bitcoin as btc
import sys
import sqlite3
import base64

from socket import gethostname
nickname = 'cj-maker' + btc.sha256(gethostname())[:6]
seed = sys.argv[
    1
]  #btc.sha256('dont use brainwallets except for holding testnet coins')


class CoinJoinOrder(object):

    def __init__(self, irc, nick, oid, amount):
        self.oid = oid
        self.cj_amount = amount
        order = db.execute('SELECT * FROM myorders WHERE oid=?;',
                           (oid,)).fetchone()
        if amount <= order['minsize'] or amount >= order['maxsize']:
            irc.privmsg(nick, command_prefix + 'error Amount out of range')
        #TODO logic for this error causing the order to be removed from list of open orders
        self.utxos, self.mixing_depth = oid_to_order(oid, amount)
        self.ordertype = order['ordertype']
        self.txfee = order['txfee']
        self.cjfee = order['cjfee']
        self.cj_addr = wallet.get_receive_addr(self.mixing_depth)
        self.change_addr = wallet.get_change_addr(self.mixing_depth - 1)
        self.b64txparts = []
        #even if the order ends up never being furfilled, you dont want someone
        # pretending to fill all your orders to find out which addresses you use
        irc.privmsg(nick, command_prefix + 'myparts ' + ','.join(self.utxos) +
                    ' ' + self.cj_addr + ' ' + self.change_addr)

    def recv_tx_part(self, b64txpart):
        self.b64txparts.append(b64txpart)
        #TODO this is a dos opportunity, flood someone with !txpart
        #repeatedly to fill up their memory

    def recv_tx(self, irc, nick, b64txpart):
        self.b64txparts.append(b64txpart)
        tx = base64.b64decode(''.join(self.b64txparts)).encode('hex')
        txd = btc.deserialize(tx)
        goodtx, errmsg = self.verify_unsigned_tx(txd)
        if not goodtx:
            irc.privmsg(nick, command_prefix + 'error ' + errmsg)
            return False
        sigs = []
        for index, ins in enumerate(txd['ins']):
            utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
            if utxo not in wallet.unspent:
                continue
            addr = wallet.unspent[utxo]['address']
            txs = btc.sign(tx, index, wallet.get_key_from_addr(addr))
            sigs.append(base64.b64encode(btc.deserialize(txs)['ins'][index][
                'script'].decode('hex')))
        if len(sigs) == 0:
            print 'ERROR no private keys found'

        #TODO make this a function in irclib.py
        sigline = ''
        for sig in sigs:
            prev_sigline = sigline
            sigline = sigline + command_prefix + 'sig ' + sig
            if len(sigline) > MAX_PRIVMSG_LEN:
                irc.privmsg(nick, prev_sigline)
                sigline = command_prefix + 'sig ' + sig
        if len(sigline) > 0:
            irc.privmsg(nick, sigline)
        return True

    def verify_unsigned_tx(self, txd):
        tx_utxos = set([ins['outpoint']['hash'] + ':' + str(ins['outpoint'][
            'index']) for ins in txd['ins']])
        if not tx_utxos.issuperset(set(self.utxos)):
            return False, 'my utxos are not contained'
        my_total_in = 0
        for u in self.utxos:
            usvals = wallet.unspent[u]
            my_total_in += int(usvals['value'])

        real_cjfee = calc_cj_fee(self.ordertype, self.cjfee, self.cj_amount)
        expected_change_value = (
            my_total_in - self.cj_amount - self.txfee + real_cjfee)
        debug('earned fee = ' + str(real_cjfee))
        debug('mycjaddr, mychange = ' + self.cj_addr + ', ' + self.change_addr)

        times_seen_cj_addr = 0
        times_seen_change_addr = 0
        for outs in txd['outs']:
            addr = btc.script_to_address(outs['script'], get_vbyte())
            if addr == self.cj_addr:
                times_seen_cj_addr += 1
                if outs['value'] != self.cj_amount:
                    return False, 'Wrong cj_amount. I expect ' + str(cj_amount)
            if addr == self.change_addr:
                times_seen_change_addr += 1
                if outs['value'] != expected_change_value:
                    return False, 'wrong change, i expect ' + str(
                        expected_change_address)
        if times_seen_cj_addr != 1 or times_seen_change_addr != 1:
            return False, 'cj or change addr not in tx outputs exactly once'
        return True, None


wallet = Wallet(seed)
active_orders = {}


#these two functions create_my_orders() and oid_to_uxto() define the
# sell-side pricing algorithm of this bot
def create_my_orders():
    db.execute("CREATE TABLE myorders(oid INTEGER, ordertype TEXT, " +
               "minsize INTEGER, maxsize INTEGER, txfee INTEGER, cjfee TEXT);")

    #tells the highest value possible made by combining all utxos
    #fee is 0.2% of the cj amount
    total_value = 0
    for utxo, addrvalue in wallet.unspent.iteritems():
        total_value += addrvalue['value']
    db.execute('INSERT INTO myorders VALUES(?, ?, ?, ?, ?, ?);',
               (0, 'relorder', 0, total_value, 10000, '0.002'))
    '''
	#simple algorithm where each utxo we have becomes an order
	oid = 0
	for un in db.execute('SELECT * FROM unspent;').fetchall():
		db.execute('INSERT INTO myorders VALUES(?, ?, ?, ?, ?, ?);',
			(oid, 'absorder', 0, un['value'], 10000, '100000'))
		oid += 1
	'''


def oid_to_order(oid, amount):
    unspent = []
    for utxo, addrvalue in wallet.unspent.iteritems():
        unspent.append({'value': addrvalue['value'], 'utxo': utxo})
    inputs = btc.select(unspent, amount)
    #TODO this raises an exception if you dont have enough money, id rather it just returned None
    mixing_depth = 1
    return [i['utxo'] for i in inputs], mixing_depth
    '''
	unspent = db.execute('SELECT * FROM unspent WHERE value > ?;', (amount,)).fetchone()
	return [unspent['utxo']]
	'''


#TODO this belongs in irclib.py
def irc_privmsg_size_throttle(irc, target, lines, prefix=''):
    line = ''
    for l in lines:
        line += l
        if len(line) > MAX_PRIVMSG_LEN:
            irc.privmsg(target, prefix + line)
            line = ''
    if len(line) > 0:
        irc.privmsg(target, prefix + line)


def privmsg_all_orders(irc, target):
    orderdb_keys = ['ordertype', 'oid', 'minsize', 'maxsize', 'txfee', 'cjfee']
    orderline = ''
    for order in db.execute('SELECT * FROM myorders;').fetchall():
        elem_list = [str(order[k]) for k in orderdb_keys]
        orderline += (command_prefix + ' '.join(elem_list))
        if len(orderline) > MAX_PRIVMSG_LEN:
            irc.privmsg(target, orderline)
            orderline = ''
    if len(orderline) > 0:
        irc.privmsg(target, orderline)


def on_welcome(irc):
    privmsg_all_orders(irc, channel)


def on_privmsg(irc, nick, message):
    #debug("privmsg nick=%s message=%s" % (nick, message))
    if message[0] != command_prefix:
        return
    command_lines = message.split(command_prefix)
    for command_line in command_lines:
        chunks = command_line.split(" ")
        if chunks[0] == 'fill':
            oid = chunks[1]
            amount = int(chunks[2])
            active_orders[nick] = CoinJoinOrder(irc, nick, oid, amount)
        elif chunks[0] == 'txpart':
            b64txpart = chunks[1]  #TODO check nick appears in active_orders
            active_orders[nick].recv_tx_part(b64txpart)
        elif chunks[0] == 'tx':
            b64txpart = chunks[1]
            active_orders[nick].recv_tx(irc, nick, b64txpart)


#each order has an id for referencing to and looking up
# using the same id again overwrites it, they'll be plenty of times when an order
# has to be modified and its better to just have !order rather than !cancelorder then !order
def on_pubmsg(irc, nick, message):
    #debug("pubmsg nick=%s message=%s" % (nick, message))
    if message[0] == command_prefix:
        chunks = message[1:].split(" ")
        if chunks[0] == '%quit' or chunks[0] == '%makerquit':
            irc.shutdown()
        elif chunks[0] == '%say':  #% is a way to remind me its a testing cmd
            irc.pubmsg(message[6:])
        elif chunks[0] == '%rm':
            irc.pubmsg('!cancel ' + chunks[1])
        elif chunks[0] == 'orderbook':
            privmsg_all_orders(irc, nick)


def on_set_topic(irc, newtopic):
    chunks = newtopic.split('|')
    try:
        print chunks[1]
        print chunks[3]
    except IndexError:
        pass


def main():
    #TODO using sqlite3 to store my own orders is overkill, just
    # use a python data structure
    global db
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    db = con.cursor()
    wallet.download_wallet_history()
    wallet.find_unspent_addresses()
    create_my_orders()

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
