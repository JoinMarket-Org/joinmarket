class MessageChannel(object):
    '''
	Abstract class which implements a way for bots to communicate
	'''

    def run(self):
        pass

    def shutdown(self):
        pass

    #orderbook watcher commands
    def register_orderbookwatch_callbacks(self,
                                          on_order_seen=None,
                                          on_order_cancel=None):
        pass

    def request_orderbook(self):
        pass

    #taker commands
    def register_taker_callbacks(self,
                                 on_error=None,
                                 on_pubkey=None,
                                 on_ioauth=None,
                                 on_sigs=None):
        pass

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
        pass

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
