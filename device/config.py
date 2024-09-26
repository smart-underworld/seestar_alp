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
if getattr(sys, "frozen",  False):
    search_path = sys._MEIPASS
else:
    search_path = path.join(path.dirname(__file__))

class _Config:
    def __init__(self):
        self.path_to_dat = os.path.abspath(os.path.join(search_path, "config.toml"))
        if not os.path.exists(self.path_to_dat):
            path_to_ex = os.path.abspath(os.path.join(search_path, "config.toml.example"))
            shutil.copy(path_to_ex, self.path_to_dat)

        self.load_toml(self.path_to_dat)

    def get_toml(self, sect: str, item: str, default : typing.Any):
        if not self._dict is {} and sect in self._dict and item in self._dict[sect]:
            return self._dict[sect][item]
        else:
            return default

    def load(self, toml_path):
        self._dict = tomlkit.loads(open(toml_path).read())

        """Device configuration in ``config.toml``"""
        # ---------------
        # Network Section
        # ---------------
        self.ip_address: str = self.get_toml('network', 'ip_address', '127.0.0.1')
        self.port: int = self.get_toml('network', 'port', 5555)
        self.imgport: int = self.get_toml('network', 'imgport', 7556)
        self.stport: int = self.get_toml('network', 'stport', 8090)
        self.sthost: str = self.get_toml('network', 'sthost', 'localhost')
        self.timeout: int = self.get_toml('network', 'timeout', 5)
        self.rtsp_udp: bool = self.get_toml('network', 'rtsp_udp', True)

        # --------------
        # WebUI Section
        # --------------
        self.uiport: int = self.get_toml('webui_settings', 'uiport', 5432)
        self.uitheme: str = self.get_toml('webui_settings', 'uitheme', 'dark')
        self.twilighttimes: bool = self.get_toml('webui_settings', 'twilighttimes', False)
        self.experimental: bool = self.get_toml('webui_settings', 'experimental', False)
        self.clear_sky_img_src: str = self.get_toml('webui_settings', 'clear_sky_img_src', 'https://www.cleardarksky.com/c/LvrmrCAcsk.gif?c=1969222')
        self.clear_sky_href: str = self.get_toml('webui_settings', 'clear_sky_href', 'https://www.cleardarksky.com/c/LvrmrCAkey.html')

        # --------------
        # Server Section
        # --------------
        self.location: str = self.get_toml('server', 'location', 'Anywhere on Earth')
        self.verbose_driver_exceptions: bool = self.get_toml('server', 'verbose_driver_exceptions', True)

        # --------------
        # Device Section
        # --------------
        self.can_reverse: bool = self.get_toml('device', 'can_reverse', True)
        self.step_size: float = self.get_toml('device', 'step_size', 1.0)
        self.steps_per_sec: int = self.get_toml('device', 'steps_per_sec', 6)
        if 'seestars' in self._dict:
            self.seestars = self._dict['seestars']
        else:
            self.seestars = [
            {
                'name': 'Seestar Alpha',
                'ip_address': 'seestar.local',
                'device_num': 1
            }
            ]

        # ---------------
        # Logging Section
        # ---------------
        self.log_level: int = logging.getLevelName(self.get_toml('logging', 'log_level', 'INFO'))  # Not documented but works (!!!!)
        self.log_to_stdout: str = self.get_toml('logging', 'log_to_stdout', False)
        self.max_size_mb: int = self.get_toml('logging', 'max_size_mb', 5)
        self.num_keep_logs: int = self.get_toml('logging', 'num_keep_logs', 10)
        self.log_prefix: str = self.get_toml('logging', 'log_prefix', '')
        self.log_events_in_info: bool = self.get_toml('logging', 'log_events_in_info', False)


        # ---------------
        # seestar_initialization Section
        # ---------------
        section = 'seestar_initialization'

        self.init_save_good_frames: bool = self.get_toml(section, 'save_good_frames', True)
        self.init_save_all_frames: bool = self.get_toml(section, 'save_all_frames', True)
        self.init_lat: float = self.get_toml(section, 'lat', 0)
        self.init_long: float = self.get_toml(section, 'long', 0)
        self.init_gain: int = self.get_toml(section, 'gain', 80)
        self.init_expo_preview_ms: int = self.get_toml(section, 'exposure_length_preview_ms', 500)
        self.init_expo_stack_ms: int = self.get_toml(section, 'exposure_length_stack_ms', 10000)
        self.init_dither_enabled: bool = self.get_toml(section, 'dither_enabled', True)
        self.init_dither_length_pixel: int = self.get_toml(section, 'dither_length_pixel', 50)
        self.init_dither_frequency: int = self.get_toml(section, 'dither_frequency', 10)
        self.init_activate_LP_filter: bool = self.get_toml(section, 'activate_LP_filter', False)
        self.init_dew_heater_power: int = self.get_toml(section, 'dew_heater_power', 0)
        self.init_scope_aim_up_time_s: float = self.get_toml(section, 'scope_aim_up_time_s', 19.4)
        self.init_scope_aim_clockwise_time_s: float = self.get_toml(section, 'scope_aim_clockwise_time_s', 10.8)

    def load_from_form(self, req):
        # network
        self.set_toml('network', 'ip_address', req.media['ip_address'])
        self.set_toml('network', 'port', int(req.media['port']))
        self.set_toml('network', 'imgport', int(req.media['imgport']))
        self.set_toml('network', 'stport', int(req.media['stport']))
        self.set_toml('network', 'sthost', req.media['sthost'])
        self.set_toml('network', 'timeout', int(req.media['timeout']))
        self.set_toml('network', 'rtsp_udp', 'rtsp_udp' in req.media)

        # webUI
        self.set_toml('webui_settings', 'uiport', int(req.media['uiport']))
        self.set_toml('webui_settings', 'uitheme', req.media['uitheme'])
        self.set_toml('webui_settings', 'twilighttimes', 'twilighttimes' in req.media)
        self.set_toml('webui_settings', 'experimental', 'experimental' in req.media)
        self.set_toml('webui_settings', 'clear_sky_img_src', req.media['clear_sky_img_src'])
        self.set_toml('webui_settings', 'clear_sky_href', req.media['clear_sky_href'])

        # server
        self.set_toml('server', 'location', req.media['location'])
        self.set_toml('server', 'verbose_driver_exceptions', 'verbose_driver_exceptions' in req.media)

        # device
        self.set_toml('device', 'can_reverse', 'can_reverse' in req.media)
        self.set_toml('device', 'step_size', float(req.media['step_size']))
        self.set_toml('device', 'steps_per_sec', int(req.media['steps_per_sec']))

        # logging
        self.set_toml('logging', 'log_level', req.media['log_level'])
        self.set_toml('logging', 'log_prefix', req.media['log_prefix'])
        self.set_toml('logging', 'log_to_stdout', 'log_to_stdout' in req.media)
        self.set_toml('logging', 'max_size_mb', int(req.media['max_size_mb']))
        self.set_toml('logging', 'num_keep_logs', int(req.media['num_keep_logs']))
        self.set_toml('logging', 'log_events_in_info', 'log_events_in_info' in req.media)

        # seestar_initialization
        self.set_toml('seestar_initialization', 'save_good_frames', 'init_save_good_frames' in req.media)
        self.set_toml('seestar_initialization', 'save_all_frames', 'init_save_all_frames' in req.media)
        self.set_toml('seestar_initialization', 'lat', float(req.media['init_lat']))
        self.set_toml('seestar_initialization', 'long', float(req.media['init_long']))
        self.set_toml('seestar_initialization', 'gain', int(req.media['init_gain']))
        self.set_toml('seestar_initialization', 'exposure_length_preview_ms', int(req.media['init_expo_preview_ms']))
        self.set_toml('seestar_initialization', 'exposure_length_stack_ms', int(req.media['init_expo_stack_ms']))
        self.set_toml('seestar_initialization', 'dither_enabled', 'init_dither_enabled' in req.media)
        self.set_toml('seestar_initialization', 'dither_length_pixel', int(req.media['init_dither_length_pixel']))
        self.set_toml('seestar_initialization', 'dither_frequency', int(req.media['init_dither_frequency']))
        self.set_toml('seestar_initialization', 'activate_LP_filter', 'init_activate_LP_filter' in req.media)
        self.set_toml('seestar_initialization', 'dew_heater_power', int(req.media['init_dew_heater_power']))
        self.set_toml('seestar_initialization', 'scope_aim_up_time_s', float(req.media['init_scope_aim_up_time_s']))
        self.set_toml('seestar_initialization', 'scope_aim_clockwise_time_s', float(req.media['init_scope_aim_clockwise_time_s']))

    def load_toml(self, load_name = None):
        if load_name == None:
            load_name = self.path_to_dat
        self.load(load_name)

    def set_toml(self, section, key, value):
        self._dict[section][key] = value

    def save_toml(self, save_name = None):
        if save_name == None:
            save_name = self.path_to_dat
        print(f"save_toml: writing toml to {save_name}")
        with open(save_name, "w") as toml_file:
            toml_file.write(tomlkit.dumps(self._dict))

Config = _Config()