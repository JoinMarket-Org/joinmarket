JoinMarket 0.2.0:
=================

<https://github.com/joinmarket-org/joinmarket/releases/tag/v0.2.0>

This is a major change to Joinmarket and is not compatible with earlier releases.

Please report bugs using the issue tracker at github:

<https://github.com/joinmarket-org/joinmarket/issues>

Upgrading and downgrading
=========================

There is a significant change to installation.

What has not changed:
* libsodium must be installed on the system

What has changed:
* `libnacl` and `secp256k1` are now configured as required dependencies in the `requirements*.txt` files.
* `secp256k1` (the Python binding to `libsecp256k1` is **no longer optional, but required**. See instructions [here](https://github.com/JoinMarket-Org/joinmarket/wiki/Installing-the-libsecp256k1-binding)
* Even if you already installed `secp256k1`, you will need to update to the latest version (at least 0.13.1). The requirements.txt should handle this.

Windows specific instructions are in the [wiki](https://github.com/JoinMarket-Org/joinmarket/wiki/Installing-the-libsecp256k1-binding#installing-the-libsecp256k1-binding-on-windows) [pages](https://github.com/JoinMarket-Org/joinmarket/wiki/Installing-JoinMarket-on-Windows).

The short version is, follow the installation [instructions](https://github.com/JoinMarket-Org/joinmarket/tree/develop#required-installation-dependencies) in the README, even if you are upgrading.

Important: it's recommended to move/delete your current `joinmarket.cfg` file before starting, since there are several new default settings, particularly in the POLICY section. Then, overwrite your old preferences.

Notable changes
===============

### "Commitments" (PoDLE) required to request coinjoins.

##### If you plan to use Joinmarket only as a Maker, not as a Taker:
There is very little effect, except:
* you will want to maintain the file `blacklist` in your root Joinmarket directory, it contains information that helps your bot to prevent spying activity, so don't delete it (although it's not a disaster if you do).
* Joinmarket now *by default* only offers two yield generator bots, `yield-generator-basic.py` (as before) and `yg-pe.py` (short for "privacy-enhancing"). The "enchancement" here is attempting to reduce to the minimum the number of order reannouncements, which give useful information to spies. This is a rationalisation to reduce workload, not an attempt to prevent people running more complex bots.

##### If you use Joinmarket as a Taker (initiating Coinjoins):
[This](https://github.com/JoinMarket-Org/joinmarket/wiki/Sourcing-commitments-for-joins) wiki page is a summary
of what you need to know, at the least you **must** read the **bolded** parts.

### Protocol changes

See [here] for some technical details, other documentation on the protocol will be updated soon.

As well as the changes specifically needed for the above mentioned commitments, there are other changes to the messaging protocol between bots implemented. Most notably:
* "Orders" are renamed to offers: "reloffer" and "absoffer" currently (other "offer" names are ignored)
* Previous taker MITM utxo is removed, as that goal is achieved from Maker side only.
* Maker authorizing pubkey for MITM prevention is now an input pubkey, not the coinjoin output pubkey. See some discussions in #90
* Signatures are appended to each private message for prevention of squatting cross-message channel.

Because of these changes, 0.2.0 bots and 0.1.* bots are incompatible; they should ignore each other, since the ordernames they are using are disjoint.

### Support for multiple IRC servers

You can now have your bot (of any type) join multiple IRC servers, although the default remains the same (Cyberguerrilla).
If you want to do this, you can change your `joinmarket.cfg` MESSAGING settings to something like this:

```
host = 6dvj6v5imhny3anf.onion, irc.rizon.net
channel = joinmarket-pit, joinmarket-pit
port = 6697, 6697
usessl = true, true
socks5 = true, false
socks5_host = localhost, localhost
socks5_port = 9150, 9150
```

This is just an example; the community may decide on a set of 2 or 3 "standard"
rendezvous servers in future, hopefully all of which will support Tor and be relatively
stable. We may also start to use non-IRC messaging servers, the code already supports this and there have been some investigations.

For now you can just leave the default (Cyberguerrilla).


0.2.0 Change log
=================

PoDLE commitments:
- `082d5bb` .. `59443a2` PoDLE commitments, particular commits of note below:
- `cdcbc67` removed pybitcointools, modified and refactored donations and tests to use secp256k1 binding
- `f152495` change ordernames to absoFFer and relOFFer
- `b6a585c` add commitment utxo btc amount requirement as fraction of coinjoin amount, default 20%
- `af1c1bc` add age restriction on PoDLE (incl facility to query utxo age from bc-interface, test)
- `83f2703` add add-utxo tool to import commitments from other wallets into the external set
- `2adeb30` Remove taker authorizing via btc utxo; addresses #90
- `0568b5c` btc.podle.PoDLE class for encapsulation; flexible design to allow other style of commit/reveal in future, with type byte as part of serialization; commitments from external sources allowed; commitments persisted in file commitments.json. Add test_podle detailed tests
- `f4984c2` upgrade protocol to version 5

Other features:
- `bf4c3a8` added config absurd_fee_per_kb default 150k sats, and test case
- `f9fb9f0` socks.py: randomize socks5 credentials for tor stream isolation
- `ff399af` sendpayment/tumbler: increase default maker count
- `632ef1a` sendpayment and tumbler: If the user does not give an initial fee estimation, dynamically estimate from the blockchain.
- `a393f9b` `088ca1d` `65bb4de` `80774b0` `eda7c64` `c3646f0` `e8ad6fa` `6b8fcce` Message channel refactoring to allow multiple MCs and future different MCs (not IRC) (#505)

- `30d69a0` `340b32b` New yieldgenerator type yg-pe.py, refactor to remove duplication.
- `00301e1` use requirements.txt for install of libnacl, secp256k1

Bugfixes:
- `ad0f95b` fixed bug from changing blockchaininterface, also added sleep because of issue #516
- `ed4d242` made options in tumbler a dict, required for tumbler resume
- `848d221` catch exceptions in encryption initialization (potential DOS)
- `af78bf9` silence terminal spam
- `f96119c` Allow 'maxsize' and 'minsize' to be type long as well as type int.
- `f9fd64f` fix crash on insufficient coins in any mixdepth
- `4d63940` sendpayment: increase default waittime from 5 to 15
- `d01d5b1` yg-oscill: fix empty filtered_mix_balance crash
- `3eb126c` fixed tumbler crash (#538)
- `1301aab` yieldgens: fix issue 567 for max_size orders
- `643f1fb` `2c6b465` `1fb7c3c` `984626b` `ab0b2ea` `0381405` `dba1220` Wallet sync improvements and corrections
- `5057226` Quote csv values

Credits
=======

Thanks to everyone who directly contributed to this release

- @AdamISZ
- @chris-belcher
- @adlai
- @AlexCato
- @raedah
- @nkuttler
- @jamesphillipturpin

And those who contributed additional code review, ideas, debug logs and comments, and especially those who helped with testing!.
