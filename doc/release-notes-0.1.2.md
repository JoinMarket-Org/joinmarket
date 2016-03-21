Joinmarket 0.1.2:

  <https://github.com/joinmarket-org/joinmarket/releases/tag/v0.1.1>

This is a minor bugfix release. Please update immediately.

For detailed release notes, see the most recent major release [notes](https://github.com/joinmarket-org/joinmarket/tree/master/doc/release-notes.md).

Please report bugs using the issue tracker at github:

  <https://github.com/joinmarket-org/joinmarket/issues>

Upgrading and downgrading
=========================

There is no binary component of the installation yet supported. If you have already
installed libsodium and Python, you will not need to re-install anything, but
only update the joinmarket source code.

Be sure to update your joinmarket.cfg file by moving or deleting it and recreating
it on first startup.

Notable changes
===============

Preventing anybody being able to crash all bots by sending an invalid message

Returning the alert system to JoinMarket after it was mistakenly removed in a refactor

------------------------------------

See [400](https://github.com/joinmarket-org/joinmarket/issues/400)
Anybody announcing a command to cancel an order without an order id would cause 
all bots to crash
This fix prevents that.


0.1.1 Change log
=================

- #398 `fb624cc` fix crash caused by malformed cancel message
- #401 `6eac518` put back joinmarket alerts and core alerts
- #387 `77ef4b4` clump coins differently in yieldgenerator to increase privacy
- #397 `6ced862` fix issue 395 about accidental negative fees in yieldgenerator deluxe
- #392 `00ef236` fix issue #392

