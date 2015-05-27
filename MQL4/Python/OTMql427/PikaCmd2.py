# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""
This script can be run from the command line to send commands
to a OTMql4Pika enabled Metatrader. It will start a command loop to
listen, send commands, or query the RabbitMQ management interface, based 
on the cmd2 REPL: see cmd2plus.py in https://github.com/OpenTrading/OTMql4Lib

Type help at the command prompt to get more help.

Call the script with --help to see the script options.

The normal usage is:

sub run timer# retval.#  - start a thread listening for messages: timer,tick,retval
pub cmd AccountBalance   - to send a command to OTMql4Pika,
                         the return will be a retval message on the listener
sub hide timer           - stop seeing timer messages (just see the retval.#)
orders list              - list your open order tickets
"""

sCHART__doc__ = """
Set and query the chart used for messages to and from RabbitMQ:
  list   - all the charts the listener has heard of,
           iff you have already started a listener with "sub run"
  get    - get the default chart to be published or subscribed to.
  set ID - set the default chart ID to be published or subscribed to.
  set    - set the default chart to be the last chart the listener has heard of,
           iff you have already started a listener with "sub run"

The chart ID will look something like: oChart_EURGBP_240_93ACD6A2_1
"""

sSUB__doc__ = """
Subscribe to messages from RabbitMQ on a given topic:
  sub topics            - shows topics subscribed to.
  sub run TOPIC1 ...    - start a thread to listen for messages,
                          TOPIC is one or more Rabbit topic patterns.
  sub stop              - stop a thread listening for messages.
  sub hide TOPIC        - stop seeing TOPIC messages (e.g. tick - not a pattern)
  sub show              - list the message topics that are being hidden
  sub show TOPIC        - start seeing TOPIC messages (e.g. tick - not a pattern)
  sub pprint ?0|1       - seeing TOPIC messages with pretty-printing,
                          with 0 - off, 1 - on, no argument - current value

Common RabbitMQ topic patterns are: # for all messages, tick.# for ticks,
timer.# for timer events, retval.# for return values.
You can choose as specific chart with syntax like:
    tick.oChart.EURGBP.240.93ACD6A2.#
"""

sPUB__doc__ = """
Publish a message via RabbitMQ to a given chart on a OTMql4Py enabled terminal:
  pub cmd  COMMAND ARG1 ... - publish a Mql command to Mt4,
      the command should be a single string, with a space seperating arguments.
  pub eval COMMAND ARG1 ... - publish a Python command to the OTMql4Py,
      the command should be a single string, with a space seperating arguments.

You wont see the return value unless you have already done a:
  sub run retval.#
"""

sORD__doc__ = """
  ord list          - list the ticket numbers of current orders.
  ord info iTicket  - list the current order information about iTicket.
  ord trades        - list the details of current orders.
  ord history       - list the details of closed orders.
  ord close         - close the order with arguments: iTicket fPrice iSlippage
  ord open
  ord stoploss
  ord trail
  ord exposure      - total exposure of all orders, worst case scenario
  
"""

sBAC__doc__ = """
"""

lRABBIT_GET_THUNKS = ['vhost_names', 'channels',
                      'connections', 'queues']
sRABBIT__doc__ = """
If we have pyrabbit installed, and iff the rabbitmq_management plugin
has been installed in your server, we can introspect some useful
information if the HTTP interface is enabled. Commands include:
    get %s
""" % (" or ".join(lRABBIT_GET_THUNKS),)

import sys
import os
import json
from pprint import pprint, pformat
import traceback
import threading
import time
import unittest
from pika import exceptions
try:
    import OTrader.OTBackTest as pybacktest
except ImportError:
    # sys.stdout.write("pybacktest not installed: pip install pybacktest\n")
    pybacktest = None
try:
    import pyrabbit
except ImportError:
    # sys.stdout.write("pyrabbit not installed: pip install pyrabbit\n")
    pyrabbit = None

from cmd2plus import Cmd, options, make_option, Cmd2TestCase

from PikaChart import PikaChart
_dCHARTS = {}

class MqlError(Exception):
    pass

def gRetvalToPython(lElts):
    # raises MqlError
    global dPENDING

    sType = lElts[4]
    sVal = lElts[5]
    if sVal == "":
        return ""
    if sType == 'string':
        gRetval = sVal
    elif sType == 'error':
        #? should I raise an error?
        raise MqlError(sVal)
    elif sType == 'datetime':
        #? how do I convert this
        # I think it's epoch seconds as an int
        # but what TZ? TZ of the server?
        # I'll treat it as a float like time.time()
        # but probably better to convert it to datetime
        gRetval = float(sVal)
    elif sType == 'bool':
        gRetval = bool(sVal)
    elif sType == 'int':
        gRetval = int(sVal)
    elif sType == 'json':
        gRetval = json.loads(sVal)
    elif sType == 'double':
        gRetval = float(sVal)
    elif sType == 'none':
        gRetval = None
    elif sType == 'void':
        gRetval = None
    else:
        sys.stdout.write("WARN: unknown type %s in %r\n" % (sType, lElts,))
        gRetval = None
    return gRetval

# should do something better if there are multiple clients
def sMakeMark():
    return "%15.5f" % time.time()

# FixMe:
# The messaging to and from OTMql4Py is still being done with a
# very simple format:
#       sMsgType|sChartId|sIgnored|sMark|sPayload
# where sMsgType is one of: cmd eval (outgoing), timer tick retval (incoming);
#       sChartId is the Mt4 chart sChartId the message is to or from;
#       sMark is a simple floating point timestamp, with milliseconds;
# and   sPayload is command|arg1|arg2... (outgoing) or type|value (incoming),
#       where type is one of: bool int double string json.
# This breaks if the sPayload args or value contain a | -
# we will probably replace this with json or pickled serialization, or kombu.
def sFormatMessage(sMsgType, sChartId, *lArgs):
    """
    Just a very simple message format for now:
    We are moving over to JSON so *lArgs will be replaced by sJson,
    a single JSON list of [command, arg1, arg2,...]
    """
    
    # sMark is a simple timestamp: unix time with msec.
    sMark = sMakeMark()
    # iIgnore is reserved for being a hash on the payload
    iIgnore = 0
    # We are moving over to JSON - for now a command is separated by |
    sInfo = '|'.join(lArgs)
    sMsg = "%s|%s|%d|%s|%s" % (sMsgType, sChartId, iIgnore, sMark, sInfo,)
    return sMsg

def lUnFormatMessage(sBody):
    lArgs = sBody.split('|')
    sCmd = lArgs[0]
    sChart = lArgs[1]
    sIgnore = lArgs[2]
    sMark = lArgs[3]
    return lArgs

class PikaListenerThread(threading.Thread, PikaChart):
    def __init__(self, sName, lTopics, **dArgs):
        dThreadArgs = {'name': sName, 'target': self.run}
        PikaChart.__init__(self, sName, **dArgs)
        threading.Thread.__init__(self, **dThreadArgs)
        self.oLocal = threading.local()
        self.lCharts = []
        self.jLastRetval = []
        self.jLastTick = []
        self.gLastTimer = []
        self._running = threading.Event()
        if not lTopics:
            self.lTopics = ['#']
        else:
            self.lTopics = lTopics
        self.bPprint = False
        self.lHide = []
        # eBindBlockingListener
        self.vPyRecvOnListener('listen-for-ticks', self.lTopics)
        self._running.set()

    def run(self):
        try:
            while self._running.is_set() and len(self.oListenerChannel._consumers):
                self.oListenerChannel.connection.process_data_events()
        except (exceptions.ConsumerCancelled, KeyboardInterrupt,):
            pass

    def stop(self):
        self._running.clear()
        #? self.oListenerChannel.stop_consuming()
        
    def vPprint(self, sMsgType, sMsg=None):
        if sMsgType == 'get':
            sys.stdout.write("INFO: bPprint" +repr(self.bPprint) + "\n")
        elif sMsgType == 'set':
            self.bPprint = bool(sMsg)
        elif sMsgType in self.lHide:
            pass
        elif self.bPprint and sMsg:
            # may need more info here - chart and sMark
            sys.stdout.write("INFO: " +sMsgType +" = " +pformat(sMsg) +"\n")
        else:
            sys.stdout.write("INFO: " +sMsgType +" = " +repr(sMsg) +"\n")
        
    def vHide(self, sMsgType=None):
        if not sMsgType:
            sys.stdout.write("INFO: hiding" +repr(self.lHide) + "\n")
            return
        if sMsgType not in self.lHide:
            self.lHide.append(sMsgType)
            
    def vShow(self, sMsgType=None):
        if not sMsgType:
            sys.stdout.write("INFO: hiding" +repr(self.lHide) + "\n")
            return
        if sMsgType in self.lHide:
            self.lHide.remove(sMsgType)
            
    def vPyCallbackOnListener(self, oChannel, oMethod, oProperties, sBody):
        # dir(oProperties) = [app_id', 'cluster_id', 'content_encoding', 'content_type', 'correlation_id', 'decode', 'delivery_mode', 'encode', 'expiration', 'headers', 'message_id', 'priority', 'reply_to', 'timestamp', 'type', 'user_id']
        
        oChannel.basic_ack(delivery_tag=oMethod.delivery_tag)
        lArgs = lUnFormatMessage(sBody)
        sMsgType = lArgs[0]
        sChart = lArgs[1]
        sIgnore = lArgs[2] # should be a hash on the payload
        sMark = lArgs[3]
        sPayloadType = lArgs[4]
        gPayload = lArgs[4:] # overwritten below
        try:
            # keep a list of charts that we have seen for "chart list"
            if sChart not in self.lCharts:
                self.lCharts.append(sChart)

            if sMsgType == 'retval':
                gPayload = gRetvalToPython(lArgs)
                self.jLastRetval = gPayload
            elif sMsgType == 'tick':
                assert sPayloadType == 'json', \
                    sMsgType +" sPayloadType expected 'json'" +"\n" +sBody
                # can use this to find the current bid and ask
                gPayload =json.loads(lArgs[5])
                self.jLastTick = gPayload
            elif sMsgType == 'timer':
                assert sPayloadType == 'json', \
                    sMsgType +" sPayloadType expected 'json'" +"\n" +sBody
                # can use this to find if we are currently connected
                gPayload = json.loads(lArgs[5])
                self.gLastTimer = gPayload
            else:
                vWarn("vPyCallbackOnListener unrecognized sMsgType: %r" % (sBody, ))
                return
                
            self.vPprint(sMsgType, G(gPayload))
        except Exception, e:
            sys.stderr.write(traceback.format_exc(10) +"\n")

_G = None
def G(gRetval=None):
    global _G
    _G = gRetval
    return gRetval

class CmdLineApp(Cmd):
    multilineCommands = []
    testfiles = ['exampleSession.txt']

    oChart = None
    oListenerThread = None
    oRabbit = None
    prompt = 'OTPy> '
    
    def __init__(self, oOptions, lArgs):
        Cmd.__init__(self)
        self.oOptions = oOptions
        self.lArgs = lArgs
        self.lTopics = ['#']
        self.sDefaultChart = oOptions.sDefaultChartId
        del oOptions.__dict__['sDefaultChartId']
        # FixMe: refactor for multiple charts
        self.dCharts = {}
        # Keep a copy of what goes out;
        # I'm not sure how these will be used yet.
        self.dLastCmd = {}
        self.dLastEval = {}
        self.dLastJson = {}
        self.oBt = None
        
    def G(self):
        global _G
        return _G
    
    def eSendOnSpeaker(self, sChartId, sMsgType, sMsg):
        if self.oListenerThread is None:
            self.vWarn("PikaListenerThread not started; you wont see the retval")
        if not self.oChart:
            # FixMe: refactor for multiple charts
            self.oChart = PikaChart(sChartId, **self.oOptions.__dict__)
        # if sMsgType == 'cmd': warn if not Mt4 connected?
        return(self.oChart.eSendOnSpeaker(sMsgType, sMsg))
    
    ## charts
    def do_chart(self, oArgs, oOpts=None):
        __doc__ = sCHART__doc__
        if not oArgs:
            self.poutput("Chart operations are required\n" + __doc__)
            return
        lArgs = oArgs.split()
        if lArgs[0] == 'get':
            self.poutput(G(self.sDefaultChart))
            return
        
        if lArgs[0] == 'set':
            if len(lArgs) > 1:
                self.sDefaultChart = G(lArgs[1])
            elif self.oListenerThread.lCharts:
                self.sDefaultChart = G(self.oListenerThread.lCharts[-1])
            else:
                self.vWarn("No default charts available; try 'sub run'")
            return
        
        if lArgs[0] == 'list':
            if self.oListenerThread is None:
                self.poutput(repr(G([])))
            else:
                self.poutput(repr(G(self.oListenerThread.lCharts)))
            return
        self.vError("Unrecognized chart command: " + str(oArgs))
        
    ## subscribe
    @options([make_option("-c", "--chart",
                            dest="sChartId",
                            help="the target chart to subscribe to"),
    ],
               arg_desc="command",
               usage=sSUB__doc__,
    )
    def do_sub(self, oArgs, oOpts=None):
        __doc__ = sSUB__doc__
        if not oArgs:
            self.poutput("Topics to subscribe to (optionally including # or *) are required\n" + __doc__)
            return
        if oOpts and oOpts.sChartId:
            sChartId = oOpts.sChartId
        else:
            sChartId = self.sDefaultChart

        lArgs = oArgs.split()
        if lArgs[0] == 'topics':
            # what if self.oListenerThread is not None:
            assert len(lArgs) > 1, "ERROR: sub topics TOPIC1..."
            self.lTopics = lArgs[1:]
            self.vInfo("Set topics to: " + repr(G(self.lTopics)))
            return

        if lArgs[0] == 'clear':
            # what if self.oListenerThread is not None:
            # do we dynamically change the subsciption or terminate the thread?
            self.lTopics = []
            return

        if lArgs[0] == 'topics':
            if self.oListenerThread:
                self.poutput("oListenerThread.lTopics: " + repr(G(self.oListenerThread.lTopics)))
            else:
                self.poutput("Default lTopics: " + repr(G(self.lTopics)))
            return

        if lArgs[0] == 'run':
            if self.oListenerThread is None:
                if len(lArgs) > 1:
                    self.lTopics = lArgs[1:]
                self.vInfo("Starting PikaListenerThread listening to to: " + repr(G(self.lTopics)))
                self.oListenerThread = PikaListenerThread(sChartId, self.lTopics,
                                                          **self.oOptions.__dict__)
                self.oListenerThread.start()
            else:
                self.vWarn("PikaListenerThread already listening to: " + repr(self.oListenerThread.lTopics))

            return

        if lArgs[0] == 'stop':
            if not self.oListenerThread:
                self.vWarn("PikaListenerThread not already started")
                return
            self.pfeedback("oListenerThread.stop()")
            self.oListenerThread.stop()
            self.oListenerThread.join()
            self.oListenerThread = None
            return

        if lArgs[0] == 'hide':
            if not self.oListenerThread:
                self.vWarn("PikaListenerThread not already started")
                return
            if len(lArgs) == 1:
                self.oListenerThread.vHide()
            else:
                for sElt in lArgs[1:]:
                    self.oListenerThread.vHide(sElt)
            return
        
        if lArgs[0] == 'show':
            if not self.oListenerThread:
                self.vWarn("PikaListenerThread not already started")
                return
            if len(lArgs) == 1:
                self.oListenerThread.vShow()
            else:
                for sElt in lArgs[1:]:
                    self.oListenerThread.vShow(sElt)
            return
        
        if lArgs[0] == 'pprint':
            if not self.oListenerThread:
                self.vWarn("PikaListenerThread not already started")
                return
            if len(lArgs) == 1:
                self.oListenerThread.vPprint('get')
            else:
                self.oListenerThread.vPprint('set', bool(lArgs[1]))
            return
        
        self.vError("Unrecognized subscribe command: " + str(oArgs))
        
    do_subscribe = do_sub
    
    ## publish
    @options([make_option("-c", "--chart",
                            dest="sChartId",
                            help="the target chart to publish to (or: ANY ALL NONE)"),
    ],
               arg_desc="command",
               usage=sPUB__doc__,
    )
    def do_pub(self, oArgs, oOpts=None):
        __doc__ = sPUB__doc__
        if not oArgs:
            self.poutput("Commands to publish (and arguments) are required\n" + __doc__)
            return
        if oOpts and oOpts.sChartId:
            sChartId = oOpts.sChartId
        else:
            sChartId = self.sDefaultChart
        if self.oListenerThread is None:
            self.vError("PikaListenerThread not started; use 'sub run ...'")
            return

        lArgs = oArgs.split()
        if lArgs[0] == 'cmd':
            sMsgType = 'cmd' # Mt4 command
            assert len(lArgs) > 1, "ERROR: pub cmd COMMAND ARG1..."
            sMsg = sFormatMessage(sMsgType, sChartId, *lArgs[1:])
            self.vInfo("Publishing: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            self.dLastCmd[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'eval':
            sMsgType = 'eval'
            assert len(lArgs) > 1, "ERROR: pub eval COMMAND ARG1..."
            sInfo = str(lArgs[1]) # FixMe: how do we distinguish variable or thunk?
            if len(lArgs) > 2:
                sInfo += '(' +str(','.join(lArgs[2:])) +')'
            sMsg = sFormatMessage(sMsgType, sChartId, sInfo,)
            self.vInfo("Publishing: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            self.dLastEval[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'json':
            sMsgType = 'json'
            assert len(lArgs) > 1, "ERROR: pub eval COMMAND ARG1..."
            # FixMe: broken but unused
            sInfo = json.dumps(str(' '.join(lArgs[1:])))
            sMsg = sFormatMessage(sMsgType, sChartId, sInfo,)
            self.vInfo("Publishing: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            self.dLastJson[sChartId] = G(sMsg)
            return
        self.vError("Unrecognized publish command: " + str(oArgs))
        
    do_publish = do_pub
    
    ## orders
    @options([make_option("-c", "--chart",
                            dest="sChartId",
                            help="the target chart to order with (or: ANY ALL NONE)"),
    ],
               arg_desc="command",
               usage=sORD__doc__,
    )
    def do_ord(self, oArgs, oOpts=None):
        __doc__ = sORD__doc__
        if not oArgs:
            self.poutput("Commands to order (and arguments) are required\n" + __doc__)
            return
        if self.oListenerThread is None:
            self.vError("PikaListenerThread not started; use 'sub run ...'")
            return
        
        if oOpts and oOpts.sChartId:
            sChartId = oOpts.sChartId
        else:
            sChartId = self.sDefaultChart

        lArgs = oArgs.split()
        if lArgs[0] == 'list' or lArgs[0] == 'tickets':
            sMsgType = 'cmd' # Mt4 command
            # FixMe: trailing |
            sInfo='jOTOrdersTickets'
            sMsg = sFormatMessage(sMsgType, sChartId, sInfo)
            self.vDebug("Ordering: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            # FixMe: Tag with sMark
            self.dLastCmd[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'trades':
            sMsgType = 'cmd' # Mt4 command
            # FixMe: trailing |
            sInfo='jOTOrdersTrades'
            sMsg = sFormatMessage(sMsgType, sChartId, sInfo)
            self.vDebug("Ordering: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            # FixMe: Tag with sMark
            self.dLastCmd[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'history':
            sMsgType = 'cmd' # Mt4 command
            # FixMe: trailing |
            sInfo='jOTOrdersHistory'
            sMsg = sFormatMessage(sMsgType, sChartId, sInfo)
            self.vDebug("Ordering: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            # FixMe: Tag with sMark
            self.dLastCmd[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'info':
            sMsgType = 'cmd' # Mt4 command
            sCmd='jOTOrderInformation'
            assert len(lArgs) > 1, "ERROR: orders info iTicket"
            sArg1 = str(lArgs[1])
            sMsg = sFormatMessage(sMsgType, sChartId, sCmd, sArg1)
            self.vDebug("Ordering: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            # FixMe: Tag with sMark
            self.dLastCmd[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'exposure':
            sMsgType = 'cmd' # Mt4 command
            sCmd='fOTExposedEcuInMarket'
            sArg1 = str(0)
            sMsg = sFormatMessage(sMsgType, sChartId, sCmd, sArg1)
            self.vDebug("Ordering: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            # FixMe: Tag with sMark
            self.dLastCmd[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'close':
            sMsgType = 'cmd' # Mt4 command
            sCmd='iOTOrderCloseFull'
            assert len(lArgs) == 4, "ERROR: order close iTicket fPrice iSlippage"
            sArg1 = lArgs[1]
            sArg2 = lArgs[2]
            sArg3 = lArgs[3]
            sMsg = sFormatMessage(sMsgType, sChartId, sCmd, sArg1, sArg2, sArg3)
            self.vDebug("Ordering: " +sMsg)
            self.eSendOnSpeaker(sChartId, sMsgType, sMsg)
            # FixMe: Tag with sMark
            self.dLastCmd[sChartId] = G(sMsg)
            return
        # (int iTicket, double fPrice, int iSlippage, color cColor=CLR_NONE)
        self.vError("Unrecognized order command: " + str(oArgs))
        
    do_order = do_ord
    do_orders = do_ord
    
    # backtest
    @options([make_option("-b", "--backtester",
                            dest="sBackTester",
                            help="the backtest package (one of: pybacktest)"),
    ],
               arg_desc="command",
               usage=sBAC__doc__
             )
    def do_back(self, oArgs, oOpts=None):
        __doc__ = sBAC__doc__
        if not pybacktest:
            self.poutput("Install pybacktest from git://github.com/ematvey/pybacktest/")
            return
        if not oArgs:
            self.poutput("Commands to backtest (and arguments) are required\n" + __doc__)
            return
        # unfinished
        from OTrader.BacktestCmd import vDoBacktestCmd
        vDoBacktestCmd(self, oArgs, oOpts=None)
        
    do_bac = do_back
    do_backtest = do_back
    
    ## rabbit
    @options([make_option("-a", "--address",
                            dest="sHttpAddress",
                            default="127.0.0.1",
                            help="the TCP address of the HTTP rabbitmq_management  (default 127.0.0.1)"),
                make_option('-p', '--port', type="int",
                            dest="iHttpPort", default=15672,
                            help="the TCP port of the HTTP rabbitmq_management plugin (default 15672)"),],
               arg_desc="command",
               usage=sRABBIT__doc__
    )
    def do_rabbit(self, oArgs, oOpts=None):
        __doc__ = sRABBIT__doc__
        if not pyrabbit:
            self.poutput("Install pyrabbit from http://pypi.python.org/pypi/pyrabbit")
            return
        if not oArgs:
            self.poutput("Command required: get\n" + __doc__)
            return

        if self.oRabbit is None:
            sTo = oOpts.sHttpAddress +':' +str(oOpts.iHttpPort)
            sUser = self.oOptions.sUsername
            sPass = self.oOptions.sPassword
            self.oRabbit = pyrabbit.api.Client(sTo, sUser, sPass)
            vNullifyLocalhostProxy(oOpts.sHttpAddress)

        lArgs = oArgs.split()
        if lArgs[0] == 'get':
            assert len(lArgs) > 1, "ERROR: one of: get " +",".join(lRABBIT_GET_THUNKS)
            oFun = getattr(self.oRabbit, lArgs[0] +'_' +lArgs[1])
            if lArgs[1] == 'queues':
                lRetval = oFun()
                # do we need a sub-command here?
                lRetval = [x['name'] for x in lRetval]
                self.poutput(repr(G(lRetval)))
            elif lArgs[1] in lRABBIT_GET_THUNKS:
                lRetval = oFun()
                self.poutput(repr(G(lRetval)))
            else:
                self.vError("Choose one of: get " +",".join(lRABBIT_GET_THUNKS))
            return
        self.vError("Unrecognized rabbit command: " + str(oArgs))

    def postloop(self):
        self.vDebug("atexit")
        if self.oListenerThread is not None:
            # for sub
            self.vInfo("oListenerThread.bCloseConnectionSockets")
            self.oListenerThread.bCloseConnectionSockets()
            self.oListenerThread = None
        if self.oChart is not None:
            # for pub
            self.vInfo("oChart.bCloseConnectionSockets")
            # FixMe: refactor for multiple charts
            self.oChart.bCloseConnectionSockets()
            self.oChart = None

    def vError(self, sMsg):
        self.poutput("ERROR: " +sMsg)
        
    def vWarn(self, sMsg):
        self.poutput("WARN: " +sMsg)
        
    def vInfo(self, sMsg):
        self.pfeedback("INFO: " +sMsg)
        
    def vDebug(self, sMsg):
        self.pfeedback("DEBUG: " +sMsg)

def vNullifyLocalhostProxy(sHost):
    """
    We probably dont want to go via a proxy to localhost.
    """
    if sHost not in ['localhost', "127.0.0.1"]: return
    for sElt in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',]:
        if sElt in os.environ: del os.environ[sElt]

class TestMyAppCase(Cmd2TestCase):
    CmdApp = CmdLineApp
    transcriptFileName = 'exampleSession.txt'

def iMain():
    from PikaArguments import oParseOptions

    sUsage = __doc__.strip()
    oArgParser = oParseOptions(sUsage)
    oArgParser.add_argument('-t', '--test',
                            dest='bUnittests', action='store_true', default=False,
                            help='Run unit test suite')
    oArgParser.add_argument('-u', '--use_talib',
                            dest='bUseTalib', action='store_true', default=False,
                            help='Use Ta-lib for chart operations')
    oArgParser.add_argument("-c", "--chart",
                            dest="sDefaultChartId", action='store_true', default='oANY_0_FFFF_0',
                            help="the default target chart to sub or pub")
    #? matplotlib_use?
    oArgParser.add_argument('lArgs', action="store",
                            nargs="*",
                            help="command line arguments (optional)")
    oOptions = oArgParser.parse_args()
    # FixMe: handle command line args?
    # is this default?
    lArgs = oOptions.lArgs

    if oOptions.bUnittests:
        sys.argv = [sys.argv[0]]  # the --test argument upsets unittest.main()
        unittest.main()
        return 0

    oApp = None
    try:
        oApp = CmdLineApp(oOptions, lArgs)
        if lArgs:
            initial_command = ' '.join(lArgs)
            oApp.onecmd_plus_hooks(initial_command + '\n')
            return 0
        else:
            oApp._cmdloop()
            return 0
    except KeyboardInterrupt:
        pass
    except Exception, e:
        print(traceback.format_exc(10))

    if oApp and hasattr(oApp, 'oChart') and oApp.oChart:
        # failsafe
        try:
            print "DEBUG: Waiting for message queues to flush..."
            oApp.oChart.bCloseConnectionSockets(oOptions)
            time.sleep(1.0)
        except (KeyboardInterrupt, exceptions.ConnectionClosed):
            # impatient
            pass

if __name__ == '__main__':
    iMain()

# grep '//0' ../../Libraries/OTMql4/OTLibMt4ProcessCmd.mq4 |sed -e 's/.*== "/pub /' -e 's/".*//' > PikaCmd2-0.test
