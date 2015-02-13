import taker
from irclib import IRCMessageChannel
from common import *

import BaseHTTPServer, SimpleHTTPServer, threading
from decimal import Decimal

import io
import base64

tableheading = '''
<table>
 <tr>
  <th>Type</th>
  <th>Counterparty</th>
  <th>Order ID</th>
  <th>Fee</th>
  <th>Miner Fee Contribution</th>
  <th>Minimum Size</th>
  <th>Maximum Size</th>
 </tr>
'''

shutdownform = '<form action="shutdown" method="post"><input type="submit" value="Shutdown" /></form>'

shutdownpage = '<html><body><center><h1>Successfully Shut down</h1></center></body></html>'


def calc_depth_data(db, value):
    pass


def calc_order_size_data(db):
    return ordersizes


def create_size_histogram(db):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return 'Install matplotlib to see graphs'
    rows = db.execute('SELECT maxsize FROM orderbook;').fetchall()
    ordersizes = [r['maxsize'] / 1e8 for r in rows]

    fig = plt.figure()
    plt.hist(ordersizes, 30, histtype='bar', rwidth=0.8)
    plt.grid()
    #plt.title('Order size distribution')
    plt.xlabel('Order sizes / btc')
    plt.ylabel('Frequency')
    return get_graph_html(fig)


def get_graph_html(fig):
    imbuf = io.BytesIO()
    fig.savefig(imbuf, format='png')
    b64 = base64.b64encode(imbuf.getvalue())
    return '<img src="data:image/png;base64,' + b64 + '" />'


def do_nothing(arg, order):
    return arg


def ordertype_display(ordertype, order):
    ordertypes = {'absorder': 'Absolute Fee', 'relorder': 'Relative Fee'}
    return ordertypes[ordertype]


def cjfee_display(cjfee, order):
    if order['ordertype'] == 'absorder':
        return satoshi_to_unit(cjfee, order)
    elif order['ordertype'] == 'relorder':
        return str(float(cjfee) * 100) + '%'


def satoshi_to_unit(sat, order):
    return str(Decimal(sat) / Decimal(1e8))


def order_str(s, order):
    return str(s)


class OrderbookPageRequestHeader(SimpleHTTPServer.SimpleHTTPRequestHandler):

    def __init__(self, request, client_address, base_server):
        self.taker = base_server.taker
        self.base_server = base_server
        SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(
            self, request, client_address, base_server)

    def create_orderbook_table(self):
        result = ''
        rows = self.taker.db.execute('SELECT * FROM orderbook;').fetchall()
        for o in rows:
            result += ' <tr>\n'
            order_keys_display = (
                ('ordertype', ordertype_display), ('counterparty', do_nothing),
                ('oid', order_str), ('cjfee', cjfee_display),
                ('txfee', satoshi_to_unit), ('minsize', satoshi_to_unit),
                ('maxsize', satoshi_to_unit))
            for key, displayer in order_keys_display:
                result += '  <td>' + displayer(o[key], o) + '</td>\n'
            result += ' </tr>\n'
        return len(rows), result

    def get_counterparty_count(self):
        counterparties = self.taker.db.execute(
            'SELECT DISTINCT counterparty FROM orderbook;').fetchall()
        return str(len(counterparties))

    def do_GET(self):
        #SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)
        #print 'httpd received ' + self.path + ' request'
        pages = ['/', '/ordersize']
        if self.path not in pages:
            return
        fd = open('orderbook.html', 'r')
        orderbook_fmt = fd.read()
        fd.close()
        if self.path == '/':
            ordercount, ordertable = self.create_orderbook_table()
            replacements = {
                'PAGETITLE': 'Joinmarket Browser Interface',
                'MAINHEADING': 'Joinmarket Orderbook',
                'SECONDHEADING': (
                    str(ordercount) + ' orders found by ' +
                    self.get_counterparty_count() + ' counterparties'),
                'MAINBODY':
                shutdownform + tableheading + ordertable + '</table>\n'
            }
        elif self.path == '/ordersize':
            replacements = {
                'PAGETITLE': 'Joinmarket Browser Interface',
                'MAINHEADING': 'Order Sizes',
                'SECONDHEADING': 'Order Size Histogram',
                'MAINBODY': create_size_histogram(self.taker.db)
            }
        orderbook_page = orderbook_fmt
        for key, rep in replacements.iteritems():
            orderbook_page = orderbook_page.replace(key, rep)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(orderbook_page))
        self.end_headers()
        self.wfile.write(orderbook_page)

    def do_POST(self):
        if self.path == '/shutdown':
            self.taker.msgchan.shutdown()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(shutdownpage))
            self.end_headers()
            self.wfile.write(shutdownpage)
            self.base_server.__shutdown_request = True


class HTTPDThread(threading.Thread):

    def __init__(self, taker):
        threading.Thread.__init__(self)
        self.daemon = True
        self.taker = taker

    def run(self):
        hostport = ('localhost', 62601)
        httpd = BaseHTTPServer.HTTPServer(hostport, OrderbookPageRequestHeader)
        httpd.taker = self.taker
        print 'started http server, visit http://{0}:{1}/'.format(*hostport)
        httpd.serve_forever()


class GUITaker(taker.OrderbookWatch):

    def on_welcome(self):
        taker.OrderbookWatch.on_welcome(self)
        HTTPDThread(self).start()


def main():
    from socket import gethostname
    import bitcoin as btc
    nickname = 'guitaker-' + btc.sha256(gethostname())[:6]

    irc = IRCMessageChannel(nickname)
    taker = GUITaker(irc)
    print 'starting irc'
    irc.run()


if __name__ == "__main__":
    main()
    print('done')
