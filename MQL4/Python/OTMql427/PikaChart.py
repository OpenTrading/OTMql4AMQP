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
import pika

oLOG = logging

from Mq4Chart import Mq4Chart
from PikaListener import PikaMixin

if True:
    ePikaCallme = "PikaCallme disabled "
    PikaCallme = None
else:
    # The callme server is optional and may not be installed.
    # But it might be a whole lot of fun it it works.
    # It has prerequisities: kombu httplib2 amqp
    try:
        import PikaCallme
        from Mt4SafeEval import sPySafeEval
        ePikaCallme = ""
    except ImportError, e:
        ePikaCallme = "Failed to import PikaCallme: " + str(e)
        PikaCallme = None

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
        sTopic = 'exec'
        sMark = "%15.5f" % time.time()
        sMess = "%s|%s|0|%s|Print|PY: %s" % (sTopic, self.sChartId, sMark, sMark,)
        if self.oQueue.empty():
            # only push if there is nothing to do
            self.eMq4PushQueue(sMess)
            
        # while we are here flush stdout so we can read the log file
        # whilst the program is running
        sys.stdout.flush()
        sys.stderr.flush()

        # now for the hard part - see if there is anything to receive
        # does this block? do we set a timeout?
        if self.oListenerChannel is None:
            lBindingKeys = ['cmd.#']
            self.vPikaRecvOnListener("listen-for-commands", lBindingKeys)

        # This is the disabled callme server code
        if iTimeout > 0 and self.oListenerServer:
            # join it and do a little work but dont block for long
            # cant use self.oListenerServer.wait()
            print "DEBUG: listening on server"
            self.oListenerServer.drain_event(iTimeout=iTimeout)
            
        return ""
    
    def vPikaCallbackOnListener(self, oChannel, oMethod, oProperties, sBody):
        assert sBody
        sMess = "vPikaCallbackOnListener Listened: %r" % sBody
        print "INFO: " +sMess
        # we will assume that the lBody[0]
        # is a "|" seperated list of command and arguments
        # FixMe: the sMess must be in the right format
        self.eMq4PushQueue(sBody)
        oChannel.basic_ack(delivery_tag=oMethod.delivery_tag)

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
    oOptions = oArgParser.parse_args()
    lArgs = oOptions.lArgs

    assert lArgs, "Give the command you want to send as arguments to this script"

    sSymbol = 'USDUSD'
    iPeriod = 0
    sTopic = 'cmd'
    sMark = "%15.5f" % time.time()
    sMsg = "%s|%s|%d|%s|%s" % (sTopic, sSymbol, iPeriod, sMark, '|'.join(lArgs),)
    
    o = None
    try:
        o = PikaChart('oUSDUSD_0_FFFF_0', **oOptions.__dict__)
        iMax = 1
        i = 0
        oLOG.info("Sending: %s %d times " % (sMsg, iMax,))
        while i < iMax:
            # send a burst of iMax copies
            o.eSendOnSpeaker('cmd', sMsg)
            i += 1
        # print "Waiting for message queues to flush..."
        time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    except Exception, e:
        print(str(e))

    try:
        if o:
            print "DEBUG: Waiting for message queues to flush..."
            o.bCloseConnectionSockets(oOptions)
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    iMain()
