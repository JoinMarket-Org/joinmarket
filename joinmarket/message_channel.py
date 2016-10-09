import base64, abc, threading, time, hashlib, os, binascii
from joinmarket.enc_wrapper import encrypt_encode, decode_decrypt
from joinmarket.support import get_log, chunks
from joinmarket.configure import jm_single
import bitcoin as btc

from functools import wraps
COMMAND_PREFIX = '!'
JOINMARKET_NICK_HEADER = 'J'
NICK_HASH_LENGTH = 10
NICK_MAX_ENCODED = 14 #comes from base58 expansion; recalculate if above changes

encrypted_commands = ["auth", "ioauth", "tx", "sig"]
plaintext_commands = ["fill", "error", "pubkey", "orderbook", "push"]
plaintext_commands += jm_single().ordername_list
plaintext_commands += jm_single().commitment_broadcast_list

log = get_log()

class CJPeerError(StandardError):
    pass


class MChannelThread(threading.Thread):
    def __init__(self, mc):
        threading.Thread.__init__(self, name='MCThread')
        self.daemon = True
        self.mc = mc

    def run(self):
        self.mc.run()

class MessageChannelCollection(object):
    """Class which encapsulates a set of
    message channels. Maintains state about active
    connections to counterparties, and state of
    encapsulated message channel instances.
    Public messages are broadcast over all available
    channels, while privmsgs with one counterparty are
    "locked" to the channel on which they are initiated,
    although bear in mind they need not be the same for
    both sides of the conversation.
    In the current joinmarket protocol, this "lock" 
    is set at the time of the !reloffer (etc) privmsg or
    pubmsg from the maker.
    Note that MessageChannel implementations must support
    asynchronous messaging (adding to Queue.Queue objects,
    which are thread safe, e.g.)
    Callback chain is in some cases extended with an extra
    layer, e.g. to manage a "connected" state across all
    encapsulated message channels.
    """
    
    def check_privmsg(func):
        """decorator to check if private messages
        are correctly activated
        """
        @wraps(func)
        def func_wrapper(inst, *args, **kwargs):
            cp = args[0]
            if cp in inst.active_channels:
                return func(inst, *args, **kwargs)
            else:
                for mc in inst.available_channels():
                    #nicks_seen[mc] guaranteed to exist
                    #from constructor
                    if cp in inst.nicks_seen[mc]:
                        log.debug("Dynamic switch nick: " + cp)
                        inst.active_channels[cp] = mc
                        #early return on first success;
                        #means that we assume that if we have
                        #ever seen a message from this counterparty
                        #on one messagechannel which is currently active,
                        #we assume it's still
                        #available. Of course, this is optimistic,
                        #but still much better to do this than to
                        #immediately give up when any one connection
                        #is broken.
                        return func(inst, *args, **kwargs)
                #Failure to send is a critical error for a transaction,
                #but should not kill the bot. So, we don't raise an
                #exception, but rather allow sending to continue, which
                #should usually result in tx completion just timing out.
                log.warn("Couldn't find a route to send privmsg")
                log.warn("For counterparty: " + str(cp))
        return func_wrapper

    def __init__(self, mchannels):
        self.mchannels = mchannels
        #To keep track of chosen channels
        #for private messaging counterparties.
        self.active_channels = {}
        #To keep track of message channel status;
        #0: not started 1: started 2: failed/broken/inactive
        self.mc_status = dict([(x, 0) for x in self.mchannels])
        #To keep track of counterparties having at least once
        #made their presence known on a channel
        self.nicks_seen = {}
        for mc in self.mchannels:
            self.nicks_seen[mc] = set()
            #callback to mark nicks as seen when they privmsg
            mc.on_privmsg_trigger = self.on_privmsg
        #keep track of whether we want to deliberately
        #shut down the connections
        self.give_up = False
        #only allow on_welcome() to fire once.
        self.welcomed = False
        #control access
        self.mc_lock = threading.Lock()
        #Create an ephemeral keypair for the duration
        #of this run, same across all message channels,
        #and set the nickname for all message channels using it.
        self.nick_priv = hashlib.sha256(os.urandom(16)).hexdigest() + '01'
        self.nick_pubkey = btc.privtopub(self.nick_priv)
        self.nick_pkh_raw = hashlib.sha256(self.nick_pubkey).digest()[
            :NICK_HASH_LENGTH]
        self.nick_pkh = btc.changebase(self.nick_pkh_raw, 256, 58)
        #right pad to maximum possible; b58 is not fixed length.
        #Use 'O' as one of the 4 not included chars in base58.
        self.nick_pkh += 'O' * (NICK_MAX_ENCODED - len(self.nick_pkh))
        #The constructed length will be 1 + 1 + NICK_MAX_ENCODED
        self.nick = JOINMARKET_NICK_HEADER + str(
            jm_single().JM_VERSION) + self.nick_pkh
        jm_single().nickname = self.nick
        for mc in self.mchannels:
            mc.set_nick(self.nick, self.nick_priv, self.nick_pubkey)

    def available_channels(self):
        return [x for x in self.mchannels if self.mc_status[x]==1]

    def unavailable_channels(self):
        return [x for x in self.mchannels if self.mc_status[x] != 1]

    def flush_nicks(self):
        """Any message channel which is not
        active must wipe any state information on peers
        connected for that message channel. If a peer is
        available on another chan, switch the active_channel
        for that nick to (an)(the) other, to make failure
        to communicate as unlikely as possible.
        """
        for mc in self.unavailable_channels():
            self.nicks_seen[mc] = set()
            ac = self.active_channels
            for peer in [x for x in ac if ac[x] == mc]:
                for mc2 in self.available_channels():
                    if peer in self.nicks_seen[mc2]:
                        log.debug("Dynamically switching: " + peer + " to: " + \
                                  str(mc2.serverport))
                        self.active_channels[peer] = mc2
                        break
            #Remove all entries for the newly unavailable channel
            self.active_channels = dict([(a, ac[a]) for a in ac if ac[a] != mc])

    def set_cjpeer(self, cjpeer):
        for mc in self.mchannels:
            mc.cjpeer = cjpeer

    def add_channel(self, mchannel):
        """TODO Not currently in use,
        may be some issues with intialization.
        """
        if mchannel not in self.mchannels:
            self.mc_status[mc] = 0
            self.nicks_seen[mc] = set()
        self.mchannels += mchannel
        self.mchannels = list(set(self.mchannels))

    def see_nick(self, nick, mc):
        with self.mc_lock:
            self.nicks_seen[mc].add(nick)

    def unsee_nick(self, nick, mc):
        with self.mc_lock:
            self.nicks_seen[mc] = self.nicks_seen[mc].difference(set([nick]))

    def run(self, failures=None):
        """At the moment this is effectively a
        do-nothing main loop. May be suboptimal.
        For now it allows us to receive the
        shutdown() signal for all message channels
        and propagate it.
        Additionally, for testing, a parameter 'failures'
        may be passed, a tuple (type, message channel index, count)
        which will perform a connection shutdown of type type
        after iteration count count on message channel
        self.mchannels[channel index].
        """
        for mc in self.mchannels:
            MChannelThread(mc).start()
        i = 0
        while True:
            time.sleep(1)
            i += 1
            if self.give_up:
                log.info("Shutting down all connections")
                break
            #feature only used for testing:
            #deliberately shutdown a connection at a certain time.
            #TODO may not be sufficiently deterministic.
            if failures and i==failures[2]:
                if failures[0] == 'break':
                    self.mchannels[failures[1]].close()
                elif failures[0] == 'shutdown':
                    self.mchannels[failures[1]].shutdown()
                else:
                    raise NotImplementedError("Failure injection type unknown")

    #UNCONDITIONAL PUBLIC/BROADCAST: use all message
    #channels for these functions.
    
    def shutdown(self):
        """Stop the main loop of the message channel,
        shutting down subsidiary resources gracefully.
        Note that unexpected disconnections MUST be
        handled by the implementation itself (restarting
        as appropriate).
        """
        for mc in self.available_channels():
            mc.shutdown()
        self.give_up = True

    def pubmsg(self, msg):
        """Send a message onto the shared, public
        channels (the joinmarket pit).
        """
        for mc in self.available_channels():
            mc.pubmsg(msg)

    def cancel_orders(self, oid_list):
        for mc in self.available_channels():
            mc.cancel_orders(oid_list)

    # OrderbookWatch callback
    def request_orderbook(self):
        for mc in self.available_channels():
            mc.request_orderbook()

    #END PUBLIC/BROADCAST SECTION

    def privmsg(self, nick, cmd, message, mc=None):
        """Send a message to a specific counterparty,
        either specifying a single message channel, or
        allowing it to be deduced from self.active_channels dict
        """
        if mc is not None:
            if mc not in self.available_channels():
                #raise because implies logic error
                raise Exception(
                    "Tried to privmsg on an unavailable message channel.")
            else:
                mc.privmsg(nick, cmd, message)
                return
        if nick in self.active_channels:
            self.active_channels[nick].privmsg(nick, cmd, message)
            return
        else:
            log.warn("Failed to send message to: " + str(nick) + \
                          "; cannot find on any message channel.")
            return

    def announce_orders(self, orderlist, nick=None, new_mc=None):
        """Send orders defined in list orderlist either
        to the shared public channel (pit), on all
        message channels, if nick=None,
        or to an individual counterparty nick, as
        privmsg, on a specific mc.
        """
        order_keys = ['oid', 'minsize', 'maxsize', 'txfee', 'cjfee']
        orderlines = []
        for order in orderlist:
            orderlines.append(COMMAND_PREFIX + order['ordertype'] + \
                    ' ' + ' '.join([str(order[k]) for k in order_keys]))
        if new_mc is not None and new_mc not in self.available_channels():
            log.info(
                "Tried to announce orders on an unavailable message channel.")
            return
        if nick is None:
            for mc in self.available_channels():
                mc.announce_orders(orderlines)
        else:
            #we are sending to one cp, so privmsg
            #in order to use privmsg, we must set "cmd" to be the first command
            #in the first orderline, and the rest are treated like a message.
            cmd = orderlist[0]['ordertype']
            msg = ' '.join(orderlines[0].split(' ')[1:])
            msg += ''.join(orderlines[1:])
            if new_mc:
                self.privmsg(nick, cmd, msg, new_mc)
            else:
                for mc in self.available_channels():
                    if nick in self.nicks_seen[mc]:
                        self.privmsg(nick, cmd, msg, mc)

    @check_privmsg
    def send_pubkey(self, nick, pubkey):
        self.active_channels[nick].privmsg(nick, 'pubkey', pubkey)

    @check_privmsg
    def send_ioauth(self, nick, utxo_list, auth_pub, cj_addr, change_addr, sig):
        self.active_channels[nick].send_ioauth(nick, utxo_list, auth_pub,
                                         cj_addr, change_addr, sig)

    @check_privmsg
    def send_sigs(self, nick, sig_list):
        self.active_channels[nick].send_sigs(nick, sig_list)

    # Taker callbacks
    def fill_orders(self, nick_order_dict, cj_amount, taker_pubkey,
                    commitment):
        """
        The orders dict does not contain information
        about which message channel the counterparty bots are active
        on; this can be hacked-around by including that information
        in the order data, but this is highly undesirable, partly
        architecturally (the joinmarket business logic has no business
        knowing about the message channel), and partly because it
        would break backwards compatibility.
        So, we use a trigger in on_order_seen and assume that it
        makes sense to set the active_channel for that nick to the one
        it was last seen active on.
        """
        for mc in self.available_channels():
            filtered_nick_order_dict = {k:v for k,v in nick_order_dict.iteritems(
                ) if mc == self.active_channels[k]}
            mc.fill_orders(filtered_nick_order_dict, cj_amount, taker_pubkey,
                           commitment)

    @check_privmsg
    def send_auth(self, nick, cr):
        self.active_channels[nick].send_auth(nick, cr)

    @check_privmsg
    def send_error(self, nick, errormsg):
        #TODO this might need to support non-active nicks TODO
        self.active_channels[nick].send_error(nick, errormsg)

    @check_privmsg
    def push_tx(self, nick, txhex):
        #TODO supporting sending to arbitrary nicks
        #adds quite a bit of complexity, not supported
        #initially; will fail if nick is not part of TX
        self.active_channels[nick].push_tx(nick, txhex)

    def send_tx(self, nick_list, txhex):
        """Push out the transaction to nicks
        in groups by their message channel.
        """
        tx_nick_sets = {}
        for nick in nick_list:
            if nick not in self.active_channels:
                #This could be a fatal error for a transaction,
                #but might not be for the bot (tx recreation etc.)
                #TODO look for another channel via nicks_seen.
                #Rare case so not a high priority.
                log.info(
                    "Cannot send transaction to nick, not active: " + nick)
                return
            if self.active_channels[nick] not in tx_nick_sets:
                tx_nick_sets[self.active_channels[nick]] = [nick]
            else:
                tx_nick_sets[self.active_channels[nick]].append(nick)
        for mc, nl in tx_nick_sets.iteritems():
            mc.send_tx(nl, txhex)

    #CALLBACKS REGISTRATION SECTION

    # taker commands
    def register_taker_callbacks(self,
                                 on_error=None,
                                 on_pubkey=None,
                                 on_ioauth=None,
                                 on_sig=None):
        for mc in self.mchannels:
            mc.register_taker_callbacks(on_error,
                                        on_pubkey,
                                        on_ioauth,
                                        on_sig)

    def on_connect_trigger(self, mc):
        """Mark the specified message channel
        as (re) connected.
        """
        self.mc_status[mc] = 1

    def on_disconnect_trigger(self, mc):
        """Mark the specified message channel as
        disconnected. Track loss of private connections
        to individual nicks. If no message channels are
        now connected, fire on_disconnect to calling code.
        """
        self.mc_status[mc] = 2
        self.flush_nicks()
        log.debug("On disconnect fired, nicks_seen is now: " + str(self.nicks_seen))
        if not any([x==1 for x in self.mc_status.values()]):
            if self.on_disconnect:
                self.on_disconnect()

    def on_welcome_trigger(self, mc):
        """Update status of specified message channel
        as connected. If all required message channels
        are initialized (not state 0), fire the
        on_welcome() event to calling code to signal
        that processing can start.
        This is wrapped with a lock as can be fired by
        message channel child threads.
        """
        with self.mc_lock:
            if self.welcomed:
                return
            #This trigger indicates successful login
            #so we update status.
            self.mc_status[mc] = 1
            #This way broadcasts orders or requests ONCE to ALL mchans
            #which are actually available.
            if not any([x == 0 for x in self.mc_status.values()]):
                if self.on_welcome:
                    self.on_welcome()
                self.welcomed = True

    def on_nick_leave_trigger(self, nick, mc):
        """If a nick leaves one message channel,
        and we are currently talking to it on that
        channel, attempt to dynamically switch to
        another channel on which it has been seen.
        If we are currently talking to it on a different
        channel, we ignore the signal, since it shouldn't
        interrupt processing.
        If we are not currently talking to it at all,
        just call on_nick_leave (which currently does nothing).
        """

        #mark the nick as 'unseen' on that channel
        self.unsee_nick(nick, mc)
        if nick not in self.active_channels:
            if self.on_nick_leave:
                self.on_nick_leave(nick)
        elif self.active_channels[nick] == mc:
            del self.active_channels[nick]
            #Attempt to dynamically switch channels
            #Is the nick available on another channel?
            other_channels = [x for x in self.available_channels() if x != mc]
            if len(other_channels) == 0:
                log.warn(
                    "Cannot reconnect to dropped nick, no connections available.")
                if self.on_nick_leave:
                    self.on_nick_leave(nick)
                return
            for oc in other_channels:
                if nick in self.nicks_seen[oc]:
                    log.debug("Found a new channel, setting to: " + nick + \
                              "," + str(oc.serverport))
                    self.active_channels[nick] = oc
                    #Note we don't call on_nick_leave in this case
                    return
            #If loop completed without success, we failed to find
            #this counterparty anywhere else
            log.debug("Nick: " + nick + " has left.")
            if self.on_nick_leave:
                self.on_nick_leave(nick)
        #The remaining case is if the channel that the
        #nick has left is not the one we're currently using.
        return

    def register_channel_callbacks(self,
                                   on_welcome=None,
                                   on_set_topic=None,
                                   on_connect=None,
                                   on_disconnect=None,
                                   on_nick_leave=None,
                                   on_nick_change=None):
        """Special cases:
        on_welcome: we maintain it
        in this class, since we only want to trigger arrival
        when all channels are joined, not multiple times, then
        broadcast whatever it is we want to broadcast on arrival.

        on_nick_leave: this needs to be maintained in this class,
        since a nick only leaves the pit when it has departed *all* our
        message channels.

        on_nick_change: a bot which changes its nick on one channel
        must also successfully change its nick on all channels, or quit.

        on_disconnect: must be maintained here; if a bot disconnects
        only one it must remain viable, otherwise this has no point!

        on_connect: must reset the message channel status to connected.
        """
        self.on_welcome = on_welcome
        self.on_disconnect = on_disconnect
        self.on_nick_leave = on_nick_leave
        self.on_connect = on_connect
        self.on_nick_change = on_nick_change
        for mc in self.mchannels:
            mc.register_channel_callbacks(self.on_welcome_trigger,
                                          on_set_topic,
                                          self.on_connect_trigger,
                                          self.on_disconnect_trigger,
                                          self.on_nick_leave_trigger,
                                          self.on_nick_change_trigger,
                                          self.see_nick)

    def on_nick_change_trigger(self, new_nick):
        """If any underlying messagechannel object fails to register
        a nick/username, trigger all of them to change to the newly
        chosen nick/user.
        """
        for mc in self.available_channels():
            mc.change_nick(new_nick)
        if self.on_nick_change:
            self.on_nick_change(new_nick)

    def on_order_seen_trigger(self, mc, counterparty, oid, ordertype, minsize,
                              maxsize, txfee, cjfee):
        """This is the entry point into private messaging.
        Hence, it fixes for the rest of the conversation, which
        message channel the bots are going to communicate over
        (privately).
        Use the orderbook update as a signal that this counterparty (nick)
        is present on this message channel, before passing to calling code.
        Note that this will get called at least once per message channel,
        so it will simply end up setting the active channel to the last one
        that arrives.
        """
        #Note that the counterparty will be added to the set for *each*
        #message channel where it has published an order (priv or pub),
        #so that we can hope to contact it at any one of those mcs.
        self.nicks_seen[mc].add(counterparty)

        self.active_channels[counterparty] = mc
        if self.on_order_seen:
            self.on_order_seen(counterparty, oid, ordertype, minsize, maxsize,
                           txfee, cjfee)

    # orderbook watcher commands
    def register_orderbookwatch_callbacks(self,
                                          on_order_seen=None,
                                          on_order_cancel=None):
        """Special cases:
        on_order_seen: use it as a trigger for presence of nick.
        on_order_cancel: what happens if cancel/modify in one place
        but not another? TODO
        """
        self.on_order_seen = on_order_seen
        for mc in self.mchannels:
            mc.register_orderbookwatch_callbacks(self.on_order_seen_trigger,
                                                 on_order_cancel)

    def on_orderbook_requested_trigger(self, nick, mc):
        """Update nicks_seen state to reflect presence of
        taker on this message channel before pass-through.
        """
        self.see_nick(nick, mc)
        if self.on_orderbook_requested:
            self.on_orderbook_requested(nick, mc)

    # maker commands
    def register_maker_callbacks(self,
                                 on_orderbook_requested=None,
                                 on_order_fill=None,
                                 on_seen_auth=None,
                                 on_seen_tx=None,
                                 on_push_tx=None,
                                 on_commitment_seen=None,
                                 on_commitment_transferred=None):
        """Special cases:
        on_orderbook_requested must trigger addition to the nicks_seen
        database, so that makers can know that a taker is in principle
        available on this message channel.
        """
        self.on_orderbook_requested = on_orderbook_requested
        for mc in self.mchannels:
            mc.register_maker_callbacks(self.on_orderbook_requested_trigger,
                                        on_order_fill,
                                        on_seen_auth,
                                        on_seen_tx,
                                        on_push_tx,
                                        on_commitment_seen,
                                        on_commitment_transferred)

    def on_privmsg(self, nick, mchan):
        """Registered as a callback for all mchannels:
        set the nick as seen on privmsg, as it may not
        be triggered if it doesn't issue a pubmsg.
        """
        if mchan in self.available_channels():
            self.see_nick(nick, mchan)
        #Should not be reached; but in weird case that the channel
        #is not available, there is nothing to do.

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
        self.on_pubmsg_trigger = None
        self.on_privmsg_trigger = None
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

        self.cjpeer = None
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

    @abc.abstractmethod
    def change_nick(self, new_nick):
        """Change the nick/username for this message channel
        instance to new_nick
        """

    """END OF SUBCLASS IMPLEMENTATION SECTION"""

    def set_nick(self, nick, nick_priv, nick_pubkey):
        self.given_nick = nick
        self.nick = self.given_nick
        self.nick_priv = nick_priv
        self.nick_pubkey = nick_pubkey

    def register_channel_callbacks(self,
                                   on_welcome=None,
                                   on_set_topic=None,
                                   on_connect=None,
                                   on_disconnect=None,
                                   on_nick_leave=None,
                                   on_nick_change=None,
                                   on_pubmsg_trigger=None):
        self.on_welcome = on_welcome
        self.on_set_topic = on_set_topic
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_nick_leave = on_nick_leave
        self.on_nick_change = on_nick_change
        #Fire to MCcollection to mark nicks as "seen"
        self.on_pubmsg_trigger = on_pubmsg_trigger

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
                                 on_push_tx=None,
                                 on_commitment_seen=None,
                                 on_commitment_transferred=None):
        self.on_orderbook_requested = on_orderbook_requested
        self.on_order_fill = on_order_fill
        self.on_seen_auth = on_seen_auth
        self.on_seen_tx = on_seen_tx
        self.on_push_tx = on_push_tx
        self.on_commitment_seen = on_commitment_seen
        self.on_commitment_transferred = on_commitment_transferred

    def announce_orders(self, orderlines):
        self._announce_orders(orderlines)

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
                    self.on_order_seen(self, counterparty, oid, ordertype, minsize,
                                       maxsize, txfee, cjfee)
            except IndexError as e:
                log.debug(e)
                log.debug('index error parsing chunks, possibly malformed'
                          'offer by other party. No user action required.')
                # TODO what now? just ignore iirc
            finally:
                return True
        return False
    
    def check_for_commitments(self, nick, _chunks, private=False):
        """If a commitment message is found in a pubmsg, trigger
        callback on_commitment_seen, if as a privmsg, trigger
        callback on_commitment_transferred. These callbacks are (for now)
        only used by Makers.
        """
        if _chunks[0] in jm_single().commitment_broadcast_list:
            try:
                counterparty = nick
                commitment = _chunks[1]
                if private:
                    if self.on_commitment_transferred:
                        self.on_commitment_transferred(counterparty, commitment)
                else:
                    if self.on_commitment_seen:
                        self.on_commitment_seen(counterparty, commitment)
            except IndexError as e:
                log.debug(e)
                log.debug('index error parsing chunks, possibly malformed'
                          'offer by other party. No user action required.')
            finally:
                return True
        return False

    def cancel_orders(self, oid_list):
        clines = [COMMAND_PREFIX + 'cancel ' + str(oid) for oid in oid_list]
        self.pubmsg(''.join(clines))

    def send_pubkey(self, nick, pubkey):
        self.privmsg(nick, 'pubkey', pubkey)

    def send_ioauth(self, nick, utxo_list, auth_pub, cj_addr, change_addr, sig):
        authmsg = str(','.join(utxo_list)) + ' ' + ' '.join([auth_pub,
                                            cj_addr, change_addr, sig])
        self.privmsg(nick, 'ioauth', authmsg)

    def send_sigs(self, nick, sig_list):
        # TODO make it send the sigs on one line if there's space
        for s in sig_list:
            self.privmsg(nick, 'sig', s)

    # OrderbookWatch callback
    def request_orderbook(self):
        self.pubmsg(COMMAND_PREFIX + 'orderbook')

    # Taker callbacks
    def fill_orders(self, nick_order_dict, cj_amount, taker_pubkey, commitment):
        for c, order in nick_order_dict.iteritems():
            msg = str(order['oid']) + ' ' + str(cj_amount) + ' ' + taker_pubkey
            msg += ' ' + commitment
            self.privmsg(c, 'fill', msg)

    def send_auth(self, nick, cr):
        self.privmsg(nick, 'auth', str(cr))

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
        log.info('error<%s> : %s' % (nick, errormsg))
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

        #Anti-replay measure: append the message channel identifier
        #to the signature; this prevents cross-channel replay but NOT
        #same-channel replay (in case of snooper after dropped connection
        #on this channel).
        msg_to_be_signed = message + str(self.hostid)

        sig = btc.ecdsa_sign(msg_to_be_signed, self.nick_priv)
        message += ' ' + self.nick_pubkey + ' ' + sig
        #forward to the implementation class (use single _ for polymrphsm to work)
        self._privmsg(nick, cmd, message)

    def on_pubmsg(self, nick, message):
        #Even illegal messages mark a nick as "seen"
        if self.on_pubmsg_trigger:
            self.on_pubmsg_trigger(nick, self)
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
            if self.check_for_commitments(nick, _chunks):
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
                    self.on_orderbook_requested(nick, self)
            else:
                # TODO this is for testing/debugging, should be removed, see taker.py
                if hasattr(self, 'debug_on_pubmsg_cmd'):
                    self.debug_on_pubmsg_cmd(nick, _chunks)

    def verify_nick(self, nick, sig, message):
        if not btc.ecdsa_verify(message + str(self.hostid), sig[1], sig[0]):
            log.debug("nick signature verification failed, ignoring.")
            return False
        #check that nick matches hash of pubkey
        nick_pkh_raw = hashlib.sha256(sig[0]).digest()[:NICK_HASH_LENGTH]
        nick_stripped = nick[2:2+NICK_MAX_ENCODED]
        #strip right padding
        nick_unpadded = ''.join([x for x in nick_stripped if x != 'O'])
        if not nick_unpadded == btc.changebase(nick_pkh_raw, 256, 58):
            log.debug("Nick hash check failed, expected: " + str(
                nick_unpadded) + ", got: " + str(
                    btc.changebase(nick_pkh_raw, 256, 58)))
            return False
        return True

    def on_privmsg(self, nick, message):
        """handles the case when a private message is received"""
        #Aberrant short messages should be handled by subclasses
        #in _privmsg, but this constitutes a sanity check. Note that
        #messages which use an encrypted_command but present no
        #ciphertext will be rejected with the ValueError on decryption.
        #Other ill formatted messages will be caught in the try block.
        if len(message) < 2:
            return

        if message[0] != COMMAND_PREFIX:
            log.debug('message not a cmd')
            return
        cmd_string = message[1:].split(' ')[0]
        if cmd_string not in plaintext_commands + encrypted_commands:
            log.debug('cmd not in cmd_list, line="' + message + '"')
            return
        #Verify nick ownership
        sig = message[1:].split(' ')[-2:]
        #reconstruct original message without cmd
        rawmessage = ' '.join(message[1:].split(' ')[1:-2])
        #sanity check that the sig was appended properly
        if len(sig) != 2 or len(rawmessage) == 0:
            log.debug("Sig not properly appended to privmsg, ignoring")
            return
        if not self.verify_nick(nick, sig, rawmessage):
            #This is an impostor; just ignore
            log.debug("Message received from unverified counterparty; ignoring")
            return

        #Marks the nick as active on this channel; note *only* if verified.
        #Otherwise squatter/attacker can persuade us to send privmsgs to him.
        if self.on_privmsg_trigger:
            self.on_privmsg_trigger(nick, self)
        #strip sig from message for processing, having verified
        message = " ".join(message[1:].split(" ")[:-2])
        for command in message.split(COMMAND_PREFIX):
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
                    auth_pub = _chunks[2]
                    cj_addr = _chunks[3]
                    change_addr = _chunks[4]
                    btc_sig = _chunks[5]
                    if self.on_ioauth:
                        self.on_ioauth(nick, utxo_list, auth_pub, cj_addr,
                                       change_addr, btc_sig)
                elif _chunks[0] == 'sig':
                    sig = _chunks[1]
                    if self.on_sig:
                        self.on_sig(nick, sig)

                # maker commands
                if self.check_for_commitments(nick, _chunks, private=True):
                    pass
                if _chunks[0] == 'fill':
                    try:
                        oid = int(_chunks[1])
                        amount = int(_chunks[2])
                        taker_pk = _chunks[3]
                        if len(_chunks) > 4:
                            commit = _chunks[4]
                        else:
                            commit = None
                    except (ValueError, IndexError) as e:
                        self.send_error(nick, str(e))
                    if self.on_order_fill:
                        self.on_order_fill(nick, oid, amount, taker_pk, commit)
                elif _chunks[0] == 'auth':
                    try:
                        cr = _chunks[1]
                    except (ValueError, IndexError) as e:
                        self.send_error(nick, str(e))
                    if self.on_seen_auth:
                        self.on_seen_auth(nick, cr)
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
