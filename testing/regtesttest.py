import sys
import os
import subprocess
import unittest
'''Expectations
1. Any bot should run indefinitely irrespective of the input
messages it receives, except:
a. Bots which perform a finite action
b. When there is a network failure, the bot should quit gracefully.

2. A bot must never spend an unacceptably high transaction fee.

3. A bot must explicitly reject interactions with another bot not
respecting the JoinMarket protocol for its version.


'''
bitcointoolsdir = '/home/adam/bitcoin/bitcoin-0.9.1-linux/bin/64/'
btc_client = bitcointoolsdir + 'bitcoin-cli'
btc_client_flags = '-regtest'


class FooTests(unittest.TestCase):

    def testFoo(self):
        self.failUnless(False)
        #subprocess.Popen([btc_client,btc_client_flags,'listunspent'])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
