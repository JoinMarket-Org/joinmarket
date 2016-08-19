import pytest
import os
import time
import subprocess
from commontest import local_command
from joinmarket import load_program_config

bitcoin_path = None
bitcoin_conf = None
bitcoin_rpcpassword = None
bitcoin_rpcusername = None
miniircd_proc = None


def pytest_addoption(parser):
    parser.addoption("--btcroot", action="store", default='',
                     help="the fully qualified path to the directory containing "+\
                     "the bitcoin binaries, e.g. /home/user/bitcoin/bin/")
    parser.addoption("--btcconf", action="store",
                         help="the fully qualified path to the location of the "+\
                         "bitcoin configuration file you use for testing, e.g. "+\
                         "/home/user/.bitcoin/bitcoin.conf")
    parser.addoption("--btcpwd",
                     action="store",
                     help="the RPC password for your test bitcoin instance")
    parser.addoption("--btcuser",
                     action="store",
                     default='bitcoinrpc',
                     help="the RPC username for your test bitcoin instance (default=bitcoinrpc)")

## a lot of these sleeps should be replaced by rpc calls which detech
## when bitcoin core is ready
def start_bitcoind(additional_args=None):
    if not additional_args:
        additional_args = []
    #start up regtest blockchain
    btc_proc = subprocess.call([bitcoin_path + "bitcoind", "-regtest",
            "-daemon", "-conf=" + bitcoin_conf] + additional_args)
    time.sleep(20)
    #generate blocks
    local_command([bitcoin_path + "bitcoin-cli", "-regtest", "-rpcuser=" +
            bitcoin_rpcusername, "-rpcpassword=" + bitcoin_rpcpassword,
            "generate", "101"])
    time.sleep(10)

def stop_bitcoind():
    #shut down bitcoin and remove the regtest dir
    local_command([bitcoin_path + "bitcoin-cli", "-regtest", "-rpcuser=" + bitcoin_rpcusername,
                   "-rpcpassword=" + bitcoin_rpcpassword, "stop"])
    #note, it is better to clean out ~/.bitcoin/regtest but too
    #dangerous to automate it here perhaps
    time.sleep(10)

def teardown():
    #didn't find a stop command in miniircd, so just kill
    global miniircd_proc
    miniircd_proc.kill()
    stop_bitcoind()

@pytest.fixture(scope="session", autouse=True)
def setup(request):
    request.addfinalizer(teardown)

    global bitcoin_conf, bitcoin_path, bitcoin_rpcpassword, bitcoin_rpcusername
    bitcoin_path = request.config.getoption("--btcroot")
    bitcoin_conf = request.config.getoption("--btcconf")
    bitcoin_rpcpassword = request.config.getoption("--btcpwd")
    bitcoin_rpcusername = request.config.getoption("--btcuser")

    #start up miniircd
    #minor bug in miniircd (seems); need *full* unqualified path for motd file
    cwd = os.getcwd()
    global miniircd_proc
    miniircd_proc = local_command(
        ["./miniircd/miniircd", "--motd=" + cwd + "/miniircd/testmotd"],
        bg=True)

    start_bitcoind()
