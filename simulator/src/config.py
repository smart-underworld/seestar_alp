# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# conf.py - Device configuration file and shared logger construction
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
# 24-Dec-2022   rbd 0.1 Logging
# 25-Dec-2022   rbd 0.1 More config items, separate logging section
# 27-Dec-2022   rbd 0.1 Move shared logger construction and global
#               var here. MIT license and module header. No mcast.
#
import sys
import tomlkit
import logging
import shutil

### rwr
from os import path
import os

### end rwr
import typing

#
# This slimy hack is for Sphinx which, despite the toml.load() being
# run only once on the first import, it can't deal with _dict not being
# initialized or ?!?!?!?!? If you try to use getcwd() in the file name
# here, it will also choke Sphinx. This cost me a day.
#
### RWR Added
if getattr(sys, "frozen", False):
    search_path = sys._MEIPASS
else:
    search_path = path.join(path.dirname(__file__))


class _Config:
    def __init__(self):
        self.path_to_dat = os.path.abspath(os.path.join(search_path, "config.toml"))
        if not os.path.exists(self.path_to_dat):
            path_to_ex = os.path.abspath(
                os.path.join(search_path, "config.toml.example")
            )
            shutil.copy(path_to_ex, self.path_to_dat)

        self.load_toml(self.path_to_dat)

    @staticmethod
    def strToBool(inputString: str):
        if inputString in ["True", "true", "on"] or inputString:
            return True
        else:
            return False

    def get_toml(self, sect: str, item: str, default: typing.Any):
        """
        Helper method for getting a toml value out of the dict representation
        """
        if self._dict != {} and sect in self._dict and item in self._dict[sect]:
            return self._dict[sect][item]
        else:
            return default

    def load(self, toml_path):
        """
        Load a config.toml file into a Config object.

        NOTE to developers modifying this with new config
            Modification of this method to add, or remove config items should
            also include modifications to:
              - def render_config_html to add/remove html form representation
              - def load_from_form (below) to update this object when the form is submitted
        """
        self._dict = tomlkit.loads(open(toml_path).read())

        """Device configuration in ``config.toml``"""
        # ---------------
        # Network Section
        # ---------------
        self.ip_address: str = self.get_toml("network", "ip_address", "127.0.0.1")
        self.tcp_port: int = self.get_toml("network", "tcp_port", 4700)
        self.udp_port: int = self.get_toml("network", "udp_port", 4720)

        # ---------------
        # Logging Section
        # ---------------
        self.log_level: int = logging.getLevelName(
            self.get_toml("logging", "log_level", "INFO")
        )  # Not documented but works (!!!!)
        self.log_to_stdout: str = self.get_toml("logging", "log_to_stdout", False)
        self.max_size_mb: int = self.get_toml("logging", "max_size_mb", 5)
        self.num_keep_logs: int = self.get_toml("logging", "num_keep_logs", 10)
        self.log_prefix: str = self.get_toml("logging", "log_prefix", "")
        self.log_events_in_info: bool = self.get_toml(
            "logging", "log_events_in_info", False
        )

    def load_toml(self, load_name=None):
        """
        Load a specific path to a toml file into this Config object
        """
        if load_name is None:
            load_name = self.path_to_dat
        self.load(load_name)

    def set_toml(self, section, key, value):
        """
        Set a value in-memory for the toml dict
        """
        self._dict[section][key] = value


Config = _Config()

# Optionally, provide module-level shortcuts for convenience:
# ip_address = Config.ip_address
# tcp_port = getattr(Config, "tcp_port", getattr(Config, "port", 5555))
# udp_port = getattr(Config, "udp_port", getattr(Config, "imgport", 7556))
