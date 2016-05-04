Joinmarket 0.1.0:

  <https://github.com/joinmarket-org/joinmarket/releases/tag/v0.1.0>

This is the initial release of Joinmarket.

Please report bugs using the issue tracker at github:

  <https://github.com/joinmarket-org/joinmarket/issues>

Upgrading and downgrading
=========================

There is no binary component of the installation yet supported. If you have already
installed libsodium and Python, you will not need to re-install anything, but
only update the joinmarket source code.


Notable changes
===============

Throttling to avoid IRC flood
------------------------------------

See [366](https://github.com/joinmarket-org/joinmarket/issues/366). Introduced a 1 line/second limit and a secondary 3kB/10s limit to data 
sending. It is hoped that this will reduce or remove the possibility of bots getting
kicked from the server when engaging in large transactions. PING messages bypass
the limits, and responses to orderbook requests must wait for other messages (i.e. 
have lowest priority.) In case of very large transactions, takers should bump their
maker_timeout_sec variable in the config file from the new default of 60s to something
higher.

Dynamic fee calculation
-----------------------------------------

See [346](https://github.com/joinmarket-org/joinmarket/issues/346). Before these changes, the default fee was set statically at 10,000 satoshis, but this
is clearly insufficient on the Bitcoin network as of now, unless the transaction is
very small (and Joinmarket transactions are perforce larger than normal). An emergency
fix of 30,000 satoshis was applied to the master branch, but in this update the 
transaction fee is determined from the output of estimatefee, if running Core, or from
the API at blockcypher.com if running from blockr. Due to the joinmarket protocol, we
cannot know in advance the exact size of the transaction when we create it. Hence,
some reasonable heuristics are applied to estimate the size of the transaction, then
use the value returned from estimatefee, combined with a user-configured choice of
how many blocks to target combination for, to get to a reasonable transaction fee.
The user can reset the value of `tx_fees` in the joinmarket.cfg file from the default 
value of 3 (i.e. targetting confirmation within 3 blocks) to make confirmation likely 
to be faster or slower.

Users should be aware that in case of sweep transactions or large N transactions - whereever
the number of input utxos is large - the fee estimate can be quite high (in excess of 100,000
satoshis is quite possible); if this is deemed undesirable then set the value of `tx_fees` to
something higher, bearing in mind it might result in slow confirmation. Most normal joinmarket
transactions with 3-6 counterparties will result in fees between 20,000 and 50,000 satoshis,
using the 3 block confirmation target, as of today.

Note that this does introduce the possibility of a transaction failing to be created
correctly in corner cases where the amount selected from the wallet is insufficient,
but every effort has been made to make this outcome extremely unlikely, and has been
heavily tested to that end.

Code refactoring
-----------------------------------

See [340](https://github.com/joinmarket-org/joinmarket/issues/340) and 
[345](https://github.com/joinmarket-org/joinmarket/issues/345). 
This is considered an initial (but quite significant) step in cleaning
up the codebase, making formatting standardised, and enabling better analysis of the code.
The set of commits created preserves blame in git, and the diff can be verified using 
the yapf tool, combined with diff. See [340](https://github.com/joinmarket-org/joinmarket/issues/340) 
for details. A manual review of these changes
was undertaken also. There were no functional changes to the code as a result of this.

New yield-generator scripts.
-----------------------------------

See [353](https://github.com/joinmarket-org/joinmarket/issues/353), 
[357](https://github.com/joinmarket-org/joinmarket/issues/357),
[371](https://github.com/joinmarket-org/joinmarket/issues/371). 
The updates are spread over a few PRs due to refactoring
and bugfix changes. 

The main yield-generator.py script has been renamed to 
`yield-generator-basic.py`, the new-yieldgen-algo variant which was previously on a different
git branch has been renamed to `yield-generator-mixdepth.py` and a third variant called
`yield-generator-deluxe.py` has been created.

The -basic version is sufficient and not functionally changed from the former version.
The -mixdepth version has one small advantage: it allows one to set a different coinjoin
fee for joining different amounts. It does *not* give a higher chance of being chosen.
The -deluxe version is a new one, with a lot of extra configuration variables as can
be seen from reading the top of the script.

Change to 'internal/external' branches from 'for change/receive'
-----------------------------------

See [368](https://github.com/joinmarket-org/joinmarket/issues/368) fixing 
[283](https://github.com/joinmarket-org/joinmarket/issues/283). 
There is a possibility of address reuse if coins are added
to a mixdepth in the receive branch, while that address is also chosen by a bot for use.
This led to this improvement of the design: 'external' branch is only added to by the 
user from outside sources, while the bot itself will only choose new addresses from the
'internal' branch. The user merely has to bear in mind that they should only add coins
to the 'external' branch, just as before they were advised only to add coins to the
'receive' branch.

Displaying unconfirmed (or differently confirmed) coins.
-----------------------------------

See [367](https://github.com/joinmarket-org/joinmarket/issues/367).
This by default shows unconfirmed coins in the output of `wallet-tool.py`,
if you are using Bitcoin Core as your blockchain interface, but not for blockr.
It also provides a configuration variable `listunspent_args` that allows to specify
the range of confirmations to include in what Bitcoin Core returns in utxo queries.
This is a work in progress in as much as it is not yet advised to use this variable
with any script except `wallet-tool.py`.


0.1.0 Change log
=================

For the first release, this will be a list of the notable changes since
[the last significant update to the master branch](https://github.com/JoinMarket-Org/joinmarket/commit/2ef37996f90d3c4ea3ca7880a1619a182e710e67). 
Minor string fixes or test updates are not included. In future, this section will be
a list of all functional changes since the previous release.

- #345 `77cf5fa` Complete code refactoring. See #340 #345 for details on verification.
- #346 `3b3c05d` dynamic fee calculation, including sweep, and tumbler, and test updates
- #356 `0d7f14b` refactoring for yieldgens: new variants, see also #353 #357 #371
- #361 `f71b2db`  reduce DOS possibility via orderbook calls, see issue 298
- #366 `a33a851`  throttling with Queue 
- #367 `5322791`  add confirmation-spendability knob for bitcoind-rpc 
- #368 `f90e992`  Restructure for_change HD branch as {in,ex}ternal 
- #369 `1537d3e`  Handle pushtx failures. Catch jsonrpcerror exception and retry for tumbler
- #372 `9b809db`  Add gaplimit option for sendpayment.py. 


Credits
=======

Thanks to everyone who directly contributed to this release:

- @chris-belcher
- @adlai
- @AdamISZ
- @ghtdak
- @raedah
- @domob1812

And those who contributed additional code review, ideas and comments.


