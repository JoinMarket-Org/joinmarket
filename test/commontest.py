#! /usr/bin/env python
from __future__ import absolute_import
'''Some helper functions for testing'''

import sys
import os
import time
import binascii
import pexpect
import random
import subprocess
import platform
from decimal import Decimal

data_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(data_dir))

from joinmarket import jm_single, Wallet, get_log
from joinmarket.support import chunks

log = get_log()
'''This code is intended to provide
subprocess startup cross-platform with
some useful options; it could do with
some simplification/improvement.'''
import platform
OS = platform.system()
PINL = '\r\n' if OS == 'Windows' else '\n'


def local_command(command, bg=False, redirect=''):
    if redirect == 'NULL':
        if OS == 'Windows':
            command.append(' > NUL 2>&1')
        elif OS == 'Linux':
            command.extend(['>', '/dev/null', '2>&1'])
        else:
            print "OS not recognised, quitting."
    elif redirect:
        command.extend(['>', redirect])

    if bg:
        #using subprocess.PIPE seems to cause problems
        FNULL = open(os.devnull, 'w')
        return subprocess.Popen(command,
                                stdout=FNULL,
                                stderr=subprocess.STDOUT,
                                close_fds=True)
    else:
        #in case of foreground execution, we can use the output; if not
        #it doesn't matter
        return subprocess.check_output(command)


def make_wallets(n,
                 wallet_structures=None,
                 mean_amt=1,
                 sdev_amt=0,
                 start_index=0,
                 fixed_seeds=None):
    '''n: number of wallets to be created
       wallet_structure: array of n arrays , each subarray
       specifying the number of addresses to be populated with coins
       at each depth (for now, this will only populate coins into 'receive' addresses)
       mean_amt: the number of coins (in btc units) in each address as above
       sdev_amt: if randomness in amouts is desired, specify here.
       Returns: a dict of dicts of form {0:{'seed':seed,'wallet':Wallet object},1:..,}'''
    if len(wallet_structures) != n:
        raise Exception("Number of wallets doesn't match wallet structures")
    if not fixed_seeds:
        seeds = chunks(binascii.hexlify(os.urandom(15 * n)), 15 * 2)
    else:
        seeds = fixed_seeds
    wallets = {}
    for i in range(n):
        wallets[i + start_index] = {'seed': seeds[i],
                                    'wallet': Wallet(seeds[i],
                                                     max_mix_depth=5)}
        for j in range(5):
            for k in range(wallet_structures[i][j]):
                deviation = sdev_amt * random.random()
                amt = mean_amt - sdev_amt / 2.0 + deviation
                if amt < 0: amt = 0.001
                amt = float(Decimal(amt).quantize(Decimal(10)**-8))
                jm_single().bc_interface.grab_coins(
                    wallets[i + start_index]['wallet'].get_external_addr(j),
                    amt)
            #reset the index so the coins can be seen if running in same script
            wallets[i + start_index]['wallet'].index[j][0] -= wallet_structures[i][j]
    return wallets


def interact(process, inputs, expected):
    if len(inputs) != len(expected):
        raise Exception("Invalid inputs to interact()")
    for i, inp in enumerate(inputs):
        process.expect(expected[i])
        process.sendline(inp)
