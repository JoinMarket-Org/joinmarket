
IRC Channel:
#joinmarket on irc.freenode.net
https://webchat.freenode.net/?channels=%23joinmarket

Bitcointalk thread:
https://bitcointalk.org/index.php?topic=919116.msg10096563

Subreddit:
www.reddit.com/r/joinmarket

Twitter:
www.twitter.com/joinmarket

Wiki page for more detailed articles:
https://github.com/chris-belcher/joinmarket/wiki

INSTALLING
0. You will need python 2.7
1. You will need libsodium installed
 Get it here: http://doc.libsodium.org/
 use this line to check it was installed correctly
 python lib/enc_wrapper.py
2. You will need slowaes installed for encrypting your wallet
 sudo pip install slowaes
3. you will need numpy 1.7 or later installed
4. (optional) matplotlib for displaying the graphs in orderbook-watcher

in the joinmarket.cfg configuration file, set
    network = mainnet
for the actual bitcoin mainnet

Read the wiki for more detailed articles on how to use
