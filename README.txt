FIRST IMPLEMENTATION OF JOINMARKET

you will need to know python somewhat to play around with it
 also get some testnet coins

HOWTO try
1. create two wallet seeds string (can be just brainwallets if you're only storing testnet btc)
 one seed for each maker and taker
 use wallet-tool.py to output a bunch of addresses from the seeds
 send testnet coins to one mixing-depth=0 receive address
 seeds are taken as a command line argument

2. join irc.freenode.net #joinmarket-pit-test and run both taker.py and yield-generator.py

3. when both bots join and have announced their orders, use this
 command to start a coinjoining
 !%fill [counterparty] [order-id] [cj-amount] [utxo]

so for example if the maker is called 'cj-maker' and you want to mix 1.9btc
 !%fill cj-maker 0 190000000 5cf68d4c42132f8f0bef8573454036953ddb3ba77a3bf3797d9862b7102d65cd:1

all values are in satoshis, the first order has order-id 0 and it counts up
you can use !%unspent to see a printout of taker's unspent transaction outputs
and !%showob to see the orderbook

4. watch the outputs of both bots, soon enough taker.py will say it has completed
 a transaction, maker will wait for the transaction to be seen and confirmed

theres lots that needs to be done
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

