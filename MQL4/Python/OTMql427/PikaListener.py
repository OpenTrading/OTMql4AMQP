# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""

This module can be run from the command line to test RabbitMQ
by listening to the broker for messages sent by a speaker
such as PikaChart.py. Give  --help to see the options.
"""

# We will only have on Pika Connection for any given process, so
# we assign the connection object to the module variable oCONNECTION.
oCONNECTION = None

import sys, logging
import time
import threading
import Queue

import pika

oLOG = logging

# The callme server is optional and may not be installed.
# But it might be a whole lot of fun it it works.
# It has prerequisities: kombu httplib2 amqp
try:
    import PikaCallme
    from Mt4SafeEval import sPySafeEval
    ePikaCallme = ""
    def _run_server_thread(server):
        t = threading.Thread(target=server.start)
        t.daemon = True
        t.start()
        return t
except ImportError, e:
    ePikaCallme = "Failed to import PikaCallme: " + str(e)
    PikaCallme = None
    
class PikaMixin(object):

    iDeliveryMode = 1 # (non-persisted)
    sContentType = 'text/plain'

    def __init__(self, **dParams):
        self.oListenerChannel = None
        self.oSpeakerChannel = None
        self.oListenerThread = None
        self.oListenerServer = None
        self.sName = dParams.get('sName', "")
        self.iSpeakerPort = dParams.get('iSpeakerPort', 5672)
        self.iListenerPort = dParams.get('iListenerPort', 5672)
        self.sHostaddress = dParams.get('sHostaddress', '127.0.0.1')
        # I think really this should be program PID specific
        # I think we want one exchange per terminal process
        self.sExchangeName = dParams.get('sExchangeName', 'Mt4')
        self.sUsername = dParams.get('sUsername', 'guest')
        self.sPassword = dParams.get('sPassword', 'guest')
        # I think really this should be Mt4 specific - for permissions
        self.sVirtualHost = dParams.get('sVirtualHost', '/')
        self.iDebugLevel = dParams.get('iDebugLevel', 4)

        self.oCredentials = pika.PlainCredentials(self.sUsername, self.sPassword)
        #? channel_max heartbeat_interval connection_attempts socket_timeout
        self.oParameters = pika.ConnectionParameters(credentials=self.oCredentials,
                                                     host=self.sHostaddress,
                                                     virtual_host=self.sVirtualHost)
        self.oProperties = pika.BasicProperties(content_type=self.sContentType,
                                                delivery_mode=self.iDeliveryMode)
        self.oConnection = None
        self.oQueue = Queue.Queue()
        
    def oCreateConnection(self):
        global oCONNECTION
        if not self.oConnection:
            try:
                oConnection = pika.BlockingConnection(self.oParameters)
                assert oConnection
                self.oConnection = oConnection
                oCONNECTION = oConnection
            except Exception, e:
                oLOG.exception("Error in oCreateConnection " + str(e))
                raise
            
        return self.oConnection
    
    def eHeartBeat(self, sChartName, iTimeout=0):
        """
        The heartbeat is usually called from the Mt4 OnTimer.
        We push a simple Print exec command onto the queue of things
        for Mt4 to do. This way we get a message in the Log,
        but with a string made in Python.
        """
        sTopic = 'exec'
        sMark = "%15.5f" % time.time()
        sMess = "%s|%s|0|%s|Print|PY: %s" % (sTopic, sChartName, sMark, sMark,)
        if self.oQueue.empty():
            # only push if there is nothing to do
            self.eMt4PushQueue(sMess)
            
        # while we are here flush stdout so we can read the log file
        # whilst the program is running
        sys.stdout.flush()
        sys.stderr.flush()

        # now for the hard part - join self.oListenerServer
        if iTimeout > 0 and self.oListenerServer:
            # join it and do a little work but dont block for long
            # cant use self.oListenerServer.wait()
            print "DEBUG: listening on server"
            self.oListenerServer.drain_event(iTimeout=iTimeout)
            
        return sMess
    
    def zMt4PopQueue(self, sChartName):
        """
        The PopQueue is usually called from the Mt4 OnTimer.
        We use is a queue of things for the ProcessCommand in Mt4.
        """
        if self.oQueue.empty():
            return ""
        
        # while we are here flush stdout so we can read the log file
        # whilst the program is running
        sys.stdout.flush()
        sys.stderr.flush()

        return(self.oQueue.get())
    
    def eMt4PushQueue(self, sMessage):
        """
        """
        self.oQueue.put(sMessage)
        return("")
    
    def eMt4Retval(self, sMessage):
        sTopic = 'retval'
        # sMark = "%15.5f" % time.time()
        # FixMe: the sMessage must be in the right format
        sMess = "%s|%s|0|%s" % (sTopic, sChartName, sMessage,)
        self.eMt4PushQueue(sMess)
    
    def eBindBlockingSpeaker(self, sRoutingKey):
        """
        We are going to use our Speaker channel as a broadcast
        channel for ticks, so we will set it up as a "topic".
        """
        if self.oSpeakerChannel is None:
            self.oCreateConnection()
            oChannel = self.oConnection.channel()

            oChannel.exchange_declare(exchange=self.sExchangeName,
                                      passive=False,
                                      auto_delete=True,
                                      type='topic')

            #? oResult = oChannel.queue_declare(exclusive=True)
            #? only one routing key?
            # oChannel.queue_bind(exchange=self.sExchangeName,
            # queue=oResult.method.queue,
            # routing_key=sRoutingKey)
            time.sleep(0.1)
            self.oSpeakerChannel = oChannel

    def eBindBlockingListener(self, sRoutingKey='#'):
        """
        We bind on our Metatrader end, and connect from the scripts.
        """
        if self.oListenerChannel is None:
            self.oCreateConnection()
            oChannel = self.oConnection.channel()

            oChannel.exchange_declare(exchange=self.sExchangeName,
                                      auto_delete=True,
                                      type='topic')
            sQueueName = "listen-to-mt4"
            oResult = oChannel.queue_declare(queue=sQueueName)
            # self.oListenerQueueName = oResult.method.queue
            self.oListenerQueueName = sQueueName
            oChannel.queue_bind(exchange=self.sExchangeName,
                                queue=sQueueName,
                                routing_key=sRoutingKey,
            )
            time.sleep(0.1)
            self.oListenerChannel = oChannel
            
    def eSendOnSpeaker(self, sType, sMsg):
        """
        """
        if sType not in ['tick', 'timer', 'retval', 'bar', 'test']:
            # raise?
            return "ERROR: oSpeakerChannel unhandled topic" +sMsg
        sRoutingKey = sType
        sRoutingKey = 'tick'
        if self.oSpeakerChannel is None:
            self.eBindBlockingSpeaker(sRoutingKey)

        assert self.oSpeakerChannel, "ERROR: oSpeakerChannel is null"
        
        self.oSpeakerChannel.basic_publish(exchange=self.sExchangeName,
                                           routing_key=sRoutingKey,
                                           body=sMsg,
                                           properties=self.oProperties)

        return ""

    def vCallbackOnListener(self, oChannel, oMethod, oProperties, lBody):
        print "INFO: Listened: %r" % (lBody,)
        
    def sRecvOnListener(self):
        self.vRecvOnListener()
        
    def vRecvOnListener(self):
        if self.oListenerChannel is None:
            self.eBindBlockingListener()
        assert self.oListenerChannel
        self.oListenerChannel.basic_consume(self.vCallbackOnListener,
                                            queue=self.oListenerQueueName,
                                            exclusive=True,
                                            no_ack=True)
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
            oServer.register_function(self.eMt4PushQueue, 'eMt4PushQueue')
            self.oListenerServer = oServer
            print "DEBUG: started the callme server %d" % id(oServer)
            
        return ""

    def bCloseConnectionSockets(self, oOptions=None):
        global oCONNECTION

        # might be called during a broken __init__
        if not hasattr(self, 'oListenerThread'): return False
        
        if self.oListenerThread:
            self.oListenerServer.stop()
            self.oListenerThread.join()
            self.oListenerServer = None
            self.oListenerThread = None
        elif self.oListenerServer:
            self.oListenerServer.disconnect()
            self.oListenerServer = None

        if self.iDebugLevel >= 1:
            print "DEBUG: destroying the connection"
        sys.stdout.flush()
        sys.stderr.flush()
        if self.oConnection:
            self.oConnection.close()
        if self.oListenerChannel:
            self.oListenerChannel = None
        if self.oSpeakerChannel:
            self.oSpeakerChannel = None
        time.sleep(0.1)
        oCONNECTION = None
        return True

def iMain():
    from PikaArguments import oParseOptions
    
    sUsage = __doc__.strip()
    oArgParser = oParseOptions(sUsage)
    oOptions = oArgParser.parse_args()
    lArgs = oOptions.lArgs

    # FixMe: handle many?
    sRoutingKey = lArgs[0]

    assert lArgs
    o = None
    try:
        if oOptions.iVerbose >= 4:
            print "INFO: Listening for topics: " +" ".join(lArgs)
        o = PikaMixin(**oOptions.__dict__)
        
        o.eBindBlockingListener(sRoutingKey)
        
        o.sRecvOnListener()
        if oOptions.iVerbose >= 4:
            print "DEBUG: Listening: " 
        o.oListenerChannel.start_consuming()
    except KeyboardInterrupt:
        pass
    except Exception, e:
        print "ERROR: " +str(e)
        raise
    finally:
        if o:
            o.bCloseConnectionSockets(oOptions)
        print "DEBUG: Waiting for message queues to flush..."
        time.sleep(1.0)

if __name__ == '__main__':
    iMain()
