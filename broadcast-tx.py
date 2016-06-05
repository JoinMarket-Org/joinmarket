#! /usr/bin/env python
from __future__ import absolute_import

import sys
import threading
from optparse import OptionParser
import time

from joinmarket import OrderbookWatch, load_program_config, IRCMessageChannel
from joinmarket import jm_single, MessageChannelCollection
from joinmarket import random_nick
from joinmarket import get_log, debug_dump_object, get_irc_mchannels

log = get_log()

class BroadcastThread(threading.Thread):

    def __init__(self, taker):
        threading.Thread.__init__(self)
        self.daemon = True
        self.taker = taker

    def run(self):
        print('waiting for all orders to certainly arrive')
        time.sleep(self.taker.waittime)
        crow = self.taker.db.execute(
            'SELECT DISTINCT counterparty FROM orderbook ORDER BY RANDOM() LIMIT 1;'
        ).fetchone()
        counterparty = crow['counterparty']
        log.debug('sending tx to ' + counterparty)
        self.taker.msgchan.push_tx(counterparty, self.taker.txhex)
        time.sleep(30) #wait for the irc throttle thread to send everything
        #when the tx notify callback is written, use that instead of a hardcoded wait
        self.taker.msgchan.shutdown()

class Broadcaster(OrderbookWatch):

    def __init__(self, msgchan, waittime, txhex):
        OrderbookWatch.__init__(self, msgchan)
        self.waittime = waittime
        self.txhex = txhex

    def on_welcome(self):
        OrderbookWatch.on_welcome(self)
        BroadcastThread(self).start()

def main():
    parser = OptionParser(
        usage=
        'usage: %prog [options] [tx hex]',
        description='Sends a transaction to a random market maker requesting that they broadcast it '
        +
        'to the wider bitcoin network. Used to add a layer between your own IP address and the network '
        +
        'where other methods are not possible.')
    parser.add_option(
        '-w',
        '--wait-time',
        action='store',
        type='float',
        dest='waittime',
        help='wait time in seconds to allow orders to arrive, default=5',
        default=10)
    (options, args) = parser.parse_args()

    if len(args) < 1:
        parser.error('Needs a transaction hex string')
        sys.exit(0)
    txhex = args[0]

    load_program_config()
    jm_single().nickname = random_nick()
    log.debug('starting broadcast-tx')
    mcs = [IRCMessageChannel(c, jm_single().nickname) for c in get_irc_mchannels()]
    mcc = MessageChannelCollection(mcs)
    taker = Broadcaster(mcc, options.waittime, txhex)
    try:
        log.debug('starting message channels')
        mcc.run()
    except:
        log.debug('CRASHING, DUMPING EVERYTHING')
        debug_dump_object(taker)
        import traceback
        log.debug(traceback.format_exc())

if __name__ == "__main__":
    main()
    print('done')
