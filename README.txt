FIRST IMPLEMENTATION OF JOINMARKET

you will need to know python somewhat to play around with it
 also get some testnet coins

HOWTO try
1. use bip32-tool.py to output a bunch of addresses
 send testnet coins to one mixing-depth=0 receive address
 do this for two wallet seeds, one for each taker and maker
 seeds are taken as a command line argument

2. for taker.py set the unspent transaction output (utxo) variable
 for the coin you want to spend

3. join irc.freenode.net #joinmarket and run both taker.py and maker.py

4. when both bots join and have announced their orders, use this
 command to start a coinjoining
 !%fill [counterparty] [order-id] [cj-amount]

so for example if the maker is called 'cj-maker' and you want to mix 1.9btc
 !%fill cj-maker 0 190000000

all values are in satoshis, the first order has order-id 0 and it counts up

5. watch the outputs of both bots, soon enough taker.py will say it has completed
 a transaction, it will not do pushtx() but instead print the tx hex
 you can examine this, with a blockchain explorer or my coin-jumble app and
 push it to the network yourself, or not, whatever

theres lots that needs to be done
some other notes below..

#COINJOIN PROTOCOL
#when a maker joins the channel it says out all its orders
# an order contains an order id, max size, min size, fee, whether the fee is absolute or
# as a proportion of the coinjoin amount
#when a taker joins the channel, it asks for orders to be pmed to him
#taker initiates coinjoin
#tells maker(s) by pm which order it wants to fill, sends the order id and the coinjoin amount
#maker(s) pm back the utxos they will input, and exactly two addresses, the coinjoin output and the change address
#taker collects all the utxos and outputs and makes a transaction
# pms them to the maker(s) who check everything is ok
#  that the miner fee is right, that the cj fee is right
# and pm back signatures
# iv checked, it easily possible to put the signatures back into a tx
#taker then signs his own and pushtx()

#TODO
#ask people on the testnet stuff to code up a few trading algos to see if the interface/protocol that
# iv invented is general enough
a few algos:
fees proportional to how many utxos used, since the marginal cost is unrelated to your cj amount, only to
 the amount of utxos you use up

#TODO think of names
#cj-market, cjex, but this isnt really an exchange
#Indra's Net
#If we now arbitrarily select one of these jewels for inspection and look closely at it, we will discover that in its polished surface there are reflected all the other jewels in the net, infinite in number. Not only that, but each of the jewels reflected in this one jewel is also reflecting all the other jewels, so that there is an infinite reflecting process occurring.
# but it sounds a bit like 'internet' with an accent
#maybe Indra, Indra's mixer
#other allusions, hall of mirrors, mirror labyrinth
#from discussing on irc, a simple name could just be JoinMarket or CoinJoinMarket
# JoinMarket seems the best probably

#TODO dont always pick the lowest cost order, instead have an exponentially decaying
# distribution, so most of the time you pick the lowest and sometimes you take higher ones
# this represents your uncertainty in sybil attackers, the cheapest may not always be the best
#i.e. randomly chosen makers, weighted by the price they offer

#TODO on nickname change, change also the counterparty variable in any open orders

#TODO use electrum json_rpc instead of the pybitcointools stuff
# problem, i dont think that supports testnet
# bitcoind json_rpc obviously supports testnet, but someone else can download
#  the blockchain 

#TODO option for how many blocks deep to wait before using a utxo for more mixing
# 1 confirm is probably enough

#TODO encrypt messages between taker and maker, to stop trivial server eavesdropping
# but that wont stop mitm
# after chats on irc, easiest is to do Trust On First Use, maker sends a pubkey over
#  TOFU requires a human to verify each first time, might not be practical
#  skip the human verification, it will probably be okay
# also theres some algorithm for detecting mitm

#TODO implement something against dust
# e.g. where the change address ends up having an output of value 1000 satoshis

#TODO completely abstract away the irc stuff, so it can be switched to something else
# e.g. twitter but more likely darkwallet obelisk and/or electrum server

TODO combine the taker and maker code into one file where you can make different kinds of
 bot which combine both roles
e.g. tumbler.py repeatedly takes orders on the same coins again and again in an effort
 to improve privacy and break the link between them, make sure to split up and combine them again
 in random amounts, because the income-collector will also be splitting and combining coins
 random intervals between blocks included might be worth it too, since income-collector.py
 will appear to have coins which dont get mixed again for a while
e.g. patient-tumbler.py which waits a while being a maker, then just starts to take orders
 after a time limit for people who want to mix coins but dont mind waiting until a fixed upper time limit
e.g. income-collector.py which acts as a maker solely for the purpose of making money
 might need to take orders at some point, for very small outputs which have a small probability of being filled
e.g. single-tx.py which takes a single order, using it to send coins to some address
 typically as a payment, so this is what the electrum plugin would look like

TODO
code a gui where a human can see the state of the orderbook and easily choose orders to fill
code a gui that easily explains to a human how they can choose a fee for their income-collector.py
both are important for market forces, since markets emerge from human decisions and actions

#TODO add random delays to the orderbook stuff so there isnt such a traffic spike when a new bot joins
#two options, random delay !orderbook for ones which dont mind, !orderbook without delay for bots
# which need the orders asap

#TODO error checking so you cant crash the bot by sending malformed orders
when an error happens, send back a !error command so the counterparty knows
 something went wrong, and then cancel that partly filled order

#TODO make an ordertype where maker publishes the utxo he will use
# this is a way to auction off the use of a desirable coin, maybe a 
# very newly mined coin or one which hasnt been moved for years
