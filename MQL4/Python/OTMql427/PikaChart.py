# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""
A PikaChart object is a simple abstraction to encapsulate a Mt4 chart
that has a RabbitMQ connection on it. There should be only one connection for
the whole application, so it is set as the module variable oCONNECTION.

This module can be run from the command line to test RabbitMQ with a listener
such as OTMql427/PikaListener.py. Give the message you want to publish
as arguments to this script, or --help to see the options.
"""

import sys, logging
import time
import traceback
import pika

oLOG = logging

from Mq4Chart import Mq4Chart
from PikaListener import PikaMixin
from Mt4SafeEval import sPySafeEval

if True:
    ePikaCallme = "PikaCallme disabled "
    PikaCallme = None
else:
    # The callme server is optional and may not be installed.
    # But it might be a whole lot of fun it it works.
    # It has prerequisities: kombu httplib2 amqp
    try:
        import PikaCallme
        ePikaCallme = ""
    except ImportError, e:
        ePikaCallme = "Failed to import PikaCallme: " + str(e)
        PikaCallme = None

# FixMe:
# The messaging to and from OTMql4Py is still being done with a
# very simple format:
#       sMsgType|sChartId|sIgnored|sMark|sPayload
# where sMsgType is one of: cmd eval (outgoing), timer tick retval (incoming);
#       sChartId is the Mt4 chart sChartId the message is to or from;
#       sMark is a simple floating point timestamp, with milliseconds;
# and   sPayload is command|arg1|arg2... (outgoing) or type|value (incoming),
#       where type is one of: bool int double string json.
# This breaks if the sPayload args or value contain a | 
# We will probably replace this with json or pickled serialization, or kombu.

class PikaChart(Mq4Chart, PikaMixin):

    iDeliveryMode = 1 # (non-persisted)
    sContentType = 'text/plain'

    def __init__(self, sChartId, **dParams):
        Mq4Chart.__init__(self, sChartId, dParams)
        PikaMixin.__init__(self, sChartId, **dParams)
        self.sChartId = sChartId

    def eHeartBeat(self, iTimeout=0):
        """
        The heartbeat is usually called from the Mt4 OnTimer.
        We push a simple Print exec command onto the queue of things
        for Mt4 to do if there's nothing else happening. This way we get 
        a message in the Mt4 Log,  but with a string made in Python.
        """
        if self.oQueue.empty():
            # only push if there is nothing to do
            sTopic = 'exec'
            sMark = "%15.5f" % time.time()
            sInfo = "PY: " +sMark
            sMess = "%s|%s|0|%s|Print|%s" % (sTopic, self.sChartId, sMark, sInfo,)
            self.eMq4PushQueue(sMess)
            
        # while we are here flush stdout so we can read the log file
        # whilst the program is running
        sys.stdout.flush()
        sys.stderr.flush()

        # now for the hard part - see if there is anything to receive
        # does this block? do we set a timeout?
        if self.oListenerChannel is None:
            lBindingKeys = ['cmd.#', 'eval.#', 'json.#']
            self.vPikaRecvOnListener("listen-for-commands", lBindingKeys)

        # This is the disabled callme server code
        if iTimeout > 0 and self.oListenerServer:
            # join it and do a little work but dont block for long
            # cant use self.oListenerServer.wait()
            print "DEBUG: listening on server"
            self.oListenerServer.drain_event(iTimeout=iTimeout)
            
        return ""
    
    def vPikaCallbackOnListener(self, oChannel, oMethod, oProperties, sBody):
        assert sBody, "vPikaCallbackOnListener: no sBody received"
        sMess = "vPikaCallbackOnListener Listened: %r" % sBody
        oChannel.basic_ack(delivery_tag=oMethod.delivery_tag)
        sys.stdout.write("INFO: " +sMess +"\n")
        sys.stdout.flush()
        # we will assume that the sBody
        # is a "|" seperated list of command and arguments
        # FixMe: the sMess must be in the right format
        # FixMe: refactor for multiple charts:
        # we must push to the right chart
        try:
            lArgs = sBody.split('|')
            if lArgs[0] == 'cmd':
                self.eMq4PushQueue(sBody)
                return
            if lArgs[0] == 'eval':
                lRetval = ['retval']
                lRetval += lArgs[1:3]
                sCmd = lArgs[4]
                if len(lArgs) > 5:
                    sCmd += '(' +lArgs[5] +')'
                sRetval = sPySafeEval(sCmd)
                if sRetval.find('ERROR:') >= 0:
                    lRetval += ['error', sRetval]
                else:
                    lRetval += ['string', sRetval]
                sReturn = '|'.join(lRetval)
                self.eReturnOnSpeaker('retval', sReturn, sBody)
                return
            if lArgs[0] == 'json':
                # FixMe: but why?
                sys.stdout.write("WARN: not yet json: " +sBody +"\n")
                sys.stdout.flush()
                return
        except Exception, e:
            sys.stdout.write("ERROR: " +str(e) +"\n" + \
                             traceback.format_exc(10) +"\n")
            sys.stdout.flush()
            sys.exc_clear()
            
    # unused
    def eStartCallmeServer(self, sId='Mt4Server'):
        # The callme server is optional and may not be installed
        if not PikaCallme:
            return ePikaCallme
        if self.oListenerServer is None:
            oServer = PikaCallme.Server(server_id=sId)
            # danger - we are running this in the main thread
            # self.oListenerThread = _run_server_thread(oServer)
            oServer.connect()
            oServer.register_function(sPySafeEval, 'sPySafeEval')
            oServer.register_function(self.eMq4PushQueue, 'eMq4PushQueue')
            self.oListenerServer = oServer
            print "DEBUG: started the callme server %d" % id(oServer)
            
        return ""

    
def iMain():
    from PikaArguments import oParseOptions
    
    sUsage = __doc__.strip()
    oArgParser = oParseOptions(sUsage)
    oArgParser.add_argument('lArgs', action="store",
                            nargs="*",
                            help="the message to send (required)")
    oOptions = oArgParser.parse_args()
    lArgs = oOptions.lArgs

    assert lArgs, "Give the command you want to send as arguments to this script"

    sSymbol = 'ANY'
    iPeriod = 0
    sTopic = 'cmd'
    sMark = "%15.5f" % time.time()
    sMsg = "%s|%s|%d|%s|%s" % (sTopic, sSymbol, iPeriod, sMark, '|'.join(lArgs),)
    
    oChart = None
    try:
        oChart = PikaChart('oANY_0_FFFF_0', **oOptions.__dict__)
        iMax = 1
        i = 0
        print "Sending: %s %d times " % (sMsg, iMax,)
        while i < iMax:
            # send a burst of iMax copies
            oChart.eSendOnSpeaker('cmd', sMsg)
            i += 1
        # print "Waiting for message queues to flush..."
        time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    except Exception, e:
        print(traceback.format_exc(10))

    try:
        if oChart:
            print "DEBUG: Waiting for message queues to flush..."
            oChart.bCloseConnectionSockets(oOptions)
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    iMain()
