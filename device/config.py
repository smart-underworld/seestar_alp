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

#print(path_to_dat)
### RWR _dict = toml.load(f'{sys.path[0]}/config.toml')    # Errors here are fatal.
_dict = tomlkit.loads(open(path_to_dat).read())
def get_toml(sect: str, item: str, default : typing.Any):
    if not _dict is {} and sect in _dict and item in _dict[sect]:
        return _dict[sect][item]
    else:
        return default

class Config:
    """Device configuration in ``config.toml``"""
    # ---------------
    # Network Section
    # ---------------
    ip_address: str = get_toml('network', 'ip_address', '127.0.0.1')
    port: int = get_toml('network', 'port', 5555)
    imgport: int = get_toml('network', 'imgport', 7556)
    stport: int = get_toml('network', 'stport', 8090)
    sthost: str = get_toml('network', 'sthost', 'localhost')
    timeout: int = get_toml('network', 'timeout', 5)
    rtsp_udp: bool = get_toml('network', 'rtsp_udp', True)

    # --------------
    # WebUI Section
    # --------------
    uiport: int = get_toml('webui_settings', 'uiport', 5432)
    uitheme: str = get_toml('webui_settings', 'uitheme', 'dark')
    twilighttimes: bool = get_toml('webui_settings', 'twilighttimes', False)
    experimental: bool = get_toml('webui_settings', 'experimental', False)

    # --------------
    # Server Section
    # --------------
    location: str = get_toml('server', 'location', 'Anywhere on Earth')
    verbose_driver_exceptions: bool = get_toml('server', 'verbose_driver_exceptions', True)

    # --------------
    # Device Section
    # --------------
    can_reverse: bool = get_toml('device', 'can_reverse', True)
    step_size: float = get_toml('device', 'step_size', 1.0)
    steps_per_sec: int = get_toml('device', 'steps_per_sec', 6)
    if 'seestars' in _dict:
        seestars = _dict['seestars']
    else:
        seestars = [
          {
            'name': 'Seestar Alpha',
            'ip_address': 'seestar.local',
            'device_num': 1
          }
        ]

    # ---------------
    # Logging Section
    # ---------------
    log_level: int = logging.getLevelName(get_toml('logging', 'log_level', 'INFO'))  # Not documented but works (!!!!)
    log_to_stdout: str = get_toml('logging', 'log_to_stdout', False)
    max_size_mb: int = get_toml('logging', 'max_size_mb', 5)
    num_keep_logs: int = get_toml('logging', 'num_keep_logs', 10)
    log_prefix: str = get_toml('logging', 'log_prefix', '')
    log_events_in_info: bool = get_toml('logging', 'log_events_in_info', False)


    # ---------------
    # seestar_initialization Section
    # ---------------
    secion = 'seestar_initialization'

    init_save_good_frames: bool = get_toml(secion, 'save_good_frames', True)
    init_save_all_frames: bool = get_toml(secion, 'save_all_frames', True)
    init_lat: float = get_toml(secion, 'lat', 0)
    init_long: float = get_toml(secion, 'long', 0)
    init_gain: int = get_toml(secion, 'gain', 80)
    init_expo_preview_ms: int = get_toml(secion, 'exposure_length_preview_ms', 500)
    init_expo_stack_ms: int = get_toml(secion, 'exposure_length_stack_ms', 10000)
    init_dither_enabled: bool = get_toml(secion, 'dither_enabled', True)
    init_dither_length_pixel: int = get_toml(secion, 'dither_length_pixel', 50)
    init_dither_frequency: int = get_toml(secion, 'dither_frequency', 10)
    init_activate_LP_filter: bool = get_toml(secion, 'activate_LP_filter', False)
    init_dew_heater_power: int = get_toml(secion, 'dew_heater_power', 0)
    init_scope_aim_up_time_s: float = get_toml(secion, 'scope_aim_up_time_s', 19.4)
    init_scope_aim_clockwise_time_s: float = get_toml(secion, 'scope_aim_clockwise_time_s', 10.8)

    def set_toml(section, key, value):
        _dict[section][key] = value

    def save_toml(save_name = path_to_dat):
        with open(save_name, "w") as toml_file:
            toml_file.write(tomlkit.dumps(_dict))
