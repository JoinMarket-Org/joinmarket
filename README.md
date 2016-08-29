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

 - Debian/Ubuntu, apt-get install libsodium-dev
 - Arch, pacman -S libsodium
 - or build:

    ```
    git clone git://github.com/jedisct1/libsodium.git
    cd libsodium
    git checkout tags/1.0.3
    ./autogen.sh
    ./configure
    make check
    sudo make install
    ```

+ Install Python dependencies:
    You need `pip` (e.g. `sudo apt-get python-pip`, recent Python usually ships with pip).

    (Setuptools version must be >= 3.3).

    (Recommended but not needed) : use `virtualenv` to keep dependencies isolated.

    If on Linux/OSX:

    The Python binding to libsecp256k1 will most likely have some dependencies; read the [Wiki article](https://github.com/JoinMarket-Org/joinmarket/wiki/Installing-the-libsecp256k1-binding).

    Try running the below without following those instructions, most likely it will fail and you will then have to follow them.

    ```
    pip install -r requirements.txt
    ```

    If on Windows:

    ```
    pip install -r requirements-windows.txt
    ```

+ Matplotlib for displaying the graphs in orderbook-watcher (optional)

###DEBIAN / UBUNTU QUICK INSTALL FOR USERS:

1. `sudo apt-get update -y && sudo apt-get upgrade -y && sudo apt-get install python libsodium-dev -y`
2. `pip install -r requirements.txt`
2. `sudo apt-get install python-matplotlib -y` (optional)
3. Download JoinMarket 0.2.0 source from [here](https://github.com/joinmarket-org/joinmarket/releases/tag/v0.2.0)
4. Extract or unzip and `cd joinmarket-0.2.0`
4. Generating your first wallet will populate the configuration file: `joinmarket.cfg`.
   Check if the default settings suit your needs.

###[INSTALL FOR WINDOWS USERS](https://github.com/JoinMarket-Org/joinmarket/wiki/Installing-JoinMarket-on-Windows)

###[WIKI PAGES FOR DETAILED ARTICLES/GUIDES](https://github.com/joinmarket-org/joinmarket/wiki)

###CONTRIBUTING TO JOINMARKET AS A DEVELOPER

Clone the repo, then read the notes [here](./CONTRIBUTING.md).

###TESTING

Install the development requirements:

    pip install -r requirements-dev.txt

Run the tests:

    PYTHONPATH=.:$PYTHONPATH py.test

Generating html code coverage reports:

    PYTHONPATH=.:$PYTHONPATH py.test --cov-report html --btcroot=/path/to/bitcoin/bin/ --btcconf=/path/to/bitcoin.conf --btcpwd=123456abcdef
    open htmlcov/index.html

See more information on testing in the [Wiki page](https://github.com/JoinMarket-Org/joinmarket/wiki/Testing)

---

+ IRC: `#joinmarket` on irc.freenode.net https://webchat.freenode.net/?channels=%23joinmarket

+ Bitcointalk thread: https://bitcointalk.org/index.php?topic=919116.msg10096563

+ Subreddit: https://reddit.com/r/joinmarket

+ Twitter: https://twitter.com/joinmarket

+ Donation address: `1AZgQZWYRteh6UyF87hwuvyWj73NvWKpL`
