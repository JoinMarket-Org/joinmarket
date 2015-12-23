##What is JoinMarket ?

The idea behind JoinMarket is to allow users to have their bitcoins mixed with other JoinMarket users in return for a fee. A form of smart contract is created, meaning the private keys will never be broadcasted outside of your computer, resulting in virtually zero risk of loss (aside from malware or bugs).

Simply put, JoinMarket allows its users to improve the privacy of their bitcoin transactions (and therefore maintaining or even restoring fungibility) in a decentralized fashion. On the other side, there are the JoinMarket operators who provide access to their bitcoins for others to use in mixing transactions. Their incentive is in the form of a fee in return for the provision of their bitcoins, meaning JoinMarket could become a form of passive income. 

As a result of free-market forces (i.e. anyone with bitcoins can become a JoinMarket operator), the fees will eventually be next to nothing. 

##Installation

#####REQUIRED INSTALLATION DEPENDENCIES

+ You will need python 2.7

+ You will need libsodium installed

 - Either get it via apt-get as `libsodium-dev` or build:
 
    ``` 
    git clone git://github.com/jedisct1/libsodium.git
    cd libsodium
    git checkout tags/1.0.3
    ./autogen.sh
    ./configure
    make check
    sudo make install
    ```
    
 - After installation of JoinMarket, use this line to check it was installed correctly: `PYTHONPATH=.:$PYTHONPATH python joinmarket/enc_wrapper.py`

+ Matplotlib for displaying the graphs in orderbook-watcher (optional)

###DEBIAN / UBUNTU QUICK INSTALL FOR USERS:

1. `sudo apt-get update -y && sudo apt-get upgrade -y && sudo apt-get install python libsodium-dev -y`
2. `sudo apt-get install python-matplotlib -y` (optional)
3. Download JoinMarket 0.1.0 source from [here](https://github.com/joinmarket-org/joinmarket/releases/tag/v0.1.0)
4. Extract or unzip and `cd joinmarket-0.1.0`
4. Generating your first wallet will populate the configuration file: `joinmarket.cfg`.
   Check if the default settings suit your needs.

###[INSTALL FOR WINDOWS USERS](https://github.com/joinmarket-org/joinmarket/wiki/Installing-JoinMarket-on-Windows-7-(temporary))

###[WIKI PAGES FOR DETAILED ARTICLES/GUIDES](https://github.com/joinmarket-org/joinmarket/wiki)

###CONTRIBUTING TO JOINMARKET AS A DEVELOPER

Clone the repo, then read the notes [here](./CONTRIBUTING.md).

---

+ IRC: `#joinmarket` on irc.freenode.net https://webchat.freenode.net/?channels=%23joinmarket

+ Bitcointalk thread: https://bitcointalk.org/index.php?topic=919116.msg10096563

+ Subreddit: https://reddit.com/r/joinmarket

+ Twitter: https://twitter.com/joinmarket

+ Donation address: `1AZgQZWYRteh6UyF87hwuvyWj73NvWKpL`
