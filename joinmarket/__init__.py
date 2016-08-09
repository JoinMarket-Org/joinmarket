from __future__ import absolute_import, print_function

import logging

from .support import get_log, calc_cj_fee, debug_dump_object, \
    choose_sweep_orders, choose_orders, \
    pick_order, cheapest_order_choose, weighted_order_choose, \
    rand_norm_array, rand_pow_array, rand_exp_array, joinmarket_alert, core_alert
from .enc_wrapper import as_init_encryption, decode_decrypt, \
    encrypt_encode, init_keypair, init_pubkey, get_pubkey, NaclError
from .irc import IRCMessageChannel, random_nick, B_PER_SEC
from .jsonrpc import JsonRpcError, JsonRpcConnectionError, JsonRpc
from .maker import Maker
from .message_channel import MessageChannel, MessageChannelCollection
from .old_mnemonic import mn_decode, mn_encode
from .slowaes import decryptData, encryptData
from .taker import Taker, OrderbookWatch, CoinJoinTX
from .wallet import AbstractWallet, BitcoinCoreInterface, Wallet, \
    BitcoinCoreWallet
from .configure import load_program_config, jm_single, get_p2pk_vbyte, \
    get_network, jm_single, get_network, validate_address, get_irc_mchannels, \
    check_utxo_blacklist
from .blockchaininterface import BlockrInterface, BlockchainInterface
from .yieldgenerator import YieldGenerator, ygmain
# Set default logging handler to avoid "No handler found" warnings.

try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

logging.getLogger(__name__).addHandler(NullHandler())

