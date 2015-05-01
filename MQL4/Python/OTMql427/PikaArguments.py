# -*-mode: python; py-indent-offset: 4; indent-tabs-mode: nil; encoding: utf-8-dos; coding: utf-8 -*-

"""
This file declares oParseOptions in a separate file so that the
arguments parsing can be uniform between applications that use it.

"""

from argparse import ArgumentParser

def oParseOptions(sUsage):
    oArgParser = ArgumentParser(description=sUsage)
    # rabbit
    oArgParser.add_argument("-a", "--address", action="store",
                            dest="sHostaddress",
                            default="127.0.0.1",
                            help="the TCP address to subscribe on (default 127.0.0.1)")
    oArgParser.add_argument("-o", "--pubport", action="store",
                            dest="iPubPort", type=int, default=5672,
                            help="the TCP port number to publish to (default 5672)")
    oArgParser.add_argument("-u", "--username", action="store",
                            dest="sUsername", default="guest",
                            help="the username for the connection (default guest)")
    oArgParser.add_argument("-p", "--password", action="store",
                            dest="sPassword", default="guest",
                            help="the password for the connection (default guest)")
    oArgParser.add_argument("-e", "--exchange", action="store",
                            dest="sExchangeName", default="Mt4",
                            help="sExchangeName for the connection (default topic_logs)")
    oArgParser.add_argument("-i", "--virtual", action="store",
                            dest="sVirtualHost", default="/",
                            help="the VirtualHost for the connection (default /)")
    oArgParser.add_argument("-v", "--verbose", action="store",
                            dest="iVerbose", type=int, default=4,
                            help="the verbosity, 0 for silent 4 max (default 4)")
    oArgParser.add_argument('lArgs', action="store",
                            nargs="+",
                            help="the message to send (required)")
    return(oArgParser)

