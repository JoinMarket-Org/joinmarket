class MessageChannel(object):
    '''
	Abstract class which implements a way for bots to communicate
	'''

    def run(self):
        pass

    def shutdown(self):
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
                                          on_orders_seen=None,
                                          on_orders_cancel=None):
        self.on_orders_seen = on_orders_seen
        self.on_orders_cancel = on_orders_cancel

    def request_orderbook(self):
        pass

    #taker commands
    def register_taker_callbacks(self,
                                 on_error=None,
                                 on_pubkey=None,
                                 on_ioauth=None,
                                 on_sigs=None):
        self.on_error = on_error
        self.on_pubkey = on_pubkey
        self.on_ioauth = on_ioauth
        self.on_sigs = on_sigs

    def fill_order(self, nick, oid, cj_amount, taker_pubkey):
        pass

    def send_auth(self, nick, pubkey, sig):
        pass

    def send_tx(self, nick, txhex):
        pass

    #maker commands
    def register_maker_callbacks(self,
                                 on_orderbook_requested=None,
                                 on_order_filled=None,
                                 on_seen_auth=None,
                                 on_seen_tx=None):
        self.on_orderbook_requested = on_orderbook_requested
        self.on_order_filled = on_order_filled
        self.on_seen_auth = on_seen_auth
        self.on_seen_tx = on_seen_tx

    def announce_orders(self, orderlist, nick=None):
        pass  #nick=None means announce publicly

    def cancel_orders(self, oid_list):
        pass

    def send_error(self, nick, errormsg):
        pass

    def send_pubkey(self, nick, pubkey):
        pass

    def send_ioauth(self, nick, utxo_list, cj_pubkey, change_addr, sig):
        pass

    def send_sigs(self, nick, sig_list):
        pass
