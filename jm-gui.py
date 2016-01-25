
'''
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''


import sys, base64, textwrap, re, datetime, os, math, json, logging
import Queue

from decimal import Decimal
from functools import partial
from collections import namedtuple

from PyQt4 import QtCore
from PyQt4.QtGui import *

import platform

if platform.system() == 'Windows':
    MONOSPACE_FONT = 'Lucida Console'
elif platform.system() == 'Darwin':
    MONOSPACE_FONT = 'Monaco'
else:
    MONOSPACE_FONT = 'monospace'

GREEN_BG = "QWidget {background-color:#80ff80;}"
RED_BG = "QWidget {background-color:#ffcccc;}"
RED_FG = "QWidget {color:red;}"
BLUE_FG = "QWidget {color:blue;}"
BLACK_FG = "QWidget {color:black;}"

import bitcoin as btc

from joinmarket import load_program_config, get_network, Wallet, encryptData, \
    get_p2pk_vbyte, jm_single, mn_decode, mn_encode, create_wallet_file, \
    validate_address, random_nick, get_log, IRCMessageChannel, \
    weighted_order_choose 

from sendpayment import SendPayment, PT
#https://gist.github.com/e000/869791
import socks
#from socksipyhandler import SocksiPyHandler

log = get_log()
#TODO options/settings not global
gaplimit = 6

#configuration types
config_types = {'rpc_port': int,
                'port': int,
                'usessl': bool,
                'socks5': bool,
                'network': bool,
                'socks5_port': int,
                'maker_timeout_sec': int,
                'tx_fees': int}
config_tips = {'blockchain_source': 
               'options: blockr, bitcoin-rpc',
               'network':
               'one of "testnet" or "mainnet"',
               'rpc_host':
               'the host for bitcoind; only used if blockchain_source is bitcoin-rpc',
               'rpc_port':
               'port for connecting to bitcoind over rpc',
               'rpc_user':
               'user for connecting to bitcoind over rpc',
               'rpc_password':
               'password for connecting to bitcoind over rpc',
               'host':
               'hostname for IRC server',
               'channel':
               'channel name on IRC server',
               'port':
               'port for connecting to IRC server',
               'usessl':
               'check to use SSL for connection to IRC',
               'socks5':
               'check to use SOCKS5 proxy for IRC connection',
               'socks5_host':
               'host for SOCKS5 proxy',
               'socks5_port':
               'port for SOCKS5 proxy',
               'maker_timeout_sec':
               'timeout for waiting for replies from makers',
               'merge_algorithm':
               'for dust sweeping, try merge_algorithm = gradual, \n'+
               'for more rapid dust sweeping, try merge_algorithm = greedy \n'+
               'for most rapid dust sweeping, try merge_algorithm = greediest \n' +
               ' but dont forget to bump your miner fees!',
               'tx_fees':
               'the fee estimate is based on a projection of how many satoshis \n'+
               'per kB are needed to get in one of the next N blocks, N set here \n'+
               'as the value of "tx_fees". This estimate is high if you set N=1, \n'+
               'so we choose N=3 for a more reasonable figure, \n'+
               'as our default. Note that for clients not using a local blockchain \n'+
               'instance, we retrieve an estimate from the API at blockcypher.com, currently. \n' 
               }

class QtHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
    def emit(self, record):
        record = self.format(record)
        if record: XStream.stdout().write('%s\n'%record)

handler = QtHandler()
handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
log.addHandler(handler)

class XStream(QtCore.QObject):
    _stdout = None
    _stderr = None
    messageWritten = QtCore.pyqtSignal(str)
    def flush( self ):
        pass
    def fileno( self ):
        return -1
    def write( self, msg ):
        if ( not self.signalsBlocked() ):
            self.messageWritten.emit(unicode(msg))
    @staticmethod
    def stdout():
        if ( not XStream._stdout ):
            XStream._stdout = XStream()
            sys.stdout = XStream._stdout
        return XStream._stdout
    @staticmethod
    def stderr():
        if ( not XStream._stderr ):
            XStream._stderr = XStream()
            sys.stderr = XStream._stderr
        return XStream._stderr

class Buttons(QHBoxLayout):
    def __init__(self, *buttons):
        QHBoxLayout.__init__(self)
        self.addStretch(1)
        for b in buttons:
            self.addWidget(b)

class CloseButton(QPushButton):
    def __init__(self, dialog):
        QPushButton.__init__(self, "Close")
        self.clicked.connect(dialog.close)
        self.setDefault(True)

class CopyButton(QPushButton):
    def __init__(self, text_getter, app):
        QPushButton.__init__(self, "Copy")
        self.clicked.connect(lambda: app.clipboard().setText(text_getter()))

class CopyCloseButton(QPushButton):
    def __init__(self, text_getter, app, dialog):
        QPushButton.__init__(self, "Copy and Close")
        self.clicked.connect(lambda: app.clipboard().setText(text_getter()))
        self.clicked.connect(dialog.close)
        self.setDefault(True)

class OkButton(QPushButton):
    def __init__(self, dialog, label=None):
        QPushButton.__init__(self, label or "OK")
        self.clicked.connect(dialog.accept)
        self.setDefault(True)

class CancelButton(QPushButton):
    def __init__(self, dialog, label=None):
        QPushButton.__init__(self, label or "Cancel")
        self.clicked.connect(dialog.reject)


def check_password_strength(password):
    '''
    Check the strength of the password entered by the user and return back the same
    :param password: password entered by user in New Password
    :return: password strength Weak or Medium or Strong
    '''
    password = unicode(password)
    n = math.log(len(set(password)))
    num = re.search("[0-9]", password) is not None and re.match("^[0-9]*$", password) is None
    caps = password != password.upper() and password != password.lower()
    extra = re.match("^[a-zA-Z0-9]*$", password) is None
    score = len(password)*( n + caps + num + extra)/20
    password_strength = {0:"Weak",1:"Medium",2:"Strong",3:"Very Strong"}
    return password_strength[min(3, int(score))]

def update_password_strength(pw_strength_label,password):
    '''
    call the function check_password_strength and update the label pw_strength 
    interactively as the user is typing the password
    :param pw_strength_label: the label pw_strength
    :param password: password entered in New Password text box
    :return: None
    '''
    if password:
        colors = {"Weak":"Red","Medium":"Blue","Strong":"Green", 
                  "Very Strong":"Green"}
        strength = check_password_strength(password)
        label = "Password Strength"+ ": "+"<font color=" + \
        colors[strength] + ">" + strength + "</font>"
    else:
        label = ""
    pw_strength_label.setText(label)

def make_password_dialog(self, msg, new_pass=True):

    self.new_pw = QLineEdit()
    self.new_pw.setEchoMode(2)
    self.conf_pw = QLineEdit()
    self.conf_pw.setEchoMode(2)

    vbox = QVBoxLayout()
    label = QLabel(msg)
    label.setWordWrap(True)

    grid = QGridLayout()
    grid.setSpacing(8)
    grid.setColumnMinimumWidth(0, 70)
    grid.setColumnStretch(1,1)

    logo = QLabel()
    lockfile = ":icons/lock.png"
    logo.setPixmap(QPixmap(lockfile).scaledToWidth(36))
    logo.setAlignment(QtCore.Qt.AlignCenter)

    grid.addWidget(logo,  0, 0)
    grid.addWidget(label, 0, 1, 1, 2)
    vbox.addLayout(grid)

    grid = QGridLayout()
    grid.setSpacing(8)
    grid.setColumnMinimumWidth(0, 250)
    grid.setColumnStretch(1,1)

    grid.addWidget(QLabel('New Password' if new_pass else 'Password'), 1, 0)
    grid.addWidget(self.new_pw, 1, 1)

    grid.addWidget(QLabel('Confirm Password'), 2, 0)
    grid.addWidget(self.conf_pw, 2, 1)
    vbox.addLayout(grid)

    #Password Strength Label
    self.pw_strength = QLabel()
    grid.addWidget(self.pw_strength, 3, 0, 1, 2)
    self.new_pw.textChanged.connect(lambda: update_password_strength(
        self.pw_strength, self.new_pw.text()))

    vbox.addStretch(1)
    vbox.addLayout(Buttons(CancelButton(self), OkButton(self)))
    return vbox

class PasswordDialog(QDialog):
    
    def __init__(self):
        super(PasswordDialog, self).__init__()
        self.initUI()
        
    def initUI(self):      
        #self.setGeometry(300, 300, 290, 150)
        self.setWindowTitle('Create a new password')
        msg = "Enter a new password"
        self.setLayout(make_password_dialog(self,msg))
        self.show()

class MyTreeWidget(QTreeWidget):

    def __init__(self, parent, create_menu, headers, stretch_column=None,
                 editable_columns=None):
        QTreeWidget.__init__(self, parent)
        self.parent = parent
        self.stretch_column = stretch_column
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.create_menu)
        self.setUniformRowHeights(True)
        # extend the syntax for consistency
        self.addChild = self.addTopLevelItem
        self.insertChild = self.insertTopLevelItem

        # Control which columns are editable
        self.editor = None
        self.pending_update = False
        if editable_columns is None:
            editable_columns = [stretch_column]
        self.editable_columns = editable_columns
        #self.setItemDelegate(ElectrumItemDelegate(self))
        self.itemActivated.connect(self.on_activated)
        self.update_headers(headers)

    def create_menu(self, position):
        self.selectedIndexes()
        item = self.currentItem()
        address_valid = False
        if item:
            address = str(item.text(0))
            try:
                btc.b58check_to_hex(address)
                address_valid = True
            except AssertionError:
                print 'no btc address found, not creating menu item'
        
        menu = QMenu()
        if address_valid:
            menu.addAction("Copy address to clipboard", 
                           lambda: app.clipboard().setText(address))
        menu.addAction("Resync wallet from blockchain", lambda: w.resyncWallet())
        #TODO add more items to context menu
        #menu.addAction(_("Details"), lambda: self.parent.show_transaction(self.wallet.transactions.get(tx_hash)))
        #menu.addAction(_("Edit description"), lambda: self.editItem(item, self.editable_columns[0]))
        #menu.addAction(_("View on block explorer"), lambda: webbrowser.open(tx_URL))
        menu.exec_(self.viewport().mapToGlobal(position))    

    def update_headers(self, headers):
        self.setColumnCount(len(headers))
        self.setHeaderLabels(headers)
        self.header().setStretchLastSection(False)
        for col in range(len(headers)):
            sm = QHeaderView.Stretch if col == self.stretch_column else QHeaderView.ResizeToContents
            self.header().setResizeMode(col, sm)

    def editItem(self, item, column):
        if column in self.editable_columns:
            self.editing_itemcol = (item, column, unicode(item.text(column)))
            # Calling setFlags causes on_changed events for some reason
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            QTreeWidget.editItem(self, item, column)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_F2:
            self.on_activated(self.currentItem(), self.currentColumn())
        else:
            QTreeWidget.keyPressEvent(self, event)

    def permit_edit(self, item, column):
        return (column in self.editable_columns
                and self.on_permit_edit(item, column))

    def on_permit_edit(self, item, column):
        return True

    def on_activated(self, item, column):
        if self.permit_edit(item, column):
            self.editItem(item, column)
        else:
            pt = self.visualItemRect(item).bottomLeft()
            pt.setX(50)
            self.emit(QtCore.SIGNAL('customContextMenuRequested(const QPoint&)'), pt)

    def createEditor(self, parent, option, index):
        self.editor = QStyledItemDelegate.createEditor(self.itemDelegate(),
                                                       parent, option, index)
        self.editor.connect(self.editor, QtCore.SIGNAL("editingFinished()"),
                            self.editing_finished)
        return self.editor

    def editing_finished(self):
        # Long-time QT bug - pressing Enter to finish editing signals
        # editingFinished twice.  If the item changed the sequence is
        # Enter key:  editingFinished, on_change, editingFinished
        # Mouse: on_change, editingFinished
        # This mess is the cleanest way to ensure we make the
        # on_edited callback with the updated item
        if self.editor:
            (item, column, prior_text) = self.editing_itemcol
            if self.editor.text() == prior_text:
                self.editor = None  # Unchanged - ignore any 2nd call
            elif item.text(column) == prior_text:
                pass # Buggy first call on Enter key, item not yet updated
            else:
                # What we want - the updated item
                self.on_edited(*self.editing_itemcol)
                self.editor = None

            # Now do any pending updates
            if self.editor is None and self.pending_update:
                self.pending_update = False
                self.on_update()

    def on_edited(self, item, column, prior):
        '''Called only when the text actually changes'''
        key = str(item.data(0, Qt.UserRole).toString())
        text = unicode(item.text(column))
        self.parent.wallet.set_label(key, text)
        if text:
            item.setForeground(column, QBrush(QColor('black')))
        else:
            text = self.parent.wallet.get_default_label(key)
            item.setText(column, text)
            item.setForeground(column, QBrush(QColor('gray')))
        self.parent.history_list.update()
        self.parent.update_completions()

    def update(self):
        # Defer updates if editing
        if self.editor:
            self.pending_update = True
        else:
            self.on_update()

    def on_update(self):
        pass

    def get_leaves(self, root):
        child_count = root.childCount()
        if child_count == 0:
            yield root
        for i in range(child_count):
            item = root.child(i)
            for x in self.get_leaves(item):
                yield x

    def filter(self, p, columns):
        p = unicode(p).lower()
        for item in self.get_leaves(self.invisibleRootItem()):
            item.setHidden(all([unicode(item.text(column)).lower().find(p) == -1
                                for column in columns]))
            
#TODO change denominations, mbtc, ubtc, bits
# make a satoshi_to_unit() and unit_to_satoshi()
class SettingsTab(QDialog):
    def __init__(self):
        super(SettingsTab, self).__init__()
        self.initUI()

    def initUI(self):
        outerGrid = QGridLayout()
        sA = QScrollArea()
        sA.setWidgetResizable(True)
        frame = QFrame()
        grid = QGridLayout()
        self.settingsFields = []
        j = 0
        for i,section in enumerate(jm_single().config.sections()):
            pairs = jm_single().config.items(section)
            newSettingsFields = self.getSettingsFields(section, 
                                [_[0] for _ in pairs])
            self.settingsFields.extend(newSettingsFields)
            sL = QLabel(section)
            sL.setStyleSheet("QLabel {color: blue;}")
            grid.addWidget(sL)
            j += 1
            for k, ns in enumerate(newSettingsFields):
                grid.addWidget(ns[0],j,0)
                #try to find the tooltip for this label from config tips;
                #it might not be there
                if str(ns[0].text()) in config_tips:
                    ttS = config_tips[str(ns[0].text())]
                    ns[0].setToolTip(ttS)
                #TODO why doesn't addWidget() with colspan = -1 work?
                grid.addWidget(ns[1],j,1)
                sfindex = len(self.settingsFields)-len(newSettingsFields)+k
                if isinstance(ns[1], QCheckBox):
                    ns[1].toggled.connect(lambda checked, s=section, 
                                          q=sfindex: self.handleEdit(
                                    s, self.settingsFields[q], checked))
                else:
                    ns[1].editingFinished.connect(
                    lambda q=sfindex, s=section: self.handleEdit(s, 
                                                      self.settingsFields[q]))
                j+=1
        outerGrid.addWidget(sA)
        sA.setWidget(frame)        
        frame.setLayout(grid)
        frame.adjustSize()
        self.setLayout(outerGrid)
        self.show()

    def handleEdit(self, section, t, checked=None):
        if isinstance(t[1], QCheckBox):
            if str(t[0].text()) == 'Testnet':
                oname = 'network'
                oval = 'testnet' if checked else 'mainnet'
                add = '' if not checked else ' - Testnet'
                w.setWindowTitle(appWindowTitle + add)                
            else:
                oname = str(t[0].text())
                oval = 'true' if checked else 'false'
            print 'setting sectoin: '+section+' and name: '+oname+' to: '+oval
            jm_single().config.set(section,oname,oval)
    
        else: #currently there is only QLineEdit
            jm_single().config.set(section, str(t[0].text()),str(t[1].text()))
        
    def getSettingsFields(self, section, names):
        results = []
        for name in names:
            val = jm_single().config.get(section, name)
            if name in config_types:
                t = config_types[name]
                if t == bool:
                    qt = QCheckBox()
                    if val=='testnet' or val.lower()=='true':
                        qt.setChecked(True)
                else:
                    qt = QLineEdit(val)
                    if t == int:
                        qt.setValidator(QIntValidator(0, 65535))
            else:
                qt = QLineEdit(val)
            label = 'Testnet' if name=='network' else name
            results.append((QLabel(label), qt))
        return results

class SpendTab(QWidget):
    def __init__(self):
        super(SpendTab, self).__init__()
        self.initUI()

    def initUI(self):
        vbox = QVBoxLayout(self)
        top = QFrame()
        top.setFrameShape(QFrame.StyledPanel)
        topLayout = QGridLayout()
        top.setLayout(topLayout)
        sA = QScrollArea()
        sA.setWidgetResizable(True)
        topLayout.addWidget(sA)
        iFrame = QFrame()
        sA.setWidget(iFrame)
        innerTopLayout = QGridLayout()
        innerTopLayout.setSpacing(4)
        iFrame.setLayout(innerTopLayout)
        
        self.widgets = self.getSettingsWidgets()
        for i, x in enumerate(self.widgets):
            innerTopLayout.addWidget(x[0],i,0)
            innerTopLayout.addWidget(x[1],i,1)
        self.widgets[0][1].editingFinished.connect(lambda : self.checkAddress(
            self.widgets[0][1].text()))
        self.startButton =QPushButton('Start')
        self.startButton.setToolTip('You will be prompted to decide whether to accept\n'+
                               'the transaction after connecting, and shown the\n'+
                               'fees to pay; you can cancel at that point if you wish.')
        self.startButton.clicked.connect(self.startSendPayment)
        #TODO: how to make the Abort button work, at least some of the time..
        self.abortButton = QPushButton('Abort')
        self.abortButton.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.startButton)
        buttons.addWidget(self.abortButton)
        innerTopLayout.addLayout(buttons, len(self.widgets), 0, 1, 2)        
        splitter1 = QSplitter(QtCore.Qt.Vertical)
        textedit = QTextEdit()
        XStream.stdout().messageWritten.connect(textedit.insertPlainText)
        XStream.stderr().messageWritten.connect(textedit.insertPlainText)        
        splitter1.addWidget(top)
        splitter1.addWidget(textedit)
        splitter1.setSizes([200,200])
        self.setLayout(vbox)
        vbox.addWidget(splitter1)
        self.show()
    
    def startSendPayment(self):
        self.aborted = False
        if not self.validateSettings():
            return
        #all settings are valid; start
        QMessageBox.information(self,"Sendpayment","Connecting to IRC.\n"+
                                        "View real-time log in the lower pane.")        
        self.startButton.setEnabled(False)
        self.abortButton.setEnabled(True)
    
        jm_single().nickname = random_nick()
    
        log.debug('starting sendpayment')
        #TODO: is this necessary?
        #jm_single().bc_interface.sync_wallet(wallet)
    
        self.irc = IRCMessageChannel(jm_single().nickname)
        self.destaddr = str(self.widgets[0][1].text())
        #convert from bitcoins (enforced by QDoubleValidator) to satoshis
        self.btc_amount_str = str(self.widgets[3][1].text())
        amount = int(Decimal(self.btc_amount_str)*Decimal('1e8'))
        makercount = int(self.widgets[1][1].text())
        mixdepth = int(self.widgets[2][1].text())
        self.taker = SendPayment(self.irc, w.wallet, self.destaddr, amount, makercount,
                                            5000, 30, mixdepth,
                                            False, weighted_order_choose,
                                            isolated=True)        
        thread = TaskThread(self)
        thread.add(self.runIRC, on_done=self.cleanUp)                
        w.statusBar().showMessage("Connecting to IRC ...")
        thread2 = TaskThread(self)
        thread2.add(self.createTxThread, on_done=self.doTx)      
    
    def createTxThread(self):
        self.pt = PT(self.taker)
        self.orders, self.total_cj_fee = self.pt.create_tx()
        log.debug("Finished create_tx")
        #TODO this can't be done in a thread as currently built;
        #how else? or fix?
        #w.statusBar().showMessage("Found counterparties...")
    
    def doTx(self):
        if not self.orders:
            QMessageBox.warning(self,"Error","Not enough matching orders found.")
            self.giveUp()
            return
        total_fee_pc = 1.0 * self.total_cj_fee / self.taker.amount
        mbinfo = []
        mbinfo.append("Sending amount: "+self.btc_amount_str+" BTC")
        mbinfo.append("to address: "+self.destaddr)
        mbinfo.append(" ")
        mbinfo.append("Counterparties chosen:")
        mbinfo.append('\t'.join(['Name','Order id']))
        for k,o in self.orders.iteritems():
            mbinfo.append('\t'.join([k,str(o)]))
        mbinfo.append('Total coinjoin fee = ' + str(float('%.3g' % (
            100.0 * total_fee_pc))) + '%')
        title = 'Check Transaction'
        if total_fee_pc > 2:
            title += ': WARNING: Fee is HIGH!!'
        reply = QMessageBox.question(self,
                                     title,'\n'.join(mbinfo),
                                     QMessageBox.Yes,QMessageBox.No)
        if reply == QMessageBox.Yes:
            log.debug('You agreed, transaction proceeding')
            w.statusBar().showMessage("Building transaction...")
            thread3 = TaskThread(self)
            thread3.add(partial(self.pt.do_tx,self.total_cj_fee, self.orders), 
                        on_done=None)
        else:
            self.giveUp()
            return
    
    def giveUp(self):
        self.aborted = True
        log.debug("Transaction aborted.")
        self.taker.msgchan.shutdown()
        self.abortButton.setEnabled(False)
        self.startButton.setEnabled(True)
        w.statusBar().showMessage("Transaction aborted.")
    
    def cleanUp(self):
        if not self.taker.txid:
            if not self.aborted:
                w.statusBar().showMessage("Transaction failed.")
                QMessageBox.warning(self,"Failed","Transaction was not completed.")
        else:
            w.statusBar().showMessage("Transaction completed successfully.")
            QMessageBox.information(self,"Success",
                                    "Transaction has been broadcast.\n"+
                                "Txid: "+str(self.taker.txid))
        self.startButton.setEnabled(True)
        self.abortButton.setEnabled(False)
        
    def runIRC(self):
        try:
            log.debug('starting irc')
            self.irc.run()
        except:
            log.debug('CRASHING, DUMPING EVERYTHING')
            debug_dump_object(w.wallet, ['addr_cache', 'keys', 'wallet_name', 'seed'])
            debug_dump_object(self.taker)
            import traceback
            log.debug(traceback.format_exc())

    def finishPayment(self):
        log.debug("Done")
        
    def validateSettings(self):
        valid, errmsg = validate_address(self.widgets[0][1].text())
        if not valid:
            QMessageBox.warning(self,"Error", errmsg)
            return False
        errs = ["Number of counterparties must be provided.",
                "Mixdepth must be chosen.",
                "Amount, in bitcoins, must be provided."
                ]
        for i in range(1,4):
            if self.widgets[i][1].text().size()==0:
                QMessageBox.warning(self, "Error",errs[i-1])
                return False
        if not w.wallet:
            QMessageBox.warning(self,"Error","There is no wallet loaded.")
            return False
        return True
                
    def checkAddress(self, addr):
        valid, errmsg = validate_address(str(addr))
        if not valid:
            QMessageBox.warning(self, "Error","Bitcoin address not valid.\n"+errmsg)

    def getSettingsWidgets(self):
        results = []
        sN = ['Recipient address', 'Number of counterparties',
                         'Mixdepth','Amount in bitcoins (BTC)']
        sH = ['The address you want to send the payment to',
                         'How many other parties to send to; if you enter 4\n'+
                         ', there will be 5 participants, including you',
                         'The mixdepth of the wallet to send the payment from',
                         'The amount IN BITCOINS to send.\n']
        sT = [str, int, int, float]
        #todo maxmixdepth
        sMM = ['',(2,20),(0,5),(0.00000001,100.0,8)]
        sD = ['', '3', '0', '']
        for x in zip(sN, sH, sT, sD, sMM):
            ql = QLabel(x[0])
            ql.setToolTip(x[1])
            qle = QLineEdit(x[3])
            if x[2]==int:
                qle.setValidator(QIntValidator(*x[4]))
            if x[2]==float:
                qle.setValidator(QDoubleValidator(*x[4]))
            results.append((ql, qle))
        return results
        

class JMWalletTab(QWidget):
    def __init__(self, mixdepths):
        super(JMWalletTab, self).__init__()
        self.mixdepths = mixdepths
        self.wallet_name = 'NONE'
        self.initUI()
    
    def initUI(self):
        self.label1 = QLabel(
            "CURRENT WALLET: "+self.wallet_name + ', total balance: 0.0',
                             self)
        #label1.resize(300,120)
        v = MyTreeWidget(self, None, self.getHeaders())
        v.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.on_update = self.updateWalletInfo
        self.history = v
        vbox = QVBoxLayout()
        self.setLayout(vbox)
        vbox.setMargin(0)
        vbox.setSpacing(0)
        vbox.addWidget(self.label1)
        vbox.addWidget(v)
        buttons = QWidget()
        vbox.addWidget(buttons)
        self.updateWalletInfo()
        #vBoxLayout.addWidget(self.label2)
        #vBoxLayout.addWidget(self.table)
        self.show()
    
    def getHeaders(self):
        '''Function included in case dynamic in future'''
        return ['Address','Index','Balance','Used/New']

    def updateWalletInfo(self, walletinfo=None):
        l = self.history
        l.clear()
        if walletinfo:
            self.mainwindow = self.parent().parent().parent()
            rows, mbalances, total_bal = walletinfo
            if get_network() == 'testnet':
                self.wallet_name = self.mainwindow.wallet.seed
            else:
                self.wallet_name = os.path.basename(self.mainwindow.wallet.path)
            self.label1.setText(
            "CURRENT WALLET: "+self.wallet_name + ', total balance: '+total_bal)

        for i in range(self.mixdepths):
            if walletinfo:
                mdbalance = mbalances[i]
            else:
                mdbalance = "{0:.8f}".format(0)
            m_item = QTreeWidgetItem(["Mixdepth " +str(i) + " , balance: "+mdbalance,
                                      '','','',''])
            l.addChild(m_item)
            for forchange in [0,1]:
                heading = 'EXTERNAL' if forchange==0 else 'INTERNAL'
                heading_end = ' addresses m/0/%d/%d/' % (i, forchange)
                heading += heading_end
                seq_item = QTreeWidgetItem([ heading, '', '', '', ''])
                m_item.addChild(seq_item)
                if not forchange:
                    seq_item.setExpanded(True)
                if not walletinfo:
                    item = QTreeWidgetItem(['None', '', '', ''])
                    seq_item.addChild(item)
                else:
                    for j in range(len(rows[i][forchange])):
                        item = QTreeWidgetItem(rows[i][forchange][j])
                        item.setFont(0,QFont(MONOSPACE_FONT))
                        if rows[i][forchange][j][3] == 'used':
                            item.setForeground(3, QBrush(QColor('red')))
                        seq_item.addChild(item)
        

class TaskThread(QtCore.QThread):
    '''Thread that runs background tasks.  Callbacks are guaranteed
    to happen in the context of its parent.'''

    Task = namedtuple("Task", "task cb_success cb_done cb_error")
    doneSig = QtCore.pyqtSignal(object, object, object)

    def __init__(self, parent, on_error=None):
        super(TaskThread, self).__init__(parent)
        self.on_error = on_error
        self.tasks = Queue.Queue()
        self.doneSig.connect(self.on_done)
        self.start()

    def add(self, task, on_success=None, on_done=None, on_error=None):
        on_error = on_error or self.on_error
        self.tasks.put(TaskThread.Task(task, on_success, on_done, on_error))

    def run(self):
        while True:
            task = self.tasks.get()
            if not task:
                break
            try:
                result = task.task()
                self.doneSig.emit(result, task.cb_done, task.cb_success)
            except BaseException:
                self.doneSig.emit(sys.exc_info(), task.cb_done, task.cb_error)

    def on_done(self, result, cb_done, cb):
        # This runs in the parent's thread.
        if cb_done:
            cb_done()
        if cb:
            cb(result)

    def stop(self):
        self.tasks.put(None)

class JMMainWindow(QMainWindow):
    def __init__(self):
        super(JMMainWindow, self).__init__()
        self.wallet=None
        self.initUI()
    
    def initUI(self):
        self.statusBar().showMessage("Ready")
        self.setGeometry(300,300,250,150)
        exitAction = QAction(QIcon('exit.png'), '&Exit', self)        
        exitAction.setShortcut('Ctrl+Q')
        exitAction.setStatusTip('Exit application')
        exitAction.triggered.connect(qApp.quit)
        generateAction = QAction('&Generate', self)
        generateAction.setStatusTip('Generate new wallet')
        generateAction.triggered.connect(self.generateWallet)
        loadAction = QAction('&Load', self)
        loadAction.setStatusTip('Load wallet from file')
        loadAction.triggered.connect(self.selectWallet)
        recoverAction = QAction('&Recover', self)
        recoverAction.setStatusTip('Recover wallet from seedphrase')
        recoverAction.triggered.connect(self.recoverWallet)
        aboutAction = QAction('About Joinmarket', self)
        aboutAction.triggered.connect(self.showAboutDialog)
        menubar = QMenuBar()
        
        walletMenu = menubar.addMenu('&Wallet')
        walletMenu.addAction(loadAction)
        walletMenu.addAction(generateAction)
        walletMenu.addAction(recoverAction)
        walletMenu.addAction(exitAction)
        aboutMenu = menubar.addMenu('&About')
        aboutMenu.addAction(aboutAction)
        
        self.setMenuBar(menubar)
        self.show()

    def showAboutDialog(self):
        QMessageBox.about(self, "Joinmarket",
            "Version"+" %s" % (str(jm_single().JM_VERSION)) + 
            "\n\n" + 
            "Joinmarket sendpayment tool")
        
    def recoverWallet(self):
        if get_network()=='testnet':
            QMessageBox.information(self, 'Error',
                            'recover from seedphrase not supported for testnet')
            return
        d = QDialog(self)
        d.setModal(1)
        d.setWindowTitle('Recover from seed')
        #d.setMinimumSize(290, 130)
        layout = QGridLayout(d)
        message_e = QTextEdit()
        layout.addWidget(QLabel('Enter 12 words'), 0, 0)
        layout.addWidget(message_e, 1, 0)
        #layout.setRowStretch(2,3)
        hbox = QHBoxLayout()       
        buttonBox = QDialogButtonBox(self)
        buttonBox.setStandardButtons(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttonBox.button(QDialogButtonBox.Ok).clicked.connect(d.accept)
        buttonBox.button(QDialogButtonBox.Cancel).clicked.connect(d.reject)
        hbox.addWidget(buttonBox)
        layout.addLayout(hbox, 3, 0)
        result = d.exec_()
        if result != QDialog.Accepted:
            print 'cancelled'
            return
        msg = str(message_e.toPlainText())
        words = msg.split() #splits on any number of ws chars
        print words
        if not len(words)==12:
            QMessageBox.warning(self, "Error","You did not provide 12 words, aborting.")
        else:
            seed = mn_decode(words)
            print 'seed is: '+seed
            self.initWallet(seed=seed)
            

    def selectWallet(self, testnet_seed=None):
        if get_network() != 'testnet':
            firstarg = QFileDialog.getOpenFileName(self, 'Choose Wallet File', 
                    directory='/home/adam/DevRepos/JoinMarket/testing/joinmarket/wallets')
            #TODO validate the wallet file, set the directory properly
            log.debug('first arg is: '+firstarg)
            if not firstarg:
                return
            decrypted = False
            while not decrypted:
                text, ok = QInputDialog.getText(self, 'Decrypt wallet', 
                    'Enter your password:', mode=QLineEdit.Password)
                if not ok:
                    return
                pwd = str(text).strip()
                decrypted = self.loadWalletFromBlockchain(firstarg, pwd)
        else:
            if not testnet_seed:
                testnet_seed, ok = QInputDialog.getText(self, 'Load Testnet wallet',
                    'Enter a testnet seed:', mode=QLineEdit.Normal)
                if not ok:
                    return
            firstarg = str(testnet_seed)
            pwd = None
            #ignore return value as there is no decryption failure possible
            self.loadWalletFromBlockchain(firstarg, pwd)        
        
    def loadWalletFromBlockchain(self, firstarg=None, pwd=None):
        if (firstarg and pwd) or (firstarg and get_network()=='testnet'):
            self.wallet = Wallet(str(firstarg), max_mix_depth=5, pwd=pwd)
            if not self.wallet.decrypted:
                QMessageBox.warning(self,"Error","Wrong password")
                return False
        if 'listunspent_args' not in jm_single().config.options('POLICY'):
            jm_single().config.set('POLICY','listunspent_args', '[0]')
        assert self.wallet, "No wallet loaded"
        thread = TaskThread(self)
        task = partial(jm_single().bc_interface.sync_wallet, self.wallet)
        thread.add(task, on_done=self.updateWalletInfo)                
        self.statusBar().showMessage("Reading wallet from blockchain ...")
        return True

    def updateWalletInfo(self):
        t = self.centralWidget().widget(0)
        if not self.wallet: #failure to sync in constructor means object is not created
            newstmsg = "Unable to sync wallet - see error in console."
        else:
            t.updateWalletInfo(get_wallet_printout(self.wallet))
            newstmsg = "Wallet synced successfully."
        self.statusBar().showMessage(newstmsg)
    
    def resyncWallet(self):
        if not self.wallet:
            QMessageBox.warning(self, "Error", "No wallet loaded")
            return
        self.wallet.init_index() #sync operation assumes index is empty
        self.loadWalletFromBlockchain()
        

    def generateWallet(self):
        print 'generating wallet'
        if get_network() == 'testnet':
            seed = self.getTestnetSeed()
            self.selectWallet(testnet_seed=seed)
        else:
            self.initWallet()
    
    def getTestnetSeed(self):
        text, ok = QInputDialog.getText(self, 'Testnet seed', 
                        'Enter a string as seed (can be anything):')
        if not ok or not text:
            QMessageBox.warning(self,"Error","No seed entered, aborting")
            return
        return str(text).strip()
        
    def initWallet(self, seed = None):
        '''Creates a new mainnet
        wallet
        '''
        if not seed:
            seed = btc.sha256(os.urandom(64))[:32]
            words = mn_encode(seed)
            mb = QMessageBox()
            #TODO: CONSIDERABLY! improve this dialog
            mb.setText("Write down this wallet recovery seed.")
            mb.setInformativeText(' '.join(words))
            mb.setStandardButtons(QMessageBox.Ok)
            ret = mb.exec_()
        
        pd = PasswordDialog()
        while True:
            pd.exec_()
            if pd.new_pw.text() != pd.conf_pw.text():
                QMessageBox.warning(self,"Error","Passwords don't match.")
                continue
            break
        
        print 'got password: '+str(pd.new_pw.text())
        walletfile = create_wallet_file(str(pd.new_pw.text()), seed)
        walletname, ok = QInputDialog.getText(self, 'Choose wallet name', 
                    'Enter wallet file name:', QLineEdit.Normal,"wallet.json")
        if not ok:
            QMessageBox.warning(self,"Error","Create wallet aborted")
            return
        walletpath = os.path.join('wallets', str(walletname))
        # Does a wallet with the same name exist?
        if os.path.isfile(walletpath):
            QMessageBox.warning(self, 'Error', 
                                walletpath + ' already exists. Aborting.')
            return
        else:
            fd = open(walletpath, 'w')
            fd.write(walletfile)
            fd.close()
            QMessageBox.information(self, "Wallet created", 
                                    'Wallet saved to ' + str(walletname))
            self.loadWalletFromBlockchain(str(walletname), str(pd.new_pw.text()))
            

def get_wallet_printout(wallet):
    rows = []
    mbalances = []
    total_balance = 0
    for m in range(wallet.max_mix_depth):
        rows.append([])
        balance_depth = 0
        for forchange in [0,1]:
            rows[m].append([])
            for k in range(wallet.index[m][forchange] + gaplimit):
                addr = wallet.get_addr(m, forchange, k)
                balance = 0.0
                for addrvalue in wallet.unspent.values():
                    if addr == addrvalue['address']:
                        balance += addrvalue['value']
                balance_depth += balance
                used = ('used' if k < wallet.index[m][forchange] else 'new')
                if balance > 0.0 or k >= wallet.index[m][forchange]:
                    rows[m][forchange].append([addr, str(k), 
                                               "{0:.8f}".format(balance/1e8),used])
        mbalances.append(balance_depth)
        total_balance += balance_depth
    #rows is of format [[[addr,index,bal,used],[addr,...]*5],
    #[[addr, index,..], [addr, index..]*5]]
    #mbalances is a simple array of 5 mixdepth balances
    return (rows, ["{0:.8f}".format(x/1e8) for x in mbalances], 
            "{0:.8f}".format(total_balance/1e8))

################################
load_program_config()
app = QApplication(sys.argv)
appWindowTitle = 'Joinmarket GUI'
w = JMMainWindow()
tabWidget = QTabWidget(w)
mdepths = 5
tabWidget.addTab(JMWalletTab(mdepths), "JM Wallet")
settingsTab = SettingsTab()
tabWidget.addTab(settingsTab, "Settings")
tabWidget.addTab(SpendTab(), "Send Payment")
w.resize(500, 300)
#w.move(300, 300)
suffix = ' - Testnet' if get_network() == 'testnet' else ''
w.setWindowTitle(appWindowTitle + suffix)
tabWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
w.setCentralWidget(tabWidget)
w.show()

sys.exit(app.exec_())