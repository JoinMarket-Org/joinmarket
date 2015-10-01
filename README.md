##What is JoinMarket ?

The idea behind JoinMarket is to allow users to have their bitcoins mixed with other JoinMarket users in return for a fee. A form of smart contract is created, meaning the private keys will never be broadcasted outside of your computer, resulting in virtually zero risk of loss (aside from malware or bugs).

Simply put, JoinMarket allows its users to improve the privacy of their bitcoin transactions (and therefore maintaining or even restoring fungibility) in a decentralized fashion. On the other side, there are the JoinMarket operators who provide access to their bitcoins for others to use in mixing transactions. Their incentive is in the form of a fee in return for the provision of their bitcoins, meaning JoinMarket could become a form of passive income. 

As a result of free-market forces (i.e. anyone with bitcoins can become a JoinMarket operator), the fees will eventually be next to nothing. 

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
