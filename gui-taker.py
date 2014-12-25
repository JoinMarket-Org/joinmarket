from taker import *

import BaseHTTPServer, SimpleHTTPServer, threading
from decimal import Decimal

import io
import base64


def create_depth_graph(db):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return 'Install matplotlib to see graphs'
    fig = plt.figure()
    plt.plot(range(10), range(10))
    plt.grid()
    plt.title(
        'this graph shows nothing but there could be a graph about the orderbook here later')

    imbuf = io.BytesIO()
    fig.savefig(imbuf, format='png')
    b64 = base64.b64encode(imbuf.getvalue())
    return '<img src="data:image/png;base64,' + b64 + '" />'
    #fd = open('fig.png', 'wb')
    #fd.write(imbuf.getvalue())
    #fd.close()


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
        SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(
            self, request, client_address, base_server)

    def create_orderbook_table(self):
        result = ''
        rows = self.taker.db.execute('SELECT * FROM orderbook;').fetchall()
        for o in rows:
            result += '<tr>'
            order_keys_display = (
                ('ordertype', ordertype_display), ('counterparty', do_nothing),
                ('oid', order_str), ('cjfee', cjfee_display),
                ('txfee', satoshi_to_unit), ('minsize', satoshi_to_unit),
                ('maxsize', satoshi_to_unit))
            for key, displayer in order_keys_display:
                result += '<td>' + displayer(o[key], o) + '</td>'
            result += '</tr>'
        return len(rows), result

    def get_counterparty_count(self):
        counterparties = self.taker.db.execute(
            'SELECT DISTINCT counterparty FROM orderbook;').fetchall()
        return str(len(counterparties))

    def do_GET(self):
        #SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)
        #print 'httpd received ' + self.path + ' request'
        if self.path == '/':
            fd = open('orderbook.html', 'r')
            orderbook_fmt = fd.read()
            fd.close()
            ordercount, ordertable = self.create_orderbook_table()
            replacements = {
                'ORDERCOUNT': str(ordercount),
                'CPCOUNT': self.get_counterparty_count(),
                'ORDERTABLE': ordertable,
                'DEPTHGRAPH': create_depth_graph(self.taker.db)
            }
            orderbook_page = orderbook_fmt
            for key, rep in replacements.iteritems():
                orderbook_page = orderbook_page.replace(key, rep)

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Content-length', len(orderbook_page))
            self.end_headers()
            self.wfile.write(orderbook_page)


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


class GUITaker(Taker):

    def on_welcome(self):
        Taker.on_welcome(self)
        HTTPDThread(self).start()


def main():
    from socket import gethostname
    nickname = 'guitaker-' + btc.sha256(gethostname())[:6]

    print 'starting irc'
    taker = GUITaker()
    taker.run(HOST, PORT, nickname, CHANNEL)

    #create_depth_graph()


if __name__ == "__main__":
    main()
    print('done')
