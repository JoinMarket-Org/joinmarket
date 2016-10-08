JoinMarket 0.2.1: 
================= 

<https://github.com/joinmarket-org/joinmarket/releases/tag/v0.2.1> 

This is a minor release fixing bugs in 0.2.0, however for some classes of users these bugs may be important, so please update immediately.

Please report bugs using the issue tracker at github: 

<https://github.com/joinmarket-org/joinmarket/issues> 

Upgrading and downgrading 
========================= 

For users already running version 0.2.0 it is only required to update the Joinmarket code, i.e. either `git pull` or download the zip from the release link above.

Users updating from a version pre-0.2.0 **must** carefully follow the instructions for updating in the [previous release notes](https://github.com/JoinMarket-Org/joinmarket/blob/master/doc/release-notes-0.2.0.md)

Bugfixes 
======== 

The bugfixes are for these specific issues:

* Windows secp256k1 binding had errors preventing correct running.
* Use of the `--rpcwallet` flag in `sendpayment.py` failed due to a bug in privkey format.
* `yield-generator-basic.py` had a (very!) old bug re-introduced in 0.2.0 which allowed small negative fees to occur.


0.2.1 Change log 
================= 

- `52a85b0` Fix bug in minsize calculation for yield-generator-basic
- `748263e` Workaround for missing custom_nonce field in old secp256k1-py code for Windows
- `4352d1f` workaround for [bug](https://github.com/ludbb/secp256k1-py/pull/10) in underlying secp256k1-py code used in Windows binding
- `9c954d7` remove raw binary from object dump in log 
- `47479d5` improve log messages
- `6a86338` Fix bug in --rpcwallet option and add test; BitcoinCoreWallet.get_key_from_addr now returns hex, not wif privkey.

Credits 
======= 

Minor bugfixes by @AdamISZ.

Thanks to those who submitted bug reports and otherwise helped out. 
