Bitcointalk thread:
https://bitcointalk.org/index.php?topic=919116.msg10096563


FIRST IMPLEMENTATION OF JOINMARKET

you will need to know python somewhat to play around with it
 also get some testnet coins

HOWTO try
1. You will need libsodium installed
 Get it here: http://doc.libsodium.org/installation/README.html

2. Come up with a wallet seed. This is a bit like a brainwallet, it can be any string.
 For real bitcoins you would probably generate it from 128 bits of entropy and encode
 in a 12-word mnemonic. For testnet just use anything.

$ python gui-taker.py
  Starts a local http server which you can connect to and will display the orderbook as well as some graphs

$ python wallet-tool.py [seed]
  To print out a bunch of addresses, send some testnet coins to an address

$ python sendpayment.py -N 1 [seed] [amount-in-satoshi] [destination address]
  Chooses the cheapest offer to do a 2-party coinjoin to send money to a destination address

If you're a frugal user and don't want to pay for a coinjoin if you dont have to, use this command
$ python patientsendpayments.py -N 1 -w 2 [wallet seed] [amount in satoshi] [destination address]
  Announces orders and waits to coinjoin for a maximum of 2 hours. Once that time it up cancels the
  orders and pays to do a 2-party coinjoin.

$ python yield-generator.py [seed]
  Becomes an investor bot, being online indefinitely and doing coinjoin for the purpose of profit.
  Edit the file to change the IRC nick, offered fee, nickserv password and so on

Watch the output of your bot(s), soon enough the taker will say it has completed
 a transaction, maker will wait for the transaction to be seen and confirmed
If there are no orders, you could run two bots from the same machine. Be sure to use
 two seperate wallet seeds though.


