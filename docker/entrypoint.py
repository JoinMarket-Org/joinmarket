#!/usr/bin/env python2
"""Entrypoints for Docker containers to run joinmarket.

todo: wait_for_file should probably be a decorator
todo: either always force wallet.json or make waiting for the wallet smarter
"""
import argparse
import logging
import os
import os.path
import subprocess
import sys
import time


#
# Helpers
#

DEBUG_LOG_FORMAT = (
    '-' * 80 + '\n' +
    '%(asctime)s %(levelname)s in %(name)s @ %(threadName)s:\n' +
    '%(pathname)s:%(lineno)d\n' +
    '%(message)s\n' +
    '-' * 80
)
DEFAULT_LOG_FORMAT = '%(asctime)s %(levelname)s: %(threadName)s: %(name)s: %(message)s'  # noqa

log = logging.getLogger(__name__)


def run(*args):
    """Run a python command inside the joinmarket virtualenv.

    Raises subprocess.CalledProcessError if the command fails.
    """
    if not args:
        raise ValueError("run needs at least one arg")

    command_list = [sys.executable] + map(str, args)

    log.info("Running %s...", command_list[1])
    log.debug("Full command: %s", command_list)

    return subprocess.check_call(command_list, env=os.environ)


def run_or_exit(*args):
    """Run a python command inside the joinmarket virtualenv.

    Logs and exits if the command fails.
    """
    try:
        return run(*args)
    except subprocess.CalledProcessError as e:
        log.error("%s", e)
        sys.exit(e.returncode)


def wait_for_config(*args):
    """Sleep until config loads.

    Config loading includes bitcoind responding to getblockchaininfo

    Todo: exponential backoff of the sleep. maybe log less, too
    Todo: args here are hacky. make this function and the command seperate
    """
    while True:
        try:
            run('check-config.py')
        except subprocess.CalledProcessError as e:
            # TODO: this is too verbose
            log.error("Unable to load config: %s. Sleeping..." % e)
            time.sleep(60)
        else:
            break

    return True


def wait_for_file(filename, sleep=10):
    """Sleep until a given file exists."""
    if os.path.exists(filename):
        return

    log.info("'%s' does not exist. Check the README", filename)

    log.info("Sleeping until '%s' exists...", filename)
    while not os.path.exists(filename):
        time.sleep(sleep)

    log.info("Found '%s'", filename)
    return


#
# Commands
#

def get_parser():
    """Create an argument parser that routes to the command functions."""
    # create the top-level parser
    parser = argparse.ArgumentParser()
    # todo: configurable log level
    subparsers = parser.add_subparsers()

    # create the parser for the "maker" command
    parser_maker = subparsers.add_parser('maker')
    parser_maker.set_defaults(func=maker)

    # create the parser for the "ob_watcher" command
    parser_ob_watcher = subparsers.add_parser('ob_watcher')
    parser_ob_watcher.set_defaults(func=ob_watcher)

    # create the parser for the "sendpayment" command
    parser_sendpayment = subparsers.add_parser('sendpayment')
    parser_sendpayment.set_defaults(func=sendpayment)

    # create the parser for the "taker" command
    parser_tumbler = subparsers.add_parser('tumbler')
    parser_tumbler.set_defaults(func=tumbler)

    # create the parser for the "wallet_tool" command
    parser_wallet_tool = subparsers.add_parser('wallet_tool')
    parser_wallet_tool.set_defaults(func=wallet_tool)

    # other scripts might find waiting for the config helpful, too
    parser_wait_for_config = subparsers.add_parser('wait_for_config')
    parser_wait_for_config.set_defaults(func=wait_for_config)

    return parser


def maker(args):
    """Earn Bitcoins and privacy."""
    wallet_filename = 'wallet.json'
    wait_for_file("wallets/%s" % wallet_filename)

    # wait for bitcoind to respond
    wait_for_config()

    run_or_exit('yg-pe.py', wallet_filename, *args)


def ob_watcher(args):
    """Watch the orderbook."""
    # wait for bitcoind to respond
    # todo: although, why does the orderbook need bitcoind?
    wait_for_config()

    run_or_exit('ob-watcher.py', *args)


def sendpayment(args):
    """"Send Bitcoins with privacy.

    todo: make sure we only sendpayment with coins that have already been
          joined at least once.
    """
    wallet_filename = 'wallet.json'
    wait_for_file("wallets/%s" % wallet_filename)

    # wait for bitcoind to respond
    wait_for_config()

    run_or_exit('sendpayment.py', *args)


def tumbler(args):
    """"Send Bitcoins with layers of privacy."""
    wallet_filename = 'wallet.json'
    wait_for_file("wallets/%s" % wallet_filename)

    # wait for bitcoind to respond
    wait_for_config()

    run_or_exit('tumbler.py', *args)


def wallet_tool(args):
    """Inspect and manage your Bitcoin wallet."""
    run_or_exit('wallet-tool.py', *args)


def main():
    """Manage joinmarket."""
    parser = get_parser()
    args, passthrough_args = parser.parse_known_args()

    log_level = logging.DEBUG  # todo: get log_level from args

    if log_level == logging.DEBUG:
        log_format = DEBUG_LOG_FORMAT
    else:
        log_format = DEFAULT_LOG_FORMAT

    logging.basicConfig(
        format=log_format,
        level=log_level,
        stream=sys.stdout,
    )
    log.debug("Hello!")

    args.func(passthrough_args)


if __name__ == '__main__':
    sys.exit(main())
