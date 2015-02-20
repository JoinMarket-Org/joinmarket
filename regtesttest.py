import sys
import os
import subprocess
import unittest
from common import *
from blockchaininterface import *
import bitcoin as btc
import binascii
'''Expectations
1. Any bot should run indefinitely irrespective of the input
messages it receives, except bots which perform a finite action

2. A bot must never spend an unacceptably high transaction fee.

3. A bot must explicitly reject interactions with another bot not
respecting the JoinMarket protocol for its version.

4. Bots must never send bitcoin data in the clear over the wire.
'''
'''helper functions put here to avoid polluting the main codebase.'''

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
    if OS == 'Windows':
        if bg:
            #20 Sep 2013:
            #a hack is needed here.
            #Additional note: finally fixed this incredibly pernicious bug!
            #for details, see my post at: http://www.reddit.com/r/Python/
            #comments/1mpxus/subprocess_modules_and_double_quotes/ccc4sqr
            return subprocess.Popen(command,stdout=subprocess.PIPE,\
                                    stderr=subprocess.PIPE,stdin=subprocess.PIPE)
        else:
            return subprocess.check_output(command)
    elif OS == 'Linux':
        if bg:
            return subprocess.Popen(command,stdout=subprocess.PIPE,\
                                    stderr=subprocess.PIPE,stdin=subprocess.PIPE)
        else:
            #in case of foreground execution, we can use the output; if not
            #it doesn't matter
            return subprocess.check_output(command)
    else:
        print "OS not recognised, quitting."


class Join2PTests(unittest.TestCase):

    def setUp(self):
        for cf in ['yield.out', 'send.out']:
            if (os.path.isfile(cf)):
                os.remove(cf)
    #create 2 new random wallets.
    #put 100 coins into the first receive address
    #to allow that bot to start.
        seed1, seed2 = [binascii.hexlify(x)
                        for x in [os.urandom(15), os.urandom(15)]]
        self.wallets = {}
        wallet1 = Wallet(seed1)
        wallet2 = Wallet(seed2)
        self.wallets[1] = {'seed': seed1, 'wallet': wallet1}
        self.wallets[2] = {'seed': seed2, 'wallet': wallet2}
        bci = RegTestImp(btc_cli_loc)
        #get first address in each wallet
        addr1 = wallet1.get_receive_addr(0)
        print "got this address for wallet1: " + addr1
        addr2 = wallet2.get_receive_addr(0)
        print "got this address for wallet2: " + addr2
        bci.grab_coins(addr1, 10)
        bci.grab_coins(addr2, 10)

    def run_single_send(self):
        #start yield generator with wallet1
        print "This is the seed: "
        print self.wallets[1]['seed']
        yigen_proc = local_command(
            ['python', 'yield-generator.py', str(self.wallets[1]['seed'])],
            bg=True)

        #A significant delay is needed to wait for the yield generator to sync its wallet
        time.sleep(30)

        #run a single sendpayment call with wallet2
        amt = 100000000  #in satoshis
        dest_address = btc.privkey_to_address(os.urandom(32), get_addr_vbyte())
        try:
            sp_proc = local_command(['python','sendpayment.py','-N','1',self.wallets[2]['seed'],\
                                               str(amt),dest_address])
        except subprocess.CalledProcessError, e:
            if yigen_proc:
                yigen_proc.kill()
            print e.returncode
            print e.message
            raise

        if yigen_proc:
            yigen_proc.kill()

        for cf in ['yield.out', 'send.out']:
            if os.path.isfile(cf):
                with open(cf, 'rb') as f:
                    if 'CRASHING' in f.read(): return False

        myBCI = blockchaininterface.RegTestImp(btc_cli_loc)
        received = myBCI.get_balance_at_addr([dest_address])['data'][0][
            'balance']
        if received != amt:
            return False
        return True

    def testSimpleSend(self):
        self.failUnless(self.run_single_send())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
