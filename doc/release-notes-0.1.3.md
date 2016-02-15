JoinMarket 0.1.3:

  <https://github.com/joinmarket-org/joinmarket/releases/tag/v0.1.3>

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

Fixing a race condition that allowed makers to get a higher amount of the takers
coins as fees than advertised.


0.1.3 Change log
=================

- `508d65f` fix for race condition involving orders
