#from joinmarket import *
import subprocess
import unittest
import json
import abc
from decimal import Decimal
import bitcoin as btc


class BlockChainInterface(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self):
        #TODO: pass in network type (main/test)
        pass

    @abc.abstractmethod
    def get_utxos_from_addr(self, address):
        '''Given an address, return a list of utxos
        in format txid:vout'''
        pass

    def get_balance_at_addr(self, address):
        '''Given an address, return a balance in satoshis'''
        pass

    @abc.abstractmethod
    def send_tx(self, tx_hex):
        '''Given raw txhex, push to network and return result in form: TODO'''
        print 'got herer'
        pass

    def get_net_info(self):
        pass

    def get_addr_from_utxo(self, txhash, index):
        '''Given utxo in form txhash, index, return the address
        owning the utxo and the amount in satoshis in form (addr,amt)'''
        pass


#class for regtest chain access
#running on local daemon. Only 
#to be instantiated after network is up
#with > 100 blocks.
class RegTestImp(BlockChainInterface):

    def __init__(self, client_location):
        self.command_params = [client_location, '-regtest']
        #quick check that it's up else quit
        res = self.rpc(['getbalance'])
        try:
            self.current_balance = int(Decimal(res))
            print "Instantiated interface to regtest, wallet balance is: " + str(
                self.current_balance) + " bitcoins."
            if not self.current_balance > 0:
                raise Exception("Regtest network not properly initialised.")
        except Exception as e:
            print e

    def rpc(self, args, accept_failure=[]):
        try:
            res = subprocess.check_output(self.command_params + args)
        except subprocess.CalledProcessError, e:
            if e.returncode in accept_failure:
                return ''
            raise
        return res

    def send_tx(self, tx_hex):
        res = self.rpc(['sendrawtransaction', tx_hex])
        #TODO parse return string
        print res
        return True

    def get_utxos_from_addr(self, addresses):
        for address in addresses:
            res = json.loads(self.rpc(['listunspent', '1', '9999999', '[\"' +
                                       address + '\"]']))
        #utxos = []
        #for r in res:
        #    utxos.append(r['txid']+':'+str(r['vout']))
        #return utxos
        r = []
        for address in addresses:
            utxos = [x for x in res if x['address'] == address]
            unspents = []
            for u in utxos:
                unspents.append({'tx': u['txid'],
                                 'n': u['vout'],
                                 'amount': str(u['amount']),
                                 'address': address,
                                 'confirmations': u['confirmations']})
            r.append({'address': address, 'unspent': unspents})
        return {'data': r}

    def get_txs_from_addr(self, addresses):
        #use listtransactions and then filter
        #e.g.: -regtest listtransactions 'watchonly' 1000 0 true
        #to get the last 1000 transactions TODO 1000 is arbitrary

        res = json.loads(self.rpc(['listtransactions', 'watchonly', '1000', '0',
                                   'true']))
        #print "Got this res: "
        #print res

        result = []
        for address in addresses:
            nbtxs = 0
            txs = []
            for a in res:
                if a['address'] != address:
                    continue
                nbtxs += 1
                txs.append({'confirmations': a['confirmations'],
                            'tx': a['txid'],
                            'amount': a['amount']})
            result.append({'nb_txs': nbtxs, 'address': address, 'txs': txs})
        #print "Returning this data: "
        #print result
        return {'data': result}

    def get_tx_info(self, txhash):
        res = json.loads(self.rpc(['gettransaction', txhash, 'true']))
        tx = btc.deserialize(res['hex'])
        #build vout list
        vouts = []
        n = 0
        for o in tx['outs']:
            vouts.append({'n': n,
                          'amount': o['value'],
                          'address': btc.script_to_address(o['script'])})
            n += 1

        return {'data': {'vouts': vouts}}

    def get_balance_at_addr(self, addresses):
        #NB This will NOT return coinbase coins (but wont matter in our use case).
        #In order to have the Bitcoin RPC read balances at addresses
        #it doesn't own, we must import the addresses as watch-only 
        #Note that this is a 0.10 feature; won't work with older bitcoin clients.
        #TODO : there can be a performance issue with rescanning here.

        #allow importaddress to fail in case the address is already in the wallet
        res = []
        for address in addresses:
            self.rpc(['importaddress', address, 'watchonly'], [4])
            res.append({'address': address,
                        'balance': int(Decimal(1e8) * Decimal(self.rpc(
                            ['getreceivedbyaddress', address])))})
        return {'data': res}

    def tick_forward_chain(self, n):
        '''Special method for regtest only;
        instruct to mine n blocks.'''
        self.rpc(['setgenerate', 'true', str(n)])

    def grab_coins(self, receiving_addr, amt=50):
        '''
        NOTE! amt is passed in Coins, not Satoshis!
        Special method for regtest only:
        take coins from bitcoind's own wallet
        and put them in the receiving addr.
        Return the txid.
        '''
        if amt > 500:
            raise Exception(
                "Either you forgot to pass the amount in Bitcoins, or you\'re too greedy")
        if amt > self.current_balance:
            #mine enough to get to the reqd amt
            reqd = int(amt - self.current_balance)
            reqd_blocks = str(int(reqd / 50) + 1)
            if self.rpc(['setgenerate', 'true', reqd_blocks]):
                raise Exception("Something went wrong")
        #now we do a custom create transaction and push to the receiver
        txid = self.rpc(['sendtoaddress', receiving_addr, str(amt)])
        if not txid:
            raise Exception("Failed to broadcast transaction")
        #confirm
        self.tick_forward_chain(1)
        return txid

    def get_addr_from_utxo(self, txhash, index):
        #get the transaction details
        res = json.loads(self.rpc(['gettxout', txhash, str(index)]))
        amt = int(Decimal(1e8) * Decimal(res['value']))
        address = res('addresses')[0]
        return (address, amt)


def main():
    bitcointoolsdir = '/home/adam/DevRepos/bitcoin/src/'
    btc_client = bitcointoolsdir + 'bitcoin-cli'
    myBCI = RegTestImp(btc_client)
    #myBCI.send_tx('stuff')
    print myBCI.get_utxos_from_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
    print myBCI.get_balance_at_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
    txid = myBCI.grab_coins('mtc6UaPPp2x1Fabugi8JG4BNouFo9rADNb', 23)
    print txid
    print myBCI.get_balance_at_addr(['mtc6UaPPp2x1Fabugi8JG4BNouFo9rADNb'])
    print myBCI.get_utxos_from_addr(['mtc6UaPPp2x1Fabugi8JG4BNouFo9rADNb'])


if __name__ == '__main__':
    main()
