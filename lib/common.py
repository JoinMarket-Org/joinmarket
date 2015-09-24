import bitcoin as btc
from decimal import Decimal, InvalidOperation
from math import factorial, exp
import sys, datetime, json, time, pprint, threading, getpass
import random
import blockchaininterface, slowaes
from ConfigParser import SafeConfigParser, NoSectionError, NoOptionError
import os, io, itertools

JM_VERSION = 2
nickname = ''
DUST_THRESHOLD = 546
bc_interface = None
ordername_list = ["absorder", "relorder"]
maker_timeout_sec = 30

debug_file_lock = threading.Lock()
debug_file_handle = None
core_alert = None
joinmarket_alert = None
debug_silence = False

config = SafeConfigParser()
config_location = 'joinmarket.cfg'
# FIXME: Add rpc_* options here in the future!
required_options = {'BLOCKCHAIN': ['blockchain_source', 'network'],
                    'MESSAGING': ['host', 'channel', 'port']}

defaultconfig =\
"""
[BLOCKCHAIN]
blockchain_source = blockr 
#options: blockr, bitcoin-rpc, json-rpc, regtest
#for instructions on bitcoin-rpc read https://github.com/chris-belcher/joinmarket/wiki/Running-JoinMarket-with-Bitcoin-Core-full-node 
network = mainnet
rpc_host = localhost
rpc_port = 8332
rpc_user = bitcoin
rpc_password = password

[MESSAGING]
host = irc.cyberguerrilla.org
channel = joinmarket-pit
port = 6697
usessl = true
socks5 = false
socks5_host = localhost
socks5_port = 9050
#for tor
#host = 6dvj6v5imhny3anf.onion
#port = 6697
#usessl = true
#socks5 = true
maker_timeout_sec = 30

[POLICY]
#for dust sweeping, try merge_algorithm = gradual
merge_algorithm = default
"""


def load_program_config():
    loadedFiles = config.read([config_location])
    #Create default config file if not found
    if len(loadedFiles) != 1:
        config.readfp(io.BytesIO(defaultconfig))
        with open(config_location, "w") as configfile:
            configfile.write(defaultconfig)

    #check for sections
    for s in required_options:
        if s not in config.sections():
            raise Exception(
                "Config file does not contain the required section: " + s)
    #then check for specific options
    for k, v in required_options.iteritems():
        for o in v:
            if o not in config.options(k):
                raise Exception(
                    "Config file does not contain the required option: " + o)

    try:
        global maker_timeout_sec
        maker_timeout_sec = config.getint('MESSAGING', 'maker_timeout_sec')
    except NoOptionError:
        debug('maker_timeout_sec not found in .cfg file, using default value')

    #configure the interface to the blockchain on startup
    global bc_interface
    bc_interface = blockchaininterface.get_blockchain_interface_instance(config)


def get_config_irc_channel():
    channel = '#' + config.get("MESSAGING", "channel")
    if get_network() == 'testnet':
        channel += '-test'
    return channel


def debug(msg):
    global debug_file_handle
    with debug_file_lock:
        if nickname and not debug_file_handle:
            debug_file_handle = open(
                os.path.join('logs', nickname + '.log'), 'ab', 1)
        outmsg = datetime.datetime.now().strftime("[%Y/%m/%d %H:%M:%S] ") + msg
        if not debug_silence:
            if core_alert:
                print 'Core Alert Message: ' + core_alert
            if joinmarket_alert:
                print 'JoinMarket Alert Message: ' + joinmarket_alert
            print outmsg
        if nickname:  #debugs before creating bot nick won't be handled like this
            debug_file_handle.write(outmsg + '\r\n')


            #Random functions - replacing some NumPy features
            #NOTE THESE ARE NEITHER CRYPTOGRAPHICALLY SECURE 
            #NOR PERFORMANT NOR HIGH PRECISION!
            #Only for sampling purposes
def rand_norm_array(mu, sigma, n):
    #use normalvariate instead of gauss for thread safety
    return [random.normalvariate(mu, sigma) for i in range(n)]


def rand_exp_array(lamda, n):
    #'lambda' is reserved (in case you are triggered by spelling errors)
    return [random.expovariate(1.0 / lamda) for i in range(n)]


def rand_pow_array(power, n):
    #rather crude in that uses a uniform sample which is a multiple of 1e-4
    #for basis of formula, see: http://mathworld.wolfram.com/RandomNumber.html
    return [y**(1.0 / power)
            for y in [x * 0.0001 for x in random.sample(
                xrange(10000), n)]]


def rand_weighted_choice(n, p_arr):
    '''Choose a value in 0..n-1
	with the choice weighted by the probabilities
	in the list p_arr. Note that there will be some
	floating point rounding errors, but see the note
	at the top of this section.'''
    if abs(sum(p_arr) - 1.0) > 1e-4:
        raise ValueError("Sum of probabilities must be 1")
    if len(p_arr) != n:
        raise ValueError("Need: " + str(n) + " probabilities.")
    cum_pr = [sum(p_arr[:i + 1]) for i in xrange(len(p_arr))]
    r = random.random()
    return sorted(cum_pr + [r]).index(r)
#End random functions


def chunks(d, n):
    return [d[x:x + n] for x in xrange(0, len(d), n)]


def get_network():
    '''Returns network name'''
    return config.get("BLOCKCHAIN", "network")


def get_addr_vbyte():
    if get_network() == 'testnet':
        return 0x6f
    else:
        return 0x00


def validate_address(addr):
    try:
        ver = btc.get_version_byte(addr)
    except AssertionError:
        return False, 'Checksum wrong. Typo in address?'
    if ver != get_addr_vbyte():
        return False, 'Wrong address version. Testnet/mainnet confused?'
    return True, 'address validated'


def debug_dump_object(obj, skip_fields=[]):
    debug('Class debug dump, name:' + obj.__class__.__name__)
    for k, v in obj.__dict__.iteritems():
        if k in skip_fields:
            continue
        debug('key=' + k)
        if isinstance(v, str):
            debug('string: len:' + str(len(v)))
            debug(v)
        elif isinstance(v, dict) or isinstance(v, list):
            debug(pprint.pformat(v))
        else:
            debug(str(v))


def select_gradual(unspent, value):
    '''
	UTXO selection algorithm for gradual dust reduction
	If possible, combines outputs, picking as few as possible of the largest
	utxos less than the target value; if the target value is larger than the
	sum of all smaller utxos, uses the smallest utxo larger than the value.
	'''
    value, key = int(value), lambda u: u["value"]
    high = sorted([u for u in unspent if key(u) >= value], key=key)
    low = sorted([u for u in unspent if key(u) < value], key=key)
    lowsum = reduce(lambda x, y: x + y, map(key, low), 0)
    if value > lowsum:
        if len(high) == 0:
            raise Exception('Not enough funds')
        else:
            return [high[0]]
    else:
        start, end, total = 0, 0, 0
        while total < value:
            total += low[end]['value']
            end += 1
        while total >= value + low[start]['value']:
            total -= low[start]['value']
            start += 1
        return low[start:end]


def select_greedy(unspent, value):
    '''
	UTXO selection algorithm for rapid dust reduction
	Combines the shortest run of utxos (sorted by size, from smallest) which
	exceeds the target value; if the target value is larger than the sum of
	all smaller utxos, uses the smallest utxo larger than the target value.
	'''
    value, key = int(value), lambda u: u["value"]
    high = sorted([u for u in unspent if key(u) >= value], key=key)
    low = sorted([u for u in unspent if key(u) < value], key=key)
    lowsum = reduce(lambda x, y: x + y, map(key, low), 0)
    if value > lowsum:
        if len(high) == 0:
            raise Exception('Not enough funds')
        else:
            return [high[0]]
    else:
        end, total = 0, 0
        while total < value:
            total += low[end]['value']
            end += 1
        return low[0:end]


class AbstractWallet(object):
    '''
	Abstract wallet for use with JoinMarket
	Mostly written with Wallet in mind, the default JoinMarket HD wallet
	'''

    def __init__(self):
        self.utxo_selector = btc.select  # default fallback: upstream
        try:
            if config.get("POLICY", "merge_algorithm") == "gradual":
                self.utxo_selector = select_gradual
            elif config.get("POLICY", "merge_algorithm") == "greedy":
                self.utxo_selector = select_greedy
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

    def __init__(self, seedarg, max_mix_depth=2, gaplimit=6):
        super(Wallet, self).__init__()
        self.max_mix_depth = max_mix_depth
        self.gaplimit = gaplimit
        self.seed = self.get_seed(seedarg)
        master = btc.bip32_master_key(self.seed)
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
        self.spent_utxos = []

    def get_seed(self, seedarg):
        self.path = None
        self.index_cache = [[0, 0]] * self.max_mix_depth
        path = os.path.join('wallets', seedarg)
        if not os.path.isfile(path):
            if get_network() == 'testnet':
                debug(
                    'seedarg interpreted as seed, only available in testnet because this probably has lower entropy')
                return seedarg
            else:
                raise IOError('wallet file not found')
        #debug('seedarg interpreted as wallet file name')
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
            password = getpass.getpass('Enter wallet decryption passphrase: ')
            password_key = btc.bin_dbl_sha256(password)
            encrypted_seed = walletdata['encrypted_seed']
            try:
                decrypted_seed = slowaes.decryptData(
                    password_key, encrypted_seed.decode('hex')).encode('hex')
                #there is a small probability of getting a valid PKCS7 padding
                #by chance from a wrong password; sanity check the seed length
                if len(decrypted_seed) == 32:
                    decrypted = True
                else:
                    raise ValueError
            except ValueError:
                print 'Incorrect password'
                decrypted = False
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
            self.get_key(mixing_depth, forchange, i), get_addr_vbyte())

    def get_new_addr(self, mixing_depth, forchange):
        index = self.index[mixing_depth]
        addr = self.get_addr(mixing_depth, forchange, index[forchange])
        self.addr_cache[addr] = (mixing_depth, forchange, index[forchange])
        index[forchange] += 1
        #self.update_cache_index()
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
        debug('removed utxos, wallet now is \n' + pprint.pformat(
            self.get_utxos_by_mixdepth()))
        self.spent_utxos += removed_utxos.keys()
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
                          blockchaininterface.BitcoinCoreInterface):
            raise RuntimeError(
                'Bitcoin Core wallet can only be used when blockchain interface is BitcoinCoreInterface')
        self.fromaccount = fromaccount
        self.max_mix_depth = 1

    def get_key_from_addr(self, addr):
        return bc_interface.rpc('dumpprivkey', [addr])

    def get_utxos_by_mixdepth(self):
        unspent_list = bc_interface.rpc('listunspent', [])
        result = {0: {}}
        for u in unspent_list:
            if not u['spendable']:
                continue
            if self.fromaccount and (
                ('account' not in u) or u['account'] != self.fromaccount):
                continue
            result[0][u['txid'] + ':' + str(u[
                'vout'])] = {'address': u['address'],
                             'value':
                             int(Decimal(str(u['amount'])) * Decimal('1e8'))}
        return result

    def get_change_addr(self, mixing_depth):
        return bc_interface.rpc('getrawchangeaddress', [])


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


def weighted_order_choose(orders, n, feekey):
    '''
	Algorithm for choosing the weighting function
	it is an exponential
	P(f) = exp(-(f - fmin) / phi)
	P(f) - probability of order being chosen
	f - order fee
	fmin - minimum fee in the order book
	phi - scaling parameter, 63% of the distribution is within

	define number M, related to the number of counterparties in this coinjoin
	phi has a value such that it contains up to the Mth order
	unless M < orderbook size, then phi goes up to the last order
	'''
    minfee = feekey(orders[0])
    M = int(3 * n)
    if len(orders) > M:
        phi = feekey(orders[M]) - minfee
    else:
        phi = feekey(orders[-1]) - minfee
    fee = [feekey(o) for o in orders]
    debug('phi=' + str(phi) + ' fee=' + ','.join([str(f) for f in fee]))
    if phi > 0:
        weight = [exp(-(1.0 * f - minfee) / phi) for f in fee]
    else:
        weight = [1.0] * len(fee)
    weight = [x / sum(weight) for x in weight]
    debug('randomly choosing orders with weighting\n' + pprint.pformat(zip(
        orders, weight)))
    chosen_order_index = rand_weighted_choice(len(orders), weight)
    return orders[chosen_order_index]


def cheapest_order_choose(orders, n, feekey):
    '''
	Return the cheapest order from the orders.
	'''
    return sorted(orders, key=feekey)[0]


def pick_order(orders, n, feekey):
    i = -1
    print("Considered orders:")
    for o in orders:
        i += 1
        print("    %2d. %20s, CJ fee: %6d, tx fee: %6d" % (i, o[0], o[2], o[3]))
    pickedOrderIndex = -1
    if i == 0:
        print("Only one possible pick, picking it.")
        return orders[0]
    while pickedOrderIndex == -1:
        try:
            pickedOrderIndex = int(raw_input('Pick an order between 0 and ' +
                                             str(i) + ': '))
        except ValueError:
            pickedOrderIndex = -1
            continue

        if pickedOrderIndex >= 0 and pickedOrderIndex < len(orders):
            return orders[pickedOrderIndex]
        pickedOrderIndex = -1


def choose_orders(db, cj_amount, n, chooseOrdersBy, ignored_makers=[]):
    sqlorders = db.execute('SELECT * FROM orderbook;').fetchall()
    orders = [(o['counterparty'], o['oid'], calc_cj_fee(
        o['ordertype'], o['cjfee'], cj_amount), o['txfee'])
              for o in sqlorders
              if cj_amount >= o['minsize'] and cj_amount <= o['maxsize'] and o[
                  'counterparty'] not in ignored_makers]
    counterparties = set([o[0] for o in orders])
    if n > len(counterparties):
        debug(
            'ERROR not enough liquidity in the orderbook n=%d suitable-counterparties=%d amount=%d totalorders=%d'
            % (n, len(counterparties), cj_amount, len(orders)))
        return None, 0  #TODO handle not enough liquidity better, maybe an Exception
    orders = sorted(orders,
                    key=lambda k: k[2])  #sort from smallest to biggest cj fee
    debug('considered orders = ' + str(orders))
    total_cj_fee = 0
    chosen_orders = []
    for i in range(n):
        chosen_order = chooseOrdersBy(orders, n, lambda k: k[2])
        orders = [o for o in orders if o[0] != chosen_order[0]
                 ]  #remove all orders from that same counterparty
        chosen_orders.append(chosen_order)
        total_cj_fee += chosen_order[2]
    debug('chosen orders = ' + str(chosen_orders))
    chosen_orders = [o[:2] for o in chosen_orders]
    return dict(chosen_orders), total_cj_fee


def choose_sweep_orders(db,
                        my_total_input,
                        my_tx_fee,
                        n,
                        chooseOrdersBy,
                        ignored_makers=[]):
    '''
	choose an order given that we want to be left with no change
	i.e. sweep an entire group of utxos

	solve for cjamount when mychange = 0
	for an order with many makers, a mixture of absorder and relorder
	mychange = totalin - cjamount - mytxfee - sum(absfee) - sum(relfee*cjamount)
	=> 0 = totalin - mytxfee - sum(absfee) - cjamount*(1 + sum(relfee))
	=> cjamount = (totalin - mytxfee - sum(absfee)) / (1 + sum(relfee))
	'''

    def calc_zero_change_cj_amount(ordercombo):
        sumabsfee = 0
        sumrelfee = Decimal('0')
        for order in ordercombo:
            if order['ordertype'] == 'absorder':
                sumabsfee += int(order['cjfee'])
            elif order['ordertype'] == 'relorder':
                sumrelfee += Decimal(order['cjfee'])
            else:
                raise RuntimeError('unknown order type: ' + str(ordertype))
        cjamount = (my_total_input - my_tx_fee - sumabsfee) / (1 + sumrelfee)
        cjamount = int(cjamount.quantize(Decimal(1)))
        return cjamount, int(sumabsfee + sumrelfee * cjamount)

    def is_amount_in_range(ordercombo, cjamount):
        for order in ordercombo:
            if cjamount >= order['maxsize'] or cjamount <= order['minsize']:
                return False
        return True

    sqlorders = db.execute('SELECT * FROM orderbook;').fetchall()
    orderkeys = ['counterparty', 'oid', 'ordertype', 'minsize', 'maxsize',
                 'txfee', 'cjfee']
    orderlist = [dict([(k, o[k]) for k in orderkeys])
                 for o in sqlorders if o['counterparty'] not in ignored_makers]

    ordercombos = [combo for combo in itertools.combinations(orderlist, n)]

    ordercombos = [(c, calc_zero_change_cj_amount(c)) for c in ordercombos]
    ordercombos = [oc for oc in ordercombos
                   if is_amount_in_range(oc[0], oc[1][0])]
    ordercombos = sorted(ordercombos, key=lambda k: k[1][0], reverse=True)
    dbgprint = [([(o['counterparty'], o['oid']) for o in oc[0]], oc[1])
                for oc in ordercombos]
    debug('considered order combinations')
    debug(pprint.pformat(dbgprint))

    if len(ordercombos) == 0:
        debug('ERROR not enough liquidity in the orderbook')
        return None, 0  #TODO handle not enough liquidity better, maybe an Exception

    ordercombo = chooseOrdersBy(ordercombos, n, lambda k: k[1][1]
                               )  #index [1][1] = cjfee
    orders = dict([(o['counterparty'], o['oid']) for o in ordercombo[0]])
    cjamount = ordercombo[1][0]
    debug('chosen orders = ' + str(orders))
    debug('cj amount = ' + str(cjamount))
    return orders, cjamount
