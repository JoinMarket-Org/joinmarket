import bitcoin as btc
from decimal import Decimal
import sys, datetime, json, time
import threading

HOST = 'irc.freenode.net'
CHANNEL = '#joinmarket-pit-test'
PORT = 6667

#for the mainnet its #joinmarket-pit

#TODO make this var all in caps
command_prefix = '!'
MAX_PRIVMSG_LEN = 400

ordername_list = ["absorder", "relorder"]


def debug(msg):
    print datetime.datetime.now().strftime("[%Y/%m/%d %H:%M:%S] ") + msg


def get_network():
    return 'testnet'


#TODO change this name into get_addr_ver() or something
def get_addr_vbyte():
    if get_network() == 'testnet':
        return 0x6f
    else:
        return 0x00


class Wallet(object):

    def __init__(self, seed, max_mix_depth=2):
        self.max_mix_depth = max_mix_depth
        master = btc.bip32_master_key(seed)
        m_0 = btc.bip32_ckd(master, 0)
        mixing_depth_keys = [btc.bip32_ckd(m_0, c)
                             for c in range(max_mix_depth)]
        self.keys = [(btc.bip32_ckd(m, 0), btc.bip32_ckd(m, 1))
                     for m in mixing_depth_keys]

        #self.index = [[0, 0]]*max_mix_depth
        self.index = []
        for i in range(max_mix_depth):
            self.index.append([0, 0])

        #example
        #index = self.index[mixing_depth]
        #key = btc.bip32_ckd(self.keys[mixing_depth][index[0]], index[1])

        self.addr_cache = {}
        self.unspent = {}

    def get_key(self, mixing_depth, forchange, i):
        return btc.bip32_extract_key(btc.bip32_ckd(self.keys[mixing_depth][
            forchange], i))

    def get_addr(self, mixing_depth, forchange, i):
        return btc.privtoaddr(
            self.get_key(mixing_depth, forchange, i), get_addr_vbyte())

    def get_new_addr(self, mixing_depth, forchange):
        index = self.index[mixing_depth]
        addr = self.get_addr(mixing_depth, forchange, index[forchange])
        self.addr_cache[addr] = (mixing_depth, forchange, index[forchange])
        index[forchange] += 1
        return addr

    def get_receive_addr(self, mixing_depth):
        return self.get_new_addr(mixing_depth, False)

    def get_change_addr(self, mixing_depth):
        return self.get_new_addr(mixing_depth, True)

    def get_key_from_addr(self, addr):
        if addr in self.addr_cache:
            return self.get_key(*self.addr_cache[addr])
        else:
            return None

    def remove_old_utxos(self, tx):
        removed_utxos = {}
        for ins in tx['ins']:
            utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
            if utxo not in self.unspent:
                continue
            removed_utxos[utxo] = self.unspent[utxo]
            del self.unspent[utxo]
        return removed_utxos

    def add_new_utxos(self, tx, txid):
        added_utxos = {}
        for index, outs in enumerate(tx['outs']):
            addr = btc.script_to_address(outs['script'], get_addr_vbyte())
            if addr not in self.addr_cache:
                continue
            addrdict = {'address': addr, 'value': outs['value']}
            utxo = txid + ':' + str(index)
            added_utxos[utxo] = addrdict
            self.unspent[utxo] = addrdict
        return added_utxos

    def download_wallet_history(self, gaplimit=6):
        '''
		sets Wallet internal indexes to be at the next unused address
		'''
        addr_req_count = 20

        for mix_depth in range(self.max_mix_depth):
            for forchange in [0, 1]:
                unused_addr_count = 0
                last_used_addr = ''
                while unused_addr_count < gaplimit:
                    addrs = [self.get_new_addr(mix_depth, forchange)
                             for i in range(addr_req_count)]

                    #TODO send a pull request to pybitcointools
                    # because this surely should be possible with a function from it
                    if get_network() == 'testnet':
                        blockr_url = 'http://tbtc.blockr.io/api/v1/address/txs/'
                    elif network == 'btc':
                        blockr_url = 'http://btc.blockr.io/api/v1/address/txs/'
                    res = btc.make_request(blockr_url + ','.join(addrs))
                    data = json.loads(res)['data']
                    for dat in data:
                        if dat['nb_txs'] != 0:
                            last_used_addr = dat['address']
                        else:
                            unused_addr_count += 1
                            if unused_addr_count >= gaplimit:
                                break
                if last_used_addr == '':
                    self.index[mix_depth][forchange] = 0
                else:
                    self.index[mix_depth][forchange] = self.addr_cache[
                        last_used_addr][2] + 1

    def find_unspent_addresses(self):
        '''
		finds utxos in the wallet
		assumes you've already called download_wallet_history() so
		you know which addresses have been used
		'''

        addr_req_count = 20

        #TODO handle the case where there are so many addresses it cant
        # fit into one api call (>50 or so)
        addrs = {}
        for m in range(self.max_mix_depth):
            for forchange in [0, 1]:
                for n in range(self.index[m][forchange]):
                    addrs[self.get_addr(m, forchange, n)] = m
        if len(addrs) == 0:
            print 'no tx used'
            return

        i = 0
        addrkeys = addrs.keys()
        while i < len(addrkeys):
            inc = min(len(addrkeys) - i, addr_req_count)
            req = addrkeys[i:i + inc]
            i += inc

            #TODO send a pull request to pybitcointools 
            # unspent() doesnt tell you which address, you get a bunch of utxos
            # but dont know which privkey to sign with
            if get_network() == 'testnet':
                blockr_url = 'http://tbtc.blockr.io/api/v1/address/unspent/'
            elif network == 'btc':
                blockr_url = 'http://btc.blockr.io/api/v1/address/unspent/'
            res = btc.make_request(blockr_url + ','.join(req))
            data = json.loads(res)['data']
            if 'unspent' in data:
                data = [data]
            for dat in data:
                for u in dat['unspent']:
                    self.unspent[u['tx'] + ':' + str(u[
                        'n'])] = {'address': dat['address'],
                                  'value': int(u['amount'].replace('.', ''))}


#awful way of doing this, but works for now
# later use websocket api for people who dont download the blockchain
# and -walletnotify for people who do
def add_addr_notify(address, unconfirmfun, confirmfun):

    class NotifyThread(threading.Thread):

        def __init__(self, address, unconfirmfun, confirmfun):
            threading.Thread.__init__(self)
            self.daemon = True
            self.address = address
            self.unconfirmfun = unconfirmfun
            self.confirmfun = confirmfun

        def run(self):
            while True:
                time.sleep(5)
                if get_network() == 'testnet':
                    blockr_url = 'http://tbtc.blockr.io/api/v1/address/balance/'
                else:
                    blockr_url = 'http://btc.blockr.io/api/v1/address/balance/'
                res = btc.make_request(blockr_url + self.address +
                                       '?confirmations=0')
                data = json.loads(res)['data']
                if data['balance'] > 0:
                    break
            self.unconfirmfun(data['balance'] * 1e8)
            while True:
                time.sleep(5 * 60)
                if get_network() == 'testnet':
                    blockr_url = 'http://tbtc.blockr.io/api/v1/address/txs/'
                else:
                    blockr_url = 'http://btc.blockr.io/api/v1/address/txs/'
                res = btc.make_request(blockr_url + self.address +
                                       '?confirmations=0')
                data = json.loads(res)['data']
                if data['nb_txs'] == 0:
                    continue
                if data['txs'][0][
                        'confirmations'] >= 1:  #confirmation threshold
                    break
            self.confirmfun(data['txs'][0]['confirmations'],
                            data['txs'][0]['tx'],
                            data['txs'][0]['amount'] * 1e8)

    NotifyThread(address, unconfirmfun, confirmfun).start()


def calc_cj_fee(ordertype, cjfee, cj_amount):
    real_cjfee = None
    if ordertype == 'absorder':
        real_cjfee = int(cjfee)
    elif ordertype == 'relorder':
        real_cjfee = int((Decimal(cjfee) * Decimal(cj_amount)).quantize(Decimal(
            1)))
    else:
        raise RuntimeError('unknown order type: ' + str(ordertype))
    return real_cjfee


def calc_total_input_value(utxos):
    input_sum = 0
    for utxo in utxos:
        tx = btc.blockr_fetchtx(utxo[:64], get_network())
        input_sum += int(btc.deserialize(tx)['outs'][int(utxo[65:])]['value'])
    return input_sum
