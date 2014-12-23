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

    def __init__(self, taker, initial_unspents):
        threading.Thread.__init__(self)
        self.daemon = True
        self.taker = taker
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
                self.taker.shutdown()
                #break

                #utxo, addrvalue = self.initial_unspents.popitem()
            utxo, addrvalue = [(k, v)
                               for k, v in self.initial_unspents.iteritems()
                               if v['value'] == 200000000][0]
            counterparty, oid, cj_amount = choose_sweep_order(
                addrvalue['value'], my_tx_fee)
            self.finished_cj = False
            cjtx = CoinJoinTX(
                self.taker,
                cj_amount,
                [counterparty],
                [int(oid)],
                [utxo],
                self.taker.wallet.get_receive_addr(mixing_depth=1),
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


def main():
    print 'downloading wallet history'
    wallet = Wallet(seed)
    wallet.download_wallet_history()
    wallet.find_unspent_addresses()


if __name__ == "__main__":
    main()
    print('done')
