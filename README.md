[![Build Status](https://travis-ci.org/JoinMarket-Org/joinmarket.svg?branch=develop)](https://travis-ci.org/JoinMarket-Org/joinmarket.svg?branch=develop)

[![Coverage Status](https://coveralls.io/repos/github/JoinMarket-Org/joinmarket/badge.svg?branch=develop)](https://coveralls.io/github/JoinMarket-Org/joinmarket?branch=develop)

##What is JoinMarket ?

The idea behind JoinMarket is to help create a special kind of bitcoin transaction called a CoinJoin transaction. It's aim is to improve the confidentiality and privacy of bitcoin transactions, as well as improve the capacity of the blockchain therefore reduce costs. The concept has enormous potential, but had not seen much usage despite the multiple projects that implement it. This is probably because the incentive structure was not right.

A CoinJoin transaction requires other people to take part. The right resources (coins) have to be in the right place, at the right time, in the right quantity. This isn't a software or tech problem, its an economic problem. JoinMarket works by creating a new kind of market that would allocate these resources in the best way.

One group of participants (called market makers) will always be available to take part in CoinJoins at any time. Other participants (called market takers) can create a CoinJoin at any time. The takers pay a fee which incentivizes the makers. A form of smart contract is created, meaning the private keys will never be broadcasted outside of your computer, resulting in virtually zero risk of loss (aside from malware or bugs). As a result of free-market forces the fees will eventually be next to nothing. 

Widespread use of JoinMarket could improve bitcoin's fungibility as a commodity. The privacy aspect has many applications. For example, some users of bitcoin exchanges have a problem of being front-run. As all bitcoin transactions are public, when a seller sends a large amount of coins to an exchange it will be public knowledge and the price will move downwards accordingly.

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

+ Matplotlib for displaying the graphs in orderbook-watcher (optional)

###DEBIAN / UBUNTU QUICK INSTALL FOR USERS:

1. `sudo apt-get update -y && sudo apt-get upgrade -y && sudo apt-get install python libsodium-dev -y`
2. `sudo apt-get install python-matplotlib -y` (optional)
3. Download JoinMarket 0.1.2 source from [here](https://github.com/joinmarket-org/joinmarket/releases/tag/v0.1.3)
4. Extract or unzip and `cd joinmarket-0.1.2`
4. Generating your first wallet will populate the configuration file: `joinmarket.cfg`.
   Check if the default settings suit your needs.

###[INSTALL FOR WINDOWS USERS](https://github.com/joinmarket-org/joinmarket/wiki/Installing-JoinMarket-on-Windows-7-(temporary))

###[WIKI PAGES FOR DETAILED ARTICLES/GUIDES](https://github.com/joinmarket-org/joinmarket/wiki)

###CONTRIBUTING TO JOINMARKET AS A DEVELOPER

Clone the repo, then read the notes [here](./CONTRIBUTING.md).

###TESTING

Install the developement requirements:

    ```
    pip install -r requirements-dev.txt
    ```

Run the tests:

    ```
    PYTHONPATH=.:$PYTHONPATH py.test
    ```

Generating html code coverage reports:

    ```
    PYTHONPATH=.:$PYTHONPATH py.test --cov-report html
    open htmlcov/index.html
    ```

---

+ IRC: `#joinmarket` on irc.freenode.net https://webchat.freenode.net/?channels=%23joinmarket

+ Bitcointalk thread: https://bitcointalk.org/index.php?topic=919116.msg10096563

+ Subreddit: https://reddit.com/r/joinmarket

+ Twitter: https://twitter.com/joinmarket

+ Donation address: `1AZgQZWYRteh6UyF87hwuvyWj73NvWKpL`
