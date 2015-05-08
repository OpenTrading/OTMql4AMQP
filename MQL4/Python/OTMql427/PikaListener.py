# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""
This module can be run from the command line to test RabbitMQ
by listening to the broker for messages sent by a speaker
such as PikaChart.py. For example, to see bars and timer topics do:
  python PikaListener.py -v 4 'bar.#' 'timer.#'
The known topics are: bar tick timer retval

Give  --help to see the options.
"""

# We will only have one Pika Connection for any given process, so
# we assign the connection object to the module variable oCONNECTION.
oCONNECTION = None

import sys, logging
import time
import threading

import pika

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

lKNOWN_TOPICS=['tick', 'timer', 'retval', 'bar', 'cmd'] # 'exec'
oLOG = logging

class PikaMixin(object):

    iDeliveryMode = 1 # (non-persisted)
    sContentType = 'text/plain'

    def __init__(self, sChartId, **dParams):
        self.oSpeakerChannel = None
        self.oListenerChannel = None
        self.oListenerThread = None
        self.oListenerServer = None
        self.sChartId = sChartId
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
    
    def eBindBlockingSpeaker(self):
        """
        We are going to use our Speaker channel as a broadcast
        channel for ticks, so we will set it up as a "topic".
        """
        if self.oSpeakerChannel is None:
            self.oCreateConnection()
            oChannel = self.oConnection.channel()

            oChannel.exchange_declare(exchange=self.sExchangeName,
                                      passive=False,
                                      # auto_delete=True,
                                      type='topic')

            time.sleep(0.1)
            self.oSpeakerChannel = oChannel

    def eBindBlockingListener(self, sQueueName, lBindingKeys=None):
        """
        """
        if self.oListenerChannel is None:
            if lBindingKeys is None:
                lBindingKeys = ['#']
            self.oCreateConnection()
            oChannel = self.oConnection.channel()

            oChannel.exchange_declare(exchange=self.sExchangeName,
                                      passive=False,
                                      # auto_delete=True,
                                      type='topic')
            # oResult = oChannel.queue_declare(exclusive=True)
            # self.oListenerQueueName = oResult.method.queue
            # I don't think we want exclusive here:
            # we could have more than one listener,
            # and we could have one listening for retvals...
            oResult = oChannel.queue_declare(queue=sQueueName,
                                             exclusive=False)
            self.oListenerQueueName = sQueueName
            for sBindingKey in lBindingKeys:
                oChannel.queue_bind(exchange=self.sExchangeName,
                                    queue=sQueueName,
                                    routing_key=sBindingKey,
                )
            time.sleep(0.1)
            self.oListenerChannel = oChannel
            
    def eSendOnSpeaker(self, sType, sMsg, sOrigin=None):
        """
        """
        if sType not in lKNOWN_TOPICS:
            # raise?
            return "ERROR: oSpeakerChannel unhandled topic" +sMsg
        # we will break the sChartId up into dots from the underscores
        # That way the end consumer can look at the feed selectively
        sPublishingKey = sType + '.' + self.sChartId.replace('_', '.')

        if sOrigin:
	    # This message is a reply in a cmd
            lOrigin = sOrigin.split("|")
            assert lOrigin[0] == 'cmd', repr(lOrigin)
            sMark = lOrigin[3]
            lMsg = sMsg.split("|")
            assert lMsg[0] == 'retval', repr(lMsg)
            lMsg[3] = sMark
	    # Replace the mark in the reply with the mark in the cmd
            sMsg = '|'.join(lMsg)
            
        if self.oSpeakerChannel is None:
            self.eBindBlockingSpeaker()

        assert self.oSpeakerChannel, "ERROR: oSpeakerChannel is null"
        
        self.oSpeakerChannel.basic_publish(exchange=self.sExchangeName,
                                           routing_key=sPublishingKey,
                                           body=sMsg,
                                           mandatory=False, immediate=False,
                                           properties=self.oProperties)

        return ""

    def vPikaRecvOnListener(self, sQueueName, lBindingKeys):
        if self.oListenerChannel is None:
            self.eBindBlockingListener(sQueueName, lBindingKeys)
        assert self.oListenerChannel
        #FixMe: does this block?
        # http://www.rabbitmq.com/amqp-0-9-1-reference.html#basic.consume
        # no-wait no-wait
        # not in pika.channel.Channel.basic_consume
        self.oListenerChannel.basic_consume(self.vPikaCallbackOnListener,
                                            queue=self.oListenerQueueName,
                                            exclusive=True,
                                            no_ack=False
        )
        
    def vPyCallbackOnListener(self, oChannel, oMethod, oProperties, lBody):
        # dir(oProperties) = [app_id', 'cluster_id', 'content_encoding', 'content_type', 'correlation_id', 'decode', 'delivery_mode', 'encode', 'expiration', 'headers', 'message_id', 'priority', 'reply_to', 'timestamp', 'type', 'user_id']
        sMess = "vPyCallbackOnListener: %r" % (lBody, )
        print "INFO: " +sMess
        oChannel.basic_ack(delivery_tag=oMethod.delivery_tag)
        
    def vPyRecvOnListener(self, sQueueName,  lBindingKeys):
        if self.oListenerChannel is None:
            self.eBindBlockingListener(sQueueName,  lBindingKeys)
        assert self.oListenerChannel
        #FixMe: does this block? no
        # http://www.rabbitmq.com/amqp-0-9-1-reference.html#basic.consume
        # no-wait no-wait
        # not in pika.channel.Channel.basic_consume
        self.oListenerChannel.basic_consume(self.vPyCallbackOnListener,
                                            queue=self.oListenerQueueName,
                                            # exclusive=True,
        )
        
    def bCloseConnectionSockets(self, oOptions=None):
        global oCONNECTION

        # might be called during a broken __init__
        if not hasattr(self, 'oListenerChannel'): return False

        if self.oListenerChannel:
            # we dont want to purge the queue because we are just a listener
            # blocking_connection.py", line 89, in ready...    self.poll_timeout)
            # throws a select.error: (10004, 'Windows Error 0x2714')
            # self.oListenerChannel.queue_purge(queue=self.oListenerQueueName,
            #                                  nowait=True)
            # TypeError: queue_delete() got an unexpected keyword argument 'callback'
            self.oListenerChannel.queue_delete(queue=self.oListenerQueueName,
                                               nowait=True)
      
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
        oCONNECTION = None

        time.sleep(0.1)
        return True

def iMain():
    from PikaArguments import oParseOptions
    
    sUsage = __doc__.strip()
    oArgParser = oParseOptions(sUsage)
    oOptions = oArgParser.parse_args()
    lArgs = oOptions.lArgs

    # FixMe: if no arguments, run a REPL loop dispatching commands
    assert lArgs

    o = None
    try:
        if oOptions.iVerbose >= 4:
            print "INFO: Listening with binding keys: " +" ".join(lArgs)
        o = PikaMixin('oUSDUSD_0_PIKA_0', **oOptions.__dict__)
        
        o.eBindBlockingListener('listen-for-ticks', lArgs)

        i=0
        while i < 5:
            i += 1
            if oOptions.iVerbose >= 4:
                print "DEBUG: Listening: " +str(i)
            try:
                #raises:  pika.exceptions.ConnectionClosed
                o.vPyRecvOnListener('listen-for-ticks', lArgs)
                break
            except  pika.exceptions.ConnectionClosed:
                print "WARN: ConnectionClosed vPyRecvOnListener " +str(i)
                continue
        i=0
        while True:
            i += 1
            try:
                # o.oListenerChannel.start_consuming()
                o.oConnection.process_data_events()
            except  pika.exceptions.ConnectionClosed:
                print "WARN: ConnectionClosed process_data_events" +str(i)
                time.sleep(1)
            
    except KeyboardInterrupt:
        pass
    except Exception, e:
        print "ERROR: " +str(e)

    try:
        if o:
            print "DEBUG: Waiting for message queues to flush..."
            o.bCloseConnectionSockets(oOptions)
            time.sleep(1.0)
    except (KeyboardInterrupt, pika.exceptions.ConsumerCancelled,):
        pass

if __name__ == '__main__':
    iMain()
