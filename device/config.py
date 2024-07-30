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
import toml
import logging
import shutil
### rwr
from os import path
import os
### end rwr

#
# This slimy hack is for Sphinx which, despite the toml.load() being
# run only once on the first import, it can't deal with _dict not being
# initialized or ?!?!?!?!? If you try to use getcwd() in the file name
# here, it will also choke Sphinx. This cost me a day.
#
_dict = {}
### RWR Added
if getattr(sys, "frozen",  False):
    search_path = sys._MEIPASS
else:
    search_path = path.join(path.dirname(__file__))

path_to_dat = os.path.abspath(os.path.join(search_path, "config.toml"))
if not os.path.exists(path_to_dat):
  path_to_ex = os.path.abspath(os.path.join(search_path, "config.toml.example"))
  shutil.copy(path_to_ex, path_to_dat)

print(path_to_dat)
### RWR _dict = toml.load(f'{sys.path[0]}/config.toml')    # Errors here are fatal.
_dict = toml.load(path_to_dat)    # Errors here are fatal.
def get_toml(sect: str, item: str):
    if not _dict is {}:
        return _dict[sect][item]
    else:
        return ''

class Config:
    """Device configuration in ``config.toml``"""
    # ---------------
    # Network Section
    # ---------------
    ip_address: str = get_toml('network', 'ip_address')
    port: int = get_toml('network', 'port')
    stport: int = get_toml('network', 'stport')
    
    # --------------
    # WebUI Section
    # --------------
    uiport: int = get_toml('webui_settings', 'uiport')
    uitheme: str = get_toml('webui_settings', 'uitheme')

    # --------------
    # Server Section
    # --------------
    location: str = get_toml('server', 'location')
    verbose_driver_exceptions: bool = get_toml('server', 'verbose_driver_exceptions')

    # --------------
    # Device Section
    # --------------
    can_reverse: bool = get_toml('device', 'can_reverse')
    step_size: float = get_toml('device', 'step_size')
    steps_per_sec: int = get_toml('device', 'steps_per_sec')
    seestars = _dict['seestars']

    # ---------------
    # Logging Section
    # ---------------
    log_level: int = logging.getLevelName(get_toml('logging', 'log_level'))  # Not documented but works (!!!!)
    log_to_stdout: str = get_toml('logging', 'log_to_stdout')
    max_size_mb: int = get_toml('logging', 'max_size_mb')
    num_keep_logs: int = get_toml('logging', 'num_keep_logs')

