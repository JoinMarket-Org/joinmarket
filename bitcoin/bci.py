#!/usr/bin/python
import json, re
import random
import sys
import time
import platform
from joinmarket.support import get_log
if platform.system() == "Windows":
    import ssl
    import urllib2
else:
    try:
        from urllib.request import build_opener
    except:
        from urllib2 import build_opener

log = get_log()

# Makes a request to a given URL (first arg) and optional params (second arg)
def make_request(*args):
    if platform.system() == "Windows":
        sctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        sh = urllib2.HTTPSHandler(debuglevel=0, context=sctx)
        opener = urllib2.build_opener(sh)
    else:
        opener = build_opener()
    opener.addheaders = [('User-agent',
                          'Mozilla/5.0 (Windows NT 6.1; rv:45.0) Gecko/20100101 Firefox/45.0')]
    try:
        return opener.open(*args).read().strip()
    except Exception as e:
        try:
            p = e.read().strip()
        except:
            p = e
        raise Exception(p)

# Pushes a transaction to the network using https://blockchain.info/pushtx
def bci_pushtx(tx):
    if not re.match('^[0-9a-fA-F]*$', tx):
        tx = tx.encode('hex')
    return make_request('https://blockchain.info/pushtx', 'tx=' + tx)
