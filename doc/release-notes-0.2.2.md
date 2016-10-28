JoinMarket 0.2.2:
=================

<https://github.com/joinmarket-org/joinmarket/releases/tag/v0.2.2>

This is a minor release with some workarounds to avoid the effect of non-responding makers,
some useful new features and fixing bugs in 0.2.1

Please report bugs using the issue tracker at github:

<https://github.com/joinmarket-org/joinmarket/issues>

Upgrading and downgrading
=========================

For users already running version 0.2.x it is only required to update the Joinmarket code, i.e. either `git pull` or download the zip from the release link above.

Users updating from a version pre-0.2.0 **must** carefully follow the instructions for updating in the [previous release notes](https://github.com/JoinMarket-Org/joinmarket/blob/master/doc/release-notes-0.2.0.md)

Features, in approximate order of importance
============================================

### Complete-with-subset

In cases where one of the Maker bots you select, either accidentally or by malicious
intent, fails to complete the transaction negotiation process, pre-0.2.2, this would
result in a failure that costs one utxo commitment (see the 0.2.0 notes for details).
This can cause serious inconvenience for a Taker if it happens repeatedly, and this
has been observed due to a number of non-responsive Makers in the pit.
With this new feature, the transaction can still complete with a lower number of
Makers (i.e. the ones that did respond).

For example, with the default setting of minimum_makers=2 in the POLICY section of
the joinmarket.cfg file, then if you request 5 counterparties, but only 3 respond,
the transaction will go ahead with those 3 (and will still go ahead with as few as 2).
You will get a slightly smaller privacy effect, but also pay less fees.
In testing this has been seen to greatly reduce the chance of a transaction failure.
You can disable this feature by setting minimum_makers=0.

Do consider also using the -P feature for fine-grained counterparty selection,
where that's possible. Note also that a future upgrade may offer even better
"smart" counterparty selection.

### Direct Send

You can now send coins out of your Joinmarket wallet with the sendpayment.py script;
use the option -N 0 (means 0 counterparties). All other syntax is the same, e.g. set
amount 0 for sweeping. This sends coins from *1 mixdepth*; in Joinmarket we never
send coins from multiple mixdepths at the same time, for privacy.

This method of course does not connect to IRC, so it will be quicker, and of course
cheaper than using a normal Joinmarket transaction. Before the transaction gets
broadcast, it will be presented to you in raw and serialized form to check.

Yield generators and other heavy users should be careful not to use this to send
coins between mixdepths in the same wallet, as this could lead to unexpected and
undesirable privacy outcomes.

### Fast sync option

When using Bitcoin Core, if the wallet has lots of used addresses, it results in a
slow import and sync currently (the full context for this is a bit complex to explain).
If you are *not* recovering a wallet or using a new Core instance, where you must
start from scratch and *not* use this new feature, but are instead simply restarting
your script, it's recommend to append the option --fast to *all* scripts (yieldgen,
tumbler, sendpayment, wallet-tool). This uses a different, more efficient way of
gathering the history of all the addresses. In tests it's been reported to reduce
sync time by anything from 50-90% depending on your exact situation. If you are only
an occasional user (e.g. using sendpayment) and have only few used addresses, it
isn't important.

### Logging levels

By default, the logging messages *on the terminal* are now much reduced, corresponding
to log level "INFO". The logging messages in the log file still contain everything
("DEBUG" level).

You can change the logging level on the terminal to one of INFO, WARNING, ERROR or
DEBUG by setting the config variable console_log_level in section LOGGING. See the
default joinmarket.cfg for reference.

### Extra new default IRC server

For better censorship resistance and redundancy it's recommended to use more than one
"Message Channel" (at the moment only IRC is supported, but other messaging servers are
easy to code, PRs welcome!). Some bots have already been using the agora IRC server
(for donations, see: anarplex.net, address 12qvastA6FVod8L45Q3RPD8whbzvrZhxcQ).

This extra IRC server is now added to the default config, so it's suggested that all
participants use it as well as the existing CGAN. Note the rather ugly comma-separated
lists; this format is required, with the same number of entries for *all* settings in
the MESSAGING section.

### Dump individual private key

You can now use the method "dumpprivkey" to wallet-tool.py, in combination with the
-H option, to dump the private key of one address without a full wallet sync.

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
================

- `c7d692d` `5effddb` minsize bug fixed in ygs.
- `86d8c3a` `3506294` `b126535` handle too many requests to blockr
- `93dfefc` remove random-nick code, no longer used in 0.2
- `6210225` `7ecaa56` fast sync
- `e46cad9` `7b4b36a` bump dust threshold
- `51ed5a2` `908208f` `d40d113` add agora to default IRC config
- `ca245e8` bugfix for rpcwallet
- `961e817` `6aaa4c9` `6b14fa2` `2ce4d8c` cleanup
- `4195589` `e256672` update installation instructions
- `4ff5519` `03fbcfd` `033662f` `2f95d88` `481d9a4`
  `e1ca488` `9fba63a` implementation of logging levels
- `502b6a8` prevent crash based on tumbler changing index_cache
- `c30c4cd` direct send
- `3387422` add hostid to debug log
- `fcc1c5e` dump individual privkey
- `baefc05` `ebf28ed` `7a41623` modify some defaults
- `c89347a` `a579ff4` complete transactions with subset

Credits
=======

Thanks to everyone who directly contributed to this release -

- @AdamISZ
- @adlai
- @AlexCato
- @CohibAA
- @the9ull
- @WyseNynja

Thanks also to those who submitted bug reports, tested and otherwise helped out.

