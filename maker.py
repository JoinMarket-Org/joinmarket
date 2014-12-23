#! /usr/bin/env python

from common import *
import irclib
import bitcoin as btc
import sys
import sqlite3
import base64

from socket import gethostname
nickname = 'cj-maker-' + btc.sha256(gethostname())[:6]
seed = sys.argv[
    1
]  #btc.sha256('dont use brainwallets except for holding testnet coins')


class CoinJoinOrder(object):

    def __init__(self, maker, nick, oid, amount):
        self.maker = maker
        self.oid = oid
        self.cj_amount = amount
        order = [o for o in maker.orderlist if o['oid'] == oid][0]
        if amount <= order['minsize'] or amount >= order['maxsize']:
            maker.privmsg(nick, command_prefix + 'error amount out of range')
        #TODO logic for this error causing the order to be removed from list of open orders
        self.utxos, self.mixing_depth = maker.oid_to_order(oid, amount)
        self.ordertype = order['ordertype']
        self.txfee = order['txfee']
        self.cjfee = order['cjfee']
        self.cj_addr = maker.wallet.get_receive_addr(self.mixing_depth)
        self.change_addr = maker.wallet.get_change_addr(self.mixing_depth - 1)
        self.b64txparts = []
        #always a new address even if the order ends up never being
        # furfilled, you dont want someone pretending to fill all your
        # orders to find out which addresses you use
        maker.privmsg(nick, command_prefix + 'myparts ' + ','.join(self.utxos) +
                      ' ' + self.cj_addr + ' ' + self.change_addr)

    def recv_tx_part(self, b64txpart):
        self.b64txparts.append(b64txpart)
        #TODO this is a dos opportunity, flood someone with !txpart
        #repeatedly to fill up their memory

    def recv_tx(self, nick, b64txpart):
        self.b64txparts.append(b64txpart)
        self.tx = base64.b64decode(''.join(self.b64txparts)).encode('hex')
        txd = btc.deserialize(self.tx)
        goodtx, errmsg = self.verify_unsigned_tx(txd)
        if not goodtx:
            self.maker.privmsg(nick, command_prefix + 'error ' + errmsg)
            return False
        sigs = []
        for index, ins in enumerate(txd['ins']):
            utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
            if utxo not in self.maker.wallet.unspent:
                continue
            addr = self.maker.wallet.unspent[utxo]['address']
            txs = btc.sign(self.tx, index,
                           self.maker.wallet.get_key_from_addr(addr))
            sigs.append(base64.b64encode(btc.deserialize(txs)['ins'][index][
                'script'].decode('hex')))
        if len(sigs) == 0:
            print 'ERROR no private keys found'
        add_addr_notify(self.change_addr, self.unconfirm_callback,
                        self.confirm_callback)

        #TODO make this a function in irclib.py
        sigline = ''
        for sig in sigs:
            prev_sigline = sigline
            sigline = sigline + command_prefix + 'sig ' + sig
            if len(sigline) > MAX_PRIVMSG_LEN:
                self.maker.privmsg(nick, prev_sigline)
                sigline = command_prefix + 'sig ' + sig
        if len(sigline) > 0:
            self.maker.privmsg(nick, sigline)
        return True

    def unconfirm_callback(self, value):
        to_cancel, to_announce = self.maker.on_tx_unconfirmed(self, value)
        self.handle_modified_orders(to_cancel, to_announce)

    def confirm_callback(self, confirmations, txid, value):
        to_cancel, to_announce = self.maker.on_tx_confirmed(self, confirmations,
                                                            txid, value)
        self.handle_modified_orders(to_cancel, to_announce)

    def handle_modified_orders(self, to_cancel, to_announce):
        for oid in to_cancel:
            order = [o for o in self.maker.orderlist if o['oid'] == oid][0]
            self.maker.orderlist.remove(order)
        if len(to_cancel) > 0:
            clines = ['!cancel ' + str(oid) for oid in to_cancel]
            self.maker.pubmsg(''.join(clines))
        if len(to_announce) > 0:
            self.maker.privmsg_all_orders(CHANNEL, to_announce)
            self.maker.orderlist.append(to_announce)

    def verify_unsigned_tx(self, txd):
        tx_utxos = set([ins['outpoint']['hash'] + ':' + str(ins['outpoint'][
            'index']) for ins in txd['ins']])
        if not tx_utxos.issuperset(set(self.utxos)):
            return False, 'my utxos are not contained'
        my_total_in = 0
        for u in self.utxos:
            usvals = self.maker.wallet.unspent[u]
            my_total_in += int(usvals['value'])

        real_cjfee = calc_cj_fee(self.ordertype, self.cjfee, self.cj_amount)
        expected_change_value = (
            my_total_in - self.cj_amount - self.txfee + real_cjfee)
        debug('earned = ' + str(real_cjfee - self.txfee))
        debug('mycjaddr, mychange = ' + self.cj_addr + ', ' + self.change_addr)

        times_seen_cj_addr = 0
        times_seen_change_addr = 0
        for outs in txd['outs']:
            addr = btc.script_to_address(outs['script'], get_addr_vbyte())
            if addr == self.cj_addr:
                times_seen_cj_addr += 1
                if outs['value'] != self.cj_amount:
                    return False, 'Wrong cj_amount. I expect ' + str(cj_amount)
            if addr == self.change_addr:
                times_seen_change_addr += 1
                if outs['value'] != expected_change_value:
                    return False, 'wrong change, i expect ' + str(
                        expected_change_value)
        if times_seen_cj_addr != 1 or times_seen_change_addr != 1:
            return False, 'cj or change addr not in tx outputs exactly once'
        return True, None


class Maker(irclib.IRCClient):

    def __init__(self, wallet):
        self.active_orders = {}
        self.wallet = wallet
        self.nextoid = -1
        self.orderlist = self.create_my_orders()

    def privmsg_all_orders(self, target, orderlist=None):
        if orderlist == None:
            orderlist = self.orderlist
        order_keys = ['ordertype', 'oid', 'minsize', 'maxsize', 'txfee', 'cjfee'
                     ]
        orderline = ''
        for order in orderlist:
            elem_list = [str(order[k]) for k in order_keys]
            orderline += (command_prefix + ' '.join(elem_list))
            if len(orderline) > MAX_PRIVMSG_LEN:
                self.privmsg(target, orderline)
                orderline = ''
        if len(orderline) > 0:
            self.privmsg(target, orderline)

    def on_welcome(self):
        self.privmsg_all_orders(CHANNEL)

    def on_privmsg(self, nick, message):
        #debug("privmsg nick=%s message=%s" % (nick, message))
        if message[0] != command_prefix:
            return
        command_lines = message.split(command_prefix)
        for command_line in command_lines:
            chunks = command_line.split(" ")
            if chunks[0] == 'fill':
                oid = int(chunks[1])
                amount = int(
                    chunks[2]
                )  #TODO make sure that nick doesnt already have an open order
                self.active_orders[nick] = CoinJoinOrder(self, nick, oid,
                                                         amount)
            elif chunks[0] == 'txpart':
                b64txpart = chunks[1]  #TODO check nick appears in active_orders
                self.active_orders[nick].recv_tx_part(b64txpart)
            elif chunks[0] == 'tx':
                b64txpart = chunks[1]
                self.active_orders[nick].recv_tx(nick, b64txpart)

    #each order has an id for referencing to and looking up
    # using the same id again overwrites it, they'll be plenty of times when an order
    # has to be modified and its better to just have !order rather than !cancelorder then !order
    def on_pubmsg(self, nick, message):
        #debug("pubmsg nick=%s message=%s" % (nick, message))
        if message[0] == command_prefix:
            chunks = message[1:].split(" ")
            if chunks[0] == '%quit' or chunks[0] == '%makerquit':
                self.shutdown()
            elif chunks[
                    0] == '%say':  #% is a way to remind me its a testing cmd
                self.pubmsg(message[6:])
            elif chunks[0] == '%rm':
                self.pubmsg('!cancel ' + chunks[1])
            elif chunks[0] == 'orderbook':
                self.privmsg_all_orders(nick)

    def on_set_topic(self, newtopic):
        chunks = newtopic.split('|')
        try:
            print chunks[1].strip()
            print chunks[3].strip()
        except IndexError:
            pass

    #these functions
    # create_my_orders()
    # oid_to_uxto()
    # on_tx_unconfirmed()
    # on_tx_confirmed()
    #define the sell-side pricing algorithm of this bot
    #still might be a bad way of doing things, we'll see
    def create_my_orders(self):
        '''
		#tells the highest value possible made by combining all utxos
		#fee is 0.2% of the cj amount
		total_value = 0
		for utxo, addrvalue in self.wallet.unspent.iteritems():
			total_value += addrvalue['value']

		order = {'oid': 0, 'ordertype': 'relorder', 'minsize': 0,
			'maxsize': total_value, 'txfee': 10000, 'cjfee': '0.002'}
		return [order]
		'''

        #each utxo is a single absolute-fee order
        orderlist = []
        for utxo, addrvalue in self.wallet.unspent.iteritems():
            order = {'oid': self.get_next_oid(),
                     'ordertype': 'absorder',
                     'minsize': 0,
                     'maxsize': addrvalue['value'],
                     'txfee': 10000,
                     'cjfee': 100000,
                     'utxo': utxo,
                     'mixdepth': addrvalue['mixdepth']}
            orderlist.append(order)
        #yes you can add keys there that are never used by the rest of the Maker code
        # so im adding utxo and mixdepth here
        return orderlist

        #has to return a list of utxos and mixing depth the cj address will be in
        # the change address will be in mixing_depth-1
    def oid_to_order(self, oid, amount):
        '''
		unspent = []
		for utxo, addrvalue in self.wallet.unspent.iteritems():
			unspent.append({'value': addrvalue['value'], 'utxo': utxo})
		inputs = btc.select(unspent, amount)
		#TODO this raises an exception if you dont have enough money, id rather it just returned None
		mixing_depth = 1
		return [i['utxo'] for i in inputs], mixing_depth
		'''

        order = [o for o in self.orderlist if o['oid'] == oid][0]
        mixing_depth = order['mixdepth'] + 1
        return [order['utxo']], mixing_depth

    def get_next_oid(self):
        self.nextoid += 1
        return self.nextoid

    #gets called when the tx is seen on the network
    #must return which orders to cancel or recreate
    def on_tx_unconfirmed(self, order, value):
        print 'tx unconfirmed'
        return ([order.oid], [])

    #gets called when the tx is included in a block
    #must return which orders to cancel or recreate
    # and i have to think about how that will work for both
    # the blockchain explorer api method and the bitcoid walletnotify
    def on_tx_confirmed(self, order, confirmations, txid, value):
        print 'tx confirmed'
        to_announce = []
        txd = btc.deserialize(order.tx)
        for i, out in enumerate(txd['outs']):
            addr = btc.script_to_address(out['script'], get_addr_vbyte())
            if addr == order.change_addr:
                neworder = {'oid': self.get_next_oid(),
                            'ordertype': 'absorder',
                            'minsize': 0,
                            'maxsize': out['value'],
                            'txfee': 10000,
                            'cjfee': 100000,
                            'utxo': txid + ':' + str(i)}
                to_announce.append(neworder)
            if addr == order.cj_addr:
                neworder = {'oid': self.get_next_oid(),
                            'ordertype': 'absorder',
                            'minsize': 0,
                            'maxsize': out['value'],
                            'txfee': 10000,
                            'cjfee': 100000,
                            'utxo': txid + ':' + str(i)}
                to_announce.append(neworder)
        return ([], to_announce)


def main():
    print 'downloading wallet history'
    wallet = Wallet(seed)
    wallet.download_wallet_history()
    wallet.find_unspent_addresses()

    maker = Maker(wallet)
    print 'connecting to irc'
    maker.run(HOST, PORT, nickname, CHANNEL)


if __name__ == "__main__":
    main()
    print('done')
