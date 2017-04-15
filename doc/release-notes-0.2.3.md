JoinMarket 0.2.3:
=================

<https://github.com/joinmarket-org/joinmarket/releases/tag/v0.2.3>

This is a minor release to fix some bugs and add some features.

Please report bugs using the issue tracker at github:

<https://github.com/joinmarket-org/joinmarket/issues>

Upgrading and downgrading
=========================

For users already running version 0.2.x it is only required to update the Joinmarket code, i.e. either `git pull` or download the zip from the release link above.

Users updating from a version pre-0.2.0 **must** carefully follow the instructions for updating in the [previous release notes](https://github.com/JoinMarket-Org/joinmarket/blob/master/doc/release-notes-0.2.0.md)

Notable changes
===============

### Tor Broadcast Method

Right now on the bitcoin network, there are an unknown number of sybil nodes which aggressively announce themselves in an effort to attract more people to connect to them. Then they spy on every newly-broadcasted transaction, tracking it as it propagates through the p2p network and giving them a good idea of the IP address that originally broadcasted that transaction.

This new feature connects to a random node on the bitcoin p2p over tor, pushes it's unconfirmed transaction, then disconnects. This should stop the spying method described. It's activated by configuring `tx_broadcast = tor` in the `joinmarket.cfg` file. Also set `socks5_host` and `socks5_port` to tell JoinMarket where to find Tor.

The code uses the user-agent of `/JoinMarket:0.2.3/` so archival full node operators may want to look out for it.

### Electrum and bc.i Blockchain Interface

JoinMarket can now obtain blockchain information to synchronize it's wallet from two new sources: Electrum servers and the blockchain.info API. To configure them set `blockchain_source = electrum` or `blockchain_source = bc.i` in the `joinmarket.cfg` file. 

Note that they work somewhat slowly, are not very robust and are very bad for privacy because the server can see exactly what bitcoin addresses belong to you. These interfaces also can't be used with testnet (which contributes to their low robustness).

As always, the best solution right now for privacy and security is to tell JoinMarket to connect to your own full node.

### Transaction Fees

Users can now choose the fee rate they want to use for paying miner fees. In `joinmarket.cfg` set `tx_fees = N` where `N` is the target number of blocks to confirm within if less than 144. If `N` is set to higher than 144 then that is the fee-per-kilobyte to use.

The previous value of 150 sat/b was seen to be absurd in early 2015 when it was set, however the changing market for block space made this value the reality. The default `absurd_fee_per_kb` value is therefore set to 2000 satoshi-per-byte and JoinMarket will shut down if the `estimatefee` function returns a higher value.

### Scripting

Some changes were made to make it easier to use JoinMarket for scripting.

It's now possible to have a wallet password be an empty string, and JoinMarket won't prompt for a password if so.

Private keys can also now be imported without interactivity, see the guide on the wiki page [here](https://github.com/JoinMarket-Org/joinmarket/wiki/Using-the-JoinMarket-internal-wallet#importing-non-interactively)

### Fixing Scripts

JoinMarket version 0.2.0 changed the protocol which broke some scripts. All scripts are now updated to work and their wiki pages updated.

[patientsendpayment.py guide](https://github.com/JoinMarket-Org/joinmarket/wiki/Sending-payments-with-CoinJoin#patient-send-payment) 

[create-unsigned-tx.py guide](https://github.com/JoinMarket-Org/joinmarket/wiki/Spending-from-cold-storage,-P2SH-or-other-exotic-inputs-with-CoinJoin)


0.2.3 Change log
================

- `915eedb` Add total profit to history command in wallet-tool 
- `fa50da9` Enhance showutxos
- `9470bd8` Add ability to change encryption password of wallet.json
- `5e4d021` Increments default walletname when wallet already exists
- `fddcecc` Change user agent to Firefox ESR for improved privacy 
- `dae58c8` Improve wallet tool help format
- `44b90fc` avoid re-importing already imported addesses to bitcoind
- `ce23bc7` lock db access from taker scripts to avoid cursor exceptions 
- `f0f84a6` fix for minsize > maxsize AssertionError in yield generators
- `0253649` fix title formatting
- `064e31e` Add "extend_mixdepth=True" to yieldgen

Credits
=======

Thanks to everyone who directly contributed to this release -

- @AdamISZ
- @adlai
- @AlexCato
- @anduck
- @chris-belcher
- @eduard6
- @Empty2k12
- @instagibbs
- @juscamarena
- @meeDamian
- @nopara73
- Peter Banik
- @undeath
- @wozz
- @WyseNynja

And thanks also to those who submitted bug reports, tested and otherwise helped out.
