Bitcointalk thread:
https://bitcointalk.org/index.php?topic=919116.msg10096563


FIRST IMPLEMENTATION OF JOINMARKET

you will need to know python somewhat to play around with it
 also get some testnet coins

HOWTO try
1. You will need libsodium installed
 Get it here: http://doc.libsodium.org/installation/README.html

2. run python wallet-tool.py generate
 to create your encrypted wallet file, make sure to save the 12 word seed

$ python ob-watcher.py
  Starts a local http server which you can connect to and will display the orderbook as well as some graphs

$ python wallet-tool.py [wallet]
  To print out a bunch of addresses, send some testnet coins to an address

$ python sendpayment.py -N 3 [wallet] [amount-in-satoshi] [destination address]
  Chooses the cheapest offer to do a coinjoin with 3 other parties to send money to a destination address

If you're a frugal user and don't want to pay for a coinjoin if you dont have to, use this command
$ python patientsendpayments.py -N 1 -w 2 [wallet] [amount in satoshi] [destination address]
  Announces orders and waits to coinjoin for a maximum of 2 hours. Once that time it up cancels the
  orders and pays to do a 2-party coinjoin.

$ python yield-generator.py [wallet]
  Becomes an investor bot, being online indefinitely and doing coinjoin for the purpose of profit.
  Edit the file to change the IRC nick, offered fee, nickserv password and so on

Watch the output of your bot(s), soon enough the taker will say it has completed
 a transaction, maker will wait for the transaction to be seen and confirmed
If there are no orders, you could run two bots from the same machine. Be sure to use
 two seperate wallet seeds though.


