from __future__ import absolute_import, print_function

import BaseHTTPServer
import abc
import ast
import json
import os
import pprint
import random
import re
import sys
import threading
import time
import urllib
import urllib2
from decimal import Decimal

import bitcoin as btc

# This can be removed once CliJsonRpc is gone.
import subprocess

from joinmarket.jsonrpc import JsonRpcConnectionError, JsonRpcError
from joinmarket.configure import get_p2pk_vbyte, jm_single
from joinmarket.support import get_log, chunks

log = get_log()


class CliJsonRpc(object):
    """
    Fake JsonRpc class that uses the Bitcoin CLI executable.  This is used
    as temporary fall back before we switch completely (and exclusively)
    to the real JSON-RPC interface.
    """

    def __init__(self, cli, testnet):
        self.cli = cli
        if testnet:
            self.cli.append("-testnet")

    def call(self, method, params):
        fullCall = []
        fullCall.extend(self.cli)
        fullCall.append(method)
        for p in params:
            if isinstance(p, basestring):
                fullCall.append(p)
            else:
                fullCall.append(json.dumps(p))

        res = subprocess.check_output(fullCall)

        if res == '':
            return None

        try:
            return json.loads(res)
        except ValueError:
            return res.strip()


def is_index_ahead_of_cache(wallet, mix_depth, forchange):
    if mix_depth >= len(wallet.index_cache):
        return True
    return wallet.index[mix_depth][forchange] >= wallet.index_cache[mix_depth][
        forchange]


class BlockchainInterface(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self):
        pass

    def sync_wallet(self, wallet):
        self.sync_addresses(wallet)
        self.sync_unspent(wallet)

    @abc.abstractmethod
    def sync_addresses(self, wallet):
        """Finds which addresses have been used and sets
        wallet.index appropriately"""
        pass

    @abc.abstractmethod
    def sync_unspent(self, wallet):
        """Finds the unspent transaction outputs belonging to this wallet,
        sets wallet.unspent """
        pass

    @abc.abstractmethod
    def add_tx_notify(self, txd, unconfirmfun, confirmfun, notifyaddr):
        """Invokes unconfirmfun and confirmfun when tx is seen on the network"""
        pass

    @abc.abstractmethod
    def pushtx(self, txhex):
        """pushes tx to the network, returns txhash, or None if failed"""
        pass

    @abc.abstractmethod
    def query_utxo_set(self, txouts):
        """
        takes a utxo or a list of utxos
        returns None if they are spend or unconfirmed
        otherwise returns value in satoshis, address and output script
        """
        # address and output script contain the same information btw
    
    @abc.abstractmethod
    def estimate_fee_per_kb(self, N):
        '''Use the blockchain interface to 
        get an estimate of the transaction fee per kb
        required for inclusion in the next N blocks.
	'''


class BlockrInterface(BlockchainInterface):
    BLOCKR_MAX_ADDR_REQ_COUNT = 20

    def __init__(self, testnet=False):
        super(BlockrInterface, self).__init__()

        # see bci.py in bitcoin module
        self.network = 'testnet' if testnet else 'btc'
        self.blockr_domain = 'tbtc' if testnet else 'btc'
        self.last_sync_unspent = 0

    def sync_addresses(self, wallet):
        log.debug('downloading wallet history')
        # sets Wallet internal indexes to be at the next unused address
        for mix_depth in range(wallet.max_mix_depth):
            for forchange in [0, 1]:
                unused_addr_count = 0
                last_used_addr = ''
                while (unused_addr_count < wallet.gaplimit or
                           not is_index_ahead_of_cache(
                                   wallet, mix_depth, forchange)):
                    addrs = [wallet.get_new_addr(mix_depth, forchange)
                             for _ in range(self.BLOCKR_MAX_ADDR_REQ_COUNT)]

                    # TODO send a pull request to pybitcointools
                    # because this surely should be possible with a function from it
                    blockr_url = 'https://' + self.blockr_domain
                    blockr_url += '.blockr.io/api/v1/address/txs/'

                    res = btc.make_request(blockr_url + ','.join(addrs))
                    data = json.loads(res)['data']
                    for dat in data:
                        if dat['nb_txs'] != 0:
                            last_used_addr = dat['address']
                            unused_addr_count = 0
                        else:
                            unused_addr_count += 1
                if last_used_addr == '':
                    wallet.index[mix_depth][forchange] = 0
                else:
                    wallet.index[mix_depth][forchange] = wallet.addr_cache[
                                                             last_used_addr][
                                                             2] + 1

    def sync_unspent(self, wallet):
        # finds utxos in the wallet
        st = time.time()
        # dont refresh unspent dict more often than 10 minutes
        rate_limit_time = 10 * 60
        if st - self.last_sync_unspent < rate_limit_time:
            log.debug(
                    'blockr sync_unspent() happened too recently (%dsec), skipping'
                    % (st - self.last_sync_unspent))
            return
        wallet.unspent = {}

        addrs = wallet.addr_cache.keys()
        if len(addrs) == 0:
            log.debug('no tx used')
            return
        i = 0
        while i < len(addrs):
            inc = min(len(addrs) - i, self.BLOCKR_MAX_ADDR_REQ_COUNT)
            req = addrs[i:i + inc]
            i += inc

            # TODO send a pull request to pybitcointools
            # unspent() doesnt tell you which address, you get a bunch of utxos
            # but dont know which privkey to sign with

            blockr_url = 'https://' + self.blockr_domain + \
                         '.blockr.io/api/v1/address/unspent/'
            res = btc.make_request(blockr_url + ','.join(req))
            data = json.loads(res)['data']
            if 'unspent' in data:
                data = [data]
            for dat in data:
                for u in dat['unspent']:
                    wallet.unspent[u['tx'] + ':' + str(u['n'])] = {
                        'address': dat['address'],
                        'value': int(u['amount'].replace('.', ''))}
        for u in wallet.spent_utxos:
            wallet.unspent.pop(u, None)

        self.last_sync_unspent = time.time()
        log.debug('blockr sync_unspent took ' + str((self.last_sync_unspent -
                                                     st)) + 'sec')

    def add_tx_notify(self, txd, unconfirmfun, confirmfun, notifyaddr):
        unconfirm_timeout = 10 * 60  # seconds
        unconfirm_poll_period = 5
        confirm_timeout = 2 * 60 * 60
        confirm_poll_period = 5 * 60

        class NotifyThread(threading.Thread):

            def __init__(self, blockr_domain, txd, unconfirmfun, confirmfun):
                threading.Thread.__init__(self, name='BlockrNotifyThread')
                self.daemon = True
                self.blockr_domain = blockr_domain
                self.unconfirmfun = unconfirmfun
                self.confirmfun = confirmfun
                self.tx_output_set = set([(sv['script'], sv['value'])
                                          for sv in txd['outs']])
                self.output_addresses = [
                    btc.script_to_address(scrval[0], get_p2pk_vbyte())
                    for scrval in self.tx_output_set]
                log.debug('txoutset=' + pprint.pformat(self.tx_output_set))
                log.debug('outaddrs=' + ','.join(self.output_addresses))

            def run(self):
                st = int(time.time())
                unconfirmed_txid = None
                unconfirmed_txhex = None
                while not unconfirmed_txid:
                    time.sleep(unconfirm_poll_period)
                    if int(time.time()) - st > unconfirm_timeout:
                        log.debug('checking for unconfirmed tx timed out')
                        return
                    blockr_url = 'https://' + self.blockr_domain
                    blockr_url += '.blockr.io/api/v1/address/unspent/'
                    random.shuffle(self.output_addresses
                                   )  # seriously weird bug with blockr.io
                    data = json.loads(
                            btc.make_request(blockr_url + ','.join(
                                    self.output_addresses
                            ) + '?unconfirmed=1'))['data']

                    shared_txid = None
                    for unspent_list in data:
                        txs = set([str(txdata['tx'])
                                   for txdata in unspent_list['unspent']])
                        if not shared_txid:
                            shared_txid = txs
                        else:
                            shared_txid = shared_txid.intersection(txs)
                    log.debug('sharedtxid = ' + str(shared_txid))
                    if len(shared_txid) == 0:
                        continue
                    time.sleep(
                            2
                    )  # here for some race condition bullshit with blockr.io
                    blockr_url = 'https://' + self.blockr_domain
                    blockr_url += '.blockr.io/api/v1/tx/raw/'
                    data = json.loads(btc.make_request(blockr_url + ','.join(
                            shared_txid)))['data']
                    if not isinstance(data, list):
                        data = [data]
                    for txinfo in data:
                        txhex = str(txinfo['tx']['hex'])
                        outs = set([(sv['script'], sv['value'])
                                    for sv in btc.deserialize(txhex)['outs']])
                        log.debug('unconfirm query outs = ' + str(outs))
                        if outs == self.tx_output_set:
                            unconfirmed_txid = txinfo['tx']['txid']
                            unconfirmed_txhex = str(txinfo['tx']['hex'])
                            break

                self.unconfirmfun(
                        btc.deserialize(unconfirmed_txhex), unconfirmed_txid)

                st = int(time.time())
                confirmed_txid = None
                confirmed_txhex = None
                while not confirmed_txid:
                    time.sleep(confirm_poll_period)
                    if int(time.time()) - st > confirm_timeout:
                        log.debug('checking for confirmed tx timed out')
                        return
                    blockr_url = 'https://' + self.blockr_domain
                    blockr_url += '.blockr.io/api/v1/address/txs/'
                    data = json.loads(btc.make_request(blockr_url + ','.join(
                            self.output_addresses)))['data']
                    shared_txid = None
                    for addrtxs in data:
                        txs = set(str(txdata['tx'])
                                  for txdata in addrtxs['txs'])
                        if not shared_txid:
                            shared_txid = txs
                        else:
                            shared_txid = shared_txid.intersection(txs)
                    log.debug('sharedtxid = ' + str(shared_txid))
                    if len(shared_txid) == 0:
                        continue
                    blockr_url = 'https://' + self.blockr_domain
                    blockr_url += '.blockr.io/api/v1/tx/raw/'
                    data = json.loads(
                            btc.make_request(
                                    blockr_url + ','.join(shared_txid)))['data']
                    if not isinstance(data, list):
                        data = [data]
                    for txinfo in data:
                        txhex = str(txinfo['tx']['hex'])
                        outs = set([(sv['script'], sv['value'])
                                    for sv in btc.deserialize(txhex)['outs']])
                        log.debug('confirm query outs = ' + str(outs))
                        if outs == self.tx_output_set:
                            confirmed_txid = txinfo['tx']['txid']
                            confirmed_txhex = str(txinfo['tx']['hex'])
                            break
                self.confirmfun(
                        btc.deserialize(confirmed_txhex), confirmed_txid, 1)

        NotifyThread(self.blockr_domain, txd, unconfirmfun, confirmfun).start()

    def pushtx(self, txhex):
        try:
            json_str = btc.blockr_pushtx(txhex, self.network)
        except Exception:
            log.debug('failed blockr.io pushtx')
            return None
        data = json.loads(json_str)
        if data['status'] != 'success':
            log.debug(data)
            return None
        return data['data']

    def query_utxo_set(self, txout):
        if not isinstance(txout, list):
            txout = [txout]
        txids = [h[:64] for h in txout]
        txids = list(set(txids))  # remove duplicates
        # self.BLOCKR_MAX_ADDR_REQ_COUNT = 2
        if len(txids) > self.BLOCKR_MAX_ADDR_REQ_COUNT:
            txids = chunks(txids, self.BLOCKR_MAX_ADDR_REQ_COUNT)
        else:
            txids = [txids]
        data = []
        for ids in txids:
            blockr_url = 'https://' + self.blockr_domain + '.blockr.io/api/v1/tx/info/'
            blockr_data = json.loads(
                    btc.make_request(blockr_url + ','.join(ids)))['data']
            if not isinstance(blockr_data, list):
                blockr_data = [blockr_data]
            data += blockr_data
        result = []
        for txo in txout:
            txdata = [d for d in data if d['tx'] == txo[:64]][0]
            vout = [v for v in txdata['vouts'] if v['n'] == int(txo[65:])][0]
            if vout['is_spent'] == 1:
                result.append(None)
            else:
                result.append({'value': int(Decimal(vout['amount']) * Decimal(
                        '1e8')),
                               'address': vout['address'],
                               'script': vout['extras']['script']})
        return result

    def estimate_fee_per_kb(self, N):
        bcypher_fee_estimate_url = 'https://api.blockcypher.com/v1/btc/main'
        bcypher_data = json.loads(btc.make_request(bcypher_fee_estimate_url))
        log.debug("Got blockcypher result: "+pprint.pformat(bcypher_data))
	if N<=2:
	    fee_per_kb = bcypher_data["high_fee_per_kb"]
	elif N <=4:
	    fee_per_kb = bcypher_data["medium_fee_per_kb"]
	else:
	    fee_per_kb = bcypher_data["low_fee_per_kb"]
	    
	return fee_per_kb

class NotifyRequestHeader(BaseHTTPServer.BaseHTTPRequestHandler):
    def __init__(self, request, client_address, base_server):
        self.btcinterface = base_server.btcinterface
        self.base_server = base_server
        BaseHTTPServer.BaseHTTPRequestHandler.__init__(
                self, request, client_address, base_server)

    def do_HEAD(self):
        pages = ('/walletnotify?', '/alertnotify?')

        if self.path.startswith('/walletnotify?'):
            txid = self.path[len(pages[0]):]
            if not re.match('^[0-9a-fA-F]*$', txid):
                log.debug('not a txid')
                return
            try:
                tx = self.btcinterface.rpc('getrawtransaction', [txid])
            except (JsonRpcError, JsonRpcConnectionError) as e:
                log.debug('transaction not found, probably a conflict')
                return
            if not re.match('^[0-9a-fA-F]*$', tx):
                log.debug('not a txhex')
                return
            txd = btc.deserialize(tx)
            tx_output_set = set([(sv['script'], sv['value']) for sv in txd[
                'outs']])

            txnotify_tuple = None
            unconfirmfun, confirmfun, uc_called = None, None, None
            for tnf in self.btcinterface.txnotify_fun:
                tx_out = tnf[0]
                if tx_out == tx_output_set:
                    txnotify_tuple = tnf
                    tx_out, unconfirmfun, confirmfun, uc_called = tnf
                    break
            if unconfirmfun is None:
                log.debug('txid=' + txid + ' not being listened for')
            else:
                # on rare occasions people spend their output without waiting
                #  for a confirm
                txdata = None
                for n in range(len(txd['outs'])):
                    txdata = self.btcinterface.rpc('gettxout', [txid, n, True])
                    if txdata is not None:
                        break
                assert txdata is not None
                if txdata['confirmations'] == 0:
                    unconfirmfun(txd, txid)
                    # TODO pass the total transfered amount value here somehow
                    # wallet_name = self.get_wallet_name()
                    # amount =
                    # bitcoin-cli move wallet_name "" amount
                    self.btcinterface.txnotify_fun.remove(txnotify_tuple)
                    self.btcinterface.txnotify_fun.append(txnotify_tuple[:-1]
                        + (True,))
                    log.debug('ran unconfirmfun')
                else:
                    if not uc_called:
                        unconfirmfun(txd, txid)
                        log.debug('saw confirmed tx before unconfirmed, ' +
                            'running unconfirmfun first')
                    confirmfun(txd, txid, txdata['confirmations'])
                    self.btcinterface.txnotify_fun.remove(txnotify_tuple)
                    log.debug('ran confirmfun')

        elif self.path.startswith('/alertnotify?'):
            jm_single().core_alert[0] = urllib.unquote(self.path[len(pages[1]):])
            log.debug('Got an alert!\nMessage=' + jm_single().core_alert[0])

        else:
            log.debug('ERROR: This is not a handled URL path.  You may want to check your notify URL for typos.')

        request = urllib2.Request('http://localhost:' + str(self.base_server.server_address[1] + 1) + self.path)
        request.get_method = lambda : 'HEAD'
        try:
            urllib2.urlopen(request)
        except urllib2.URLError:
            pass
        self.send_response(200)
        # self.send_header('Connection', 'close')
        self.end_headers()


class BitcoinCoreNotifyThread(threading.Thread):
    def __init__(self, btcinterface):
        threading.Thread.__init__(self, name='CoreNotifyThread')
        self.daemon = True
        self.btcinterface = btcinterface

    def run(self):
        notify_host = 'localhost'
        notify_port = 62602  # defaults
        config = jm_single().config
        if 'notify_host' in config.options("BLOCKCHAIN"):
            notify_host = config.get("BLOCKCHAIN", "notify_host").strip()
        if 'notify_port' in config.options("BLOCKCHAIN"):
            notify_port = int(config.get("BLOCKCHAIN", "notify_port"))
        for inc in range(10):
            hostport = (notify_host, notify_port + inc)
            try:
                httpd = BaseHTTPServer.HTTPServer(hostport, NotifyRequestHeader)
            except Exception:
                continue
            httpd.btcinterface = self.btcinterface
            log.debug('started bitcoin core notify listening thread, host=' +
                      str(notify_host) + ' port=' + str(hostport[1]))
            httpd.serve_forever()
        log.debug('failed to bind for bitcoin core notify listening')


# must run bitcoind with -server
# -walletnotify="curl -sI --connect-timeout 1 http://localhost:62602/walletnotify?%s"
# and make sure curl is installed (git uses it, odds are you've already got it)

class BitcoinCoreInterface(BlockchainInterface):
    def __init__(self, jsonRpc, network):
        super(BitcoinCoreInterface, self).__init__()
        self.jsonRpc = jsonRpc

        blockchainInfo = self.jsonRpc.call("getblockchaininfo", [])
        actualNet = blockchainInfo['chain']

        netmap = {'main': 'mainnet', 'test': 'testnet', 'regtest': 'regtest'}
        if netmap[actualNet] != network:
            raise Exception('wrong network configured')

        self.notifythread = None
        self.txnotify_fun = []
        self.wallet_synced = False

    @staticmethod
    def get_wallet_name(wallet):
        return 'joinmarket-wallet-' + btc.dbl_sha256(wallet.keys[0][0])[:6]

    def rpc(self, method, args):
        if method not in ['importaddress', 'walletpassphrase']:
            log.debug('rpc: ' + method + " " + str(args))
        res = self.jsonRpc.call(method, args)
        if isinstance(res, unicode):
            res = str(res)
        return res

    def add_watchonly_addresses(self, addr_list, wallet_name):
        log.debug('importing ' + str(len(addr_list)) +
                  ' addresses into account ' + wallet_name)
        for addr in addr_list:
            self.rpc('importaddress', [addr, wallet_name, False])
        if jm_single().config.get(
                "BLOCKCHAIN", "blockchain_source") != 'regtest':
            print('restart Bitcoin Core with -rescan if you\'re '
                  'recovering an existing wallet from backup seed')
            print(' otherwise just restart this joinmarket script')
            sys.exit(0)

    def sync_addresses(self, wallet):
        from joinmarket.wallet import BitcoinCoreWallet

        if isinstance(wallet, BitcoinCoreWallet):
            return
        log.debug('requesting wallet history')
        wallet_name = self.get_wallet_name(wallet)
        addr_req_count = 20
        wallet_addr_list = []
        for mix_depth in range(wallet.max_mix_depth):
            for forchange in [0, 1]:
                wallet_addr_list += [wallet.get_new_addr(mix_depth, forchange)
                                     for _ in range(addr_req_count)]
                wallet.index[mix_depth][forchange] = 0
        # makes more sense to add these in an account called "joinmarket-imported" but its much
        # simpler to add to the same account here
        for privkey_list in wallet.imported_privkeys.values():
            for privkey in privkey_list:
                imported_addr = btc.privtoaddr(privkey, magicbyte=get_p2pk_vbyte())
                wallet_addr_list.append(imported_addr)
        imported_addr_list = self.rpc('getaddressesbyaccount', [wallet_name])
        if not set(wallet_addr_list).issubset(set(imported_addr_list)):
            self.add_watchonly_addresses(wallet_addr_list, wallet_name)
            return

        buf = self.rpc('listtransactions', [wallet_name, 1000, 0, True])
        txs = buf
        # If the buffer's full, check for more, until it ain't
        while len(buf) == 1000:
            buf = self.rpc('listtransactions', [wallet_name, 1000, len(txs),
                                                True])
            txs += buf
        # TODO check whether used_addr_list can be a set, may be faster (if
        # its a hashset) and allows using issubset() here and setdiff() for
        # finding which addresses need importing

        # TODO also check the fastest way to build up python lists, i suspect
        #  using += is slow
        used_addr_list = [tx['address']
                          for tx in txs if tx['category'] == 'receive']
        too_few_addr_mix_change = []
        for mix_depth in range(wallet.max_mix_depth):
            for forchange in [0, 1]:
                unused_addr_count = 0
                last_used_addr = ''
                breakloop = False
                while not breakloop:
                    if unused_addr_count >= wallet.gaplimit and \
                            is_index_ahead_of_cache(wallet, mix_depth,
                                                    forchange):
                        break
                    mix_change_addrs = [
                        wallet.get_new_addr(mix_depth, forchange)
                        for _ in range(addr_req_count)]
                    for mc_addr in mix_change_addrs:
                        if mc_addr not in imported_addr_list:
                            too_few_addr_mix_change.append(
                                    (mix_depth, forchange))
                            breakloop = True
                            break
                        if mc_addr in used_addr_list:
                            last_used_addr = mc_addr
                            unused_addr_count = 0
                        else:
                            unused_addr_count += 1

                if last_used_addr == '':
                    wallet.index[mix_depth][forchange] = 0
                else:
                    wallet.index[mix_depth][forchange] = \
                        wallet.addr_cache[last_used_addr][2] + 1

        wallet_addr_list = []
        if len(too_few_addr_mix_change) > 0:
            log.debug('too few addresses in ' + str(too_few_addr_mix_change))
            for mix_depth, forchange in too_few_addr_mix_change:
                wallet_addr_list += [
                    wallet.get_new_addr(mix_depth, forchange)
                    for _ in range(addr_req_count * 3)]

            self.add_watchonly_addresses(wallet_addr_list, wallet_name)
            return

        self.wallet_synced = True

    def sync_unspent(self, wallet):
        from joinmarket.wallet import BitcoinCoreWallet

        if isinstance(wallet, BitcoinCoreWallet):
            return
        st = time.time()
        wallet_name = self.get_wallet_name(wallet)
        wallet.unspent = {}

        listunspent_args = []
        if 'listunspent_args' in jm_single().config.options('POLICY'):
            listunspent_args = ast.literal_eval(
                jm_single().config.get('POLICY', 'listunspent_args'))

        unspent_list = self.rpc('listunspent', listunspent_args)
        for u in unspent_list:
            if 'account' not in u:
                continue
            if u['account'] != wallet_name:
                continue
            if u['address'] not in wallet.addr_cache:
                continue
            wallet.unspent[u['txid'] + ':' + str(u['vout'])] = {
                'address': u['address'],
                'value': int(Decimal(str(u['amount'])) * Decimal('1e8'))}
        et = time.time()
        log.debug('bitcoind sync_unspent took ' + str((et - st)) + 'sec')

    def add_tx_notify(self, txd, unconfirmfun, confirmfun, notifyaddr):
        if not self.notifythread:
            self.notifythread = BitcoinCoreNotifyThread(self)
            self.notifythread.start()
        one_addr_imported = False
        for outs in txd['outs']:
            addr = btc.script_to_address(outs['script'], get_p2pk_vbyte())
            if self.rpc('getaccount', [addr]) != '':
                one_addr_imported = True
                break
        if not one_addr_imported:
            self.rpc('importaddress', [notifyaddr, 'joinmarket-notify', False])
        tx_output_set = set([(sv['script'], sv['value']) for sv in txd['outs']])
        self.txnotify_fun.append((tx_output_set, unconfirmfun, confirmfun, False))

    def pushtx(self, txhex):
        try:
            txid = self.rpc('sendrawtransaction', [txhex])
        except JsonRpcConnectionError as e:
            log.debug('error pushing = ' + repr(e))
	    return False
        except JsonRpcError as e:
            log.debug('error pushing = ' + str(e.code) + " " + str(e.message))
	    return False
        return txid

    def query_utxo_set(self, txout):
        if not isinstance(txout, list):
            txout = [txout]
        result = []
        for txo in txout:
            ret = self.rpc('gettxout', [txo[:64], int(txo[65:]), False])
            if ret is None:
                result.append(None)
            else:
                result.append({'value': int(Decimal(str(ret['value'])) *
                                            Decimal('1e8')),
                               'address': ret['scriptPubKey']['addresses'][0],
                               'script': ret['scriptPubKey']['hex']})
        return result

    def estimate_fee_per_kb(self, N):
        estimate = Decimal(1e8)*Decimal(self.rpc('estimatefee', [N]))
	if estimate < 0:
	    #This occurs when Core has insufficient data to estimate.
	    #TODO anything better than a hardcoded default?
	    return 30000 
        else:
	    return estimate    

# class for regtest chain access
# running on local daemon. Only
# to be instantiated after network is up
# with > 100 blocks.
class RegtestBitcoinCoreInterface(BitcoinCoreInterface):
    def __init__(self, jsonRpc):
        super(RegtestBitcoinCoreInterface, self).__init__(jsonRpc, 'regtest')

    def pushtx(self, txhex):
        ret = super(RegtestBitcoinCoreInterface, self).pushtx(txhex)

        class TickChainThread(threading.Thread):
            def __init__(self, bcinterface):
                threading.Thread.__init__(self, name='TickChainThread')
                self.bcinterface = bcinterface

            def run(self):
                time.sleep(2)
                self.bcinterface.tick_forward_chain(1)

        TickChainThread(self).start()
        return ret

    def tick_forward_chain(self, n):
        """
        Special method for regtest only;
        instruct to mine n blocks.
        """
	try:
	    self.rpc('generate', [n])
	except JsonRpcConnectionError:
	    #can happen if the blockchain is shut down
	    #automatically at the end of tests; this shouldn't
	    #trigger an error
	    log.debug("Failed to generate blocks, looks like the bitcoin daemon \
	    has been shut down. Ignoring.")
	    pass

    def grab_coins(self, receiving_addr, amt=50):
        """
        NOTE! amt is passed in Coins, not Satoshis!
        Special method for regtest only:
        take coins from bitcoind's own wallet
        and put them in the receiving addr.
        Return the txid.
        """
        if amt > 500:
            raise Exception("too greedy")
        """
        if amt > self.current_balance:
        #mine enough to get to the reqd amt
        reqd = int(amt - self.current_balance)
        reqd_blocks = int(reqd/50) +1
        if self.rpc('setgenerate', [True, reqd_blocks]):
        raise Exception("Something went wrong")
        """
        # now we do a custom create transaction and push to the receiver
        txid = self.rpc('sendtoaddress', [receiving_addr, amt])
        if not txid:
            raise Exception("Failed to broadcast transaction")
        # confirm
        self.tick_forward_chain(1)
        return txid

    def get_received_by_addr(self, addresses, query_params):
        # NB This will NOT return coinbase coins (but wont matter in our use
        # case). allow importaddress to fail in case the address is already
        # in the wallet
        res = []
        for address in addresses:
            self.rpc('importaddress', [address, 'watchonly'])
            res.append({'address': address,
                        'balance': int(Decimal(1e8) * Decimal(
                                self.rpc('getreceivedbyaddress', [address])))})
        return {'data': res}

# todo: won't run anyways
# def main():
#     #TODO some useful quick testing here, so people know if they've set it up right
#     myBCI = RegtestBitcoinCoreInterface()
#     #myBCI.send_tx('stuff')
#     print myBCI.get_utxos_from_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
#     print myBCI.get_balance_at_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
#     txid = myBCI.grab_coins('mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd', 23)
#     print txid
#     print myBCI.get_balance_at_addr(['mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd'])
#     print myBCI.get_utxos_from_addr(['mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd'])
#
#
# if __name__ == '__main__':
#     main()
