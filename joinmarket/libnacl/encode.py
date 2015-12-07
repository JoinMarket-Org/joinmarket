# -*- coding: utf-8 -*-
# noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
"""
Build in routines and classes to simplify encoding routines
"""
# Import python libs
import base64
import binascii


def hex_encode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Hex encode data
        :param data:
        """
    return binascii.hexlify(data)


def hex_decode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Hex decode data
        :param data:
        """
    return binascii.unhexlify(data)


def base16_encode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Base32 encode data
        :param data:
        """
    return base64.b16encode(data)


def base16_decode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Base16 decode data
        :param data:
        """
    return base64.b16decode(data)


def base32_encode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Base16 encode data
        :param data:
        """
    return base64.b32encode(data)


def base32_decode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Base32 decode data
        :param data:
        """
    return base64.b32decode(data)


def base64_encode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Base16 encode data
        :param data:
        """
    return base64.b64encode(data)


def base64_decode(data):
    # noinspection PySingleQuotedDocstring,PySingleQuotedDocstring
    """
        Base32 decode data
        :param data:
        """
    return base64.b64decode(data)
