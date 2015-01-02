FIRST IMPLEMENTATION OF JOINMARKET

you will need to know python somewhat to play around with it
 also get some testnet coins

HOWTO try
1. create two wallet seeds string (can be just brainwallets if you're only storing testnet btc)
 one seed for each maker and taker
 use bip32-tool.py to output a bunch of addresses from the seeds
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
<taker> !fill [order id] [coinjoin amount]
<maker> !io [comma seperated list of utxos] [coinjoin address] [change address]
when taker collects inputs and outputs of all the makers it's contacted, it creates a tx out of them
<taker> !txpart [base64 encoded tx part]
...
<taker> !tx [base64 encoded tx part]
maker concatenates all the !txpart and !tx commands and obtains unsigned tx
it signs its own utxos and extracts just the script from it which contains signature and pubkey
<maker> !sig [base64 encoded script]
taker collects all scripts and places them into the tx
taker pushes tx when all the scripts have arrived


#TODO
#ask people on the testnet stuff to code up a few trading algos to see if the interface/protocol that
# iv invented is general enough
a few algos:
fees proportional to how many utxos used, since the marginal cost is unrelated to your cj amount, only to
 the amount of utxos you use up

#TODO dont always pick the lowest cost order, instead have an exponentially decaying
# distribution, so most of the time you pick the lowest and sometimes you take higher ones
# this represents your uncertainty in sybil attackers, the cheapest may not always be the best
#i.e. randomly chosen makers, weighted by the price they offer

#TODO on nickname change, change also the counterparty variable in any open orders

#TODO use electrum json_rpc instead of the pybitcointools stuff
# problem, i dont think that supports testnet
# bitcoind json_rpc obviously supports testnet, but someone else can download
#  the blockchain, actually it seems you cant replace pybitcointools with bitcoind
#  cant look up any txid or address
# could use a websocket api for learning when new blocks/tx appear
# could use python-bitcoinlib to be a node in the p2p network

#TODO option for how many blocks deep to wait before using a utxo for more mixing
# 1 confirm is probably enough
TODO
have the taker enforce this, look up the txhash of the maker's utxo and make sure
 it is already in a block


TODO implement rate limiting for irc.privmsg to stop the bot being killed due to flood
i suggest creating a thread that only dispatches/writes to the irc socket

TODO sort out the nick = nick + '_' stuff in irclib
its not a good way of doing it

#TODO encrypt messages between taker and maker, to stop trivial server eavesdropping
# but that wont stop mitm
# after chats on irc, easiest is to do Trust On First Use, maker sends a pubkey over
#  TOFU requires a human to verify each first time, might not be practical
#  skip the human verification, it will probably be okay
# make the irc nick be a hash of the pubkey
# also theres some algorithm for detecting mitm

#TODO implement something against dust
# e.g. where the change address ends up having an output of value 1000 satoshis

#TODO completely abstract away the irc stuff, so it can be switched to something else
# e.g. twitter but more likely darkwallet obelisk and/or electrum server

TODO combine the taker and maker code into one file where you can make different kinds of
 bot which combine both roles
e.g. tumbler.py repeatedly takes orders on the same coins again and again in an effort
 to improve privacy and break the link between them, make sure to split up and combine them again
 in random amounts, because the yield-generator will also be splitting and combining coins
 random intervals between blocks included might be worth it too, since yield-generator.py
 will appear to have coins which dont get mixed again for a while
e.g. patient-tumbler.py which waits a while being a maker, then just starts to take orders
 after a time limit for people who want to mix coins but dont mind waiting until a fixed upper time limit
e.g. yield-generator.py which acts as a maker solely for the purpose of making money
 might need to take orders at some point, for very small outputs which have a small probability of being filled
e.g. single-tx.py which takes a single order, using it to send coins to some address
 typically as a payment, so this is what the electrum plugin would look like
e.g. patient-single-tx.py which does the above but doesnt mind waiting up to a limit
e.g. gui-taker.py has a gui which shows the user the orderbook and they can easily fill and order
 and see other statistics, could be easily done by opening a http port and sending a html form and graphics

TODO
implement this the thing that gmaxwell wrote about in the original coinjoin post, as a kind of tumbler
"Isn't the anonymity set size limited by how many parties you can get in a single transaction?"

"Not quite. The anonymity set size of a single transaction is limited by the number of parties in it, obviously. And transaction size limits as well as failure (retry) risk mean that really huge joint transactions would not be wise. But because these transactions are cheap, there is no limit to the number of transactions you can cascade.

In particular, if you have can build transactions with m participants per transaction you can create a sequence of m*3 transactions which form a three-stage switching network that permits any of m^2 final outputs to have come from any of m^2 original inputs (e.g. using three stages of 32 transactions with 32 inputs each 1024 users can be joined with a total of 96 transactions).  This allows the anonymity set to be any size, limited only by participation."
https://en.wikipedia.org/wiki/Clos_network
Not sure if it will actually be possible in this liquidity maker/taker system

TODO need to move onto the bip44 structure of HD wallets

TODO think about this 
<> some coinjoin tools we use today were broken
<> one allowed people to use a mix of uncompressed and compressed keys, so it was obvious which party was which.

TODO
probably a good idea to have a debug.log where loads of information is dumped

TODO
for the !addrs command, firstly change its name since it also includes the utxo inputs
 secondly, the utxo list might be longer than can fit in an irc message, so create a
 !addrsparts or something command

TODO
code a gui where a human can see the state of the orderbook and easily choose orders to fill
code a gui that easily explains to a human how they can choose a fee for their yield-generator.py
both are important for market forces, since markets emerge from human decisions and actions

#TODO add random delays to the orderbook stuff so there isnt such a traffic spike when a new bot joins
#two options, random delay !orderbook for ones which dont mind, !orderbook without delay for bots
# which need the orders asap

TODO
the add_addr_notify() stuff doesnt work, so if theres several CoinJoinOrder's open it will start a few
 threads to do the notifying, they could race condition or other multithreaded errors
i suggest to create a single thread that sorts out all the stuff

#TODO error checking so you cant crash the bot by sending malformed orders
when an error happens, send back a !error command so the counterparty knows
 something went wrong, and then cancel that partly filled order

#TODO make an ordertype where maker publishes the utxo he will use
# this is a way to auction off the use of a desirable coin, maybe a 
# very newly mined coin or one which hasnt been moved for years
