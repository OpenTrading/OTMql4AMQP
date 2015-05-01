# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""
A PikaChart object is a simple abstraction to encapsulate a Mt4 chart
that has a RabbitMQ connection on it. There should be only one connection for
the whole application, so it is set as the module variable oCONNECTION.

This module can be run from the command line to test RabbitMQ with a listener
such as bin/OTZmqSubscribe.py. Give the message you want to publish
as arguments to this script, or --help to see the options.
"""

import sys, logging
import time
import pika

oLOG = logging

from Mq4Chart import Mq4Chart
from PikaListener import PikaMixin

class PikaChart(Mq4Chart, PikaMixin):

    iDeliveryMode = 1 # (non-persisted)
    sContentType = 'text/plain'

    def __init__(self, sSymbol, iPeriod, iIsEA, **dParams):
        Mq4Chart.__init__(self, sSymbol, iPeriod, iIsEA, dParams)
        PikaMixin.__init__(self, **dParams)

def iMain():
    from PikaArguments import oParseOptions
    
    sUsage = __doc__.strip()
    oArgParser = oParseOptions(sUsage)
    oOptions = oArgParser.parse_args()
    lArgs = oOptions.lArgs

    # FixMe:
    sTopic = 'test'

    assert lArgs, "Give the message you want to publish as arguments to this script"
    print lArgs
    o = None
    try:
        if oOptions.iVerbose >= 4:
            oLOG.info("Publishing with message: " +" ".join(lArgs))
        o = PikaChart('Mt4', 0, 0, **oOptions.__dict__)
        iMax = 10
        i = 0
        sMsg = str(lArgs)
        if oOptions.iVerbose >= 4:
            oLOG.debug("Sending: %s %d times " % (sMsg, iMax,))
        while i < iMax:
            # send a burst of 10 copies
            o.eSendOnSpeaker(sTopic, sMsg)
            i += 1
        # print "Waiting for message queues to flush..."
        time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    except Exception, e:
        print(str(e))
        raise
    finally:
        if o:
            o.bCloseConnectionSockets(oOptions)

if __name__ == '__main__':
    iMain()
