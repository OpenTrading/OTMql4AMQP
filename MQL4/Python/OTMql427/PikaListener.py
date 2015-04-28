# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""

This module can be run from the command line to test RabbitMQ
by listening to the broker for messages sent by a speaker
such as PikaChart.py. Give  --help to see the options.
"""

import sys, logging
import time
import pika

oLOG = logging.getLogger(__name__)

class PikaMixin(object):

    iDeliveryMode = 1 # (non-persisted)
    sContentType = 'text/plain'

    def __init__(self, **dParams):

        self.oSpeakerChannel = None
        self.oListenerChannel = None
        self.iSpeakerPort = dParams.get('iSpeakerPort', 5672)
        self.iListenerPort = dParams.get('iListenerPort', 5672)
        self.sHostaddress = dParams.get('sHostaddress', '127.0.0.1')
        # I think really this should be program PID specific
        self.sExchangeName = dParams.get('sExchangeName', 'Mt4')
        self.sUsername = dParams.get('sUsername', 'guest')
        self.sPassword = dParams.get('sPassword', 'guest')
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
        
    def oCreateConnection(self):
        global oENGINE
        if not self.oConnection:
            oConnection = pika.BlockingConnection(self.oParameters)
            assert oConnection
            self.oConnection = oConnection
            oENGINE = oConnection
        return self.oConnection
    
    def eBindBlockingSpeaker(self, sRoutingKey):
        """
        """
        if self.oSpeakerChannel is None:
            self.oCreateConnection()
            oChannel = self.oConnection.channel()

            oChannel.exchange_declare(exchange=self.sExchangeName, type='topic')

            oResult = oChannel.queue_declare(exclusive=True)
            #? only one routing key?
            oChannel.queue_bind(exchange=self.sExchangeName,
                                queue=oResult.method.queue,
                                routing_key=sRoutingKey)
            time.sleep(0.1)
            self.oSpeakerChannel = oChannel
            self.oSpeakerQueueName = oResult.method.queue

    def eBindBlockingListener(self, sRoutingKey='#'):
        """
        We bind on our Metatrader end, and connect from the scripts.
        """
        if self.oListenerChannel is None:
            self.oCreateConnection()
            oChannel = self.oConnection.channel()

            oChannel.exchange_declare(exchange=self.sExchangeName, type='topic')

            oResult = oChannel.queue_declare(exclusive=True)
            oChannel.queue_bind(exchange=self.sExchangeName,
                                queue=oResult.method.queue,
                                routing_key=sRoutingKey)
            time.sleep(0.1)
            self.oListenerChannel = oChannel
            self.oListenerQueueName = oResult.method.queue
            
    def eSendOnSpeaker(self, sTopic, sMsg):
        if self.oSpeakerChannel is None:
            self.eBindBlockingSpeaker(sTopic)
        assert self.oSpeakerChannel
        self.oSpeakerChannel.basic_publish(self.sExchangeName,
                                           sTopic,
                                           sMsg,
                                           self.oProperties)

        return ""

    def vCallbackOnListener(self, oChannel, oMethod, oProperties, lBody):
       oLOG.info("Listened: %r" % (lBody,))
        
    def sRecvOnListener(self):
        self.vRecvOnListener()
        
    def vRecvOnListener(self):
        if self.oListenerChannel is None:
            self.eBindBlockingListener()
        assert self.oListenerChannel
        self.oListenerChannel.basic_consume(self.vCallbackOnListener,
                                            queue=self.oListenerQueueName,
                                            no_ack=True)

        #? self.oListenerChannel.start_consuming()
        #? timeout?
        # self.oConnection.process_data_events()

    def eSendOnListener(self, sMsg):
        if self.oListenerChannel is None:
            self.eBindListener()
        assert self.oSpeakerChannel
        self.oListenerChannel.send(sMsg)
        return ""

    def bCloseEngineSockets(self):
        global oENGINE
        if self.iDebugLevel >= 1:
           oLOG.info("destroying the engine")
        sys.stdout.flush()
        if self.oConnection:
            self.oConnection.close()
        if self.oListenerChannel:
            self.oListenerChannel = None
        if self.oSpeakerChannel:
            self.oSpeakerChannel = None
        time.sleep(0.1)
        oENGINE = None
        return True

def iMain():
    from OTMql427.PikaArguments import oParseOptions
    
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
        print(str(e))
        raise
    finally:
        if o:
            o.bCloseEngineSockets(oOptions)
        print "Waiting for message queues to flush..."
        time.sleep(1.0)

if __name__ == '__main__':
    iMain()
