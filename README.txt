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

$ python wallet-tool.py [seed]
  To print out a bunch of addresses, send some testnet coins to an address

$ python sendpayment.py -N 1 [seed] [amount-in-satoshi] [destination address]
  Chooses the cheapest offer to do a 2-party coinjoin to send money to a destination address

If you're a frugal user and don't want to pay for a coinjoin if you dont have to, use this command
$ python patientsendpayments.py -N 1 -w 2 [wallet seed] [amount in satoshi] [destination address]
  Announces orders and waits to coinjoin for a maximum of 2 hours. Once that time it up cancels the
  orders and pays to do a 2-party coinjoin.

$ python gui-taker.py
  Starts a local http server which you can connect to and will display the orderbook as well as some graphs


Watch the output of your bot(s), soon enough the taker will say it has completed
 a transaction, maker will wait for the transaction to be seen and confirmed
If there are no orders, you could run two bots from the same machine. Be sure to use
 two seperate wallet seeds though.


some other notes below..

#COINJOIN PROTOCOL
when a maker joins the channel it says out all its orders
 an order contains an order id, max size, min size, fee, whether the fee is absolute or
 as a proportion of the coinjoin amount
when a taker joins the channel, it asks for orders to be pmed to him
taker initiates coinjoin
tells maker(s) by pm which order it wants to fill, sends the order id and the coinjoin amount
maker(s) pm back the utxos they will input, and exactly two addresses, the coinjoin output and the change address
taker collects all the utxos and outputs and makes a transaction
 pms them to the maker(s) who check everything is ok
  that the miner fee is right, that the cj fee is right
 and pm back signatures
 iv checked, it easily possible to put the signatures back into a tx
taker then signs his own and pushtx()

IRC commands used when starting a coinjoin, everything in pm
<taker> !fill [order id] [coinjoin amount] [input_pubkey]
<maker> !io [comma seperated list of utxos] [coinjoin address] [change address] [coinjoin pubkey] [bitcoin signature] [encryption pubkey]

<taker> !auth [encryption pubkey] [btc_sig]
After this, messages sent between taker and maker will be encrypted.

when taker collects inputs and outputs of all the makers it's contacted, it creates a tx out of them
<taker> !txpart [base64 encoded tx part]
...
<taker> !tx [base64 encoded tx part]
maker concatenates all the !txpart and !tx commands and obtains unsigned tx
it signs its own utxos and extracts just the script from it which contains signature and pubkey
<maker> !sig [base64 encoded script]
taker collects all scripts and places them into the tx
taker pushes tx when all the scripts have arrived

