# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# logging.py - Shared global logging object
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
# 01-Jan-2023   rbd 0.1 Initial edit, moved from config.py
# 15-Jan-2023   rbd 0.1 Documentation. No logic changes.
# 08-Nov-2023   rbd 0.4 Log name is now 'alpyca'

import logging
import logging.handlers
import time
from config import Config

global logger
# logger: logging.Logger = None  # Master copy (root) of the logger
logger = None  # Safe on Python 3.7 but no intellisense in VSCode etc.


def init_logging():
    """ Create the logger - called at app startup

        **MASTER LOGGER**

        This single logger is used throughout. The module name (the param for get_logger())
        isn't needed and would be 'root' anyway, sort of useless. Also the default date-time
        is local time, and not ISO-8601. We log in UTC/ISO format, and with fractional seconds.
        Finally our config options allow for suppression of logging to stdout, and for this
        we remove the default stdout handler. Thank heaven that Python logging is thread-safe!

        This logger is passed around throughout the app and may be used throughout. The
        :py:class:`config.Config` class has options to control the number of back generations
        of logs to keep, as well as the max size (at which point the log will be rotated).
        A new log is started each time the app is started.

    Returns:
        Customized Python logger.

    """

    global logger

    # Reinitializing the causes issues, so don't do it...
    if logger is None:
        logging.basicConfig(level=Config.log_level)  # This creates the default handler
        logger = logging.getLogger()  # Root logger, see above
        formatter = logging.Formatter('%(asctime)s.%(msecs)03d %(levelname)s %(threadName)s %(message)s',
                                      '%Y-%m-%dT%H:%M:%S')
        formatter.converter = time.gmtime  # UTC time
        logger.handlers[0].setFormatter(formatter)  # This is the stdout handler, level set above
        # Add a logfile handler, same formatter and level
        handler = logging.handlers.RotatingFileHandler('alpyca.log',
                                                       mode='w',
                                                       delay=True,  # Prevent creation of empty logs
                                                       maxBytes=Config.max_size_mb * 1000000,
                                                       backupCount=Config.num_keep_logs)
        handler.setLevel(Config.log_level)
        handler.setFormatter(formatter)
        handler.doRollover()  # Always start with fresh log
        logger.addHandler(handler)
        if not Config.log_to_stdout:
            """
                This allows control of logging to stdout by simply
                removing the stdout handler from the logger's
                handler list. It's always handler[0] as created
                by logging.basicConfig()
            """
            logger.debug('Logging to stdout disabled in settings')
            logger.removeHandler(logger.handlers[0])  # This is the stdout handler
    return logger
