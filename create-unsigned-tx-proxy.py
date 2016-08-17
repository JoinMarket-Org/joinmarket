#! /usr/bin/env python

""" create-unsigned-tx-proxy is desigend to do the joinmarket heavy-lifting on
    behalf of a client. The client allows this proxy to do so by signing a nacl
    key pair with one of the used UTXO's addresses private keys.
"""

from __future__ import absolute_import

import sys
import threading
import time
from flask import Flask, abort, jsonify, make_response, request
from optparse import OptionParser
import pprint

from joinmarket import taker as takermodule
from joinmarket import load_program_config, validate_address, \
    jm_single, get_p2pk_vbyte, random_nick
from joinmarket import get_log, choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose
from joinmarket import AbstractWallet, IRCMessageChannel, debug_dump_object

import bitcoin as btc
import sendpayment

import libnacl.public
from joinmarket import enc_wrapper

log = get_log()

app = Flask(__name__)

@app.errorhandler(400)
def bad_request(error):
    return make_response(jsonify({'error': 'Bad Request'}), 400)

@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)

@app.route('/joinmarket/v1/ping')
def ping():
    return jsonify({'ping': 'pong'})

load_program_config()
try:
    nacl_sk_hex = jm_single().config.get("JM_PROXY", "nacl_sk_hex")
    kp = libnacl.public.SecretKey(nacl_sk_hex.decode('hex'))
except:
    print('\n\nNo key for the joinmarket proxy found')
    print('please add these lines to your config:\n')
    kp = enc_wrapper.init_keypair()
    sk = kp.sk.encode('hex')
    pk = kp.pk.encode('hex')
    print('[JM_PROXY]')
    print("# generated by enc_wrapper.init_keypair().sk.encode('hex')")
    print("# clients have to use\n#   {0}\n# as public key.".format(pk))
    print('nacl_sk_hex = {0}\n\n'.format(sk))
    exit()

@app.route('/joinmarket/v1/getAuthKey', methods = ['GET'])
def get_auth_key():
    """returns a libnacl public key for the client to sign in order to approve
       this proxy.
    """
    # TODO: with one more node there is one more edge for a MITM to attack.
    # We could/should? use pk for encryption with the client, too, at least
    # optionally.
    # TODO: kp getting created per server start is one option but the client
    # doesn't know if it can trust it. Maybe there should be one key pair per
    # server instance that signs the per session keys, so the IRC can't
    # (trivially) know it's the same proxy but the client can trust the proxy
    # even without https.
    return jsonify({'pk': kp.pk.encode('hex')})

@app.route('/joinmarket/v1/getUnsignedTransaction', methods = ['POST'])
def get_unsigned_transaction():
    print(request.json)
    if (not request.json or
        not 'authUtxo' in request.json or
        not 'authUtxoPK' in request.json or
        not 'naclKeySig' in request.json or
        not 'utxos' in request.json or
        not 'change' in request.json or
        not 'recipient' in request.json or
        not 'amount' in request.json):
        abort(400)
    auth_utxo = request.json['authUtxo']
    authPK = str(request.json['authUtxoPK'])
    naclKeySig = request.json['naclKeySig'].decode('hex')
    if btc.ecdsa_verify(kp.pk.encode('hex'), naclKeySig, authPK.decode('hex')):
        print('good sig found')
        # TODO: check if the public key matches the authUtxo
    else:
        print('bad sig. aborting.')
        abort(400)
    makerCount = request.json['makerCount']
    cold_utxos = request.json['utxos']
    changeaddr = request.json['change']
    destaddr = request.json['recipient']
    cjamount = request.json['amount']
    options = type('Options', (object,), {
        'testnet': request.json['testnet'],
        'txfee': 100000,         # total miner fee in satoshis
        'waittime': 5,          # wait time in seconds to allow orders to arrive
        'makercount': 1,        # how many makers to coinjoin with
        'choosecheapest': True, # override weightened offers picking and choose
                                # cheapest
        'pickorders': False,    # manually pick which orders to take
        'answeryes': True       # answer yes to everything
    })
    tx = get_unsigned_tx(auth_utxo, naclKeySig, cjamount, destaddr, changeaddr,
        cold_utxos, options, kp, authPK)
    return jsonify({'result': tx})

#thread which does the buy-side algorithm
# chooses which coinjoins to initiate and when
class PaymentThread(threading.Thread):
    def __init__(self, taker):
        threading.Thread.__init__(self)
        self.daemon = True
        self.taker = taker
        self.ignored_makers = []

    def create_tx(self):
        crow = self.taker.db.execute(
                'SELECT COUNT(DISTINCT counterparty) FROM orderbook;'
        ).fetchone()

        counterparty_count = crow['COUNT(DISTINCT counterparty)']
        counterparty_count -= len(self.ignored_makers)
        if counterparty_count < self.taker.options.makercount:
            print 'not enough counterparties to fill order, ending'
            self.taker.msgchan.shutdown()
            return

        utxos = self.taker.utxo_data
        orders = None
        cjamount = 0
        change_addr = None
        choose_orders_recover = None
        if self.taker.cjamount == 0:
            total_value = sum([va['value'] for va in utxos.values()])
            orders, cjamount = choose_sweep_orders(
                    self.taker.db, total_value, self.taker.options.txfee,
                    self.taker.options.makercount, self.taker.chooseOrdersFunc,
                    self.ignored_makers)
        else:
            orders, total_cj_fee = self.sendpayment_choose_orders(
                    self.taker.cjamount, self.taker.options.makercount)
            if not orders:
                log.debug(
                        'ERROR not enough liquidity in the orderbook, exiting')
                self.taker.msgchan.shutdown()
                return
            total_amount = self.taker.cjamount + total_cj_fee + \
                           self.taker.options.txfee
            print 'total amount spent = ' + str(total_amount)
            cjamount = self.taker.cjamount
            change_addr = self.taker.changeaddr
            choose_orders_recover = self.sendpayment_choose_orders

        auth_addr = self.taker.utxo_data[self.taker.auth_utxo]['address']
        kp = self.taker.kp
        my_btc_sig = self.taker.naclKeySig
        my_btc_pub = self.taker.my_btc_pub
        self.taker.start_cj(None, cjamount, orders, utxos,
                            self.taker.destaddr, change_addr,
                            self.taker.options.txfee, self.finishcallback,
                            choose_orders_recover, auth_addr, kp,
                            my_btc_sig, my_btc_pub)

    def finishcallback(self, coinjointx):
        if coinjointx.all_responded:
            tx = btc.serialize(coinjointx.latest_tx)
            print 'unsigned tx = \n\n' + tx + '\n'
            self.taker.msgchan.shutdown()
            self.taker.tx = tx
            return
        self.ignored_makers += coinjointx.nonrespondants
        log.debug(
                'recreating the tx, ignored_makers=' + str(self.ignored_makers))
        self.create_tx()

    def sendpayment_choose_orders(self,
                                  cj_amount,
                                  makercount,
                                  nonrespondants=None,
                                  active_nicks=None):
        if active_nicks is None:
            active_nicks = []
        if nonrespondants is None:
            nonrespondants = []
        self.ignored_makers += nonrespondants
        orders, total_cj_fee = choose_orders(
                self.taker.db, cj_amount, makercount,
                self.taker.chooseOrdersFunc,
                self.ignored_makers + active_nicks)
        if not orders:
            return None, 0
        print 'chosen orders to fill: {0}\ntotalcjfee: {1}'.format(str(orders),
                str(total_cj_fee))
        total_fee_pc = 1.0 * total_cj_fee / cj_amount
        log.debug(' coinjoin fee = ' + str(float('%.3g' % (100.0 * total_fee_pc))) + '%')
        if total_fee_pc > 0.02:
            # TODO: do something meaningful here. Also fees configurable.
            pass
        return orders, total_cj_fee

    def run(self):
        print 'waiting for all orders to certainly arrive'
        debug_dump_object(self.taker)
        time.sleep(self.taker.options.waittime)
        self.create_tx()


class CreateUnsignedTx(takermodule.Taker):
    def __init__(self, msgchan, auth_utxo, naclKeySig, cjamount, destaddr,
                 changeaddr, utxo_data, options, chooseOrdersFunc, kp, my_btc_pub):
        super(CreateUnsignedTx, self).__init__(msgchan)
        self.auth_utxo = auth_utxo
        self.naclKeySig = naclKeySig
        self.cjamount = cjamount
        self.destaddr = destaddr
        self.changeaddr = changeaddr
        self.utxo_data = utxo_data
        self.options = options
        self.chooseOrdersFunc = chooseOrdersFunc
        self.kp = kp
        self.my_btc_pub = my_btc_pub
        self.tx = None

    def on_welcome(self):
        takermodule.Taker.on_welcome(self)
        PaymentThread(self).start()

def get_unsigned_tx(auth_utxo, naclKeySig, cjamount, destaddr, changeaddr,
                    cold_utxos, options, kp, my_btc_pub):
    addr_valid1, errormsg1 = validate_address(destaddr)
    #if amount = 0 dont bother checking changeaddr so user can write any junk
    # TODO: cjamount == 0 is the sweep option. I already partially removed it
    # but it actually makes sense to add it again. doh.
    if cjamount != 0:
        addr_valid2, errormsg2 = validate_address(changeaddr)
    else:
        addr_valid2 = True
    if not addr_valid1 or not addr_valid2:
        if not addr_valid1:
            print 'ERROR: Address invalid. ' + errormsg1
        else:
            print 'ERROR: Address invalid. ' + errormsg2
        return

    all_utxos = [auth_utxo] + cold_utxos
    query_result = jm_single().bc_interface.query_utxo_set(all_utxos)
    if None in query_result:
        print query_result
    utxo_data = {}
    for utxo, data in zip(all_utxos, query_result):
        utxo_data[utxo] = {'address': data['address'], 'value': data['value']}

    chooseOrdersFunc = cheapest_order_choose
    
    jm_single().nickname = random_nick()
    log.debug('starting sendpayment')

    irc = IRCMessageChannel(jm_single().nickname)
    taker = CreateUnsignedTx(irc, auth_utxo, naclKeySig, cjamount, destaddr,
                             changeaddr, utxo_data, options, chooseOrdersFunc,
                             kp, my_btc_pub)
    try:
        log.debug('starting irc')
        irc.run()
        log.debug('done irc')
        return taker.tx
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(taker)
        import traceback
        log.debug(traceback.format_exc())


if __name__ == "__main__":
    app.run()
