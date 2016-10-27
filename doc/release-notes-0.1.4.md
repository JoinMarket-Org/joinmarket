JoinMarket 0.1.4:
=================

  <https://github.com/joinmarket-org/joinmarket/releases/tag/v0.1.4>

This is a normal release, bringing bug fixes and new features.

Please report bugs using the issue tracker at github:

  <https://github.com/joinmarket-org/joinmarket/issues>

Upgrading and downgrading
=========================

There is no binary component of the installation yet supported. If you have already
installed libsodium and Python, you will not need to re-install anything, but
only update the joinmarket source code.

You can update your joinmarket.cfg file by moving or deleting it and it will be
recreated on first run.

Notable changes
===============

### secp256k1

The secp256k1 library can now be used in JoinMarket. It provides the very well
tested and robust code used in Bitcoin for the underlying signing and ECC operations.
It is recommended that everyone who is able to use secp256k1 with JoinMarket. In
case it cannot be installed, joinmarket should continue to run exactly as before.

On Linux it can be installed with

        pip install secp256k1

For past discussion on this feature which may be helpful, see this reddit thread

[https://www.reddit.com/r/joinmarket/comments/4cwjk9/optional_use_of_secp256k1_in_the_develop_branch/](https://www.reddit.com/r/joinmarket/comments/4cwjk9/optional_use_of_secp256k1_in_the_develop_branch/)

### Improved Stability of Tumbler Script

Many small bugfixes and features have been added with the aim of making the tumbler
script more stable and more likely to complete the entire tumbler job without crashing

### Broadcasting Transactions via Makers

In order to help stop spies that sybil attack the bitcoin p2p network in an effort
to learn the origin IP address of a transaction, JoinMarket now has a feature to
ask a maker to broadcast the coinjoin transaction with their IP.

To enable, modify the `tx_broadcast` parameter in `joinmarket.cfg`. Later versions
will have this enabled by default

### Debug Log Scrubber

JoinMarket debug logs are very useful to developers, but because they contain private
information users are often unwilling to share them publicly.

For this reason there is now a debug log scrubber script which replaces sensitive
information with placeholders that allow debugging but do not ruin privacy.

The script is found in the logs/ directory.

### Wallet History

The history of the internal wallet can now be displayed. For yield-generator users it can
work out the effective annual interest rate, as though yield-generator was a savings account.

To use, configure JoinMarket to use a Bitcoin node as a method of accessing the blockchain
and run:

        python wallet-tool.py wallet.json history

A csv file can be created for opening with spreadsheet software too:

        python wallet-tool.py --csv wallet.json history > history.csv


0.1.4 Change log
=================

Tumbler Stability:
- `671edcc` Restored debug_silence, so tumbler Insert New Address prompt can be seen
- `76d9071` Increased scope of timeout_thread_lock to stop a rare race condition
- `440357a` Fee calculation for sweep orders excludes miner fees, fixing #441
- `e47f47d` Fix not enough funds exception catch in tumbler
- `8af1376` Caught exception around getrawtransaction in the case of wallet conflicts
- `2dc3437` Create the confirm timeout feature of blockchaininterface, modified tumbler.py to use it
- `04c277e` Added sync_unspent() to tumbler create_tx() to reduce likelyhood of wallet being out of sync
- `fc3b6a3` Made tumbler update wallet file index cache, so wallet-tool display will reach the right mixdepths
- `00ac1a1` Clear irc.built_privmsg on reconnect, which prevents crashes from junk being passed to base64 decode
- `e4ff93d` Added check to make sure tumbler coins reach every destination address

Features:
- `42917f5` Always load default config with initial values first, then load potential config file afterwards
- `0f0631d` Created script broadcast-tx.py for broadcasting transactions via makers
- `22adabc` Gave names to all the threads so they appear in debug logs
- `4c08910` Adjuste IRC throttle parameters, experimentally derived
- `d82668d` maker_timeout_sec is readjusted for the second stage (!tx sending) based on transaction size, and IRC throttling variables are module vars
- `98db29f` Add yield-generator-oscillator
- `bf140fa` Bump default makercount to randint(2,4)
- `99ea24f` New re-integration of secp256k1 via ludbb binding
- `c70214d` Wallet history
- `1c20bfc` Options for broadcasting transactions via makers, issue #56
- `e7c1bf1` Show xpub keys in wallet-tool display, issue #493

Bugfixes:
- `d2be6c2` Recover from selection of spent utxos
- `184f2fe` Stop yield-generator-mixdepth announcing absorders if they havent been modified
- `96cff63` Fix crash in yield generator mixdepth when no unconfirm notify arrives
- `b814d3f` BitcoinCoreInterface now guarentees that unconfirmfun() will always be invoked, issue #436
- `388d833` Wrapped close() in try: except to stop it crashing the throttle thread
- `e7cb86d` Prevent offer minsize from going below DUST_THRESHOLD, issue #382
- `b9a673b` Added explaination to patientsendpayment in case anyone uses it
- `d650be6` Add length check to address validation; should be 20 bytes for both p2pkh and p2sh after stripping checksum and version


Credits
=======

Thanks to everyone who directly contributed to this release

- @AdamISZ
- @adlai
- @chris-belcher
- @OverlordQ
- @raedah
- @veqtrus

And those who contributed additional code review, ideas, debug logs and comments.
