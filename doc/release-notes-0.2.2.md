JoinMarket 0.2.2:
=================

<https://github.com/joinmarket-org/joinmarket/releases/tag/v0.2.2>

This is a minor release with some workarounds to avoid the effect of non-responding makers and fixing bugs in 0.2.1, however there are also several bugfixes, and for some classes of users these bugs may be important, so please update immediately. Additionally, several defaults have been amended in the direction of better privacy.

Please report bugs using the issue tracker at github:

<https://github.com/joinmarket-org/joinmarket/issues>

Upgrading and downgrading
=========================

For users already running version 0.2.x it is only required to update the Joinmarket code, i.e. either `git pull` or download the zip from the release link above.

Users updating from a version pre-0.2.0 **must** carefully follow the instructions for updating in the [previous release notes](https://github.com/JoinMarket-Org/joinmarket/blob/master/doc/release-notes-0.2.0.md)

Bugfixes
========

The bugfixes are for these specific issues:

* yg-pe.py minsize option was initially not honored
* crash in tumbler on restart due to index_cache not honoring extra mixdepths
* wallet unspent explicitly None in AbstractWallet constructor, fixes crash bug in --rpcwallet when commitments cannot be sourced
* cleaner shutdown when no commitments are available
* bug in blockr query_utxo_set
* tolerate counterparties using a dust threshold between our value and the network floor

0.2.2 Change log
=================

- `8d00f9c` Add gaplimit option for yield generators
- `d40d113` Add agora-irc to config: a second, default irc server to connect to
- `6210225` Add fast sync option for Core wallets
- `03fbcfd` Change logging system to only show relevant messages on console by default
- `c30c4cd` Add direct send feature from mixdepth using -N 0 in sendpayment script; includes sweep
- `fcc1c5e` Add command dumpprivkey to wallet-tool.py
- `baefc05` Modify default fee to 0.02% (yg-pe.py) and modify default maker_timeout_sec to 45 from 30 (bigger messages)
- `c89347a` Allow fewer maker responses to complete a coinjoin, if some makers do not answer
- `7b3b36a` Tolerate counterparties using the old DUST_THRESHOLD value
- `7a41623` Amend default number of counterparties to improve privacy

Credits
=======

Minor bugfixes and improvements by:
@AdamISZ
@adlai
@AlexCato
@CohibAA
Martino Salvetti
Bryan Stitt
Daniel Kraft

Thanks to those who submitted bug reports and otherwise helped out.
