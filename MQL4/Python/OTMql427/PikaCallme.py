# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""
This was an attempt at getting callme RPC to work under OTMql4Py.
It's not working yet, but it shouldn't take much to wire it up to
a call in eHeartBeat to look for incoming commands. It's just a
case of unrolling the consume and pulish parts to run a little bit
each time in the main Python thread, without blocking for long.

This module can be run from the command line to test callme
by sending a command to sPySafeEval.
Give  --help to see the options.

"""
import logging
import socket
import threading
import time

# callme has prerequisites
import anyjson
import amqp
import kombu
del amqp
del anyjson

from callme import exceptions as exc
from callme import protocol as pr
from callme import server

oLOG = logging

class Server(server.Server):
    """This Server class is used to provide an RPC server.

    :keyword server_id: id of the server
    :keyword amqp_host: the host of where the AMQP Broker is running
    :keyword amqp_user: the username for the AMQP Broker
    :keyword amqp_password: the password for the AMQP Broker
    :keyword amqp_vhost: the virtual host of the AMQP Broker
    :keyword amqp_port: the port of the AMQP Broker
    :keyword ssl: use SSL connection for the AMQP Broker
    :keyword threaded: use of multithreading, if set to true RPC call-execution
        will processed parallel (one thread per call) which dramatically
        improves performance
    :keyword durable: make all exchanges and queues durable
    :keyword auto_delete: delete queues after all connections are closed
    """

    def __init__(self,
                 server_id,
                 amqp_host='localhost',
                 amqp_user='guest',
                 amqp_password='guest',
                 amqp_vhost='/',
                 amqp_port=5672,
                 ssl=False,
                 threaded=False,
                 durable=False,
                 auto_delete=True):
        super(Server, self).__init__(server_id,
                                     amqp_host, amqp_user, amqp_password,
                                     amqp_vhost, amqp_port, ssl,
                                     threaded, durable, auto_delete)
    def connect(self):
        """Start the server."""
        oLOG.info("Server with id='{0}' started.".format(self._server_id))
        try:
            self.conn = kombu.connections[self._conn].acquire(block=True)
            self.exchange = self._make_exchange(
                'server_{0}_ex'.format(self._server_id),
                durable=self._durable,
                auto_delete=self._auto_delete)
            self.queue = self._make_queue(
                'server_{0}_queue'.format(self._server_id), self.exchange,
                durable=self._durable,
                auto_delete=self._auto_delete)
            self.conn.Consumer(queues=self.queue,
                               callbacks=[self._on_request],
                               accept=['pickle'])
            print "DEBUG: started server"
            self._running.set()
        except socket.error:
            raise exc.ConnectionError("Broker connection failed")

    def _on_request(self, request, message):
        """This method is automatically called when a request is incoming.

        :param request: the body of the amqp message already deserialized
            by kombu
        :param message: the plain amqp kombu.message with additional
            information
        """
        print "Got request: {0}".format(request)
        try:
            message.ack()
        except Exception:
            oLOG.exception("Failed to acknowledge AMQP message.")
        else:
            oLOG.debug("AMQP message acknowledged.")

            # check request type
            if not isinstance(request, pr.RpcRequest):
                oLOG.warning("Request is not a `RpcRequest` instance.")
                return

            # process request
            if self._threaded:
                oThread = threading.Thread(target=self._process_request,
                                     args=(request, message))
                oThread.daemon = True
                oThread.start()
                oLOG.debug("New thread spawned to process the {0} request."
                          .format(request))
            else:
                self._process_request(request, message)

    def drain_event(self, iTimeout=1):
        try:
            # if self.is_running:
            try:
                self.conn.drain_events(timeout=iTimeout)
            except socket.timeout:
                pass
            except Exception:
                oLOG.exception("Draining events failed.")
                return
            except KeyboardInterrupt:
                oLOG.info("Server with id='{0}' stopped.".format(
                    self._server_id))
                return
        except socket.error:
            raise exc.ConnectionError("Broker connection failed")

    def disconnect(self, iTimeout=1):
        try:
            self.stop()
            # need to look at unwrapping the withs
            del self.queue
            del self.exchange
            del self.conn
        except socket.error:
            raise exc.ConnectionError("Broker connection failed")

def iMain():
    import callme
    from PikaArguments import oParseOptions

    sUsage = __doc__.strip()
    oArgParser = oParseOptions(sUsage)
    oArgParser.add_argument('lArgs', action="store",
                            nargs="*",
                            help="the message to send (required)")
    oOptions = oArgParser.parse_args()
    lArgs = oOptions.lArgs

    assert lArgs, "Need the command to send on the commandline"
    sCmd = lArgs[0]

    o = None
    iMax = 20
    i = 0
    try:
        sId1 = 'Mt4Server'
        proxy1 = callme.Proxy(server_id=sId1, timeout=20)
#                 amqp_host='localhost',
#                 amqp_user='guest',
#                 amqp_password='guest',
#                 amqp_vhost='/',
#                 amqp_port=5672,
        while i < iMax:
            i += 1
            if oOptions.iDebugLevel >= 4:
                print "DEBUG: RPC %d for: %s" % (i, sCmd,)
            try:
                # sRetval = proxy1.sPySafeEval('str(' +sCmd +')')
                sRetval = proxy1.eMq4PushQueue(sCmd)
                print "INFO: " +str(sRetval)
                break
            except callme.exceptions.RpcTimeout:
                continue
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print "ERROR: " +str(e)
        raise
    finally:
        # time.sleep(1.0)
        pass

if __name__ == '__main__':
    iMain()
