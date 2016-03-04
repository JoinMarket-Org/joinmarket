from __future__ import absolute_import, print_function

import logging

from .support import get_log, calc_cj_fee, debug_dump_object, \
    choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, \
    rand_norm_array, rand_pow_array, rand_exp_array, joinmarket_alert, core_alert
from .enc_wrapper import decode_decrypt, encrypt_encode, get_pubkey
from .irc import IRCMessageChannel, random_nick
from .jsonrpc import JsonRpcError, JsonRpcConnectionError, JsonRpc
from .maker import Maker
from .message_channel import MessageChannel
from .old_mnemonic import mn_decode, mn_encode
from .slowaes import decryptData, encryptData
from .taker import Taker, OrderbookWatch
from .wallet import AbstractWallet, BitcoinCoreInterface, Wallet, \
    BitcoinCoreWallet, create_wallet_file
from .configure import load_program_config, jm_single, get_p2pk_vbyte, \
    get_network, jm_single, get_network, validate_address, \
    get_blockchain_interface_instance
from .blockchaininterface import BlockrInterface
# Set default logging handler to avoid "No handler found" warnings.

try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

logging.getLogger(__name__).addHandler(NullHandler())

