
import re
from optparse import OptionParser

parser = OptionParser(
    usage=
    'usage: %prog [options] [log file]',
    description='Removes all private information from JoinMarket log files' +
    ' so that they can be shared for debugging reasons')
parser.add_option('-e',
    '--ending',
    action='store',
    type='string',
    dest='ending',
    default='scrubbed',
    help='string to add to the filename of the destination log file')
parser.add_option(
    '--testnet',
    action='store_true',
    dest='testnet',
    default=False,
    help='Use testnet (addresses start with (n or m or 2) instaed of (1 or 3)')

(options, args) = parser.parse_args()
if len(args) < 1:
    parser.error('Needs a wallet file')
    sys.exit(0)

filename = args[0]
fd = open(filename)
logfile = fd.read()
fd.close()

#address pattern
#0OIl
#zero capital-O capital-I lowercase-l
#addresses have 26-35 characters, from https://en.bitcoin.it/wiki/Address

#each pattern is
#(regex match, callback function for replacement, name, flags[optional])
#callback function for replacement can have format strings that get replaced with the replacement count
#try to not make them depend on each other or the order they are run in 
patterns = [
    ('(\W)([' + ('1|3' if not options.testnet else 'n|m|2') + ']{1}[1-9A-HJ-NP-Za-km-z]{25,34})(\W)',
    lambda m: m.group(1) + '1ADDRESS_%023d' + m.group(3),
    'addresses'),
    ('^\d+-\d+-\d+ \d+:\d+:\d+,\d+',
    lambda m: 'TIMESTAMP_%013d',
    'timestamps', re.MULTILINE),
    ('(\W)([0-9a-fA-F]{64}):(\d+)(\W)',
    lambda m: m.group(1) + 'TXID_INDEX_%056d' + m.group(4),
    'txid:index'),
    ('(gettxout \\[u?\')([0-9a-fA-F]{64}\', \d+)(, (True|False)\\])',
    lambda m: m.group(1) + 'TXID_%059d\', IDX_%03d' +  m.group(3),
    'gettxout'),
    ('(\'value\': )(\d+)(\\})',
    lambda m: m.group(1) + 'VALUE_%010d' + m.group(3),
    'value amounts'),
    ('(\W)(76a914[0-9a-fA-f]{40}88ac)(\W)',
    lambda m: m.group(1) + 'SCRIPT_%043d' + m.group(3),
    'p2pkh scripts'),
    ('(\\{\'hash\': \')([0-9a-fA-F]{64})(\',\s*\'index\': )(\d+)',
    lambda m: m.group(1) + 'INPUT_TXID_%053d' + m.group(3) + 'IDX_%03d',
    'tx inputs'),
    ('(cmd=tx msg=)([0-9a-zA-Z/+=]+)',
    lambda m: m.group(1) + 'TXBASE64_' + '+'.join(['0'*40]*(len(m.group(2))/40-2)) + '%010d',
    'base64 encoded transactions'),
    ('(getrawtransaction \\[\')([0-9a-fA-F]{64})(\'\\])',
    lambda m: m.group(1) + 'RAW_TXID_%055d' + m.group(3),
    'getrawtransaction TXIDs'),
    ('(txid = )([0-9a-fA-F]{64})',
    lambda m: m.group(1) + 'SEND_TXID_%054d',
    'generated TXIDs'),
    ('^[0-9a-fA-F]{80,}$',
    lambda m: 'TXHEX_%010d_' + '+'.join(['0'*40]*(len(m.group(0))/40-2)),
    'tx hexes', re.MULTILINE),
    ('(sendrawtransaction \\[\')([0-9a-fA-F]{80,})(\'\\])',
    lambda m: m.group(1) + 'SENT_RAW_TX_%010d_' + '+'.join(['0'*40]*(len(m.group(0))/40-2)),
    'sendrawtransactions'),
    ('(txid=)([0-9a-fA-F]{64})( not being listened for)',
    lambda m: m.group(1) + 'REJECTED_TXID_%051d' + m.group(3),
    'rejected transactions'),
    ('(message=!sig )([0-9a-zA-Z/+=]+)',
    lambda m: m.group(1) + 'SIG_BASE64_%010d_' + ('0'*30 + '+')*4,
    'base64 encoded signatures'),
    ('(coinjoining )(\d+)( satoshi)',
    lambda m: m.group(1) + 'CJING_AMT_%05d' + m.group(3),
    'coinjoining amounts'),
    ('(choosing sweep orders for total_input_value = )(\d+)',
    lambda m: m.group(1) + 'SCJ_AMT_%05d',
    'sweep amount'),
    ('(cj amount = )(\d+)',
    lambda m: m.group(1) + 'CJ_AMT_%05d',
    'sweep coinjoin amount'),
    ('(rel/abs average fee = )(0\\.\d+ / [\d\\.{1}]+)',
    lambda m: m.group(1) + 'REL_FEE_%05d / ABS_FEE_%05d',
    'average fees'),
    ('(cmd=fill msg=\d+ )(\d+)',
    lambda m: m.group(1) + 'FILL_AMT_%05d',
    'fill messages'),
    ('(totalin=)(\d+)( cjamount=)(\d+)( txfee=)(\d+)( realcjfee=)(\d+)',
    lambda m: ''.join(['AMT_%05d' if i%2 == 0 else m.group(i) for i in range(1, 9)]),
    'summary amounts'),
    ('(totalin=)(\d+)( my_txfee=)(\d+)( makers_txfee=)(\d+)( cjfee_total=)(\d+)( => changevalue=)(\d+)',
    lambda m: ''.join(['MY_AMT_%05d' if i%2 == 0 else m.group(i) for i in range(1, 11)]),
    'my summary amounts'),
    ('(message=!ioauth \S+ )([0-9a-fA-F]{66})',
    lambda m: m.group(1) + 'CJ_PUBKEY_%056d',
    'coinjoin pubkeys'),
    ('(totalcjfee=)(\d+)',
    lambda m: m.group(1) + 'FEE_%05d',
    'total coinjoin fees'),
    ('(total estimated amount spent = )(\d+)',
    lambda m: m.group(1) + 'EST_AMT_%05d',
    'estimated amounts'),
    ('(amount=)(\d+)( selected)',
    lambda m: m.group(1) + 'MAMT_%05d' + m.group(3),
    'amounts selected'),
    ('(coinjoin of amount )(\d+)',
    lambda m: m.group(1) + 'CJ_OF_AMT_%05d',
    'coinjoins of amount'),
]

class DummyMatch:
    def group(self, i):
        return ''

counter = dict([(p[2], 0) for p in patterns])
current_pattern = None
def sub_func(m):
    counter[current_pattern[2]] += 1
    format_args = (counter[current_pattern[2]],) * current_pattern[1](DummyMatch()).count('%')
    return current_pattern[1](m) % format_args

for p in patterns:
    current_pattern = p
    p_flags = p[3] if len(p) > 3 else 0
    logfile = re.sub(p[0], sub_func, logfile, flags=p_flags)

print 'replaced patterns:\n' + '\n'.join([str(counter[p[2]]) + ' ' + p[2] for p in patterns])

##old obselete method, keep the code as it might be useful
## for thinking about how to do it
'''
use_old_address_matching_method = False
if use_old_address_matching_method:
    addr_prefix = '1|3' if not testnet else 'n|m|2'
    addr_pattern = '(\W)([' + addr_prefix + ']{1}[1-9A-HJ-NP-Za-km-z]{25,34})(\W)'

    distinguishable_addr = False
    if distinguishable_addr:
        addr_match_objs = re.finditer(addr_pattern, logfile)
        addr_set = set((m.group(2) for m in addr_match_objs))
        #print 'start, matches found: ' + str(len(addr_matches))
        addr_placeholder_map = {}
        for addr_i, addr in enumerate(addr_set):
            addr_placeholder_map[addr] = '1ADDRESS_PLACEHOLDER_%013d' % (addr_i)

    addr_count = [0]
    def replace_addresses(m):
        addr_count[0] += 1
        if distinguishable_addr:
            return m.group(1) + addr_placeholder_map[m.group(2)] + m.group(3)
        else:
            return m.group(1) + '1ADDRESS_%023d' % (addr_count[0]) + m.group(3)

    logfile = re.sub(addr_pattern, replace_addresses, logfile)
'''

scrubbed_name = filename.replace('.', '.' + options.ending + '.')
fd = open(scrubbed_name, 'w')
fd.write(logfile)
fd.close()
print 'saved to ' + scrubbed_name
