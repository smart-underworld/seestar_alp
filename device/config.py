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
    def strToBool(s) -> bool:
        if isinstance(s, bool):
            return s
        return str(s).strip().lower() in {"1", "true", "on", "yes", "y"}

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
        self.port: int = self.get_toml("network", "port", 5555)
        self.imgport: int = self.get_toml("network", "imgport", 7556)
        self.stport: int = self.get_toml("network", "stport", 8090)
        self.sthost: str = self.get_toml("network", "sthost", "localhost")
        self.timeout: int = self.get_toml("network", "timeout", 5)
        self.rtsp_udp: bool = self.get_toml("network", "rtsp_udp", True)

        # --------------
        # WebUI Section
        # --------------
        self.uiport: int = self.get_toml("webui_settings", "uiport", 5432)
        self.uitheme: str = self.get_toml("webui_settings", "uitheme", "dark")
        self.experimental: bool = self.get_toml("webui_settings", "experimental", False)
        self.confirm: bool = self.get_toml("webui_settings", "confirm", True)
        self.save_frames: bool = self.get_toml("webui_settings", "save_frames", False)
        self.save_frames_dir: str = self.get_toml(
            "webui_settings", "save_frames_dir", "."
        )
        self.loading_gif: str = self.get_toml(
            "webui_settings", "loading_gif", "loading.gif"
        )

        # Fixup bad configs
        if f"{self.save_frames_dir}" == "True" or f"{self.save_frames_dir}" == "False":
            self.save_frames_dir = "."
        if f"{self.loading_gif}" == "True" or f"{self.loading_gif}" == "False":
            self.loading_gif = "loading.gif"

        # --------------
        # Server Section
        # --------------
        self.location: str = self.get_toml("server", "location", "Anywhere on Earth")
        self.verbose_driver_exceptions: bool = self.get_toml(
            "server", "verbose_driver_exceptions", True
        )

        # --------------
        # Device Section
        # --------------
        self.can_reverse: bool = self.get_toml("device", "can_reverse", True)
        self.step_size: float = self.get_toml("device", "step_size", 1.0)
        self.steps_per_sec: int = self.get_toml("device", "steps_per_sec", 6)
        if "seestars" in self._dict:
            self.seestars = self._dict["seestars"]
        else:
            self.seestars = [
                {
                    "name": "Seestar Alpha",
                    "ip_address": "seestar.local",
                    "is_EQ_mode": False,
                    "device_num": 1,
                }
            ]

        # For the rare situation of manually edited toml where the highest
        # device_num is higher than the number of devices, we rewrite the device_num
        # sequentially.

        for seestar in self.seestars:
            if int(seestar["device_num"]) > len(self.seestars):
                counter = 1
                for ss in self.seestars:
                    ss["device_num"] = counter
                    counter += 1

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

        # ---------------
        # seestar_initialization Section
        # ---------------
        section = "seestar_initialization"

        self.init_save_good_frames: bool = self.get_toml(
            section, "save_good_frames", True
        )
        self.init_save_all_frames: bool = self.get_toml(
            section, "save_all_frames", True
        )
        self.init_lat: float = self.get_toml(section, "lat", 0)
        self.init_long: float = self.get_toml(section, "long", 0)
        self.init_gain: int = self.get_toml(section, "gain", 80)
        self.init_expo_preview_ms: int = self.get_toml(
            section, "exposure_length_preview_ms", 500
        )
        self.init_expo_stack_ms: int = self.get_toml(
            section, "exposure_length_stack_ms", 10000
        )
        self.init_dither_enabled: bool = self.get_toml(section, "dither_enabled", True)
        self.init_dither_length_pixel: int = self.get_toml(
            section, "dither_length_pixel", 50
        )
        self.init_dither_frequency: int = self.get_toml(section, "dither_frequency", 10)
        self.init_activate_LP_filter: bool = self.get_toml(
            section, "activate_LP_filter", False
        )
        self.init_dew_heater_power: int = self.get_toml(section, "dew_heater_power", 0)
        self.init_guest_mode: bool = self.get_toml(section, "guest_mode_init", True)
        self.is_EQ_mode: bool = self.get_toml(section, "is_EQ_mode", False)
        self.battery_low_limit: int = self.get_toml(section, "battery_low_limit", 3)
        self.dec_pos_index: int = self.get_toml(section, "dec_pos_index", 3)
        self.is_frame_calibrated: bool = self.get_toml(
            section, "is_frame_calibrated", True
        )

    def load_from_form(self, req):
        """
        Save the config html form into a toml file
        """

        req.get_media()

        # Reset arrays
        self.seestars = []
        self._dict["seestars"].clear()

        # Check if 'ss_name' is a list
        if isinstance(req.media["ss_name"], list):
            deviceCount = len(req.media["ss_name"])
        else:
            deviceCount = 1

        # Iterate through the devices and add them to the lists
        for devNum in range(deviceCount):
            if deviceCount > 1:
                ss_name = req.media["ss_name"][devNum]
                ss_ip = req.media["ss_ip_address"][devNum]
                key = f"ss_is_EQ_mode{devNum + 1}"
                ss_eq = key in req.media
                print(f"Device {devNum} EQ is : {ss_eq}")
            else:
                ss_name = req.media["ss_name"]
                ss_ip = req.media["ss_ip_address"]
                ss_eq = "ss_is_EQ_mode_1" in req.media

            # Add to local config
            self.seestars.append(
                {
                    "name": ss_name,
                    "ip_address": ss_ip,
                    "device_num": devNum + 1,
                    "is_EQ_mode": ss_eq,
                }
            )
            # Add to toml config
            self._dict["seestars"].append(
                {
                    "name": ss_name,
                    "ip_address": ss_ip,
                    "device_num": devNum + 1,
                    "is_EQ_mode": ss_eq,
                }
            )

        # network
        self.set_toml("network", "ip_address", req.media["ip_address"])
        self.set_toml("network", "port", int(req.media["port"]))
        self.set_toml("network", "imgport", int(req.media["imgport"]))
        self.set_toml("network", "stport", int(req.media["stport"]))
        self.set_toml("network", "sthost", req.media["sthost"])
        self.set_toml("network", "timeout", int(req.media["timeout"]))
        self.set_toml("network", "rtsp_udp", "rtsp_udp" in req.media)

        # webUI
        self.set_toml("webui_settings", "uiport", int(req.media["uiport"]))
        self.set_toml("webui_settings", "uitheme", req.media["uitheme"])
        self.set_toml("webui_settings", "experimental", "experimental" in req.media)
        self.set_toml("webui_settings", "confirm", "confirm" in req.media)
        self.set_toml("webui_settings", "save_frames", "save_frames" in req.media)
        self.set_toml("webui_settings", "save_frames_dir", req.media["save_frames_dir"])
        self.set_toml("webui_settings", "loading_gif", req.media["loading_gif"])

        # server
        self.set_toml("server", "location", req.media["location"])
        self.set_toml(
            "server",
            "verbose_driver_exceptions",
            "verbose_driver_exceptions" in req.media,
        )

        # device
        self.set_toml("device", "can_reverse", "can_reverse" in req.media)
        self.set_toml("device", "step_size", float(req.media["step_size"]))
        self.set_toml("device", "steps_per_sec", int(req.media["steps_per_sec"]))

        # logging
        self.set_toml("logging", "log_level", req.media["log_level"])
        self.set_toml("logging", "log_prefix", req.media["log_prefix"])
        self.set_toml("logging", "log_to_stdout", "log_to_stdout" in req.media)
        self.set_toml("logging", "max_size_mb", int(req.media["max_size_mb"]))
        self.set_toml("logging", "num_keep_logs", int(req.media["num_keep_logs"]))
        self.set_toml(
            "logging", "log_events_in_info", "log_events_in_info" in req.media
        )

        # seestar_initialization
        self.set_toml(
            "seestar_initialization",
            "save_good_frames",
            "init_save_good_frames" in req.media,
        )
        self.set_toml(
            "seestar_initialization",
            "save_all_frames",
            "init_save_all_frames" in req.media,
        )
        self.set_toml("seestar_initialization", "lat", float(req.media["init_lat"]))
        self.set_toml("seestar_initialization", "long", float(req.media["init_long"]))
        self.set_toml("seestar_initialization", "gain", int(req.media["init_gain"]))
        self.set_toml(
            "seestar_initialization",
            "exposure_length_preview_ms",
            int(req.media["init_expo_preview_ms"]),
        )
        self.set_toml(
            "seestar_initialization",
            "exposure_length_stack_ms",
            int(req.media["init_expo_stack_ms"]),
        )
        self.set_toml(
            "seestar_initialization",
            "dither_enabled",
            "init_dither_enabled" in req.media,
        )
        self.set_toml(
            "seestar_initialization",
            "dither_length_pixel",
            int(req.media["init_dither_length_pixel"]),
        )
        self.set_toml(
            "seestar_initialization",
            "dither_frequency",
            int(req.media["init_dither_frequency"]),
        )
        self.set_toml(
            "seestar_initialization",
            "activate_LP_filter",
            "init_activate_LP_filter" in req.media,
        )
        self.set_toml(
            "seestar_initialization",
            "dew_heater_power",
            int(req.media["init_dew_heater_power"]),
        )
        self.set_toml("seestar_initialization", "is_EQ_mode", "is_EQ_mode" in req.media)
        self.set_toml(
            "seestar_initialization", "guest_mode_init", "init_guest_mode" in req.media
        )
        self.set_toml(
            "seestar_initialization",
            "dec_pos_index",
            int(req.media["dec_pos_index"]),
        )
        self.set_toml(
            "seestar_initialization",
            "battery_low_limit",
            int(req.media["battery_low_limit"]),
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

    def save_toml(self, save_name=None):
        """
        Save the in-memory toml dict out to disk in toml format
        """
        if save_name is None:
            save_name = self.path_to_dat
        print(f"save_toml: writing toml to {save_name}")
        with open(save_name, "w") as toml_file:
            toml_file.write(tomlkit.dumps(self._dict))

    #
    # HTML config rendering
    #
    def render_text(self, name, label, value, description="", required=False):
        """
        Render config html form text input
        """
        if type(value) is tomlkit.items.Integer or type(value) is tomlkit.items.Float:
            strType = "number"
            step = 'step="any"'
        else:
            strType = "text"
            step = ""

        if required:
            valRequired = "required"
        else:
            valRequired = ""

        ret = f'''<div class="row mb-3 align-items-center"> <!-- Row -->
                            <div class="col-sm-4 text-end"> <!-- Col -->
                                <label for="{name}" class="form-label">{label}</label>
                            </div> <!-- Close Col -->
                            <div class="col-sm-8 col-md-6"> <!-- Col -->
                                <input id="{name}" name="{name}" type="{strType}" class="form-control" title="{description}" {step} value="{value}" {valRequired}>
                            </div> <!-- Close Col -->
                        </div> <!-- Close Row -->
                    '''
        return ret

    def render_checkbox(self, name, label, checked, description="", hidden=False):
        """
        Render config html form boolean checkbox
        """

        if checked:
            c = "checked"
        else:
            c = ""

        if hidden:
            t = "hidden"
            v = 'value=""'

            ret = f'''<div class="col-sm-8 col-md-6"> <!-- Checkbox -->
                                <input id="{name}_hidden" name="{name}" class="form-check-input" title="{description}" type="{t}" {v} {c}>
                            </div> <!--Close checkbox -->'''

        else:
            t = "checkbox"
            v = ""

            ret = f'''<div class="row mb-3 align-items-center"> <!-- Checkbox Row -->
                                <div class="col-sm-4 text-end"> <!-- Checkbox label -->
                                    <label for="{name}" class="form-label">
                                        {label}
                                    </label>
                                </div> <!-- Close checkbox label -->
                                <div class="col-sm-8 col-md-6"> <!-- Checkbox -->
                                    <input id="{name}" name="{name}" class="form-check-input" title="{description}" type="{t}" {c}>
                                </div> <!--Close checkbox -->
                            </div> <!-- Close checkbox row -->
                        '''
        return ret

    def render_select(self, name, label, options, default, description=""):
        """
        Render config html select dropdown
        """
        retOpt = ""
        for opt in options:
            if opt == default:
                s = "selected"
            else:
                s = ""
            retOpt += f'<option value="{opt}" {s}>{opt}</option>'

        ret = f'''<div class="row mb-3 align-items-center">
                            <div class="col-sm-4 text-end">
                                <label for="{name}" class="form-label">
                                    {label}
                                </label>
                            </div>
                            <div class="col-sm-8 col-md-6">
                                <select class="custom-select" id="{name}" name="{name}" title="{description}">
                                    {retOpt}
                                </select>
                            </div>
                       </div>
                    '''
        return ret

    def render_config_section(self, title, content, id=""):
        """
        Render config html config section div
        """
        divtxt = ""

        if id != "":
            needID = f'id="{id}">'
        else:
            needID = ">"

        divtxt += f"""<div class="card border-primary mb-3"> <!-- Card Border -->
                            <div class="card-header"> <!-- Card header -->
                                <h3>{title}</h3>
                            </div> <!-- Close card header -->
                            <div class="card-body border-primary mb-3" {needID}
                                <div class="container"> <!-- Container -->
                                    {content}
                                </div> <!-- Close container -->
                            </div> <!-- Close card body border -->
                     </div> <!-- Close card border -->
                   """
        return divtxt

    def render_seestars(self):
        """
        Render list of seestars
        """
        ssHTML = ""
        for seestar in self.seestars:
            c = ""

            if "is_EQ_mode" in seestar:
                if self.strToBool(seestar["is_EQ_mode"]):
                    c = "checked"

            ssHTML += f"""<div id="device_div_{seestar["device_num"]}">
                                <div class="col-sm-4 text-end">
                                    <label class="form-label">
                                    <h3>Device number {seestar["device_num"]}</h3>
                                    </label>
                                </div>
                                {self.render_text("ss_name", "Name", seestar["name"], required=True)}
                                {self.render_text("ss_ip_address", "IP Address", seestar["ip_address"], required=True)}

                                <div class="row mb-3 align-items-center"> <!-- Checkbox Row -->
                                    <div class="col-sm-4 text-end"> <!-- Checkbox label -->
                                        <label for="ss_is_EQ_mode_{seestar["device_num"]}" class="form-label">
                                            Is device in EQ mode
                                        </label>
                                    </div> <!-- Close checkbox label -->
                                    <div class="col-sm-8 col-md-6"> <!-- Checkbox -->
                                        <input id="ss_is_EQ_mode_{seestar["device_num"]}" name="ss_is_EQ_mode_{seestar["device_num"]}" class="form-check-input" title="Is device in EQ mode" type="checkbox" {c}>
                                    </div> <!--Close checkbox -->
                                </div> <!-- Close checkbox row -->
                                {self.render_checkbox(f"delete_{seestar['device_num']}", "Delete device", False)}

                            </div>

                        """

        ret = f"""
                <div class="row mb-3 align-items-center">
                    {ssHTML}
                </div>
                <div class="align-items-center">
                    <button style="margin:5px;" type="button" class="btn btn-primary" id="add_seestar" onclick="addSeestar()">
                        Add Seestar Device
                    </button>
                    <button style="margin:5px;" type="button" class="btn btn-primary" id="del_Seestar" onclick="delSeestar()">
                        Delete selected Seestar(s)
                    </button>
                </div>
                """
        return ret

    def convert_AOT(self, settings):
        seestars = settings["seestars"]
        ret = []
        for seestar in seestars:
            ret.append(seestar)
        return ret

    def render_config_html(self):
        """
        Render config html
        """
        log_levels = [
            logging.getLevelName(x)
            for x in sorted(list(set(logging._levelToName.keys())))
            if x != 0
        ]
        return (
            self.render_config_section(
                "Networking",
                self.render_text(
                    "ip_address",
                    "IP address:",
                    self.ip_address,
                    "IP address to open for communication, use 127.0.0.1 if running on one machine\n or use 0.0.0.0 to acess from all adresses",
                    required=True,
                )
                + self.render_text(
                    "port",
                    "Port:",
                    self.port,
                    "Port that alpaca will run on (this should not need to be changed except in extreme cases) default 5555",
                    required=True,
                )
                + self.render_text(
                    "imgport",
                    "IMG Port:",
                    self.imgport,
                    "Imaging API port (this should not need to be changed except in extreme cases) default 7556",
                    required=True,
                )
                + self.render_text(
                    "sthost",
                    "Stellarium host:",
                    self.sthost,
                    "IP address of the machine running stellarium (127.0.0.1 if on same machine as ALP)",
                )
                + self.render_text(
                    "stport",
                    "Stellarium port:",
                    self.stport,
                    "Port to connect to stellarium on (default 8090)",
                )
                + self.render_text(
                    "timeout",
                    "Timeout:",
                    self.timeout,
                    "General socket timeout (this should not need to be changed except in extreme cases) default 5",
                )
                + self.render_checkbox(
                    "rtsp_udp",
                    "RTSP UDP:",
                    self.rtsp_udp,
                    "Use UDP protocol for RSTP streaming",
                ),
            )
            + self.render_config_section(
                "Web UI",
                self.render_text(
                    "uiport",
                    "UI port:",
                    self.uiport,
                    "Port to use for connecting to the frontend (SSC) default 5432",
                    required=True,
                )
                + self.render_select(
                    "uitheme",
                    "UI theme:",
                    ["dark", "light"],
                    self.uitheme,
                    "Theme to use for the frontend",
                )
                + self.render_checkbox(
                    "experimental",
                    "Experimental:",
                    self.experimental,
                    "Show experimental features (Only recommeded for experienced users)",
                )
                + self.render_checkbox(
                    "confirm",
                    "Commands Confirmation Dialog:",
                    self.confirm,
                    "Enable/Disable the Commands page confirmation dialog",
                )
                + self.render_checkbox(
                    "save_frames",
                    "Save star preview frames locally:",
                    self.save_frames,
                    "Save frames received on live page when in preview mode",
                )
                + self.render_text(
                    "save_frames_dir",
                    "Save frames base directory:",
                    self.save_frames_dir,
                    "Location to save preview frames (. is current directory)",
                )
                + self.render_text(
                    "loading_gif",
                    "Loading gif:",
                    self.loading_gif,
                    "Filename of loading gif to use on live view page",
                ),
            )
            + self.render_config_section(
                "Server",
                self.render_text(
                    "location",
                    "Location:",
                    self.location,
                    "Descriptor for when remote access becomes available",
                )
                + self.render_checkbox(
                    "verbose_driver_exceptions",
                    "Verbose driver exceptions:",
                    self.verbose_driver_exceptions,
                    "Give more information upon driver errors",
                ),
            )
            + self.render_config_section(
                "Device",
                self.render_checkbox(
                    "can_reverse",
                    "Can reverse:",
                    self.can_reverse,
                    "Not used at this time",
                )
                + self.render_text(
                    "step_size", "Step size:", self.step_size, "Not used at this time"
                )
                + self.render_text(
                    "steps_per_sec",
                    "Steps per second:",
                    self.steps_per_sec,
                    "Not used at this time",
                ),
            )
            + self.render_config_section(
                "Logging",
                self.render_select(
                    "log_level",
                    "Log level:",
                    log_levels,
                    logging.getLevelName(self.log_level),
                    "Level of logging, default INFO",
                )
                + self.render_text(
                    "log_prefix",
                    "Log prefix:",
                    self.log_prefix,
                    "Optional prefix to add to logfiles",
                )
                + self.render_checkbox(
                    "log_to_stdout",
                    "Log to stdout:",
                    self.log_to_stdout,
                    "Log to the console as well as the logfile",
                )
                + self.render_text(
                    "max_size_mb",
                    "Max log size in MB:",
                    self.max_size_mb,
                    "Maximum size of logfile before starting a new one",
                )
                + self.render_text(
                    "num_keep_logs",
                    "Number of logs to keep:",
                    self.num_keep_logs,
                    "Number of logfiles to keep before deleting the oldest",
                )
                + self.render_checkbox(
                    "log_events_in_info",
                    "Log events in INFO:",
                    self.log_events_in_info,
                    "Log INFO events",
                ),
            )
            + self.render_config_section(
                "Seestar Initialization",
                self.render_checkbox(
                    "init_save_good_frames",
                    "Save good frames:",
                    self.init_save_good_frames,
                    "Save all good frames",
                )
                + self.render_checkbox(
                    "init_save_all_frames",
                    "Save all frames:",
                    self.init_save_all_frames,
                    "Save all frames, including ones rejected for stacking",
                )
                + self.render_text(
                    "init_lat",
                    "Latitude:",
                    self.init_lat,
                    "Your Latitude in decimal format",
                )
                + self.render_text(
                    "init_long",
                    "Longitude:",
                    self.init_long,
                    "Your Longitude in decimal format",
                )
                + self.render_text(
                    "init_gain",
                    "Gain:",
                    self.init_gain,
                    "Gain to use when initially turning on",
                )
                + self.render_text(
                    "init_expo_preview_ms",
                    "Exposure preview ms:",
                    self.init_expo_preview_ms,
                    "Exsposure length for images used in preview mode, in milliseconds",
                )
                + self.render_text(
                    "init_expo_stack_ms",
                    "Exposure stack ms:",
                    self.init_expo_stack_ms,
                    "Exposure length used in images to stack, in milliseconds",
                )
                + self.render_checkbox(
                    "init_dither_enabled",
                    "Dither enabled:",
                    self.init_dither_enabled,
                    "Enable / Disable Dithering",
                )
                + self.render_text(
                    "init_dither_length_pixel",
                    "Dither length pixels:",
                    self.init_dither_length_pixel,
                    "Number of pixels to move each dithering movement",
                )
                + self.render_text(
                    "init_dither_frequency",
                    "Dither frequency:",
                    self.init_dither_frequency,
                    "Number of frames between dithering movements",
                )
                + self.render_checkbox(
                    "init_activate_LP_filter",
                    "Activate LP filter:",
                    self.init_activate_LP_filter,
                    "Switch on Light Pollution Filter",
                )
                + self.render_text(
                    "init_dew_heater_power",
                    "Dew heater power:",
                    self.init_dew_heater_power,
                    "Dew heater power level, 0 - 100",
                )
                + self.render_checkbox(
                    "is_EQ_mode",
                    "Scope in EQ Mode:",
                    self.is_EQ_mode,
                    "Is the scope in equitorial mode",
                )
                + self.render_checkbox(
                    "init_guest_mode",
                    "Claim guest mode control:",
                    self.init_guest_mode,
                    "Claim guest mode on init",
                )
                + self.render_text(
                    "dec_pos_index",
                    "Dec Offset:",
                    self.dec_pos_index,
                    "Set Dec Offset for EQ Polar Alignment, 1-5",
                )
                + self.render_text(
                    "battery_low_limit",
                    "Battery low limit percentage:",
                    self.battery_low_limit,
                    "Lower limit for battery, before safe shutdown",
                ),
            )
            + self.render_config_section(
                "Seestar Devices", self.render_seestars(), "seestar_devices"
            )
        )
        return self._dict


Config = _Config()
