#! /usr/bin/env python

from maker import *
import bitcoin as btc
import time

import pprint

txfee = 1000
cjfee = '0.01'  # 1% fee
mix_levels = 5
nickname = 'yield-generate'
nickserv_password = ''


#is a maker for the purposes of generating a yield from held
# bitcoins without ruining privacy for the taker, the taker could easily check
# the history of the utxos this bot sends, so theres not much incentive
# to ruin the privacy for barely any more yield
#sell-side algorithm:
#add up the value of each utxo for each mixing depth,
# announce a relative-fee order of the highest balance
#spent from utxos that try to make the highest balance even higher
# so try to keep coins concentrated in one mixing depth
class YieldGenerator(Maker):

    def __init__(self, wallet):
        Maker.__init__(self, wallet)

    def on_connect(self):
        if len(nickserv_password) > 0:
            self.privmsg('NickServ', 'identify ' + nickserv_password)

    def create_my_orders(self):
        mix_utxo_list = self.wallet.get_mix_utxo_list()
        mix_balance = {}
        for mixdepth, utxo_list in mix_utxo_list.iteritems():
            total_value = 0
            for utxo in utxo_list:
                total_value += self.wallet.unspent[utxo]['value']
            mix_balance[mixdepth] = total_value

        if len([b for m, b in mix_balance.iteritems() if b > 0]) == 0:
            debug('do not have any coins left')
            return []

        #print mix_balance
        max_mix = max(mix_balance, key=mix_balance.get)
        order = {'oid': 0,
                 'ordertype': 'relorder',
                 'minsize': 0,
                 'maxsize': mix_balance[max_mix],
                 'txfee': txfee,
                 'cjfee': cjfee,
                 'mix_balance': mix_balance}
        return [order]

    def oid_to_order(self, oid, amount):
        mix_balance = self.orderlist[0]['mix_balance']
        max_mix = max(mix_balance, key=mix_balance.get)

        #algo attempts to make the largest-balance mixing depth get an even larger balance
        mixdepth = (max_mix - 1) % self.wallet.max_mix_depth
        while True:
            if mixdepth in mix_balance and mix_balance[mixdepth] > amount:
                break
            mixdepth = (mixdepth - 1) % self.wallet.max_mix_depth
        #mixdepth is the chosen depth we'll be spending from

        mix_utxo_list = self.wallet.get_mix_utxo_list()
        unspent = [{'utxo': utxo,
                    'value': self.wallet.unspent[utxo]['value']}
                   for utxo in mix_utxo_list[mixdepth]]
        inputs = btc.select(unspent, amount)
        cj_addr = self.wallet.get_receive_addr(
            (mixdepth + 1) % self.wallet.max_mix_depth)
        change_addr = self.wallet.get_change_addr(mixdepth)
        return [i['utxo'] for i in inputs], cj_addr, change_addr

    def on_tx_unconfirmed(self, cjorder, balance, removed_utxos):
        #if the balance of the highest-balance mixing depth change then reannounce it
        oldorder = self.orderlist[0]
        neworders = self.create_my_orders()
        if len(neworders) == 0:
            return ([oldorder], [])  #cancel old order
        elif oldorder['maxsize'] == neworder['maxsize']:
            return ([], [])  #change nothing
        else:
            #announce new order, replacing the old order
            return ([], [neworder[0]])

    def on_tx_confirmed(self, cjorder, confirmations, txid, balance,
                        added_utxos):
        return self.on_tx_unconfirmed(None, None, None)


def main():
    import sys
    seed = sys.argv[
        1
    ]  #btc.sha256('dont use brainwallets except for holding testnet coins')

    print 'downloading wallet history'
    wallet = Wallet(seed, max_mix_depth=mix_levels)
    wallet.download_wallet_history()
    wallet.find_unspent_addresses()

    maker = YieldGenerator(wallet)
    print 'connecting to irc'
    maker.run(HOST, PORT, nickname, CHANNEL)


if __name__ == "__main__":
    main()
    print('done')
