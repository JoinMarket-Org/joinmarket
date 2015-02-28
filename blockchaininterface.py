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
	self.fptrs = {'addrtx': self.get_txs_from_addr, 
		         'txinfo': self.get_tx_info,
		         'addrunspent': self.get_utxos_from_addr,
		         'addrbalance': self.get_balance_at_addr,
		         'txraw': self.get_tx_info,
		         'txpush': self.send_tx}	
        
    def parse_request(self, body, csv_params, query_params=None):
	return self.fptrs[body](csv_params, query_params)
    
    @abc.abstractmethod
    def get_txs_from_addr(self, addresses, query_params):
        '''Given a list of addresses, list all transactions'''
        pass
    
    @abc.abstractmethod
    def get_tx_info(self, txhash, query_params):
        '''Given a txhash and query params indicating raw,
	return the tx hex. If indicating non-raw, return a list of vouts.
	May need some more structure in query_params to handle unconfirmed. TODO'''
        pass
    
    @abc.abstractmethod
    def get_utxos_from_addr(self, addresses, query_params):
        '''Given an address, return a list of utxos
        in format txid:vout'''
        pass
    
    @abc.abstractmethod
    def get_balance_at_addr(self, addresses, query_params):
        '''Given an address, return a balance in satoshis'''
        pass

    @abc.abstractmethod
    def send_tx(self, tx_hexs, query_params):
        '''Given raw txhex, push to network and return result in form: TODO'''
        pass 
    
    @abc.abstractmethod
    def get_net_info(self):
        pass        
    ''' 
    @abc.abstractmethod
    def get_addr_from_utxo(self, txhash, index):
        Given utxo in form txhash, index, return the address
        owning the utxo and the amount in satoshis in form (addr, amt)
        pass
    '''

class BlockrImp(BlockChainInterface):
    def __init__(self, testnet = True):
        super(BlockrImp, self).__init__()
	self.bodies = {'addrtx':'address/txs/','txinfo':'tx/info/','addrunspent':'address/unspent/',
		                  'addrbalance':'address/balance/','txraw':'tx/raw/','txpush':'tx/push/'}	
	self.testnet = 'testnet' if testnet else 'btc' #see bci.py in bitcoin module
        self.query_stem = 'http://tbtc.blockr.io/api/v1/' if testnet else 'http://tbtc.blockr.io/api/v1/'
    
    def parse_request(self, body, csv_params, query_params=None):
	if body=='pushtx':
	    return super(BlockrImp, self).parse_request(body, csv_params, query_params)
	else:
	    req = self.query_stem + self.bodies[body] + '/' + ','.join(csv_params) + '?' + ','.join(query_params)
	    return btc.make_request(req)
    
    def send_tx(self, tx_hexs, query_params):
	#TODO: handle multiple txs?
	return btc.blockr_pushtx(tx_hexs[0], self.testnet)

    def get_net_info(self):
        print 'not yet done'

    def get_txs_from_addr(self, addresses, query_params):
        pass
    
    def get_tx_info(self, txhash, query_params):
        pass
    
    def get_utxos_from_addr(self, addresses, query_params):
        pass
    
    def get_balance_at_addr(self, addresses, query_params):
        pass

class TestNetImp(BlockChainInterface):
    def __init__(self, rpcport = 18332, port = 8332):
	super(TestNetImp, self).__init__()
        self.command_params = ['bitcoin-cli', '-port='+str(port), '-rpcport='+str(rpcport),'-testnet']
        #quick check that it's up else quit
        try:
            res = self.rpc(['getbalance'])
        except Exception as e:
            print e
    
    def get_net_info(self):
        print 'not yet done'
        
    def rpc(self, args, accept_failure=[]):
        try:
            #print 'making an rpc call with these parameters: '
            #print self.command_params+args
            res = subprocess.check_output(self.command_params+args)
        except subprocess.CalledProcessError, e:
            if e.returncode in accept_failure:
                return ''
            raise
        return res

    def send_tx(self, tx_hexs, query_params):
	'''csv params contains only tx hex'''
	for txhex in tx_hexs:
	    res = self.rpc(['sendrawtransaction', txhex])
        #TODO only handles a single push; handle multiple
        return {'data':res}

    def get_utxos_from_addr(self, addresses, query_params):
        r = []
        for address in addresses:
            res = json.loads(self.rpc(['listunspent','1','9999999','[\"'+address+'\"]']))
            unspents=[]
            for u in res:
                unspents.append({'tx':u['txid'],'n':u['vout'],'amount':str(u['amount']),'address':address,'confirmations':u['confirmations']})
            r.append({'address':address,'unspent':unspents})
        return {'data':r}
    
    def get_txs_from_addr(self, addresses, query_params):
        #use listtransactions and then filter
        #e.g.: -regtest listtransactions 'watchonly' 1000 0 true
        #to get the last 1000 transactions TODO 1000 is arbitrary
        acct_addrlist = self.rpc(['getaddressesbyaccount', 'watchonly'])
        for address in addresses:
            if address not in acct_addrlist:
                self.rpc(['importaddress', address,'watchonly'],[4])            
        res = json.loads(self.rpc(['listtransactions','watchonly','2000','0','true']))
        
        result=[]
        for address in addresses:
            nbtxs = 0
            txs=[]
            for a in res:
                if a['address'] != address:
                    continue
                nbtxs += 1
                txs.append({'confirmations':a['confirmations'],'tx':a['txid'],'amount':a['amount']})
            result.append({'nb_txs':nbtxs,'address':address,'txs':txs})
        return {'data':result} 
    
    def get_tx_info(self, txhashes, query_params):
	'''Returns a list of vouts if raw is False, else returns tx hex'''
	#TODO: handle more than one tx hash
        res = json.loads(self.rpc(['getrawtransaction', txhashes[0], '1']))
        if not query_params[0]:
            return {'data':{'tx':{'hex':res['hex']}}}
        tx = btc.deserialize(res['hex'])
        #build vout list
        vouts = []
        n=0
        for o in tx['outs']:
            vouts.append({'n':n,'amount':o['value'],'address':btc.script_to_address(o['script'],0x6f)})
            n+=1
        
        return {'data':{'vouts':vouts}}
   
    def get_balance_at_addr(self, addresses, query_params):
        #NB This will NOT return coinbase coins (but wont matter in our use case).
        #In order to have the Bitcoin RPC read balances at addresses
        #it doesn't own, we must import the addresses as watch-only 
        #Note that this is a 0.10 feature; won't work with older bitcoin clients.
        #TODO : there can be a performance issue with rescanning here.
	#TODO: This code is WRONG, reports *received* coins in total, not current balance.
        #allow importaddress to fail in case the address is already in the wallet
        res = []
        for address in addresses:
            self.rpc(['importaddress', address,'watchonly'],[4])
            res.append({'address':address,'balance':\
                        int(Decimal(1e8) * Decimal(self.rpc(['getreceivedbyaddress', address])))})
        return {'data':res}

    #Not used; I think, not needed
    '''def get_addr_from_utxo(self, txhash, index):
        #get the transaction details
        res = json.loads(self.rpc(['gettxout', txhash, str(index)]))
        amt = int(Decimal(1e8)*Decimal(res['value']))
        address = res('addresses')[0]
        return (address, amt)
        '''
    
#class for regtest chain access
#running on local daemon. Only 
#to be instantiated after network is up
#with > 100 blocks.
class RegTestImp(TestNetImp):
    def __init__(self, port=8331, rpcport=18331):
	super(TestNetImp,self).__init__() #note: call to *grandparent* init for fptrs
        self.command_params = ['bitcoin-cli', '-port='+str(port), '-rpcport='+str(rpcport),'-regtest']
        #quick check that it's up else quit
        try:
            res = self.rpc(['getbalance'])
            self.current_balance = int(Decimal(res))
            print "Instantiated interface to regtest, wallet balance is: "+str(self.current_balance) +" bitcoins."
            if not self.current_balance > 0:
                raise Exception("Regtest network not properly initialised.")            
        except Exception as e:
            print e        

    
    def send_tx(self, tx_hex, query_params):
        super(RegTestImp, self).send_tx(tx_hex, query_params)
        self.tick_forward_chain(1)
        
    def tick_forward_chain(self, n):
            '''Special method for regtest only;
            instruct to mine n blocks.'''
            self.rpc(['setgenerate','true', str(n)])
    
    def grab_coins(self, receiving_addr, amt=50):
        '''
        NOTE! amt is passed in Coins, not Satoshis!
        Special method for regtest only:
        take coins from bitcoind's own wallet
        and put them in the receiving addr.
        Return the txid.
        '''
        if amt > 500:
            raise Exception("too greedy")
        if amt > self.current_balance:
            #mine enough to get to the reqd amt
            reqd = int(amt - self.current_balance)
            reqd_blocks = str(int(reqd/50) +1)
            if self.rpc(['setgenerate','true', reqd_blocks]):
                raise Exception("Something went wrong")
        #now we do a custom create transaction and push to the receiver
        txid = self.rpc(['sendtoaddress', receiving_addr, str(amt)])
        if not txid:
            raise Exception("Failed to broadcast transaction")
        #confirm
        self.tick_forward_chain(1)
        return txid        

def main():
    myBCI = RegTestImp()
    #myBCI.send_tx('stuff')
    print myBCI.get_utxos_from_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
    print myBCI.get_balance_at_addr(["n4EjHhGVS4Rod8ociyviR3FH442XYMWweD"])
    txid = myBCI.grab_coins('mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd',23)
    print txid
    print myBCI.get_balance_at_addr(['mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd'])
    print myBCI.get_utxos_from_addr(['mygp9fsgEJ5U7jkPpDjX9nxRj8b5nC3Hnd'])

if __name__ == '__main__':
    main()




