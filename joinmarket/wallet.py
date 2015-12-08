import json
import os
import pprint
import sys
from decimal import Decimal

from ConfigParser import NoSectionError
from getpass import getpass

import bitcoin as btc
from joinmarket import get_network, debug, decryptData, \
    get_p2pk_vbyte, bc_interface, BitcoinCoreInterface, config, select_gradual, \
    select_greedy, select_greediest, JsonRpcError


class AbstractWallet(object):
    '''
	Abstract wallet for use with JoinMarket
	Mostly written with Wallet in mind, the default JoinMarket HD wallet
	'''

    def __init__(self):
        self.max_mix_depth = 0
        self.utxo_selector = btc.select  # default fallback: upstream
        try:
            if config.get("POLICY", "merge_algorithm") == "gradual":
                self.utxo_selector = select_gradual
            elif config.get("POLICY", "merge_algorithm") == "greedy":
                self.utxo_selector = select_greedy
            elif config.get("POLICY", "merge_algorithm") == "greediest":
                self.utxo_selector = select_greediest
            elif config.get("POLICY", "merge_algorithm") != "default":
                raise Exception("Unknown merge algorithm")
        except NoSectionError:
            pass

    def get_key_from_addr(self, addr):
        return None

    def get_utxos_by_mixdepth(self):
        return None

    def get_change_addr(self, mixing_depth):
        return None

    def update_cache_index(self):
        pass

    def remove_old_utxos(self, tx):
        pass

    def add_new_utxos(self, tx, txid):
        pass

    def select_utxos(self, mixdepth, amount):
        utxo_list = self.get_utxos_by_mixdepth()[mixdepth]
        unspent = [{'utxo': utxo,
                    'value': addrval['value']}
                   for utxo, addrval in utxo_list.iteritems()]
        inputs = self.utxo_selector(unspent, amount)
        debug('for mixdepth=' + str(mixdepth) + ' amount=' + str(amount) +
              ' selected:')
        debug(pprint.pformat(inputs))
        return dict([(i['utxo'], {'value': i['value'],
                                  'address': utxo_list[i['utxo']]['address']})
                     for i in inputs])

    def get_balance_by_mixdepth(self):
        mix_balance = {}
        for m in range(self.max_mix_depth):
            mix_balance[m] = 0
        for mixdepth, utxos in self.get_utxos_by_mixdepth().iteritems():
            mix_balance[mixdepth] = sum([addrval['value']
                                         for addrval in utxos.values()])
        return mix_balance


class Wallet(AbstractWallet):
    def __init__(self,
                 seedarg,
                 max_mix_depth=2,
                 gaplimit=6,
                 extend_mixdepth=False,
                 storepassword=False):
        super(Wallet, self).__init__()
        self.max_mix_depth = max_mix_depth
        self.storepassword = storepassword
        # key is address, value is (mixdepth, forchange, index)
        # if mixdepth = -1 it's an imported key and index refers to imported_privkeys
        self.addr_cache = {}
        self.unspent = {}
        self.spent_utxos = []
        self.imported_privkeys = {}
        self.seed = self.read_wallet_file_data(seedarg)
        if extend_mixdepth and len(self.index_cache) > max_mix_depth:
            self.max_mix_depth = len(self.index_cache)
        self.gaplimit = gaplimit
        master = btc.bip32_master_key(self.seed)
        m_0 = btc.bip32_ckd(master, 0)
        mixing_depth_keys = [btc.bip32_ckd(m_0, c)
                             for c in range(self.max_mix_depth)]
        self.keys = [(btc.bip32_ckd(m, 0), btc.bip32_ckd(m, 1))
                     for m in mixing_depth_keys]

        # self.index = [[0, 0]]*max_mix_depth
        self.index = []
        for i in range(self.max_mix_depth):
            self.index.append([0, 0])

    def read_wallet_file_data(self, filename):
        self.path = None
        self.index_cache = [[0, 0]] * self.max_mix_depth
        path = os.path.join('wallets', filename)
        if not os.path.isfile(path):
            if get_network() == 'testnet':
                debug(
                        'filename interpreted as seed, only available in testnet because this probably has lower entropy')
                return filename
            else:
                raise IOError('wallet file not found')
        self.path = path
        fd = open(path, 'r')
        walletfile = fd.read()
        fd.close()
        walletdata = json.loads(walletfile)
        if walletdata['network'] != get_network():
            print 'wallet network(%s) does not match joinmarket configured network(%s)' % (
                walletdata['network'], get_network())
            sys.exit(0)
        if 'index_cache' in walletdata:
            self.index_cache = walletdata['index_cache']
        decrypted = False
        while not decrypted:
            password = getpass('Enter wallet decryption passphrase: ')
            password_key = btc.bin_dbl_sha256(password)
            encrypted_seed = walletdata['encrypted_seed']
            try:
                decrypted_seed = decryptData(
                        password_key, encrypted_seed.decode('hex')).encode(
                    'hex')
                # there is a small probability of getting a valid PKCS7 padding
                # by chance from a wrong password; sanity check the seed length
                if len(decrypted_seed) == 32:
                    decrypted = True
                else:
                    raise ValueError
            except ValueError:
                print 'Incorrect password'
                decrypted = False
        if self.storepassword:
            self.password_key = password_key
            self.walletdata = walletdata
        if 'imported_keys' in walletdata:
            for epk_m in walletdata['imported_keys']:
                privkey = decryptData(password_key,
                                      epk_m['encrypted_privkey']
                                      .decode('hex')).encode('hex')
                privkey = btc.encode_privkey(privkey, 'hex_compressed')
                if epk_m['mixdepth'] not in self.imported_privkeys:
                    self.imported_privkeys[epk_m['mixdepth']] = []
                self.addr_cache[btc.privtoaddr(privkey, get_p2pk_vbyte())] = (
                    epk_m['mixdepth'], -1,
                    len(self.imported_privkeys[epk_m['mixdepth']]))
                self.imported_privkeys[epk_m['mixdepth']].append(privkey)
        return decrypted_seed

    def update_cache_index(self):
        if not self.path:
            return
        if not os.path.isfile(self.path):
            return
        fd = open(self.path, 'r')
        walletfile = fd.read()
        fd.close()
        walletdata = json.loads(walletfile)
        walletdata['index_cache'] = self.index
        walletfile = json.dumps(walletdata)
        fd = open(self.path, 'w')
        fd.write(walletfile)
        fd.close()

    def get_key(self, mixing_depth, forchange, i):
        return btc.bip32_extract_key(btc.bip32_ckd(self.keys[mixing_depth][
                                                       forchange], i))

    def get_addr(self, mixing_depth, forchange, i):
        return btc.privtoaddr(
                self.get_key(mixing_depth, forchange, i), get_p2pk_vbyte())

    def get_new_addr(self, mixing_depth, forchange):
        index = self.index[mixing_depth]
        addr = self.get_addr(mixing_depth, forchange, index[forchange])
        self.addr_cache[addr] = (mixing_depth, forchange, index[forchange])
        index[forchange] += 1
        # self.update_cache_index()
        if isinstance(bc_interface, BitcoinCoreInterface):
            if bc_interface.wallet_synced:  # do not import in the middle of sync_wallet()
                if bc_interface.rpc('getaccount', [addr]) == '':
                    debug('importing address ' + addr + ' to bitcoin core')
                    bc_interface.rpc('importaddress',
                                     [addr, bc_interface.get_wallet_name(self),
                                      False])
        return addr

    def get_receive_addr(self, mixing_depth):
        return self.get_new_addr(mixing_depth, False)

    def get_change_addr(self, mixing_depth):
        return self.get_new_addr(mixing_depth, True)

    def get_key_from_addr(self, addr):
        if addr not in self.addr_cache:
            return None
        ac = self.addr_cache[addr]
        if ac[1] >= 0:
            return self.get_key(*ac)
        else:
            return self.imported_privkeys[ac[0]][ac[2]]

    def remove_old_utxos(self, tx):
        removed_utxos = {}
        for ins in tx['ins']:
            utxo = ins['outpoint']['hash'] + ':' + str(ins['outpoint']['index'])
            if utxo not in self.unspent:
                continue
            removed_utxos[utxo] = self.unspent[utxo]
            del self.unspent[utxo]
        debug('removed utxos, wallet now is \n' + pprint.pformat(
                self.get_utxos_by_mixdepth()))
        self.spent_utxos += removed_utxos.keys()
        return removed_utxos

    def add_new_utxos(self, tx, txid):
        added_utxos = {}
        for index, outs in enumerate(tx['outs']):
            addr = btc.script_to_address(outs['script'], get_p2pk_vbyte())
            if addr not in self.addr_cache:
                continue
            addrdict = {'address': addr, 'value': outs['value']}
            utxo = txid + ':' + str(index)
            added_utxos[utxo] = addrdict
            self.unspent[utxo] = addrdict
        debug('added utxos, wallet now is \n' + pprint.pformat(
                self.get_utxos_by_mixdepth()))
        return added_utxos

    def get_utxos_by_mixdepth(self):
        '''
		returns a list of utxos sorted by different mix levels
		'''
        mix_utxo_list = {}
        for m in range(self.max_mix_depth):
            mix_utxo_list[m] = {}
        for utxo, addrvalue in self.unspent.iteritems():
            mixdepth = self.addr_cache[addrvalue['address']][0]
            if mixdepth not in mix_utxo_list:
                mix_utxo_list[mixdepth] = {}
            mix_utxo_list[mixdepth][utxo] = addrvalue
        debug('get_utxos_by_mixdepth = \n' + pprint.pformat(mix_utxo_list))
        return mix_utxo_list


class BitcoinCoreWallet(AbstractWallet):
    def __init__(self, fromaccount):
        super(BitcoinCoreWallet, self).__init__()
        if not isinstance(bc_interface,
                          BitcoinCoreInterface):
            raise RuntimeError(
                    'Bitcoin Core wallet can only be used when blockchain interface is BitcoinCoreInterface')
        self.fromaccount = fromaccount
        self.max_mix_depth = 1

    def get_key_from_addr(self, addr):
        self.ensure_wallet_unlocked()
        return bc_interface.rpc('dumpprivkey', [addr])

    def get_utxos_by_mixdepth(self):
        unspent_list = bc_interface.rpc('listunspent', [])
        result = {0: {}}
        for u in unspent_list:
            if not u['spendable']:
                continue
            if self.fromaccount and (
                        ('account' not in u) or u[
                        'account'] != self.fromaccount):
                continue
            result[0][u['txid'] + ':' + str(u[
                                                'vout'])] = {
                'address': u['address'],
                'value':
                    int(Decimal(str(u['amount'])) * Decimal('1e8'))}
        return result

    def get_change_addr(self, mixing_depth):
        return bc_interface.rpc('getrawchangeaddress', [])

    def ensure_wallet_unlocked(self):
        wallet_info = bc_interface.rpc('getwalletinfo', [])
        if 'unlocked_until' in wallet_info and wallet_info[
            'unlocked_until'] <= 0:
            while True:
                password = getpass(
                        'Enter passphrase to unlock wallet: ')
                if password == '':
                    raise RuntimeError('Aborting wallet unlock')
                try:
                    # TODO cleanly unlock wallet after use, not with arbitrary timeout
                    bc_interface.rpc('walletpassphrase', [password, 10])
                    break
                except JsonRpcError as exc:
                    if exc.code != -14:
                        raise exc
                        # Wrong passphrase, try again.
