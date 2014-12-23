from taker import *

my_tx_fee = 10000


class TestTaker(Taker):

    def __init__(self, wallet):
        Taker.__init__(self)
        self.wallet = wallet

    def on_privmsg(self, nick, message):
        Taker.on_privmsg(self, nick, message)
        #debug("privmsg nick=%s message=%s" % (nick, message))
        if message[0] != command_prefix:
            return
        for command in message[1:].split(command_prefix):
            chunks = command.split(" ")
        if chunks[0] == 'myparts':
            utxo_list = chunks[1].split(',')
            cj_addr = chunks[2]
            change_addr = chunks[3]
            self.cjtx.recv_tx_parts(nick, utxo_list, cj_addr, change_addr)
        elif chunks[0] == 'sig':
            sig = chunks[1]
            self.cjtx.add_signature(sig)

    def on_pubmsg(self, nick, message):
        Taker.on_pubmsg(self, nick, message)
        if message[0] != command_prefix:
            return
        for command in message[1:].split(command_prefix):
            #commands starting with % are for testing and will be removed in the final version
            chunks = command.split(" ")
            if chunks[0] == '%showob':
                print('printing orderbook')
                for o in self.db.execute('SELECT * FROM orderbook;').fetchall():
                    print '(%s %s %d %d-%d %d %s)' % (
                        o['counterparty'], o['ordertype'], o['oid'],
                        o['minsize'], o['maxsize'], o['txfee'], o['cjfee'])
                print('done')
            elif chunks[0] == '%unspent':
                from pprint import pprint
                pprint(self.wallet.unspent)
            elif chunks[0] == '%fill':
                counterparty = chunks[1]
                oid = chunks[2]
                amount = chunks[3]
                my_utxo = chunks[4]
                #!fill [counterparty] [oid] [amount] [utxo]
                print 'making cjtx'
                self.cjtx = CoinJoinTX(
                    self,
                    int(amount),
                    [counterparty],
                    [int(oid)],
                    [my_utxo],
                    self.wallet.get_receive_addr(mixing_depth=1),
                    self.wallet.get_change_addr(mixing_depth=0),
                    my_tx_fee)


def main():
    import sys
    seed = sys.argv[1]  #btc.sha256('your brainwallet goes here')
    from socket import gethostname
    nickname = 'testtakr-' + btc.sha256(gethostname())[:6]

    print 'downloading wallet history'
    wallet = Wallet(seed)
    wallet.download_wallet_history()
    wallet.find_unspent_addresses()

    print 'starting irc'
    taker = TestTaker(wallet)
    taker.run(HOST, PORT, nickname, CHANNEL)


if __name__ == "__main__":
    main()
    print('done')
