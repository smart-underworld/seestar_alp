# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# shr.py - Device characteristics and support classes/functions/data
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
# 15-Dec-2022   rbd 0.1 Initial edit for Alpaca sample/template
# 18-Dev-2022   rbd 0.1 Additional driver info items
# 20-Dec-2022   rbd 0.1 Fix idiotic error in to_bool()
# 22-Dec-2022   rbd 0.1 DeviceMetadata
# 24-Dec-2022   rbd 0.1 Logging
# 25-Dec-2022   rbd 0.1 Logging typing for intellisense
# 26-Dec-2022   rbd 0.1 Refactor logging to config module.
# 27-Dec-2022   rbd 0.1 Methods can return values. Common request
#                       logging (before starting processing).
#                       MIT license and module header. Logging cleanup.
#                       Python 3.7 global restriction.
# 28-Dec-2022   rbd 0.1 Rename conf.py to config.py to avoid conflict with sphinx
# 29-Dec-2022   rbd 0.1 ProProcess() Falcon hook class for pre-logging and
#                       common request validation (Client IDs for now).
# 31-Dec-2022   rbd 0.1 Bad boolean values return 400 Bad Request
# 10-Jan-2023   rbd 0.1 Cleanups for documentation and add docstrings for Sphinx.
# 23-May-2023   rbd 0.2 Refactoring for multiple ASCOM device type support
#               GitHub issue #1. Improve error messages in PreProcessRequest().
# 29-May-2023   rbd 0.2 Enhance get_request_field() so empty string for default
#               value means mandatory field. Add title and description info
#               to raised HTTP BAD_REQUEST.
# 30-May-2023   rbd 0.3 Improve request logging at time of arrival
# 01-Jun-2023   rbd 0.3 Issue #2 Do not return empty Value field in property
#               response, and omit Value if error is not success().

from threading import Lock
from device.exceptions import Success
import json
from falcon import Request, Response, HTTPBadRequest
from logging import Logger

logger: Logger = None
#logger = None                   # Safe on Python 3.7 but no intellisense in VSCode etc.

_bad_title = 'Bad Alpaca Request'

def set_shr_logger(lgr):
    global logger
    logger = lgr

# --------------------------
# Alpaca Device/Server Info
# --------------------------
# Static metadata not subject to configuration changes
class DeviceMetadata:
    """ Metadata describing the Alpaca Device/Server """
    Version = '0.2'
    Description = 'Alpaca Sample Rotator '
    Manufacturer = 'ASCOM Initiative'


# ---------------
# Data Validation
# ---------------
_bools = ['true', 'false']                               # Only valid JSON bools allowed
def to_bool(str: str) -> bool:
    val = str.lower()
    if val not in _bools:
        raise HTTPBadRequest(title=_bad_title, description=f'Bad boolean value "{val}"')
    return val == _bools[0]

# ---------------------------------------------------------
# Get parameter/field from query string or body "form" data
# If default is missing then the field is required. Maybe the
# field name is smisspelled, or mis-cased (for PUT), or
# missing. In any case, raise a 400 BAD REQUEST. Optional
# caseless (mostly for the ClientID and ClientTransactionID)
# ---------------------------------------------------------
def get_request_field(name: str, req: Request, caseless: bool = False, default: str = None) -> str:
    bad_desc = f'Missing, empty, or misspelled parameter "{name}"'
    lcName = name.lower()
    if req.method == 'GET':
        for param in req.params.items():        # [name,value] tuples
            if param[0].lower() == lcName:
                return param[1]
        if default == None:
            raise HTTPBadRequest(title=_bad_title, description=bad_desc)                # Missing or incorrect casing
        return default                          # not in args, return default
    else:                                       # Assume PUT since we never route other methods
        formdata = req.get_media()
        if caseless:
            for fn in formdata.keys():
                if fn.lower() == lcName:
                    return formdata[fn]
        else:
            if name in formdata and formdata[name] != '':
                return formdata[name]
        if default == None:
            raise HTTPBadRequest(title=_bad_title, description=bad_desc)                # Missing or incorrect casing
        return default

#
# Log the request as soon as the resource handler gets it so subsequent
# logged messages are in the right order. Logs PUT body as well.
#
def log_request(req: Request):
    msg = f'{req.remote_addr} -> {req.method} {req.path}'
    if req.query_string != '':
        msg += f'?{req.query_string}'
    logger.debug(msg)
    if req.method == 'PUT' and req.content_length != 0:
        logger.debug(f'{req.remote_addr} -> {req.media}')

# ------------------------------------------------
# Incoming Pre-Logging and Request Quality Control
# ------------------------------------------------
class PreProcessRequest():
    """Decorator for responders that quality-checks an incoming request

    If there is a problem, this causes a ``400 Bad Request`` to be returned
    to the client, and logs the problem.

    """
    def __init__(self, maxdev):
        self.maxdev = maxdev
        """Initialize a ``PreProcessRequest`` decorator object.

        Args:
            maxdev: The maximun device number. If multiple instances of this device
                type are supported, this will be > 0.

        Notes:
            * Bumps the ServerTransactionID value and returns it in sequence
        """

    #
    # Quality check of numerical value for trans IDs
    #
    @staticmethod
    def _pos_or_zero(val: str) -> bool:
        try:
            test = int(val)
            return test >= 0
        except ValueError:
            return False

    def _check_request(self, req: Request, devnum: int):  # Raise on failure
        if devnum > self.maxdev:
            msg = f'Device number {str(devnum)} does not exist. Maximum device number is {self.maxdev}.'
            logger.error(msg)
            raise HTTPBadRequest(title=_bad_title, description=msg)
        test: str = get_request_field('ClientID', req, True)        # Caseless
        if test is None:
            msg = 'Request has missing Alpaca ClientID value'
            logger.error(msg)
            raise HTTPBadRequest(title=_bad_title, description=msg)
        if not self._pos_or_zero(test):
            msg = f'Request has bad Alpaca ClientID value {test}'
            logger.error(msg)
            raise HTTPBadRequest(title=_bad_title, description=msg)
        test: str = get_request_field('ClientTransactionID', req, True)
        if not self._pos_or_zero(test):
            msg = f'Request has bad Alpaca ClientTransactionID value {test}'
            logger.error(msg)
            raise HTTPBadRequest(title=_bad_title, description=msg)

    #
    # params contains {'devnum': n } from the URI template matcher
    # and format converter. This is the device number from the URI
    #
    def __call__(self, req: Request, resp: Response, resource, params):
        log_request(req)                            # Log even a bad request
        self._check_request(req, params['devnum'])   # Raises to 400 error on check failure

# ------------------
# PropertyResponse
# ------------------
class PropertyResponse():
    """JSON response for an Alpaca Property (GET) Request"""
    def __init__(self, value, req: Request, err = Success()):
        """Initialize a ``PropertyResponse`` object.

        Args:
            value:  The value of the requested property, or None if there was an
                exception.
            req: The Falcon Request property that was provided to the responder.
            err: An Alpaca exception class as defined in the exceptions
                or defaults to :py:class:`~exceptions.Success`

        Notes:
            * Bumps the ServerTransactionID value and returns it in sequence
        """
        self.ServerTransactionID = getNextTransId()
        self.ClientTransactionID = int(get_request_field('ClientTransactionID', req, False, 0))  #Caseless on GET
        if err.number == 0 and not value is None:
            self.Value = value
            logger.debug(f'{req.remote_addr} <- {str(value)}')
        self.ErrorNumber = err.number
        self.ErrorMessage = err.message

    @property
    def json(self) -> str:
        """Return the JSON for the Property Response"""
        return json.dumps(self.__dict__)

# --------------
# MethodResponse
# --------------
class MethodResponse():
    """JSON response for an Alpaca Method (PUT) Request"""
    def __init__(self, req: Request, err = Success(), value = None): # value useless unless Success
        """Initialize a MethodResponse object.

        Args:
            req: The Falcon Request property that was provided to the responder.
            err: An Alpaca exception class as defined in the exceptions
                or defaults to :py:class:`~exceptions.Success`
            value:  If method returns a value, or defaults to None

        Notes:
            * Bumps the ServerTransactionID value and returns it in sequence
        """
        self.ServerTransactionID = getNextTransId()
        # This is crazy ... if casing is incorrect here, we're supposed to return the default 0
        # even if the caseless check coming in returned a valid number. This is for PUT only.
        self.ClientTransactionID = int(get_request_field('ClientTransactionID', req, False, 0))
        if err.number == 0 and not value is None:
            self.Value = value
            logger.debug(f'{req.remote_addr} <- {str(value)}')
        self.ErrorNumber = err.number
        self.ErrorMessage = err.message


    @property
    def json(self) -> str:
        """Return the JSON for the Method Response"""
        return json.dumps(self.__dict__)


# -------------------------------
# Thread-safe ServerTransactionID
# -------------------------------
_lock = Lock()
_stid = 0

def getNextTransId() -> int:
    with _lock:
        global _stid
        _stid += 1
    return _stid
