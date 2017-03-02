#! /usr/bin/env python
from __future__ import print_function

import datetime
import time

from joinmarket import jm_single
from joinmarket import get_log, calc_cj_fee
from joinmarket import YieldGenerator, ygmain

### Configure the yield generator here

# absolute offer fee you wish to receive for coinjoins (cj)
cjfee_a = 5000          # [satoshis, any integer]
# coinjoin fee you wish to receive based on a cj's amount, '0.0002' = 0.02%
cjfee_r = '0.0002'      # [percent, any str between 0-1]
# which fee type to actually use
ordertype = 'reloffer'  # [string, 'reloffer' or 'absoffer']
# the absolute transaction fee you're adding to coinjoin transactions
txfee = 1000            # [satoshis, any integer]
# minimum size of your cj offer. Lower cj amounts will be disregarded
min_minsize = 500000    # [satoshis, any integer]
# Increase the next value if the balance of your wallet is shown wrong
gaplimit = 6            # [integer]

### End of yield generator configuration


log = get_log()

# is a maker for the purposes of generating a yield from held
# bitcoins while maximising the difficulty of spying on activity;
# this is primarily attempted by avoiding reannouncemnt of orders
# after transactions whereever that is possible.


class YieldGeneratorPrivEnhance(YieldGenerator):

    def __init__(self, msgchan, wallet, offerconfig):
        self.txfee, self.cjfee_a, self.cjfee_r, self.ordertype, self.minsize, \
             = offerconfig
        super(YieldGeneratorPrivEnhance, self).__init__(msgchan, wallet)

    def create_my_orders(self):
        mix_balance = self.wallet.get_balance_by_mixdepth()
        # We publish ONLY the maximum amount and use minsize for lower bound;
        # leave it to oid_to_order to figure out the right depth to use.
        f = '0'
        if self.ordertype == 'reloffer':
            f = self.cjfee_r
            # minimum size bumped if necessary such that you always profit
            # least 50% of the miner fee
            self.minsize = max(
                int(1.5 * self.txfee / float(self.cjfee_r)), min_minsize)
        elif self.ordertype == 'absoffer':
            f = str(self.txfee + self.cjfee_a)
        mix_balance = dict([(m, b) for m, b in mix_balance.iteritems()
                            if b > self.minsize])
        if len(mix_balance) == 0:
            log.error('You do not have a balance above minsize of '
                + str(self.minsize) + ' satoshi. Cannot be an active maker with'
                + ' no funds.')
            return []
        max_mix = max(mix_balance, key=mix_balance.get)
        order = {'oid': 0,
                 'ordertype': self.ordertype,
                 'minsize': self.minsize,
                 'maxsize': mix_balance[max_mix] - max(
                     jm_single().DUST_THRESHOLD, self.txfee),
                 'txfee': self.txfee,
                 'cjfee': f}

        # sanity check
        assert order['minsize'] >= 0
        assert order['maxsize'] > 0
        if order['minsize'] > order['maxsize']:
            log.info('minsize (' + str(order['minsize']) + ') > maxsize (' + str(order['maxsize']) + ')')
            return []

        return [order]

    def oid_to_order(self, cjorder, oid, amount):
        """The only change from *basic here (for now) is that
        we choose outputs to avoid increasing the max_mixdepth
        as much as possible, thus avoiding reannouncement as
        much as possible.
        """
        total_amount = amount + cjorder.txfee
        mix_balance = self.wallet.get_balance_by_mixdepth()
        max_mix = max(mix_balance, key=mix_balance.get)
        min_mix = min(mix_balance, key=mix_balance.get)

        filtered_mix_balance = [m
                                for m in mix_balance.iteritems()
                                if m[1] >= total_amount]
        if not filtered_mix_balance:
            return None, None, None

        log.debug('mix depths that have enough = ' + str(filtered_mix_balance))

        # Avoid the max mixdepth wherever possible, to avoid changing the
        # offer. Algo:
        #"mixdepth" is the mixdepth we are spending FROM, so it is also
        # the destination of change.
        #"cjoutdepth" is the mixdepth we are sending coinjoin out to.
        #
        # Find a mixdepth, in the set that have enough, which is
        # not the maximum, and choose any from that set as "mixdepth".
        # If not possible, it means only the max_mix depth has enough,
        # so must choose "mixdepth" to be that.
        # To find the cjoutdepth: ensure that max != min, if so it means
        # we had only one depth; in that case, just set "cjoutdepth"
        # to the next mixdepth. Otherwise, we set "cjoutdepth" to the minimum.

        nonmax_mix_balance = [
            m for m in filtered_mix_balance if m[0] != max_mix]
        if not nonmax_mix_balance:
            log.debug("Could not spend from a mixdepth which is not max")
            mixdepth = max_mix
        else:
            mixdepth = nonmax_mix_balance[0][0]
        log.info('filling offer, mixdepth=' + str(mixdepth))

        # mixdepth is the chosen depth we'll be spending from
        # min_mixdepth is the one we want to send our cjout TO,
        # to minimize chance of it becoming the largest, and reannouncing
        # offer.
        if mixdepth == min_mix:
            cjoutmix = (mixdepth + 1) % self.wallet.max_mix_depth
            # don't send cjout to max
            if cjoutmix == max_mix:
                cjoutmix = (cjoutmix + 1) % self.wallet.max_mix_depth
        else:
            cjoutmix = min_mix
        cj_addr = self.wallet.get_internal_addr(cjoutmix)
        change_addr = self.wallet.get_internal_addr(mixdepth)

        utxos = self.wallet.select_utxos(mixdepth, total_amount)
        my_total_in = sum([va['value'] for va in utxos.values()])
        real_cjfee = calc_cj_fee(cjorder.ordertype, cjorder.cjfee, amount)
        change_value = my_total_in - amount - cjorder.txfee + real_cjfee
        if change_value <= jm_single().DUST_THRESHOLD:
            log.debug(('change value={} below dust threshold, '
                       'finding new utxos').format(change_value))
            try:
                utxos = self.wallet.select_utxos(
                    mixdepth, total_amount + jm_single().DUST_THRESHOLD)
            except Exception:
                log.info('dont have the required UTXOs to make a '
                          'output above the dust threshold, quitting. '
                          'This can sometimes happen and does not require user action.')
                return None, None, None

        return utxos, cj_addr, change_addr

    def on_tx_unconfirmed(self, cjorder, txid, removed_utxos):
        self.tx_unconfirm_timestamp[cjorder.cj_addr] = int(time.time())
        # if the balance of the highest-balance mixing depth change then
        # reannounce it
        oldorder = self.orderlist[0] if len(self.orderlist) > 0 else None
        neworders = self.create_my_orders()
        if len(neworders) == 0:
            return [0], []  # cancel old order
        # oldorder may not exist when this is called from on_tx_confirmed
        # (this happens when we just spent from the max mixdepth and so had
        # to cancel the order).
        if oldorder:
            if oldorder['maxsize'] == neworders[0]['maxsize']:
                return [], []  # change nothing
        # announce new order, replacing the old order
        return [], [neworders[0]]

    def on_tx_confirmed(self, cjorder, confirmations, txid):
        if cjorder.cj_addr in self.tx_unconfirm_timestamp:
            confirm_time = int(time.time()) - self.tx_unconfirm_timestamp[
                cjorder.cj_addr]
        else:
            confirm_time = 0
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.log_statement([timestamp, cjorder.cj_amount, len(
            cjorder.utxos), sum([av['value'] for av in cjorder.utxos.values(
            )]), cjorder.real_cjfee, cjorder.real_cjfee - cjorder.txfee, round(
                confirm_time / 60.0, 2), ''])
        return self.on_tx_unconfirmed(cjorder, txid, None)


if __name__ == "__main__":
    ygmain(YieldGeneratorPrivEnhance, txfee=txfee,
           cjfee_a=cjfee_a, cjfee_r=cjfee_r,
           ordertype=ordertype, nickserv_password='',
           minsize=min_minsize, gaplimit=gaplimit)
    print('done')
