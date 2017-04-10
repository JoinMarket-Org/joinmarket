from __future__ import absolute_import

import sys

from joinmarket import get_log, load_program_config


log = get_log()


def main():
    """Simple command to make sure the config loads.

    This will exit 1 if the config cannot be loaded or the blockchaininterface
    doesn't respond.
    """
    try:
        load_program_config()
    except Exception:
        log.exception("Error while loading config")
        return 1


if __name__ == "__main__":
    sys.exit(main())
