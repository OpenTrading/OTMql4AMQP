# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""
This script can be run from the command line to send commands
to a OTMql4Pika enabled Metatrader. It will start a command loop to
listen, send commands, or query the RabbitMQ management interface, based 
on the cmd2 REPL: see cmd2plus.py in https://github.com/OpenTrading/OTMql4Lib

Type help at the command prompt to get more help.

Call the script with --help to see the script options.

The normal usage is:

sub topics timer.# retval.# - to subscribe to a message queue of events
sub run                     - to start a thread listening for messages
pub cmd AccountBalance      - to send a command to OTMql4Pika,
                              the return will be a retval message on the listener
"""

sCHART__doc__ = """
Set and query the chart used for messages to and from RabbitMQ:
  list   - all the charts the listener has heard of,
           iff you have already started a listener with "sub run"
  get    - get the default chart to be published or subscribed to.
  set ID - set the default chart ID to be published or subscribed to.
  set    - set the default chart to be the last chart the listener has heard of,
           iff you have already started a listener with "sub run"
  add    - NOTImplemented
  remove - NOTImplemented

The chart ID will look something like: oChart_EURGBP_240_93ACD6A2_1
"""

sSUB__doc__ = """
Subscribe to messages from RabbitMQ on a given topic:
  sub topics TOPIC1 ... - subscribes to topics.
  sub show              - shows topics subscribed to.
  sub run               - start a thread to listen for messages.
  sub stop              - start a thread to listen for messages.
  sub clear             - clear the list of subscribed topics NOTImplemented.

Common topics are: # for all messages, tick.# for ticks,
timer.# for timer events, retval.# for return values.
You can choose as specific chart with syntax like:
    tick.oChart.EURGBP.240.93ACD6A2.#
"""

sPUB__doc__ = """
Publish a message via RabbitMQ to a given chart on a OTMql4Py enabled terminal:
  pub cmd  COMMAND|ARG1|... - publish a Mql command to Mt4,
      the command should be a single string, with | seperating from arguments.
  pub eval COMMAND|ARG1|... - publish a Python command to the OTMql4Py,
      the command should be a single string, with | seperating from arguments.

"""

sORDERS__doc__ = """
  orders list
  orders close
  orders open
  orders stoploss
  orders trail
  orders exposure
  
"""

lRABBIT_GET_THUNKS = ['vhost_names', 'channels',
                      'connections', 'queues']
sRABBIT__doc__ = """
If we have pyrabbit installed, and iff the rabbitmq_management plugin
has been installed in your server, we can introspect some useful
information if the HTTP interface is enabled. Commands include:
    get %s
""" % (" or ".join(lRABBIT_GET_THUNKS),)

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

import sys
import os
import json
import traceback
import threading
import time
import unittest
from pika import exceptions
try:
    import pyrabbit
except ImportError:
    pyrabbit = None

from cmd2plus import Cmd, options, make_option, Cmd2TestCase

from PikaChart import PikaChart
_dCHARTS = {}

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
        print "WARN: unknown type %s in %r" % (sType, lElts,)
        gRetval = None
    return gRetval

class PikaListenerThread(threading.Thread, PikaChart):
    def __init__(self, sName, lTopics, **dArgs):
        dThreadArgs = {'name': sName, 'target': self.run}
        PikaChart.__init__(self, sName, **dArgs)
        threading.Thread.__init__(self, **dThreadArgs)
        self.oLocal = threading.local()
        self.lCharts = []
        self.gLastRetval = []
        self.gLastTick = []
        self.gLastTimer = []
        self._running = threading.Event()
        if not lTopics:
            self.lTopics = ['#']
        else:
            self.lTopics = lTopics
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

    def vPyCallbackOnListener(self, oChannel, oMethod, oProperties, sBody):
        # dir(oProperties) = [app_id', 'cluster_id', 'content_encoding', 'content_type', 'correlation_id', 'decode', 'delivery_mode', 'encode', 'expiration', 'headers', 'message_id', 'priority', 'reply_to', 'timestamp', 'type', 'user_id']
        sMess = "vPyCallbackOnListener: %r" % (sBody, )
        oChannel.basic_ack(delivery_tag=oMethod.delivery_tag)
        print "INFO: " +sBody
        lArgs = sBody.split('|')
        sCmd = lArgs[0]
        sChart = lArgs[1]
        sIgnore = lArgs[2]
        sMark = lArgs[3]
        try:
            # keep a list of charts that we have seen for "chart list"
            if sChart not in self.lCharts:
                self.lCharts.append(sChart)

            if sCmd == 'retval':
                self.gLastRetval = G(gRetvalToPython(lArgs))
            elif sCmd == 'tick':
                # can use this to find the current bid and ask
                self.gLastTick = lArgs
            elif sCmd == 'timer':
                # can use this to find if we are currently connected
                self.gLastTimer = lArgs
        except Exception, e:
            sys.stderr.write(traceback.format_exc(10) +"\n")
            
# should do something better if there are multiple clients
def sMakeMark():
    # from matplotlib.dates import date2num
    # from datetime import datetime
    # str(date2num(datetime.now()))
    return "%15.5f" % time.time()

_ = None
def G(gRetval=None):
    global _
    _ = gRetval
    return gRetval

class CmdLineApp(Cmd):
    multilineCommands = ['orate']
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

    def do_chart(self, oArgs, oOpts=None):
        __doc__ = sCHART__doc__
        if not oArgs:
            sys.stdout.write("Chart operations are required\n" + __doc__)
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
            sys.stdout.write("Topics to subscribe to (optionally including # or *) are required\n" + __doc__)
            return
        if oOpts and oOpts.sChartId:
            sChartId = oOpts.sChartId
        else:
            sChartId = self.sDefaultChart

        lArgs = oArgs.split()
        if lArgs[0] == 'topics':
            # what if self.oListenerThread is not None:
            self.lTopics = lArgs[1:]
            self.vInfo("Set topics to: " + repr(G(self.lTopics)))
            return

        if lArgs[0] == 'clear':
            # what if self.oListenerThread is not None:
            # do we dynamically change the subsciption or terminate the thread?
            self.lTopics = []
            return

        if lArgs[0] == 'show':
            if self.oListenerThread:
                self.poutput("oListenerThread.lTopics: " + repr(G(self.oListenerThread.lTopics)))
            else:
                self.poutput("lTopics: " + repr(G(self.lTopics)))
            return

        if lArgs[0] == 'run':
            if self.oListenerThread is None:
                self.vInfo("starting PikaListenerThread")
                self.oListenerThread = PikaListenerThread(sChartId, self.lTopics,
                                                          **self.oOptions.__dict__)
            self.oListenerThread.start()
            return

        if lArgs[0] == 'stop':
            if self.oListenerThread is not None:
                self.pfeedback("oListenerThread.stop()")
                self.oListenerThread.stop()
                self.oListenerThread.join()
                self.oListenerThread = None
            return

        self.vError("Unrecognized sub command: " + str(oArgs))
    do_subscribe = do_sub
    
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
            sys.stdout.write("Commands to publish (and arguments) are required\n" + __doc__)
            return
        if oOpts and oOpts.sChartId:
            sChartId = oOpts.sChartId
        else:
            sChartId = self.sDefaultChart
        if not self.oChart:
            # FixMe: refactor for multiple charts
            self.oChart = PikaChart(sChartId, **self.oOptions.__dict__)

        lArgs = oArgs.split()
        if lArgs[0] == 'cmd':
            sTopic = 'cmd'
            iIgnore = 0
            sMark = sMakeMark()
            sInfo = '|'.join(lArgs[1:])
            sMsg = "%s|%s|%d|%s|%s" % (sTopic, sChartId, iIgnore, sMark, sInfo,)
            self.vInfo("Publishing: " +sMsg)
            self.oChart.eSendOnSpeaker(sTopic, sMsg)
            self.dLastCmd[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'eval':
            sTopic = 'eval'
            iIgnore = 0
            sMark = sMakeMark()
            sInfo = str(lArgs[1]) # FixMe: variable or thunk?
            if len(lArgs) > 2:
                sInfo += '(' +str(','.join(lArgs[2:])) +')'
            sMsg = "%s|%s|%d|%s|%s" % (sTopic, sChartId, iIgnore, sMark, sInfo,)
            self.vInfo("Publishing: " +sMsg)
            self.oChart.eSendOnSpeaker(sTopic, sMsg)
            self.dLastEval[sChartId] = G(sMsg)
            return
        
        if lArgs[0] == 'json':
            sTopic = 'json'
            iIgnore = 0
            sMark = sMakeMark()
            sInfo = json.dumps(str(' '.join(lArgs[1:])))
            sMsg = "%s|%s|%d|%s|%s" % (sTopic, sChartId, iIgnore, sMark, sInfo,)
            self.vInfo("Publishing: " +sMsg)
            self.oChart.eSendOnSpeaker(sTopic, sMsg)
            self.dLastJson[sChartId] = G(sMsg)
            return
    do_publish = do_pub
    
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
            sys.stdout.write("pyrabbit not installed: pip install pyrabbit\n")
            return
        if not oArgs:
            sys.stdout.write("Command required: get\n" + __doc__)
            return

        if self.oRabbit is None:
            sTo = oOpts.sHttpAddress +':' +str(oOpts.iHttpPort)
            sUser = self.oOptions.sUsername
            sPass = self.oOptions.sPassword
            self.oRabbit = pyrabbit.api.Client(sTo, sUser, sPass)
            vNullifyLocalhostProxy(oOpts.sHttpAddress)

        lArgs = oArgs.split()
        if lArgs[0] == 'get':
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
    oArgParser.add_argument("-c", "--chart",
                            dest="sDefaultChartId", action='store_true', default='oANY_0_FFFF_0',
                            help="the default target chart to sub or pub")
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
        oApp.cmdloop()
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
