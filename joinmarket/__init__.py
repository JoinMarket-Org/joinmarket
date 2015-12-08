from __future__ import absolute_import, print_function

import logging

from .enc_wrapper import decode_decrypt, encrypt_encode, get_pubkey
from .irc import IRCMessageChannel
from .jsonrpc import JsonRpcError, JsonRpcConnectionError, JsonRpc
from .maker import Maker
from .message_channel import MessageChannel
from .old_mnemonic import mn_decode, mn_encode
from .slowaes import decryptData, encryptData
from .socks import socksocket
from .taker import Taker
from .wallet import AbstractWallet, BitcoinCoreInterface, Wallet
from .configure import load_program_config, jm_single, get_p2pk_vbyte, \
    get_network
# Set default logging handler to avoid "No handler found" warnings.

try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

logging.getLogger(__name__).addHandler(NullHandler())

