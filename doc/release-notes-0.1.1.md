Joinmarket 0.1.1:

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

Preventing failure on receipt of invalid orders
------------------------------------

See [391](https://github.com/joinmarket-org/joinmarket/issues/391) and
[390](https://github.com/joinmarket-org/joinmarket/issues/390).
Makers publishing orders with non-integer amounts for an `absorder` were causing
a ValueError exception to be raised, preventing Takers from running successfully.
This fix prevents that.


0.1.1 Change log
=================


- #391 `7f5e06e` Disallow non-integer absorder in on_order_seen.
