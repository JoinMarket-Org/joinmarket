
'''
Joinmarket GUI using PyQt for doing Sendpayment.
Some widgets copied and modified from https://github.com/spesmilo/electrum
The latest version of this code is currently maintained at:
https://github.com/AdamISZ/joinmarket/tree/gui

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
import Queue, platform

from decimal import Decimal
from functools import partial
from collections import namedtuple

from PyQt4 import QtCore
from PyQt4.QtGui import *

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

JM_CORE_VERSION = '0.1.3'
JM_GUI_VERSION = '3'

from joinmarket import load_program_config, get_network, Wallet, encryptData, \
    get_p2pk_vbyte, jm_single, mn_decode, mn_encode, create_wallet_file, \
    validate_address, random_nick, get_log, IRCMessageChannel, \
    weighted_order_choose, get_blockchain_interface_instance, joinmarket_alert, \
    core_alert

from sendpayment import SendPayment, PT

log = get_log()
donation_address = '1LT6rwv26bV7mgvRosoSCyGM7ttVRsYidP'
donation_address_testnet = 'mz6FQosuiNe8135XaQqWYmXsa3aD8YsqGL'

warnings = {"blockr_privacy": """You are using blockr as your method of
connecting to the blockchain; this means
that blockr.com can see the addresses you
query. This is bad for privacy - consider
using a Bitcoin Core node instead."""}
#configuration types
config_types = {'rpc_port': int,
                'port': int,
                'usessl': bool,
                'socks5': bool,
                'network': bool,
                'socks5_port': int,
                'maker_timeout_sec': int,
                'tx_fees': int,
                'gaplimit': int,
                'check_high_fee': int,
                'max_mix_depth': int,
                'txfee_default': int,
                'order_wait_time': int,
                'privacy_warning': None}
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
               'instance, we retrieve an estimate from the API at blockcypher.com, currently. \n',
               'gaplimit': 'How far forward to search for used addresses in the HD wallet',
               'check_high_fee': 'Percent fee considered dangerously high, default 2%',
               'max_mix_depth': 'Total number of mixdepths in the wallet, default 5',
               'txfee_default': 'Number of satoshis per counterparty for an initial\n'+
               'tx fee estimate; this value is not usually used and is best left at\n'+
               'the default of 5000',
               'order_wait_time': 'How long to wait for orders to arrive on entering\n'+
               'the message channel, default is 30s'
               }

def update_config_for_gui():
    '''The default joinmarket config does not contain these GUI settings
    (they are generally set by command line flags or not needed).
    If they are set in the file, use them, else set the defaults.
    These *will* be persisted to joinmarket.cfg, but that will not affect
    operation of the command line version.
    '''
    gui_config_names = ['gaplimit', 'history_file', 'check_high_fee',
                        'max_mix_depth', 'txfee_default', 'order_wait_time']
    gui_config_default_vals = ['6', 'jm-tx-history.txt', '2', '5', '5000', '30']
    if "GUI" not in jm_single().config.sections():
        jm_single().config.add_section("GUI")
    gui_items = jm_single().config.items("GUI")
    for gcn, gcv in zip(gui_config_names, gui_config_default_vals):
        if gcn not in [_[0] for _ in gui_items]:
            jm_single().config.set("GUI", gcn, gcv)
    #Extra setting not exposed to the GUI, but only for the GUI app
    if 'privacy_warning' not in [_[0] for _ in gui_items]:
        print 'overwriting privacy_warning'
        jm_single().config.set("GUI", 'privacy_warning', '1')

def persist_config():
    '''This loses all comments in the config file.
    TODO: possibly correct that.'''
    with open('joinmarket.cfg','w') as f:
        jm_single().config.write(f)

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

class HelpLabel(QLabel):

    def __init__(self, text, help_text, wtitle):
        QLabel.__init__(self, text)
        self.help_text = help_text
        self.wtitle = wtitle
        self.font = QFont()
        self.setStyleSheet(BLUE_FG)

    def mouseReleaseEvent(self, x):
        QMessageBox.information(w, self.wtitle, self.help_text, 'OK')

    def enterEvent(self, event):
        self.font.setUnderline(True)
        self.setFont(self.font)
        app.setOverrideCursor(QCursor(QtCore.Qt.PointingHandCursor))
        return QLabel.enterEvent(self, event)

    def leaveEvent(self, event):
        self.font.setUnderline(False)
        self.setFont(self.font)
        app.setOverrideCursor(QCursor(QtCore.Qt.ArrowCursor))
        return QLabel.leaveEvent(self, event)


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
    #TODO perhaps add an icon here
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
        self.customContextMenuRequested.connect(create_menu)
        self.setUniformRowHeights(True)
        # extend the syntax for consistency
        self.addChild = self.addTopLevelItem
        self.insertChild = self.insertTopLevelItem
        self.editor = None
        self.pending_update = False
        if editable_columns is None:
            editable_columns = [stretch_column]
        self.editable_columns = editable_columns
        self.itemActivated.connect(self.on_activated)
        self.update_headers(headers)

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
            #an awkward design element from the core code: maker_timeout_sec
            #is set outside the config, if it doesn't exist in the config.
            #Add it here and it will be in the newly updated config file.
            if section=='MESSAGING' and 'maker_timeout_sec' not in [_[0] for _ in pairs]:
                jm_single().config.set(section, 'maker_timeout_sec', '60')
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
            log.debug('setting section: '+section+' and name: '+oname+' to: '+oval)
            jm_single().config.set(section,oname,oval)
    
        else: #currently there is only QLineEdit
            log.debug('setting section: '+section+' and name: '+
                      str(t[0].text())+' to: '+str(t[1].text()))
            jm_single().config.set(section, str(t[0].text()),str(t[1].text()))
            if str(t[0].text())=='blockchain_source':
                jm_single().bc_interface = get_blockchain_interface_instance(
                    jm_single().config)
        
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
                elif not t:
                    continue
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

        donateLayout = QHBoxLayout()
        self.donateCheckBox = QCheckBox()
        self.donateCheckBox.setChecked(False)
        self.donateCheckBox.setMaximumWidth(30)
        self.donateLimitBox = QDoubleSpinBox()
        self.donateLimitBox.setMinimum(0.001)
        self.donateLimitBox.setMaximum(0.100)
        self.donateLimitBox.setSingleStep(0.001)
        self.donateLimitBox.setDecimals(3)
        self.donateLimitBox.setValue(0.010)
        self.donateLimitBox.setMaximumWidth(100)
        self.donateLimitBox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        donateLayout.addWidget(self.donateCheckBox)
        label1 = QLabel("Check to send change lower than: ")
        label1.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        donateLayout.addWidget(label1)
        donateLayout.setAlignment(label1, QtCore.Qt.AlignLeft)
        donateLayout.addWidget(self.donateLimitBox)
        donateLayout.setAlignment(self.donateLimitBox, QtCore.Qt.AlignLeft)
        label2 = QLabel(" BTC as a donation.")
        donateLayout.addWidget(label2)
        label2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        donateLayout.setAlignment(label2, QtCore.Qt.AlignLeft)
        label3 = HelpLabel('More','\n'.join(
            ['If the calculated change for your transaction',
             'is smaller than the value you choose (default 0.01 btc)',
             'then that change is sent as a donation. If your change',
             'is larger than that, there will be no donation.',
             '',
             'As well as helping the developers, this feature can,',
             'in certain circumstances, improve privacy, because there',
             'is no change output that can be linked with your inputs later.']),
             'About the donation feature')
        label3.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        donateLayout.setAlignment(label3, QtCore.Qt.AlignLeft)
        donateLayout.addWidget(label3)
        donateLayout.addStretch(1)
        innerTopLayout.addLayout(donateLayout, 0, 0, 1, 2)
        
        self.widgets = self.getSettingsWidgets()
        for i, x in enumerate(self.widgets):
            innerTopLayout.addWidget(x[0], i+1, 0)
            innerTopLayout.addWidget(x[1], i+1, 1, 1, 2)
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
        innerTopLayout.addLayout(buttons, len(self.widgets)+1, 0, 1, 2)
        splitter1 = QSplitter(QtCore.Qt.Vertical)
        self.textedit = QTextEdit()
        self.textedit.verticalScrollBar().rangeChanged.connect(self.resizeScroll)
        XStream.stdout().messageWritten.connect(self.updateConsoleText)
        XStream.stderr().messageWritten.connect(self.updateConsoleText)
        splitter1.addWidget(top)
        splitter1.addWidget(self.textedit)
        splitter1.setSizes([400, 200])
        self.setLayout(vbox)
        vbox.addWidget(splitter1)
        self.show()
    
    def updateConsoleText(self, txt):
        #these alerts are a bit suboptimal;
        #colored is better, and in the ultra-rare
        #case of getting both, one will be swallowed.
        #However, the transaction confirmation dialog
        #will at least show both in RED and BOLD, and they will be more prominent.
        if joinmarket_alert[0]:
            w.statusBar().showMessage("JOINMARKET ALERT: " + joinmarket_alert[0])
        if core_alert[0]:
            w.statusBar().showMessage("BITCOIN CORE ALERT: " + core_alert[0])
        self.textedit.insertPlainText(txt)

    def resizeScroll(self, mini, maxi):
        self.textedit.verticalScrollBar().setValue(maxi)

    def startSendPayment(self, ignored_makers = None):
        self.aborted = False
        if not self.validateSettings():
            return
        if jm_single().config.get("BLOCKCHAIN", "blockchain_source")=='blockr':
            res = self.showBlockrWarning()
            if res==True:
                return

        #all settings are valid; start
        QMessageBox.information(self,"Sendpayment","Connecting to IRC.\n"+
                                        "View real-time log in the lower pane.")        
        self.startButton.setEnabled(False)
        self.abortButton.setEnabled(True)
    
        jm_single().nickname = random_nick()
    
        log.debug('starting sendpayment')

        w.statusBar().showMessage("Syncing wallet ...")
        jm_single().bc_interface.sync_wallet(w.wallet)
    
        self.irc = IRCMessageChannel(jm_single().nickname)
        self.destaddr = str(self.widgets[0][1].text())
        #convert from bitcoins (enforced by QDoubleValidator) to satoshis
        self.btc_amount_str = str(self.widgets[3][1].text())
        amount = int(Decimal(self.btc_amount_str)*Decimal('1e8'))
        makercount = int(self.widgets[1][1].text())
        mixdepth = int(self.widgets[2][1].text())
        self.taker = SendPayment(self.irc, w.wallet, self.destaddr, amount,
                                 makercount,
                                 jm_single().config.getint("GUI", "txfee_default"),
                                 jm_single().config.getint("GUI", "order_wait_time"),
                                 mixdepth, False, weighted_order_choose,
                                 isolated=True)
        self.pt = PT(self.taker)
        if ignored_makers:
            self.pt.ignored_makers.extend(ignored_makers)
        thread = TaskThread(self)
        thread.add(self.runIRC, on_done=self.cleanUp)                
        w.statusBar().showMessage("Connecting to IRC ...")
        thread2 = TaskThread(self)
        thread2.add(self.createTxThread, on_done=self.doTx)      
    
    def createTxThread(self):
        self.orders, self.total_cj_fee, self.cjamount, self.utxos = self.pt.create_tx()
        log.debug("Finished create_tx")
        #TODO this can't be done in a thread as currently built;
        #how else? or fix?
        #w.statusBar().showMessage("Found counterparties...")
    
    def doTx(self):
        if not self.orders:
            QMessageBox.warning(self,"Error","Not enough matching orders found.")
            self.giveUp()
            return

        total_fee_pc = 1.0 * self.total_cj_fee / self.cjamount

        #reset the btc amount display string if it's a sweep:
        if self.taker.amount == 0:
            self.btc_amount_str = str((Decimal(self.cjamount)/Decimal('1e8')))

        mbinfo = []
        if joinmarket_alert[0]:
            mbinfo.append("<b><font color=red>JOINMARKET ALERT: " +
                          joinmarket_alert[0] + "</font></b>")
            mbinfo.append(" ")
        if core_alert[0]:
            mbinfo.append("<b><font color=red>BITCOIN CORE ALERT: " +
                          core_alert[0] + "</font></b>")
            mbinfo.append(" ")
        mbinfo.append("Sending amount: " + self.btc_amount_str + " BTC")
        mbinfo.append("to address: " + self.destaddr)
        mbinfo.append(" ")
        mbinfo.append("Counterparties chosen:")
        mbinfo.append('Name,     Order id, Coinjoin fee (sat.)')
        for k,o in self.orders.iteritems():
            if o['ordertype']=='relorder':
                display_fee = int(self.cjamount*float(o['cjfee'])) - int(o['txfee'])
            elif o['ordertype'] ==  'absorder':
                display_fee = int(o['cjfee']) - int(o['txfee'])
            else:
                log.debug("Unsupported order type: " + str(
                    o['ordertype']) + ", aborting.")
                self.giveUp()
                return
            mbinfo.append(k + ', ' + str(o['oid']) + ',         ' + str(display_fee))
        mbinfo.append('Total coinjoin fee = ' +str(
            self.total_cj_fee) + ' satoshis, or ' + str(float('%.3g' % (
                100.0 * total_fee_pc))) + '%')
        title = 'Check Transaction'
        if total_fee_pc * 100 > jm_single().config.getint("GUI","check_high_fee"):
            title += ': WARNING: Fee is HIGH!!'
        reply = QMessageBox.question(self,
                                     title,'\n'.join([m + '<p>' for m in mbinfo]),
                                     QMessageBox.Yes,QMessageBox.No)
        if reply == QMessageBox.Yes:
            log.debug('You agreed, transaction proceeding')
            w.statusBar().showMessage("Building transaction...")
            thread3 = TaskThread(self)
            log.debug("Trigger is: "+str(self.donateLimitBox.value()))
            if get_network()=='testnet':
                da = donation_address_testnet
            else:
                da = donation_address
            thread3.add(partial(self.pt.do_tx,self.total_cj_fee, self.orders,
                                self.cjamount, self.utxos,
                                self.donateCheckBox.isChecked(),
                                self.donateLimitBox.value(),
                                da),
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
                if not self.pt.ignored_makers:
                    w.statusBar().showMessage("Transaction failed.")
                    QMessageBox.warning(self,"Failed","Transaction was not completed.")
                else:
                    reply = QMessageBox.question(self, "Transaction not completed.",
                    '\n'.join(["The following counterparties did not respond: ",
                    ','.join(self.pt.ignored_makers),
                    "This sometimes happens due to bad network connections.",
                    "",
                    "If you would like to try again, ignoring those",
                    "counterparties, click Yes."]), QMessageBox.Yes, QMessageBox.No)
                    if reply == QMessageBox.Yes:
                        self.startSendPayment(ignored_makers=self.pt.ignored_makers)
                    else:
                        self.giveUp()
                        return

        else:
            w.statusBar().showMessage("Transaction completed successfully.")
            QMessageBox.information(self,"Success",
                                    "Transaction has been broadcast.\n"+
                                "Txid: "+str(self.taker.txid))
            #persist the transaction to history
            with open(jm_single().config.get("GUI", "history_file"),'ab') as f:
                f.write(','.join([self.destaddr, self.btc_amount_str,
                        self.taker.txid,
                        datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")]))
                f.write('\n') #TODO: Windows
            #update the TxHistory tab
            txhist = w.centralWidget().widget(3)
            txhist.updateTxInfo()

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

    def showBlockrWarning(self):
        if jm_single().config.getint("GUI", "privacy_warning") == 0:
            return False
        qmb = QMessageBox()
        qmb.setIcon(QMessageBox.Warning)
        qmb.setWindowTitle("Privacy Warning")
        qcb = QCheckBox("Don't show this warning again.")
        lyt = qmb.layout()
        lyt.addWidget(QLabel(warnings['blockr_privacy']), 0, 1)
        lyt.addWidget(qcb, 1, 1)
        qmb.addButton(QPushButton("Continue"), QMessageBox.YesRole)
        qmb.addButton(QPushButton("Cancel"), QMessageBox.NoRole)

        qmb.exec_()

        switch_off_warning = '0' if qcb.isChecked() else '1'
        jm_single().config.set("GUI","privacy_warning", switch_off_warning)

        res = qmb.buttonRole(qmb.clickedButton())
        if res == QMessageBox.YesRole:
            return False
        elif res == QMessageBox.NoRole:
            return True
        else:
            log.debug("GUI error: unrecognized button, canceling.")
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
                         'The amount IN BITCOINS to send.\n'+
                         'If you enter 0, a SWEEP transaction\nwill be performed,'+
                         ' spending all the coins \nin the given mixdepth.']
        sT = [str, int, int, float]
        #todo maxmixdepth
        sMM = ['',(2,20),(0,jm_single().config.getint("GUI","max_mix_depth")-1),
               (0.00000001,100.0,8)]
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
        

class TxHistoryTab(QWidget):
    def __init__(self):
        super(TxHistoryTab, self).__init__()
        self.initUI()

    def initUI(self):
        self.tHTW = MyTreeWidget(self,
                                    self.create_menu, self.getHeaders())
        self.tHTW.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tHTW.header().setResizeMode(QHeaderView.Interactive)
        self.tHTW.header().setStretchLastSection(False)
        self.tHTW.on_update = self.updateTxInfo
        vbox = QVBoxLayout()
        self.setLayout(vbox)
        vbox.setMargin(0)
        vbox.setSpacing(0)
        vbox.addWidget(self.tHTW)
        self.updateTxInfo()
        self.show()

    def getHeaders(self):
            '''Function included in case dynamic in future'''
            return ['Receiving address','Amount in BTC','Transaction id','Date']

    def updateTxInfo(self, txinfo=None):
        self.tHTW.clear()
        if not txinfo:
            txinfo = self.getTxInfoFromFile()
        for t in txinfo:
            t_item = QTreeWidgetItem(t)
            self.tHTW.addChild(t_item)
        for i in range(4):
            self.tHTW.resizeColumnToContents(i)

    def getTxInfoFromFile(self):
        hf = jm_single().config.get("GUI", "history_file")
        if not os.path.isfile(hf):
            if w:
                w.statusBar().showMessage("No transaction history found.")
            return []
        txhist = []
        with open(hf,'rb') as f:
            txlines = f.readlines()
            for tl in txlines:
                txhist.append(tl.strip().split(','))
                if not len(txhist[-1])==4:
                    QMessageBox.warning(self,"Error",
                                "Incorrectedly formatted file "+hf)
                    w.statusBar().showMessage("No transaction history found.")
                    return []
        return txhist[::-1] #appended to file in date order, window shows reverse

    def create_menu(self, position):
        item = self.tHTW.currentItem()
        if not item:
            return
        address_valid = False
        if item:
            address = str(item.text(0))
            try:
                btc.b58check_to_hex(address)
                address_valid = True
            except AssertionError:
                log.debug('no btc address found, not creating menu item')

        menu = QMenu()
        if address_valid:
            menu.addAction("Copy address to clipboard",
                           lambda: app.clipboard().setText(address))
        menu.addAction("Copy transaction id to clipboard",
                       lambda: app.clipboard().setText(str(item.text(2))))
        menu.addAction("Copy full tx info to clipboard",
                       lambda: app.clipboard().setText(
                           ','.join([str(item.text(_)) for _ in range(4)])))
        menu.exec_(self.tHTW.viewport().mapToGlobal(position))

class JMWalletTab(QWidget):
    def __init__(self):
        super(JMWalletTab, self).__init__()
        self.wallet_name = 'NONE'
        self.initUI()
    
    def initUI(self):
        self.label1 = QLabel(
            "CURRENT WALLET: "+self.wallet_name + ', total balance: 0.0',
                             self)
        v = MyTreeWidget(self, self.create_menu, self.getHeaders())
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

    def create_menu(self, position):
        item = self.history.currentItem()
        address_valid = False
        if item:
            address = str(item.text(0))
            try:
                btc.b58check_to_hex(address)
                address_valid = True
            except AssertionError:
                log.debug('no btc address found, not creating menu item')

        menu = QMenu()
        if address_valid:
            menu.addAction("Copy address to clipboard",
                           lambda: app.clipboard().setText(address))
        menu.addAction("Resync wallet from blockchain", lambda: w.resyncWallet())
        #TODO add more items to context menu
        menu.exec_(self.history.viewport().mapToGlobal(position))

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

        for i in range(jm_single().config.getint("GUI","max_mix_depth")):
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
    
    def closeEvent(self, event):
        quit_msg = "Are you sure you want to quit?"
        reply = QMessageBox.question(self, appWindowTitle, quit_msg,
                                     QMessageBox.Yes, QMessageBox.No)
        if reply == QMessageBox.Yes:
            persist_config()
            event.accept()
        else:
            event.ignore()

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
        msgbox = QDialog(self)
        lyt = QVBoxLayout(msgbox)
        msgbox.setWindowTitle(appWindowTitle)
        label1 = QLabel()
        label1.setText("<a href="+
                       "'https://github.com/joinmarket-org/joinmarket/wiki'>"+
                       "Read more about Joinmarket</a><p>"+
                       "<p>".join(["Joinmarket core software version: "+JM_CORE_VERSION,
                                   "JoinmarketQt version: "+JM_GUI_VERSION,
                                   "Messaging protocol version:"+" %s" % (
                           str(jm_single().JM_VERSION)),
                        "Help us support Bitcoin fungibility -",
                        "donate here: "]))
        label2 = QLabel(donation_address)
        for l in [label1, label2]:
            l.setTextFormat(QtCore.Qt.RichText)
            l.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
            l.setOpenExternalLinks(True)
        label2.setText("<a href='bitcoin:"+donation_address+"'>"+donation_address+"</a>")
        lyt.addWidget(label1)
        lyt.addWidget(label2)
        btnbox = QDialogButtonBox(msgbox)
        btnbox.setStandardButtons(QDialogButtonBox.Ok)
        btnbox.accepted.connect(msgbox.accept)
        lyt.addWidget(btnbox)
        msgbox.exec_()

    def recoverWallet(self):
        if get_network()=='testnet':
            QMessageBox.information(self, 'Error',
                            'recover from seedphrase not supported for testnet')
            return
        d = QDialog(self)
        d.setModal(1)
        d.setWindowTitle('Recover from seed')
        layout = QGridLayout(d)
        message_e = QTextEdit()
        layout.addWidget(QLabel('Enter 12 words'), 0, 0)
        layout.addWidget(message_e, 1, 0)
        hbox = QHBoxLayout()       
        buttonBox = QDialogButtonBox(self)
        buttonBox.setStandardButtons(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttonBox.button(QDialogButtonBox.Ok).clicked.connect(d.accept)
        buttonBox.button(QDialogButtonBox.Cancel).clicked.connect(d.reject)
        hbox.addWidget(buttonBox)
        layout.addLayout(hbox, 3, 0)
        result = d.exec_()
        if result != QDialog.Accepted:
            return
        msg = str(message_e.toPlainText())
        words = msg.split() #splits on any number of ws chars
        if not len(words)==12:
            QMessageBox.warning(self, "Error","You did not provide 12 words, aborting.")
        else:
            try:
                seed = mn_decode(words)
                self.initWallet(seed=seed)
            except ValueError as e:
                QMessageBox.warning(self, "Error",
                                    "Could not decode seedphrase: "+repr(e))

    def selectWallet(self, testnet_seed=None):
        if get_network() != 'testnet':
            current_path = os.path.dirname(os.path.realpath(__file__))
            if os.path.isdir(os.path.join(current_path,'wallets')):
                current_path = os.path.join(current_path,'wallets')
            firstarg = QFileDialog.getOpenFileName(self, 'Choose Wallet File', 
                    directory=current_path)
            #TODO validate the file looks vaguely like a wallet file
            log.debug('Looking for wallet in: '+firstarg)
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
            self.wallet = Wallet(str(firstarg),
                max_mix_depth=jm_single().config.getint("GUI","max_mix_depth"),
                pwd=pwd)
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
        log.debug('generating wallet')
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

        walletfile = create_wallet_file(str(pd.new_pw.text()), seed)
        walletname, ok = QInputDialog.getText(self, 'Choose wallet name', 
                    'Enter wallet file name:', QLineEdit.Normal,"wallet.json")
        if not ok:
            QMessageBox.warning(self,"Error","Create wallet aborted")
            return
        #create wallets subdir if it doesn't exist
        if not os.path.exists('wallets'):
            os.makedirs('wallets')
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
            for k in range(wallet.index[m][forchange] + jm_single().config.getint(
                "GUI", "gaplimit")):
                addr = wallet.get_addr(m, forchange, k)
                balance = 0.0
                for addrvalue in wallet.unspent.values():
                    if addr == addrvalue['address']:
                        balance += addrvalue['value']
                balance_depth += balance
                used = ('used' if k < wallet.index[m][forchange] else 'new')
                if balance > 0.0 or (
                    k >= wallet.index[m][forchange] and forchange==0):
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
update_config_for_gui()

#we're not downloading from github, so logs dir
#might not exist
if not os.path.exists('logs'):
    os.makedirs('logs')
app = QApplication(sys.argv)
appWindowTitle = 'JoinMarketQt'
w = JMMainWindow()
tabWidget = QTabWidget(w)
tabWidget.addTab(JMWalletTab(), "JM Wallet")
settingsTab = SettingsTab()
tabWidget.addTab(settingsTab, "Settings")
tabWidget.addTab(SpendTab(), "Send Payment")
tabWidget.addTab(TxHistoryTab(), "Tx History")
w.resize(600, 500)
suffix = ' - Testnet' if get_network() == 'testnet' else ''
w.setWindowTitle(appWindowTitle + suffix)
tabWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
w.setCentralWidget(tabWidget)
w.show()

sys.exit(app.exec_())