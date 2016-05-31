import base64, abc
from joinmarket.enc_wrapper import encrypt_encode, decode_decrypt
from joinmarket.support import get_log, chunks
from joinmarket.configure import jm_single

COMMAND_PREFIX = '!'

encrypted_commands = ["auth", "ioauth", "tx", "sig"]
plaintext_commands = ["fill", "error", "pubkey", "orderbook", "relorder",
                      "absorder", "push"]

log = get_log()

class CJPeerError(StandardError):
    pass


class MessageChannel(object):
    __metaclass__ = abc.ABCMeta
    """Abstract class which implements a way for bots to communicate.
    The Joinmarket messaging protocol is implemented here, while
    subclasses implement the OTW messaging protocol layer, as described
    in the abstract methods section below.
    """

    def __init__(self):
        # all
        self.on_welcome = None
        self.on_set_topic = None
        self.on_connect = None
        self.on_disconnect = None
        self.on_nick_leave = None
        self.on_nick_change = None
        # orderbook watch functions
        self.on_order_seen = None
        self.on_order_cancel = None
        # taker functions
        self.on_error = None
        self.on_pubkey = None
        self.on_ioauth = None
        self.on_sig = None
        # maker functions
        self.on_orderbook_requested = None
        self.on_order_fill = None
        self.on_seen_auth = None
        self.on_seen_tx = None
        self.on_push_tx = None

    """THIS SECTION MUST BE IMPLEMENTED BY SUBCLASSES"""

    #In addition to the below functions, the implementation
    #must also call the callback function self.on_set_topic
    #to relay the public channel topic at startup.

    #Also, the implementation constructor (__init__) must
    #provide login credentials specific to itself as arguments.

    @abc.abstractmethod
    def run(self):
        """Main running loop of the message channel"""

    @abc.abstractmethod
    def shutdown(self):
        """Stop the main loop of the message channel,
        shutting down subsidiary resources gracefully.
        Note that unexpected disconnections MUST be
        handled by the implementation itself (restarting
        as appropriate)."""

    @abc.abstractmethod
    def _pubmsg(self, msg):
        """Send a message onto the shared, public
        channel (the joinmarket pit)."""

    @abc.abstractmethod
    def _privmsg(self, nick, cmd, message):
        """Send a message to a specific counterparty"""

    @abc.abstractmethod
    def _announce_orders(self, orderlist, nick):
        """Send orders defined in list orderlist either
        to the shared public channel (pit), if nick=None,
        or to an individual counterparty nick. Note that
        calling code will access this via self.announce_orders."""

    """END OF SUBCLASS IMPLEMENTATION SECTION"""

    # callbacks for everyone
    # some of these many not have meaning in a future channel, like bitmessage
    def register_channel_callbacks(self,
                                   on_welcome=None,
                                   on_set_topic=None,
                                   on_connect=None,
                                   on_disconnect=None,
                                   on_nick_leave=None,
                                   on_nick_change=None):
        self.on_welcome = on_welcome
        self.on_set_topic = on_set_topic
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_nick_leave = on_nick_leave
        self.on_nick_change = on_nick_change

    # orderbook watcher commands
    def register_orderbookwatch_callbacks(self,
                                          on_order_seen=None,
                                          on_order_cancel=None):
        self.on_order_seen = on_order_seen
        self.on_order_cancel = on_order_cancel

    # taker commands
    def register_taker_callbacks(self,
                                 on_error=None,
                                 on_pubkey=None,
                                 on_ioauth=None,
                                 on_sig=None):
        self.on_error = on_error
        self.on_pubkey = on_pubkey
        self.on_ioauth = on_ioauth
        self.on_sig = on_sig

    # maker commands
    def register_maker_callbacks(self,
                                 on_orderbook_requested=None,
                                 on_order_fill=None,
                                 on_seen_auth=None,
                                 on_seen_tx=None,
                                 on_push_tx=None):
        self.on_orderbook_requested = on_orderbook_requested
        self.on_order_fill = on_order_fill
        self.on_seen_auth = on_seen_auth
        self.on_seen_tx = on_seen_tx
        self.on_push_tx = on_push_tx

    def announce_orders(self, orderlist, nick=None):
        order_keys = ['oid', 'minsize', 'maxsize', 'txfee', 'cjfee']
        orderlines = []
        for order in orderlist:
            orderlines.append(COMMAND_PREFIX + order['ordertype'] + \
                    ' ' + ' '.join([str(order[k]) for k in order_keys]))
        self._announce_orders(orderlines, nick)

    def check_for_orders(self, nick, _chunks):
        if _chunks[0] in jm_single().ordername_list:
            try:
                counterparty = nick
                oid = _chunks[1]
                ordertype = _chunks[0]
                minsize = _chunks[2]
                maxsize = _chunks[3]
                txfee = _chunks[4]
                cjfee = _chunks[5]
                if self.on_order_seen:
                    self.on_order_seen(counterparty, oid, ordertype, minsize,
                                       maxsize, txfee, cjfee)
            except IndexError as e:
                log.warning(e)
                log.debug('index error parsing chunks, possibly malformed'
                          'offer by other party. No user action required.')
                # TODO what now? just ignore iirc
            finally:
                return True
        return False

    def cancel_orders(self, oid_list):
        clines = [COMMAND_PREFIX + 'cancel ' + str(oid) for oid in oid_list]
        self.pubmsg(''.join(clines))

    def send_pubkey(self, nick, pubkey):
        self.privmsg(nick, 'pubkey', pubkey)

    def send_ioauth(self, nick, utxo_list, cj_pubkey, change_addr, sig):
        authmsg = (str(','.join(utxo_list)) + ' ' + cj_pubkey + ' ' +
                   change_addr + ' ' + sig)
        self.privmsg(nick, 'ioauth', authmsg)

    def send_sigs(self, nick, sig_list):
        # TODO make it send the sigs on one line if there's space
        for s in sig_list:
            self.privmsg(nick, 'sig', s)

    # OrderbookWatch callback
    def request_orderbook(self):
        self.pubmsg(COMMAND_PREFIX + 'orderbook')

    # Taker callbacks
    def fill_orders(self, nick_order_dict, cj_amount, taker_pubkey):
        for c, order in nick_order_dict.iteritems():
            msg = str(order['oid']) + ' ' + str(cj_amount) + ' ' + taker_pubkey
            self.privmsg(c, 'fill', msg)

    def send_auth(self, nick, pubkey, sig):
        message = pubkey + ' ' + sig
        self.privmsg(nick, 'auth', message)

    def send_tx(self, nick_list, txhex):
        txb64 = base64.b64encode(txhex.decode('hex'))
        for nick in nick_list:
            self.privmsg(nick, 'tx', txb64)

    def push_tx(self, nick, txhex):
        txb64 = base64.b64encode(txhex.decode('hex'))
        self.privmsg(nick, 'push', txb64)

    def get_encryption_box(self, cmd, nick):
        """Establish whether the message is to be
        encrypted/decrypted based on the command string.
        If so, retrieve the appropriate crypto_box object
        and return. """
        if cmd in plaintext_commands:
            return None, False
        else:
            return self.cjpeer.get_crypto_box_from_nick(nick), True

    def send_error(self, nick, errormsg):
        log.debug('error<%s> : %s' % (nick, errormsg))
        self.privmsg(nick, 'error', errormsg)
        raise CJPeerError()

    def pubmsg(self, message):
        log.debug('>>pubmsg ' + message)
        #Currently there is no joinmarket protocol logic here;
        #just pass-through.
        self._pubmsg(message)

    def privmsg(self, nick, cmd, message):
        log.debug('>>privmsg ' + 'nick=' + nick + ' cmd=' + cmd + ' msg=' +
                  message)
        # should we encrypt?
        box, encrypt = self.get_encryption_box(cmd, nick)
        if encrypt:
            if not box:
                log.debug('error, dont have encryption box object for ' + nick +
                          ', dropping message')
                return
            message = encrypt_encode(message, box)
        #forward to the implementation class (use single _ for polymrphsm to work)
        self._privmsg(nick, cmd, message)

    def on_pubmsg(self, nick, message):
        if message[0] != COMMAND_PREFIX:
            return
        commands = message[1:].split(COMMAND_PREFIX)
        #DOS vector: repeated !orderbook requests, see #298.
        if commands.count('orderbook')>1:
            return
        for command in commands:
            _chunks = command.split(" ")
            if self.check_for_orders(nick, _chunks):
                pass
            elif _chunks[0] == 'cancel':
                # !cancel [oid]
                try:
                    oid = int(_chunks[1])
                    if self.on_order_cancel:
                        self.on_order_cancel(nick, oid)
                except (ValueError, IndexError) as e:
                    log.debug("!cancel " + repr(e))
                    return
            elif _chunks[0] == 'orderbook':
                if self.on_orderbook_requested:
                    self.on_orderbook_requested(nick)
            else:
                # TODO this is for testing/debugging, should be removed, see taker.py
                if hasattr(self, 'debug_on_pubmsg_cmd'):
                    self.debug_on_pubmsg_cmd(nick, _chunks)

    def on_privmsg(self, nick, message):
        """handles the case when a private message is received"""
        if message[0] != COMMAND_PREFIX:
            log.debug('message not a cmd')
            return
        cmd_string = message[1:].split(' ')[0]
        if cmd_string not in plaintext_commands + encrypted_commands:
            log.debug('cmd not in cmd_list, line="' + message + '"')
            return
        for command in message[1:].split(COMMAND_PREFIX):
            _chunks = command.split(" ")

            #Decrypt if necessary
            if _chunks[0] in encrypted_commands:
                box, encrypt = self.get_encryption_box(_chunks[0], nick)
                if encrypt:
                    if not box:
                        log.debug('error, dont have encryption box object for '
                                  + nick + ', dropping message')
                        return
                    # need to decrypt everything after the command string
                    to_decrypt = ''.join(_chunks[1:])
                    try:
                        decrypted = decode_decrypt(to_decrypt, box)
                    except ValueError as e:
                        log.debug('valueerror when decrypting, skipping: ' +
                                  repr(e))
                        return
                    #rebuild the chunks array as if it had been plaintext
                    _chunks = [_chunks[0]] + decrypted.split(" ")

            # looks like a very similar pattern for all of these
            # check for a command name, parse arguments, call a function
            # maybe we need some eval() trickery to do it better

            try:
                # orderbook watch commands
                if self.check_for_orders(nick, _chunks):
                    pass

                # taker commands
                elif _chunks[0] == 'pubkey':
                    maker_pk = _chunks[1]
                    if self.on_pubkey:
                        self.on_pubkey(nick, maker_pk)
                elif _chunks[0] == 'ioauth':
                    utxo_list = _chunks[1].split(',')
                    cj_pub = _chunks[2]
                    change_addr = _chunks[3]
                    btc_sig = _chunks[4]
                    if self.on_ioauth:
                        self.on_ioauth(nick, utxo_list, cj_pub, change_addr,
                                       btc_sig)
                elif _chunks[0] == 'sig':
                    sig = _chunks[1]
                    if self.on_sig:
                        self.on_sig(nick, sig)

                # maker commands
                if _chunks[0] == 'fill':
                    try:
                        oid = int(_chunks[1])
                        amount = int(_chunks[2])
                        taker_pk = _chunks[3]
                    except (ValueError, IndexError) as e:
                        self.send_error(nick, str(e))
                    if self.on_order_fill:
                        self.on_order_fill(nick, oid, amount, taker_pk)
                elif _chunks[0] == 'auth':
                    try:
                        i_utxo_pubkey = _chunks[1]
                        btc_sig = _chunks[2]
                    except (ValueError, IndexError) as e:
                        self.send_error(nick, str(e))
                    if self.on_seen_auth:
                        self.on_seen_auth(nick, i_utxo_pubkey, btc_sig)
                elif _chunks[0] == 'tx':
                    b64tx = _chunks[1]
                    try:
                        txhex = base64.b64decode(b64tx).encode('hex')
                    except TypeError as e:
                        self.send_error(nick, 'bad base64 tx. ' + repr(e))
                    if self.on_seen_tx:
                        self.on_seen_tx(nick, txhex)
                elif _chunks[0] == 'push':
                    b64tx = _chunks[1]
                    try:
                        txhex = base64.b64decode(b64tx).encode('hex')
                    except TypeError as e:
                        self.send_error(nick, 'bad base64 tx. ' + repr(e))
                    if self.on_push_tx:
                        self.on_push_tx(nick, txhex)
            except CJPeerError:
                # TODO proper error handling
                log.debug('cj peer error TODO handle')
                continue
