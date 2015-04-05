class CJPeerError(StandardError):
    pass


class MessageChannel(object):
    '''
	Abstract class which implements a way for bots to communicate
	'''

    def __init__(self):
        #all
        self.on_welcome = None
        self.on_set_topic = None
        self.on_connect = None
        self.on_disconnect = None
        self.on_nick_leave = None
        self.on_nick_change = None
        #orderbook watch functions
        self.on_order_seen = None
        self.on_order_cancel = None
        #taker functions
        self.on_error = None
        self.on_pubkey = None
        self.on_ioauth = None
        self.on_sig = None
        #maker functions
        self.on_orderbook_requested = None
        self.on_order_fill = None
        self.on_seen_auth = None
        self.on_seen_tx = None

    def run(self):
        pass

    def shutdown(self):
        pass

    def send_error(self, nick, errormsg):
        pass

    #callbacks for everyone
    #some of these many not have meaning in a future channel, like bitmessage
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

    #orderbook watcher commands
    def register_orderbookwatch_callbacks(self,
                                          on_order_seen=None,
                                          on_order_cancel=None):
        self.on_order_seen = on_order_seen
        self.on_order_cancel = on_order_cancel

    def request_orderbook(self):
        pass

    #taker commands
    def register_taker_callbacks(self,
                                 on_error=None,
                                 on_pubkey=None,
                                 on_ioauth=None,
                                 on_sig=None):
        self.on_error = on_error
        self.on_pubkey = on_pubkey
        self.on_ioauth = on_ioauth
        self.on_sig = on_sig

    def fill_orders(self, nickoid_dict, cj_amount, taker_pubkey):
        pass

    def send_auth(self, nick, pubkey, sig):
        pass

    def send_tx(self, nick_list, txhex):
        pass

    #maker commands
    def register_maker_callbacks(self,
                                 on_orderbook_requested=None,
                                 on_order_fill=None,
                                 on_seen_auth=None,
                                 on_seen_tx=None):
        self.on_orderbook_requested = on_orderbook_requested
        self.on_order_fill = on_order_fill
        self.on_seen_auth = on_seen_auth
        self.on_seen_tx = on_seen_tx

    def announce_orders(self, orderlist, nick=None):
        pass  #nick=None means announce publicly

    def cancel_orders(self, oid_list):
        pass

    def send_pubkey(self, nick, pubkey):
        pass

    def send_ioauth(self, nick, utxo_list, cj_pubkey, change_addr, sig):
        pass

    def send_sigs(self, nick, sig_list):
        pass
