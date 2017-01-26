#! /usr/bin/env python
from __future__ import absolute_import, print_function

import socket, time, random, sys
from struct import pack, unpack
from datetime import datetime

from joinmarket.configure import load_program_config, get_network
from joinmarket.socks import socksocket, setdefaultproxy, PROXY_TYPE_SOCKS5
from joinmarket.support import get_log

import bitcoin as btc
log = get_log()

PROTOCOL_VERSION = 70012
DEFAULT_USER_AGENT = '/JoinMarket:0.2.3/'

##protocol versions above this also send a relay boolean
RELAY_TX_VERSION = 70001

##length of bitcoin p2p packets
HEADER_LENGTH = 24

##how many times to connect to peer before giving up
MAX_CONNECTION_ATTEMPTS = 10

##if no message has been seen for this many seconds, send a ping
KEEPALIVE_INTERVAL = 2 * 60

#close connection if keep alive ping isnt responded to in this many seconds
KEEPALIVE_TIMEOUT = 20 * 60


TESTNET_DNS_SEEDS = [
    "testnet-seed.breadwallet.com.", "testnet-seed.bitcoin.petertodd.org.",
    "testnet-seed.bluematt.me.", "testnet-seed.bitcoin.schildbach.de."]

MAINNET_DNS_SEEDS = [
    "seed.breadwallet.com.", "seed.bitcoin.sipa.be.", "dnsseed.bluematt.me.",
    "dnsseed.bitcoin.dashjr.org.", "seed.bitcoinstats.com.",
    "bitseed.xf2.org.", "seed.bitcoin.jonasschnelli.ch."]

def ip_to_hex(ip_str):
    #ipv4 only for now
    return socket.inet_pton(socket.AF_INET, ip_str)

def create_net_addr(hexip, port): #doesnt contain time as in bitcoin wiki
    services = 0
    return pack("<Q16s", services, '\x00'*10 +
        '\xFF\xFF' + hexip) + pack(">H", port)

def create_var_str(s):
    return btc.num_to_var_int(len(s)) + s

def read_int(ptr, payload, n, littleendian=True):
    data = payload[ptr[0] : ptr[0]+n]
    if littleendian:
        data = data[::-1]
    ret =  btc.decode(data, 256)
    ptr[0] += n
    return ret

def read_var_int(ptr, payload):
    val = ord(payload[ptr[0]])
    ptr[0] += 1
    if val < 253:
        return val
    return read_int(ptr, payload, 2**(val - 252))

def read_var_str(ptr, payload):
    l = read_var_int(ptr, payload)
    ret = payload[ptr[0] : ptr[0] + l]
    ptr[0] += l
    return ret

def read_net_addr(ptr, payload):
    timestamp = read_int(ptr, payload, 4)
    services = read_int(ptr, payload, 8)
    ip_hex = payload[ptr[0] : ptr[0] + 16]
    ptr[0] += 16
    port = read_int(ptr, payload, 2, False)
    return timestamp, services, ip_hex, port

def ip_hex_to_str(ip_hex):
    #https://en.wikipedia.org/wiki/IPv6#IPv4-mapped_IPv6_addresses
    #https://www.cypherpunk.at/onioncat_trac/wiki/OnionCat
    if ip_hex[:14] == '\x00'*10 + '\xff'*2:
        #ipv4 mapped ipv6 addr
        return socket.inet_ntoa(ip_hex[12:])
    elif ip_hex[:6] == '\xfd\x87\xd8\x7e\xeb\x43':
        return base64.b32encode(ip_hex[6:]).lower() + '.onion'
    else:
        return socket.inet_ntop(socket.AF_INET6, ip_hex)

class P2PMessageHandler(object):
    def __init__(self):
        self.last_message = datetime.now()
        self.waiting_for_keepalive = False

    def check_keepalive(self, p2p):
        if self.waiting_for_keepalive:
            if (datetime.now() - self.last_message).total_seconds() < KEEPALIVE_TIMEOUT:
                return
            log.info('keepalive timed out, closing')
            p2p.sock.close()
        else:
            if (datetime.now() - self.last_message).total_seconds() < KEEPALIVE_INTERVAL:
                return
            log.debug('sending keepalive to peer')
            self.waiting_for_keepalive = True
            p2p.sock.sendall(p2p.create_message('ping', '\x00'*8))

    def handle_message(self, p2p, command, length, payload):
        self.last_message = datetime.now()
        self.waiting_for_keepalive = False
        ptr = [0]
        if command == 'version':
            version = read_int(ptr, payload, 4)
            services = read_int(ptr, payload, 8)
            timestamp = read_int(ptr, payload, 8)
            addr_recv_services = read_int(ptr, payload, 8)
            addr_recv_ip = payload[ptr[0] : ptr[0]+16]
            ptr[0] += 16
            addr_recv_port = read_int(ptr, payload, 2, False)
            addr_trans_services = read_int(ptr, payload, 8)
            addr_trans_ip = payload[ptr[0] : ptr[0]+16]
            ptr[0] += 16
            addr_trans_port = read_int(ptr, payload, 2, False)
            ptr[0] += 8 #skip over nonce
            user_agent = read_var_str(ptr, payload)
            start_height = read_int(ptr, payload, 4)
            if version > RELAY_TX_VERSION:
                relay = read_int(ptr, payload, 1) != 0
            else: ##must check this node accepts unconfirmed transactions for the broadcast
                relay = True
            log.debug(('peer version message: version=%d services=0x%x'
                + ' timestamp=%s user_agent=%s start_height=%d relay=%i'
                + ' them=%s:%d us=%s:%d') % (version,
                services, str(datetime.fromtimestamp(timestamp)),
                user_agent, start_height, relay, ip_hex_to_str(addr_trans_ip)
                , addr_trans_port, ip_hex_to_str(addr_recv_ip), addr_recv_port))
            p2p.sock.sendall(p2p.create_message('verack', ''))
            self.on_recv_version(p2p, version, services, timestamp,
                addr_recv_services, addr_recv_ip, addr_trans_services,
                addr_trans_ip, addr_trans_port, user_agent, start_height,
                relay)
        elif command == 'verack':
            self.on_connected(p2p)
        elif command == 'ping':
            p2p.sock.sendall(p2p.create_message('pong', payload))

    ##optional override these in a subclass

    def on_recv_version(self, p2p, version, services, timestamp,
            addr_recv_services, addr_recv_ip, addr_trans_services,
            addr_trans_ip, addr_trans_port, user_agent, start_height, relay):
        pass

    def on_connected(self, p2p):
        pass

    def on_heartbeat(self, p2p):
        pass

class P2PProtocol(object):
    def __init__(self, p2p_message_handler, remote_hostport=None,
            testnet=False, user_agent=DEFAULT_USER_AGENT, relay_txes=False,
            socks5_hostport=None, connect_timeout=30, heartbeat_interval=15):
        '''
        if remote_hostport = None, use dns_seeds for auto finding peers
        if socks5_hostport != None, use that proxy 
        relax_txes controls whether the peer will send you unconfirmed txes
        heartbeat_interval, how many seconds between heartbeats
        '''
        self.p2p_message_handler = p2p_message_handler
        self.testnet = testnet
        self.user_agent = user_agent
        self.relay_txes = relay_txes
        self.socks5_hostport = socks5_hostport
        self.heartbeat_interval = heartbeat_interval
        self.connect_timeout = connect_timeout
        if not self.testnet:
            self.magic = 0xd9b4bef9 #mainnet
        else:
            if testnet == True:
                self.magic = 0x0709110b #testnet
            else:
                self.magic = 0xdab5bffa #regtest
        self.closed = False
        self.connection_attempts = MAX_CONNECTION_ATTEMPTS

        if remote_hostport != None:
            self.remote_hostport = remote_hostport
            self.dns_seeds = []
        else:
            if self.testnet:
                self.dns_seeds = TESTNET_DNS_SEEDS
                port = 18333
            else:
                self.dns_seeds = MAINNET_DNS_SEEDS   
                port = 8333
            self.dns_index = random.randrange(len(self.dns_seeds))
            self.remote_hostport = (self.dns_seeds[self.dns_index], port)

    def run(self):
        services = 0 #headers only
        st = int(time.time())
        nonce = 0
        start_height = 0
        buffer_size = 4096

        netaddr = create_net_addr(ip_to_hex('0.0.0.0'), 0)
        version_message = (pack('<iQQ', PROTOCOL_VERSION, services, st)
            + netaddr
            + netaddr
            + pack('<Q', nonce)
            + create_var_str(self.user_agent)
            + pack('<I', start_height)
            + ('\x01' if self.relay_txes else '\x00'))
        data = self.create_message('version', version_message)
        while True:
            try:
                log.info('connecting to bitcoin peer (magic=' + hex(self.magic)
                    + ') at ' + str(self.remote_hostport) + ' with proxy ' +
                    str(self.socks5_hostport))
                if self.socks5_hostport == None:
                    self.sock = socket.socket(socket.AF_INET,
                        socket.SOCK_STREAM)
                else:
                    setdefaultproxy(PROXY_TYPE_SOCKS5, self.socks5_hostport[0],
                        self.socks5_hostport[1], True)
                    self.sock = socksocket()
                self.sock.settimeout(self.connect_timeout)
                self.sock.connect(self.remote_hostport)
                self.sock.sendall(data)
                break
            except IOError as e:
                if len(self.dns_seeds) == 0:
                    raise e
                else:
                    ##cycle to the next dns seed
                    time.sleep(0.5)
                    log.debug('connection attempts = ' + str(self.connection_attempts))
                    self.connection_attempts -= 1
                    if self.connection_attempts == 0:
                        raise e
                    self.dns_index = (self.dns_index + 1) % len(self.dns_seeds)
                    self.remote_hostport = (self.dns_seeds[self.dns_index],
                        self.remote_hostport[1])

        log.info('connected')
        self.sock.settimeout(self.heartbeat_interval)
        self.closed = False
        try:
            recv_buffer = ""
            payload_length = -1 #-1 means waiting for header
            command = None
            checksum = None
            while not self.closed:
                try:
                    recv_data = self.sock.recv(4096)
                    if not recv_data or len(recv_data) == 0:
                        raise EOFError()
                    recv_buffer += recv_data
                    #this is O(N^2) scaling in time, another way would be to store in a list
                    #and combine at the end with "".join()
                    #but this isnt really timing critical so didnt optimize it

                    data_remaining = True
                    while data_remaining and not self.closed:
                        if payload_length == -1 and len(recv_buffer) >= HEADER_LENGTH:
                            net_magic, command, payload_length, checksum = unpack('<I12sI4s', recv_buffer[:HEADER_LENGTH])
                            recv_buffer = recv_buffer[HEADER_LENGTH:]
                            if net_magic != self.magic:
                                log.error('wrong MAGIC: ' + hex(net_magic))
                                self.sock.close()
                                break
                            command = command.strip('\0')
                            data_remaining = True
                        else:
                            data_remaining = False

                        if payload_length >= 0 and len(recv_buffer) >= payload_length:
                            payload = recv_buffer[:payload_length]
                            recv_buffer = recv_buffer[payload_length:]
                            if btc.bin_dbl_sha256(payload)[:4] == checksum:
                                self.p2p_message_handler.handle_message(self, command,
                                    payload_length, payload)
                            else:
                                log.error('wrong checksum, dropping message, cmd=' + command + ' payloadlen=' + str(payload_length))
                            payload_length = -1
                            data_remaining = True
                        else:
                            data_remaining = False
                except socket.timeout:
                    self.p2p_message_handler.check_keepalive(self)
                    self.p2p_message_handler.on_heartbeat(self)
        except EOFError as e:
            self.closed = True
        except IOError as e:
            import traceback
            log.error("logging traceback from %s: \n" %
                traceback.format_exc())
            self.closed = True
        finally:
            try:
                self.sock.close()
            except Exception as e:
                pass


    def close(self):
        self.closed = True

    def create_message(self, command, payload):
        return (pack("<I12sI", self.magic, command, len(payload))
            + btc.bin_dbl_sha256(payload)[:4] + payload)

class P2PBroadcastTx(P2PMessageHandler):
    def __init__(self, txhex):
        P2PMessageHandler.__init__(self)
        self.txhex = txhex
        self.txid = btc.bin_txhash(self.txhex)[::-1]
        log.debug('broadcasting txid ' + str(self.txid[::-1].encode('hex')) +
            ' on ' + get_network())
        self.relay_txes = True
        self.rejected = False
        self.uploaded_tx = False

    def on_recv_version(self, p2p, version, services, timestamp,
            addr_recv_services, addr_recv_ip, addr_trans_services,
            addr_trans_ip, addr_trans_port, user_agent, start_height, relay):
        self.relay_txes = relay
        if not relay:
            log.debug('peer not accepting unconfirmed txes, trying another')
            #this happens if the other node is using blockonly=1
            p2p.close()

    def on_connected(self, p2p):
        log.debug('sending inv')
        MSG = 1 #msg_tx
        inv_payload = pack('<BI', 1, MSG) + self.txid
        p2p.sock.sendall(p2p.create_message('inv', inv_payload))
        self.time_marker = datetime.now()
        self.uploaded_tx = False

    #test when invalid tx, can probably be done from test

    def on_heartbeat(self, p2p):
        log.debug('broadcaster heartbeat')
        GETDATA_TIMEOUT = 40
        REJECT_TIMEOUT = 20
        if self.uploaded_tx:
            if (datetime.now() - self.time_marker).total_seconds() < REJECT_TIMEOUT:
                return
            #if 'reject' hasnt arrived by this time then the transaction is probably fine, disconnect
            self.rejected = False
        else:
            if (datetime.now() - self.time_marker).total_seconds() < GETDATA_TIMEOUT:
                return
            log.debug('timed out of waiting for getdata, node already has tx')
            self.rejected = False
        p2p.close()

    def handle_message(self, p2p, command, length, payload):
        P2PMessageHandler.handle_message(self, p2p, command, length, payload)
        ptr = [0]
        if command == 'getdata':
            count = read_var_int(ptr, payload)
            for i in xrange(count):
                msg_type = read_int(ptr, payload, 4)
                hash_id = payload[ptr[0] : ptr[0] + 32]
                ptr[0] += 32
                log.debug('hashid=' + hash_id[::-1].encode('hex'))
                if hash_id == self.txid:
                    log.debug('uploading tx')
                    p2p.sock.sendall(p2p.create_message('tx',
                        self.txhex.decode('hex')))
                    self.uploaded_tx = True
                    self.time_marker = datetime.now()
        elif command == 'reject':
            self.rejected = True
            message = read_var_str(ptr, payload)
            ccode = payload[ptr[0]]
            ptr[0] += 1
            reason = read_var_str(ptr, payload)
            log.debug('rejected transaction reason=' + reason)
            p2p.close()

def tor_broadcast_tx(txhex, tor_hostport, testnet, remote_hostport=None):
    ATTEMPTS = 8 #how many times to search for a node that accepts txes
    for i in range(ATTEMPTS):
        p2p_msg_handler = P2PBroadcastTx(txhex)
        p2p = P2PProtocol(p2p_msg_handler, remote_hostport=remote_hostport,
            testnet=testnet, socks5_hostport=tor_hostport, heartbeat_interval=20)
        p2p.run()
        log.debug('rejected={} relay={} uploaded={}'.format(p2p_msg_handler.rejected, p2p_msg_handler.relay_txes, p2p_msg_handler.uploaded_tx))
        if p2p_msg_handler.rejected:
            return False
        if p2p_msg_handler.uploaded_tx:
            return True
        #if p2p_msg_handler.relay_txes:
        #    continue
        #node doesnt accept unconfirmed txes, try again
    return False #never find a node that accepted unconfirms


if __name__ == "__main__":
    load_program_config()

    class P2PTest(P2PMessageHandler):
        def __init__(self, blockhash):
            P2PMessageHandler.__init__(self)
            self.blockhash = blockhash

        def on_connected(self, p2p):
            log.info('sending getaddr')
            p2p.sock.sendall(p2p.create_message('getaddr', ''))

        def on_heartbeat(self, p2p):
            log.info('heartbeat')
            MSG = 2 #MSG_BLOCK
            getdata_payload = pack('<BI', 1, MSG) + self.blockhash
            p2p.sock.sendall(p2p.create_message('getdata', getdata_payload))
            log.info('sent getdata block = ' + self.blockhash[::-1].encode('hex'))

        def handle_message(self, p2p, command, length, payload):
            P2PMessageHandler.handle_message(self, p2p, command, length,
                payload)
            ptr = [0]
            if command == 'addr':
                addr_count = read_var_int(ptr, payload)
                log.info('got ' + str(addr_count) + ' addresses')
                for i in xrange(addr_count):
                    timestamp, services, ip_hex, port = read_net_addr(ptr,
                        payload)
                    #log.info('timestamp=%s services=0x%02x addr=%s:%d' % (
                    #    str(datetime.fromtimestamp(timestamp)),
                    #    services, ip_hex_to_str(ip_hex), port))
            elif command == 'block':
                block_version, prev_block, merkle_root, timestamp, bits, nonce =\
                    unpack('<i32s32sIII', payload[ptr[0] : ptr[0]+80])
                self.blockhash = prev_block
                blockhash_str = btc.bin_dbl_sha256(payload[ptr[0] : ptr[0]+80])[::-1].encode('hex')
                #ptr[0] += 80
                log.info('hash=' + blockhash_str + ' prev=' + prev_block[::-1].encode('hex') + ' ts=' + str(datetime.fromtimestamp(timestamp)) + ' size=' + str(len(payload)))


    tor = False
    socks5_hostport = (('localhost', 9150) if tor else None)
    if len(sys.argv) > 1:
        p2p_msg_handler = P2PBroadcastTx(sys.argv[1])
        tor_broadcast_tx(sys.argv[1], tor_hostport)
    else:
        if get_network() != 'mainnet':
            blockhash = '000000000000025748e4d3eb121c4dba5c76d3d1a8069f7a22afb77183c7bddd'.decode('hex')[::-1]
        else:
            blockhash = '0000000000000000000c2190c9c9fad1fbd3a26c3f15ddff086b4bd916fb2e9c'.decode('hex')[::-1]
        p2p_msg_handler = P2PTest(blockhash)
        hostport = None
        p2p = P2PProtocol(p2p_msg_handler, testnet=(get_network() != 'mainnet'),
            socks5_hostport=socks5_hostport,
            remote_hostport=hostport)
        p2p.run()
