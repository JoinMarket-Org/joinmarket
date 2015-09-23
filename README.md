##What is JoinMarket ?

The idea behind JoinMarket is that holders of bitcoin will allow their coins to be mixed with in return for a fee. The mixing will happen in coinjoin transactions. They form a kind of smart contract which means your private keys will never leave your computer so there is no risk of loss (barring malware or bug*)

Put simply, JoinMarket allows you to improve the privacy of your bitcoin transactions for low fees in a decentralized fashion Because of the fee paid, owners of bitcoin will be able to earn an income using JoinMarket.

As the risk is very low, the reward will also be low because of competition between fee-earners. It means that you will be eventually able to do a coinjoin very cheaply. We already see that holders of bitcoin are willing to earn very small amounts per day by lending on the bitfinex exchange, and that contains a substantial risk that bitfinex will go disappear.

##Installation

#####REQUIRED INSTALLATION DEPENDENCIES

+ You will need python 2.7

+ You will need libsodium installed

 - You can get it here: http://doc.libsodium.org/ or through apt-get as `libsodium-dev`
 
 - Use this line to check it was installed correctly: `python lib/enc_wrapper.py`

+ Matplotlib for displaying the graphs in orderbook-watcher (optional)

###DEBIAN / UBUNTU QUICK INSTALL:

1. `sudo apt-get update -y && sudo apt-get upgrade -y && sudo apt-get install python libsodium-dev -y`
2. `sudo apt-get install python-matplotlib -y` (optional)
3. `git clone https://github.com/chris-belcher/joinmarket.git`
4. Generating your first wallet will populate the configuration file: `joinmarket.cfg`.
   Check if the default settings suit your needs.

###[WIKI PAGES FOR DETAILED ARTICLES/GUIDES](https://github.com/chris-belcher/joinmarket/wiki)

###[FOR WINDOWS](https://github.com/chris-belcher/joinmarket/wiki/Installing-JoinMarket-on-Windows-7-(temporary))

---

+ IRC: `#joinmarket` on irc.freenode.net https://webchat.freenode.net/?channels=%23joinmarket

+ Bitcointalk thread: https://bitcointalk.org/index.php?topic=919116.msg10096563

+ Subreddit: https://reddit.com/r/joinmarket

+ Twitter: https://twitter.com/joinmarket

+ Donation address: `1AZgQZWYRteh6UyF87hwuvyWj73NvWKpL`
