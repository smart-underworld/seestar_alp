# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# exceptions.py - Alpaca Exception Classes
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
# 17-Dec-2022   rbd 0.1 Initial edit for Alpaca sample/template
# 18-Dec-2022   rbd 0.1 Refactor to support optional overriding
#                       error message, and support DriverException
#                       with variable error number.
# 26-Dev-2022   rbd 0.1 Logging, including Python low level exceptions
# 27-Dec-2022   rbd 0.1 MIT License and module header
# 13-Jan-2023   rbd 0.1 Fix DriverException's recovery from bad error number
# 16-Jan-2023   rbd 0.1 Docstrings for other exception classes
#
import traceback
from device.config import Config
from logging import Logger

global logger
# logger: Logger = None
logger = None  # Safe on Python 3.7 but no intellisense in VSCode etc.


class Success:
    """Default err input to response classes, indicates success"""

    def __init__(self):
        """Initialize the Success object

        Args:
            number (int):   0
            message (str):  ''
        """
        self.number: int = 0
        self.message: str = ""

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class ActionNotImplementedException:
    """Requested ``Action()`` is not implemented"""

    def __init__(
        self, message: str = "The requested action is not implemented in this driver."
    ):
        """Initialize the ``ActionNotImplementedException`` object

        Args:
            number (int):   0x040C (1036)
            message (str):  'The requested action is not implemented in this driver.'

        * Logs ``ActionNotImplementedException: {message}``
        """
        self.number = 0x40C
        self.message = message
        cname = self.__class__.__name__
        logger.error(f"{cname}: {message}")

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


# The device chooses a number between 0x500 and 0xFFF, and
# provides a helpful/specific error message. Asserts the
# error number within range.
#
# args:


class DevDriverException:
    """
    **Exception Class for Driver Internal Errors**
        This exception is used for device errors and other internal exceptions.
        It can be instantiated with a captured exception object, and if so format
        the Alpaca error message to include line number/module or optionally a
        complete traceback of the exception (a config option).
    """

    def __init__(
        self,
        number: int = 0x500,
        message: str = "Internal driver error - this should be more specific.",
        exc=None,  # Python exception info
    ):
        """Initialize the DeviceException object

        Args:
            number (int):   Alpaca error number between 0x500 and 0xFFF, your choice
                            defaults to 0x500 (1280)
            message (str):  Specific error message or generic if left blank. Defaults
                            to 'Internal driver error - this should be more specific.'
            exc:            Contents 'ex' of 'except Exception as ex:' If not included
                            then only message is included. If supplied, then a detailed
                            error message with traceback is created (see full parameter)

        Notes:
            * Checks error number within legal range and if not, logs this error and substitutes
              0x500 number.
            * If the Python exception object is included as the 3rd argument, it constructs
              a message containing the name of the underlying Python exception and its basic
              context. If :py:attr:`~config.Config.verbose_driver_exceptions` is ``true``, a complete
              Python traceback is included.
            * Logs the constructed ``DriverException`` message
        """
        if number <= 0x500 and number >= 0xFFF:
            logger.error(
                f"Programmer error, bad DriverException number {hex(number)}, substituting 0x500"
            )
            number = 0x500
        self.number = number
        cname = self.__class__.__name__
        if exc is not None:
            if Config.verbose_driver_exceptions:
                self.message = f"{cname}: {message}\n{traceback.format_exc()}"  # TODO Safe if not explicitly using exc?
            else:
                self.message = f"{cname}: {message}\n{type(exc).__name__}: {str(exc)}"
        else:
            self.message = f"{cname}: {message}"
        logger.error(self.message)

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class InvalidOperationException:
    """The client asked for something that can't be done"""

    def __init__(
        self,
        message: str = "The requested operation cannot be undertaken at this time.",
    ):
        """Initialize the ``InvalidOperationException`` object

        Args:
            number (int):   0x040B (1035)
            message (str):  'The requested operation cannot be undertaken at this time.'

        * Logs ``InvalidOperationException: {message}``
        """
        self.number = 0x40B
        self.message = message
        cname = self.__class__.__name__
        logger.error(f"{cname}: {message}")

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class InvalidValueException:
    """A value given is invalid or out of range"""

    def __init__(self, message: str = "Invalid value given."):
        """Initialize the ``InvalidValueException`` object

        Args:
            number (int):   0x401 (1025)
            message (str):  'Invalid value given.'

        * Logs ``InvalidValueException: {message}``
        """
        self.number = 0x401
        self.message = message
        cname = self.__class__.__name__
        logger.error(f"{cname}: {message}")

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class DevNotConnectedException:
    def __init__(self, msg: str = "The device is not connected."):
        """Initialize the ``NotConnectedException`` object

        Args:
            number (int):   0x407 (1031)
            message (str):  'The device is not connected.'

        * Logs ``NotConnectedException: {message}``
        """
        self.number = 0x407
        self.message = msg
        cname = self.__class__.__name__
        logger.error(f"{cname}: {msg}")

    @property
    def Number(self) -> int:
        return self.Number

    @property
    def Message(self) -> str:
        return self.message


class NotImplementedException:
    """The requested property or method is not implemented"""

    def __init__(self, message: str = "Property or method not implemented."):
        """Initialize the ``NotImplementedException`` object

        Args:
            number (int):   0x400 (1024)
            message (str):  'Property or method not implemented.'

        * Logs ``NotImplementedException: {message}``
        """
        self.number = 0x400
        self.message = message
        cname = self.__class__.__name__
        logger.error(f"{cname}: {message}")

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class ParkedException:
    """Cannot do this while the device is parked"""

    def __init__(self, message: str = "Illegal operation while parked."):
        """Initialize the ``ParkedException`` object

        Args:
            number (int):  0x408 (1032)
            message (str):  'Illegal operation while parked.'

        * Logs ``ParkedException: {message}``
        """
        self.number = 0x408
        self.message = message
        cname = self.__class__.__name__
        logger.error(f"{cname}: {message}")

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class SlavedException:
    """Cannot do this while the device is slaved"""

    def __init__(self, message: str = "Illegal operation while slaved."):
        """Initialize the ``SlavedException`` object

        Args:
            number (int):   0x409 (1033)
            message (str):  'Illegal operation while slaved.'

        * Logs ``SlavedException: {message}``
        """
        self.number = 0x409
        self.message = message
        cname = self.__class__.__name__
        logger.error(f"{cname}: {message}")

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message


class ValueNotSetException:
    """The requested vzalue has not yet een set"""

    def __init__(self, message: str = "The value has not yet been set."):
        """Initialize the ``ValueNotSetException`` object

        Args:
            number (int):   0x402 (1026)
            message (str):  'The value has not yet been set.'

        * Logs ``ValueNotSetException: {message}``
        """
        self.number = 0x402
        self.message = message
        cname = self.__class__.__name__
        logger.error(f"{cname}: {message}")

    @property
    def Number(self) -> int:
        return self.number

    @property
    def Message(self) -> str:
        return self.message
