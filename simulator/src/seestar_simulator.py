import threading
import time
import collections
import uuid
import json


class SeestarSimulator:
    def __init__(
        self, logger, host, port, device_name, device_num, is_EQ_mode, is_debug=False
    ):
        self.logger = logger
        self.host = host
        self.port = port
        self.device_name = device_name
        self.device_num = device_num
        self.is_EQ_mode = is_EQ_mode
        self.is_debug = is_debug
        self.cmdid = 10000
        self.scope_radec = [0.0, 0.0]  # Simulated RA/Dec coordinates
        self.socket = None
        self.start_time = time.time()
        self.stack_start_time = 0
        self.schedule = {
            "version": 1.0,
            "Event": "Scheduler",
            "schedule_id": str(uuid.uuid4()),
            "list": collections.deque(),
            "state": "stopped",
            "is_stacking_paused": False,
            "is_stacking": False,
            "is_skip_requested": False,
            "current_item_id": "",
            "item_number": 9999,
        }
        self.event_state = {}
        self.response_dict = {}
        self.image_mode = "none"
        self.pa_enhance_mode = False
        self.state = {
            "device": {
                "name": "ASI AIR imager",
                "firmware_ver_int": 2470,
                "firmware_ver_string": "4.70",
                "is_verified": True,
                "sn": "simulated123",
                "cpuId": "simcpu123",
                "product_model": "Seestar S50",
                "user_product_model": "Seestar S50",
                "focal_len": 250.0,
                "fnumber": 5.0,
                "can_star_mode_sel_cam": False,
            },
            "setting": {
                "temp_unit": "C",
                "beep_volume": "backyard",
                "lang": "en",
                "center_xy": [540, 960],
                "stack_lenhance": False,
                "heater_enable": False,
                "heater": {"state": False, "value": 0},
                "expt_heater_enable": False,
                "focal_pos": 1500,
                "factory_focal_pos": 1500,
                "exp_ms": {"stack_l": 10000, "continuous": 500},
                "auto_power_off": True,
                "stack_dither": {"pix": 50, "interval": 5, "enable": True},
                "auto_3ppa_calib": True,
                "auto_af": False,
                "frame_calib": True,
                "calib_location": 2,
                "wide_cam": False,
                "stack_after_goto": False,
                "guest_mode": False,
                "user_stack_sim": False,
                "usb_en_eth": False,
                "dark_mode": False,
                "af_before_stack": False,
                "mosaic": {
                    "scale": 1.0,
                    "angle": 0.0,
                    "estimated_hours": 0.258333,
                    "star_map_angle": 361.0,
                    "star_map_ratio": 1.0,
                },
                "stack": {"dbe": False, "star_correction": True, "cont_capt": False},
                "rtsp_roi_index": 0,
                "ae_bri_percent": 50.0,
                "manual_exp": False,
                "isp_exp_ms": -999000.0,
                "isp_gain": -9990.0,
                "isp_range_gain": [0, 400],
                "isp_range_exp_us": [30, 1000000],
                "isp_range_exp_us_scenery": [30, 1000000],
            },
            "location_lon_lat": [-99.3533, 35.4078],
            "camera": {
                "chip_size": [1080, 1920],
                "pixel_size_um": 2.9,
                "debayer_pattern": "GR",
                "hpc_num": 5246,
            },
            "focuser": {"state": "idle", "max_step": 2600, "step": 1500},
            "ap": {"ssid": "S50_simulated", "passwd": "12345678", "is_5g": True},
            "station": {
                "server": True,
                "freq": 5240,
                "ip": "192.168.1.47",
                "ssid": "SIMNET",
                "gateway": "192.168.1.1",
                "netmask": "255.255.255.0",
                "sig_lev": -41,
                "key_mgmt": "WPA2-PSK",
            },
            "storage": {
                "is_typec_connected": False,
                "connected_storage": ["emmc"],
                "storage_volume": [
                    {
                        "name": "emmc",
                        "state": "mounted",
                        "total_mb": 51854,
                        "totalMB": 51854,
                        "free_mb": 46907,
                        "freeMB": 46907,
                        "disk_mb": 59699,
                        "diskSizeMB": 59699,
                        "used_percent": 21,
                    }
                ],
                "cur_storage": "emmc",
            },
            "balance_sensor": {
                "code": 0,
                "data": {"x": 0, "y": 0, "z": 0, "angle": 90.0},
            },
            "compass_sensor": {
                "code": 0,
                "data": {"x": 0, "y": 0, "z": 0, "direction": 90.0, "cali": 0},
            },
            "mount": {
                "move_type": "none",
                "close": True,
                "tracking": False,
                "equ_mode": True,
            },
            "pi_status": {
                "is_overtemp": False,
                "temp": 38.8,
                "charger_status": "Discharging",
                "battery_capacity": 100,
                "charge_online": False,
                "is_typec_connected": False,
                "battery_overtemp": False,
                "battery_temp": 20,
                "battery_temp_type": "normal",
            },
        }
        self.stack_settings = {
            "save_discrete_frame": True,
            "save_discrete_ok_frame": True,
            "light_duration_min": 10,
        }
        self.filter_wheel = {
            "state": "idle",
            "position": 0,
            "positions": [
                {"name": "Dark", "id": 0},
                {"name": "IRCut", "id": 1},
                {"name": "LP", "id": 2},
            ],
        }
        self.scope_time = {
            "year": 0,
            "mon": 0,
            "day": 0,
            "hour": 0,
            "ha": 0,
            "sec": 0,
            "time_zone": "UTC+0",
        }
        self.logger.info(
            f"SeestarSimulator initialized with device name: {self.device_name}, device number: {self.device_num}"
        )
        # Initialize the state with default value

    # self.simulator.set_socket(self.tcp_socket)  # Set the socket in the simulator
    def set_socket(self, sock):
        """
        Set the socket for the simulator to use for sending unsolicited messages.
        This is typically called by the SocketListener when it starts listening.
        """
        self.socket = sock
        self.logger.debug(f"Socket set in SeestarSimulator: {sock}")

    # Simulate the main API methods
    def send_message_param_sync(self, data):
        # If data is a string, try to parse it as JSON
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                self.logger.debug(f"Could not parse data as JSON: {data}")
                return {"jsonrpc": "2.0", "result": "invalid input", "id": self.cmdid}
        # print(f'Received data in send_message_parm_sync: {data}')
        method = data.get("method")
        cur_cmdid = data.get("id", self.cmdid)
        #self.logger.debug(f"Method called: {method}")
        # Simulate responses for some methods
        timestamp = f"{time.time() - self.start_time:2.9f}"

        if method == "get_device_state":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_device_state",
                "result": self.state,
                "code": 0,
                "id": cur_cmdid,
            }
        if method == "get_stack_setting":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_stack_setting",
                "result": self.stack_settings,
                "code": 0,
                "id": cur_cmdid,
            }
        if method == "get_view_state":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_view_state",
                "result": {},
                "code": 0,
                "id": cur_cmdid,
            }
        if method == "pi_station_state":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "pi_station_state",
                "result": self.state["station"],
                "code": 0,
                "id": cur_cmdid,
            }
        elif method == "set_setting":
            self.state["setting"].update(data.get("params", {}))
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "set_setting",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "pi_output_set2":
            self.state["setting"].update(data.get("params", {}))
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "pi_output_set2",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "get_setting":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_setting",
                "result": self.state["setting"],
                "id": cur_cmdid,
            }
        elif method == "get_focuser_position":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_focuser_position",
                "result": self.state["focuser"]["step"],
                "id": cur_cmdid,
            }
        elif method == "move_focuser":
            step = data.get("params", {}).get("step", self.state["focuser"]["step"])
            self.state["focuser"]["step"] = step
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "move_focuser",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "set_wheel_position":
            position = data.get("params", {})
            self.filter_wheel["state"] = "moving"
            self.filter_wheel["position"] = position[0]
            # Simulate a delay for the filter wheel movement
            time.sleep(1)
            self.filter_wheel["state"] = "idle"
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "set_wheel_position",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "get_wheel_setting":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_wheel_setting",
                "result": {
                    "names": ["dark", "IRCUT", "LP"],
                    "exp_sec": [2.0, 2.0, 2.0],
                },
                "id": cur_cmdid,
            }
        elif method == "get_wheel_state":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_wheel_state",
                "result": {"id": 0, "state": "idle", "unidirection": False},
                "id": cur_cmdid,
            }
        elif method == "set_control_value":
            params = data.get("params", [])
            if isinstance(params, list):
                # Update the state based on the parameters
                if params[0] == "exposure":
                    self.state["setting"]["isp_exp_ms"] = params[1]
                elif params[0] == "gain":
                    self.state["setting"]["isp_gain"] = params[1]
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "set_control_value",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "get_schedule":
            return self.schedule
        elif method == "start_create_dark":
            # Simulate dark frame creation
            self.create_dark()
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "start_create_dark",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "iscope_start_stack":
            self.schedule["is_stacking"] = True
            self.stack_start_time = time.time()
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "iscope_start_stack",
                "result": 0,
                "code": 0,
                "id": cur_cmdid,
            }
        elif method == "iscope_stop_view":
            self.schedule["is_stacking"] = False
            self.image_mode = "none"
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "iscope_stop_view",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "iscope_start_view":
            # Simulate starting a view
            if data.get("params", {}).get("target_ra_dec", None) is not None:
                self.schedule["is_stacking"] = True
                self.scope_radec = data.get("params", {}).get("target_ra_dec", [0, 0])
                self.goto_target(
                    {"ra": self.scope_radec[0], "dec": self.scope_radec[1]}
                )
            elif data.get("params", {}).get("mode", None) is not None:
                self.image_mode = data.get("params", {}).get("mode", "none")
                self.schedule["is_stacking"] = True
                if self.image_mode == "star":
                    self.pa_enhance_mode = True
                    self.start_pa_enhance()
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "iscope_start_view",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "scope_goto":
            # Simulate slewing
            self.state["mount"]["move_type"] = "goto"
            return {
                "jsonrpc": "2.0",
                "method": "scope_goto",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "scope_sync":
            # Simulate sync
            return {"jsonrpc": "2.0", "result": 0, "id": cur_cmdid}
        elif method == "scope_speed_move":
            # Simulate move
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "scope_speed_move",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "play_sound":
            return {
                "jsonrpc": "2.0",
                "method": "play_sound",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "start_auto_focuse":
            self.try_auto_focus()
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "start_auto_focuse",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "stop_auto_focuse":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "stop_auto_focuse",
                "status": "success",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "start_polar_align":
            self.polar_align()
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "start_polar_align",
                "result": 0,
                "code": 0,
                "id": cur_cmdid,
            }
        elif method == "set_user_location":
            loc = data.get("params", {})
            self.state["location_lon_lat"] = [loc.get("lon", 0), loc.get("lat", 0)]
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "set_user_location",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "set_stack_setting":
            # Simulate stack setting
            self.stack_settings.update(data.get("params", {}))
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "set_setting",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "get_event_state":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_event_state",
                "result": self.event_state,
                "id": cur_cmdid,
            }
        elif method == "scope_park":
            self.scope_park()
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "scope_park",
                "result": "scope park simulated",
                "id": cur_cmdid,
            }
        elif method == "pi_shutdown":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "pi_shutdown",
                "result": "shutdown simulated",
                "id": cur_cmdid,
            }
        elif method == "pi_set_time":
            # Simulate setting time
            self.scope_time = data.get("params", {})
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "pi_set_time",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "pi_is_verified":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "pi_is_verified",
                "result": self.state["device"]["is_verified"],
                "id": cur_cmdid,
            }
        elif method == "pi_reboot":
            return {"jsonrpc": "2.0", "result": "reboot simulated", "id": cur_cmdid}
        elif method == "scope_get_equ_coord":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "scope_get_equ_coord",
                "result": {"ra": self.scope_radec[0], "dec": self.scope_radec[1]},
                "code": 0,
                "id": cur_cmdid,
            }
        elif method == "set_sequence_setting":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "set_sequence_setting",
                "id": cur_cmdid,
            }
        elif method == "get_camera_exp_and_bin":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_camera_exp_and_bin",
                "result": {"exposure": self.state["setting"]["isp_exp_ms"], "bin": 1},
                "id": cur_cmdid,
            }
        elif method == "get_img_name_field":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_img_name_field",
                "result": {
                    "bin": True,
                    "date_time": True,
                    "temp": True,
                    "gain": True,
                    "camera_name": False,
                },
                "id": cur_cmdid,
            }
        elif method == "get_camera_state":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_camera_state",
                "result": {
                    "bin": True,
                    "date_time": True,
                    "temp": True,
                    "gain": True,
                    "camera_name": False,
                },
                "id": cur_cmdid,
            }
        elif method == "get_image_save_path":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_image_save_path",
                "result": self.state["storage"],
                "id": cur_cmdid,
            }
        elif method == "get_stack_info":
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "get_stack_info ",
                "result": {"width": 0, "height": 0},
                "id": cur_cmdid,
            }
        elif method == "stop_polar_align":
            self.pa_enhance_mode = False
            self.view_mode = "none"
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "stop_polar_align ",
                "result": 0,
                "id": cur_cmdid,
            }

        # Add more simulated methods as needed
        else:
            self.logger.info(
                f"=============================Unknown method: {method}, {data}"
            )
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": method,
                "result": 0,
                "id": cur_cmdid,
            }

    def start_pa_enhance(self):
        self.pa_enhance_response_thread = threading.Thread(target=self._pa_enhance)
        self.pa_enhance_response_thread.start()
        return True

    def _pa_enhance(self):
        # simulate PA enhance process
        # these are the x and y errors that will be sent to the main seestar program
        # add more x and y errors as needed
        x_errors = [0.1, -0.2, 0.15, -0.1, 0.05]
        y_errors = [0.05, -0.1, 0.1, -0.05, 0.02]

        timestamp = f"{time.time() - self.start_time:2.9f}"

        while self.pa_enhance_mode:
            for x_err, y_err in zip(x_errors, y_errors):
                timestamp = f"{time.time() - self.start_time:2.9f}"
                event = {
                    "Event": "EqModePA",
                    "Timestamp": timestamp,
                    "state": "complete",
                    "lapse_ms": 0,
                    "x": x_err,
                    "y": y_err,
                    "route": [],
                }
                self.send_unsolicited_message(
                    self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
                )
                time.sleep(2)

    def create_dark(self):
        self.create_dark_response_thread = threading.Thread(target=self._create_dark)
        self.create_dark_response_thread.start()
        return True

    def _create_dark(self):
        # simulate dark frame creation
        timestamp = f"{time.time() - self.start_time:2.9f}"

        event = {
            "Event": "DarkLibrary",
            "Timestamp": timestamp,
            "state": "working",
            "lapse_ms": 0,
            "percent": 0.0,
            "route": ["View", "Initialise"],
        }
        self.send_unsolicited_message(
            self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
        )

        for i in range(1, 100, 3):
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "DarkLibrary",
                "Timestamp": timestamp,
                "state": "working",
                "lapse_ms": 0,
                "percent": i,
                "route": ["View", "Initialise"],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )
            time.sleep(0.1)

        time.sleep(1)
        timestamp = f"{time.time() - self.start_time:2.9f}"

        # Send unsolicited TCP message to the main seestar program
        try:
            # Connect to the main seestar program's TCP server
            event = {
                "Event": "DarkLibrary",
                "Timestamp": timestamp,
                "state": "complete",
                "lapse_ms": 59123,
                "percent": 100.0,
                "route": [],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )
        except Exception as e:
            self.logger.warn(f"Error sending unsolicited TCP message: {e}")

        return

    def goto_target(self, params):
        self.state["mount"]["move_type"] = "goto"
        self.goto_target_response_thread = threading.Thread(
            target=self._goto_target_response, args=(params,)
        )
        self.goto_target_response_thread.start()
        return True

    def _goto_target_response(self, params):
        time.sleep(2)
        # {'Event': 'AutoGoto', 'Timestamp': '988.193228786', 'page': 'preview', 'tag': 'Exposure', 'func': 'goto_ra_dec', 'state': 'complete'}
        self.state["mount"]["move_type"] = "none"

        # Send unsolicited TCP message to the main seestar program
        try:
            # Connect to the main seestar program's TCP server
            event = {
                "Event": "AutoGoto",
                "Timestamp": f"{time.time():2.9f}",
                "page": "preview",
                "tag": "Exposure",
                "func": "goto_ra_dec",
                "state": "complete",
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )
        except Exception as e:
            self.logger(f"Error sending unsolicited TCP message: {e}")

        return

    def stop_goto_target(self):
        self.state["mount"]["move_type"] = "none"
        return "goto stopped"

    # {'Event': 'AutoFocus', 'Timestamp': '7191.667685231', 'state': 'complete', 'result': {'last_point': [0, 0.0]}}
    def try_auto_focus(self) -> bool:
        self.auto_focus_response_thread = threading.Thread(target=self._try_auto_focus)
        self.auto_focus_response_thread.start()
        return True

    def _try_auto_focus(self):
        time.sleep(10)
        # self.state['mount']['move_type'] = 'none'
        timestamp = f"{time.time() - self.start_time:2.9f}"
        # Send unsolicited TCP message to the main seestar program

        try:
            event = {
                "Event": "AutoFocus",
                "Timestamp": timestamp,
                "result": {"last_point": [0, 0.0]},
                "state": "complete",
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )
        except Exception as e:
            self.logger.warn(f"Error sending unsolicited TCP message: {e}")

        return

    def scope_park(self) -> bool:
        self.scope_park_response_thread = threading.Thread(target=self._scope_park)
        self.scope_park_response_thread.start()
        return True

    def _scope_park(self):
        # send out a working message before we send out the completed message
        timestamp = f"{time.time() - self.start_time:2.9f}"
        try:
            # Connect to the main seestar program's TCP server
            event = {
                "Event": "ScopeHome",
                "Timestamp": timestamp,
                "state": "working",
                "lapse_ms": 0,
                "close": False,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(10)

            timestamp = f"{time.time() - self.start_time:2.9f}"
            # Connect to the main seestar program's TCP server
            event = {
                "Event": "ScopeHome",
                "Timestamp": timestamp,
                "state": "complete",
                "lapse_ms": 10381,
                "close": True,
                "equ_mode": True,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )
        except Exception as e:
            print(f"Error sending unsolicited TCP message: {e}")

        return

    def polar_align(self) -> bool:
        self.polar_align_response_thread = threading.Thread(target=self._polar_align)
        self.polar_align_response_thread.start()
        return True

    # 'Event': 'EqModePA', 'Timestamp': '457.182378072', 'state': 'complete', 'lapse_ms': 78917, 'total': 20.020836, 'x': -20.020597, 'y': 0.097836, 'route': []}
    def _polar_align(self):
        time.sleep(1)
        # send out a working message before we send out the completed message
        timestamp = f"{time.time() - self.start_time:2.9f}"
        #  {'Event': 'EqModePA', 'Timestamp': '378.265266217', 'state': 'working', 'lapse_ms': 0, 'route': []}
        try:
            # Connect to the main seestar program's TCP server
            event = {
                "Event": "EqModePA",
                "Timestamp": timestamp,
                "state": "working",
                "lapse_ms": 0,
                "close": False,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "3PPA",
                "Timestamp": timestamp,
                "state": "start",
                "state_code": 1,
                "auto_move": True,
                "auto_update": False,
                "paused": False,
                "detail": {},
                "retry_cnt": 0,
                "lapse_ms": 4,
                "close": False,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "ScopeTrack",
                "Timestamp": timestamp,
                "state": "off",
                "tracking": False,
                "manual": True,
                "route": [],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {"Event": "WheelMove", "Timestamp": timestamp, "state": "start"}
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(0.5)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "WheelMove",
                "Timestamp": timestamp,
                "state": "complete",
                "position": 1,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            event = {
                "Event": "ScopeGoto",
                "Timestamp": timestamp,
                "state": "working",
                "lapse_ms": 0,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(0.5)

            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "ScopeTrack",
                "Timestamp": timestamp,
                "state": "off",
                "tracking": False,
                "manual": False,
                "error": "fail to operate",
                "code": 207,
                "route": [],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            # time.sleep(17)
            time.sleep(3)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "ScopeTrack",
                "Timestamp": timestamp,
                "state": "on",
                "tracking": True,
                "manual": False,
                "route": [],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(1)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "ScopeGoto",
                "Timestamp": timestamp,
                "state": "complete",
                "lapse_ms": 45775,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(1)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "ScopeTrack",
                "Timestamp": timestamp,
                "state": "off",
                "tracking": False,
                "manual": True,
                "route": [],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            event = {
                "Event": "Exposure",
                "Timestamp": timestamp,
                "state": "working",
                "lapse_ms": 0,
                "exp_ms": 2000.0,
                "route": ["EqModePA"],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            event = {
                "Event": "Exposure",
                "Timestamp": timestamp,
                "page": "preview",
                "state": "start",
                "exp_us": 2000000,
                "gain": 80,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(0.20)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "ScopeTrack",
                "Timestamp": timestamp,
                "state": "off",
                "tracking": False,
                "manual": False,
                "error": "fail to operate",
                "code": 207,
                "route": [],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(3)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "Exposure",
                "Timestamp": timestamp,
                "page": "preview",
                "state": "downloading",
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(0.1)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "Exposure",
                "Timestamp": timestamp,
                "page": "preview",
                "state": "complete",
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            event = {
                "Event": "Exposure",
                "Timestamp": timestamp,
                "state": "complete",
                "lapse_ms": 3582,
                "exp_ms": 2000.0,
                "route": ["EqModePA"],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            event = {
                "Event": "PlateSolve",
                "Timestamp": timestamp,
                "state": "working",
                "lapse_ms": 0,
                "route": ["EqModePA"],
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(0.2)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "PlateSolve",
                "Timestamp": timestamp,
                "page": "preview",
                "state": "start",
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            event = {
                "Event": "PlateSolve",
                "Timestamp": timestamp,
                "page": "preview",
                "state": "start",
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            event = {
                "Event": "PlateSolve",
                "Timestamp": timestamp,
                "page": "stack",
                "state": "complete",
                "result": {
                    "ra_dec": [12.652991, 11.645831],
                    "fov": [0.71281, 1.26685],
                    "focal_len": 251.82373,
                    "angle": 1.479996,
                    "image_id": 887,
                    "star_number": 1522,
                    "duration_ms": 3811,
                },
            }

            # uncomment if you want to test plate solve failure
            # event = {'Event': 'PlateSolve', 'Timestamp': timestamp, 'state': 'fail', 'error': 'solve failed', 'code': 251, 'lapse_ms': 1730, 'route': ['EqModePA']}
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(1)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {"Event": "WheelMove", "Timestamp": timestamp, "state": "start"}
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

            time.sleep(0.5)
            timestamp = f"{time.time() - self.start_time:2.9f}"
            event = {
                "Event": "WheelMove",
                "Timestamp": timestamp,
                "state": "complete",
                "position": 1,
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

        except Exception as e:
            print(f"Error sending unsolicited TCP message: {e}")

        time.sleep(1)
        # self.state['mount']['move_type'] = 'none'
        timestamp = f"{time.time() - self.start_time:2.9f}"
        # ends polar align
        try:
            # Connect to the main seestar program's TCP server
            event = {
                "Event": "EqModePA",
                "Timestamp": timestamp,
                "lapse_ms": 78917,
                "total": 20.020836,
                "x": -0.020597,
                "y": 0.097836,
                "route": [],
                "result": 0,
                "state": "complete",
            }
            self.send_unsolicited_message(
                self.socket, (self.host, self.port), json.dumps(event) + "\r\n"
            )

        except Exception as e:
            print(f"Error sending unsolicited TCP message: {e}")

        return

    def send_unsolicited_message(self, sock, addr, message):
        """
        Send an unsolicited message to the given socket and address.
        `sock` should be a socket.socket object (UDP or TCP).
        `addr` is a tuple (host, port).
        `message` is a string or bytes.
        """
        if isinstance(message, str):
            message = message.encode("utf-8")
        try:
            sock.sendto(message, addr)
            self.logger.debug(f"Unsolicited message sent to {addr}: {message}")
        except Exception as e:
            self.logger.debug(f"Error sending unsolicited message to {addr}: {e}")

    # ...add more methods as needed for your simulation...
