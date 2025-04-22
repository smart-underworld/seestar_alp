# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# discovery.py - Discovery Responder for Alpaca Device
#
# Part of the AlpycaDevice Alpaca skeleton/template device driver
#
# Author:   Robert B. Denny <rdenny@dc3.com> (rbd)
#
# Python Compatibility: Requires Python 3.7 or later
# GitHub: https://github.com/ASCOMInitiative/AlpycaDevice
#
# -----------------------------------------------------------------------------
# MIT License
#
# Copyright (c) 2022 Bob Denny
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------
# Edit History:
#
# 17-Dec-2022   rbd 0.1 Initial edit for Alpaca sample/template
# 19-Dec-2022   rbd 0.1 Validated with ConformU discovery diagnostics
#               Add thread name 'Discovery'
# 24-Dec-2022   rbd 0.1 Logging
# 25-Dec-2022   rbd 0.1 Logging typing for intellisense
# 27-Dec-2022   rbd 0.1 MIT license and module header. No mcast on device, duh!
#
import os
import socket                                           # for discovery responder
from threading import Thread                            # Same here
from logging import Logger

logger: Logger = None
def set_disc_logger(lgr) -> logger:
    global logger
    logger = lgr

class DiscoveryResponder(Thread):
    """Alpaca device discovery responder """

    def __init__(self, ADDR, PORT):
        """ The Alpaca Discovery responder runs in a separate thread and is invoked
        by a 1-line call during app startup::

            _DSC = DiscoveryResponder(ip_address, port)

        where the ``ip_address`` and ``port`` come from the :doc:`/config`
        ``Config`` object and ultimately from the config file ``config.toml``.
        """
        Thread.__init__(self, name='Discovery')
        # TODO See https://stackoverflow.com/a/32372627/159508
        # It's a sledge hammer technique to bind to ' ' for sending multicast
        # The right way is to bind to the broadcast address for the current
        # subnet.
        self.device_address = (ADDR, 32227)    # Listen at multicast address, not ' '
        self.alpaca_response  = "{\"AlpacaPort\": " + str(PORT) + "}"
        self.rsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  #share address
        if os.name != 'nt':
            # needed on Linux and OSX to share port with net core. Remove on windows
            self.rsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            self.rsock.bind(self.device_address)
        except:
            logger.error('Discovery responder: failure to bind receive socket')
            self.rsock.close()
            self.rsock = 0
            raise

        self.tsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  #share address
        try:
             self.tsock.bind((ADDR, 0))
        except:
            logger.error('Discovery responder: failure to bind send socket')
            self.tsock.close()
            self.tsock = 0
            raise

        # OK start the listener
        self.daemon = True
        self.start()

    def run(self):
        """Discovery responder forever loop"""
        while True:
            data, addr = self.rsock.recvfrom(1024)
            datascii = str(data, 'ascii')
            logger.info(f'Disc rcv {datascii} from {str(addr)}')
            if 'alpacadiscovery1' in datascii:
                self.tsock.sendto(self.alpaca_response.encode(), addr)
