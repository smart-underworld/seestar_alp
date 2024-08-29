import socket
import json
import time
from datetime import datetime
import threading
import sys, os
import math
import uuid
from time import sleep

import tzlocal

from config import Config
from seestar_util import Util


class Seestar:
    def __new__(cls, *args, **kwargs):
        # print("Create a new instance of Seestar.")
        return super().__new__(cls)

    # <ip_address> <port> <device name> <device num>
    def __init__(self, logger, host, port, device_name, device_num, is_debug=False):
        logger.info(
            f"Initialize the new instance of Seestar: {host}:{port}, name:{device_name}, num:{device_num}, is_debug:{is_debug}")

        self.host = host
        self.port = port
        self.device_name = device_name
        self.device_num = device_num
        self.cmdid = 10000
        self.ra = 0.0
        self.dec = 0.0
        self.is_watch_events = False  # Tracks if device has been started even if it never connected
        self.op_watch = ""
        self.op_state = ""
        self.s = None
        self.get_msg_thread = ""
        self.heartbeat_msg_thread = ""
        self.is_debug = is_debug
        self.response_dict = {}
        self.logger = logger
        self.is_connected = False
        self.site_elevation = 0
        self.site_latitude = 0
        self.site_longitude = 0
        self.is_slewing = False
        self.target_dec = 0
        self.target_ra = 0
        self.utcdate = time.time()
        self.scheduler_state = "Stopped"
        self.scheduler_item_state = "Stopped"
        self.scheduler_item_id = ""
        self.scheduler_item = "" # Text description of specific scheduler item that's running
        self.mosaic_thread = ""
        self.scheduler_thread = ""
        self.schedule = {}
        self.schedule['list'] = []
        self.schedule['state'] = self.scheduler_state
        self.schedule['current_item_id'] = ""
        # self.schedule['current_item_detail']    # Text description for mosaic?
        self.cur_solve_RA = -9999.0  #
        self.cur_solve_Dec = -9999.0
        self.cur_mosaic_nRA = -1
        self.cur_mosaic_nDec = -1
        self.goto_state = "complete"
        self.connect_count = 0
        self.below_horizon_dec_offset = 0  # we will use this to work around below horizon. This value will ve used to fool Seestar's star map
        self.view_state = {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(host={self.host}, port={self.port})"

    def heartbeat(self):  # I noticed a lot of pairs of test_connection followed by a get if nothing was going on
        #    json_message("test_connection")
        self.json_message("scope_get_equ_coord")

    def send_message(self, data):
        try:
            self.s.sendall(data.encode())  # TODO: would utf-8 or unicode_escaped help here
            return True
        except socket.timeout:
            return False
        except socket.error as e:
            # Don't bother trying to recover if watch events is False
            self.logger.error(f"Send socket error: {e}")
            self.disconnect()
            if self.is_watch_events and self.reconnect():
                return self.send_message(data)
            return False

    def socket_force_close(self):
        if self.s:
            try:
                self.s.close()
                self.s = None
            except:
                pass

    def disconnect(self):
        # Disconnect tries to clean up socket if it exists
        self.is_connected = False
        self.socket_force_close()

    def reconnect(self):
        if self.is_connected:
            return True

        try:
            self.logger.debug(f"RECONNECTING {self.device_name}")

            self.disconnect()

            # note: the below isn't thread safe!  (Reconnect can be called from different threads.)
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.settimeout(Config.timeout)
            self.s.connect((self.host, self.port))
            # self.s.settimeout(None)
            self.is_connected = True
            return True
        except socket.error as e:
            # Let's just delay a fraction of a second to avoid reconnecting too quickly
            self.is_connected = False
            sleep(0.1)
            return False

    def get_socket_msg(self):
        try:
            data = self.s.recv(1024 * 60)  # comet data is >50kb
        except socket.timeout:
            return None
        except socket.error as e:
            # todo : if general socket error, close socket, and kick off reconnect?
            # todo : no route to host...
            self.logger.error(f"Read socket error: {e}")
            # todo : handle message failure
            self.disconnect()
            if self.is_watch_events and self.reconnect():
                return self.get_socket_msg()
            return None

        data = data.decode("utf-8")
        if len(data) == 0:
            return None

        self.logger.debug(f'{self.device_name} received : {data}')
        return data

    def update_equ_coord(self, parsed_data):
        if parsed_data['method'] == "scope_get_equ_coord" and 'result' in parsed_data:
            data_result = parsed_data['result']
            self.ra = float(data_result['ra'])
            self.dec = float(data_result['dec'] - self.below_horizon_dec_offset)

    def update_view_state(self, parsed_data):
        if parsed_data['method'] == "get_view_state" and 'result' in parsed_data:
            view = parsed_data['result'].get('View')
            if view:
                self.view_state = view
            #else:
            #    self.view_state = {}

    def heartbeat_message_thread_fn(self):
        while self.is_watch_events:
            if not self.is_connected and not self.reconnect():
                sleep(5)
                continue

            self.heartbeat()
            time.sleep(3)

    def receive_message_thread_fn(self):
        msg_remainder = ""
        while self.is_watch_events:
            # print("checking for msg")
            data = self.get_socket_msg()
            if data:
                msg_remainder += data
                first_index = msg_remainder.find("\r\n")

                while first_index >= 0:
                    first_msg = msg_remainder[0:first_index]
                    msg_remainder = msg_remainder[first_index + 2:]
                    parsed_data = json.loads(first_msg)  # xxx : check for errors here!

                    self.logger.debug(f'{self.device_name} : {parsed_data}')

                    if 'jsonrpc' in parsed_data:
                        # {"jsonrpc":"2.0","Timestamp":"9507.244805160","method":"scope_get_equ_coord","result":{"ra":17.093056,"dec":34.349722},"code":0,"id":83}
                        if parsed_data["method"] == "scope_get_equ_coord":
                            self.update_equ_coord(parsed_data)
                        if parsed_data["method"] == "get_view_state":
                            self.update_view_state(parsed_data)
                        # keep a running queue of last 100 responses for sync call results
                        self.response_dict[parsed_data["id"]] = parsed_data
                        while len(parsed_data) > 100:
                            self.response_dict.popitem()

                    elif 'Event' in parsed_data:
                        event_name = parsed_data['Event']
                        if event_name == self.op_watch:  # "AutoGoto" or "AutoFocus"
                            state = parsed_data['state']
                            self.logger.info(f'{self.device_name} state {self.op_watch} : {state}')
                            if state == "complete" or state == "fail":
                                self.logger.info("Goto Final State: %s", parsed_data)
                                self.op_state = state
                        # {'Event': 'PlateSolve', 'Timestamp': '15221.315064872', 'page': 'preview', 'tag': 'Exposure-AutoGoto', 'ac_count': 1, 'state': 'complete', 'result': {'ra_dec': [3.252308, 41.867462], 'fov': [0.712052, 1.265553], 'focal_len': 252.081757, 'angle': -175.841003, 'image_id': 1161, 'star_number': 884, 'duration_ms': 13185}}
                        # {'Event': 'PlateSolve', 'Timestamp': '21778.539366227', 'state': 'fail', 'error': 'solve failed', 'code': 251, 'lapse_ms': 30985, 'route': []}

                        elif event_name == 'ScopeGoto':
                            self.goto_state = parsed_data['state']
                        elif event_name == 'PlateSolve':
                            if 'result' in parsed_data and 'ra_dec' in parsed_data['result']:
                                self.logger.info("Plate Solve Succeeded")
                                self.cur_solve_RA = parsed_data['result']['ra_dec'][0]
                                self.cur_solve_Dec = parsed_data['result']['ra_dec'][1]
                            elif parsed_data['state'] == 'fail':
                                self.logger.info("Plate Solve Failed")
                                self.cur_solve_RA = -1.0
                                self.cur_solve_Dec = -1.0

                    first_index = msg_remainder.find("\r\n")
            time.sleep(0.1)

    def json_message(self, instruction):
        data = {"id": self.cmdid, "method": instruction}
        self.cmdid += 1
        json_data = json.dumps(data)
        self.logger.debug(f'{self.device_name} sending: {json_data}')
        self.send_message(json_data + "\r\n")

    def json_message2(self, data):
        if data:
            json_data = json.dumps(data)
            self.logger.debug(f'{self.device_name} sending2: {json_data}')
            resp = self.send_message(json_data + "\r\n")

    def send_message_param(self, data):
        cur_cmdid = self.cmdid
        data['id'] = cur_cmdid
        self.cmdid += 1 # can this overflow?  not in JSON...
        json_data = json.dumps(data)
        self.logger.debug(f'{self.device_name} sending: {json_data}')
        self.send_message(json_data + "\r\n")
        return cur_cmdid

    def send_message_param_sync(self, data):
        cur_cmdid = self.send_message_param(data)
        while cur_cmdid not in self.response_dict:
            time.sleep(0.1)
        self.logger.debug(f'{self.device_name} response is {self.response_dict[cur_cmdid]}')
        return self.response_dict[cur_cmdid]

    def set_setting(self, x_stack_l, x_continuous, d_pix, d_interval, d_enable, l_enhance, heater_enable):
        # TODO:
        #   heater_enable failed. 
        #   lenhace should be by itself as it moves the wheel and thus need to wait a bit
        #    data = {"id":cmdid, "method":"set_setting", "params":{"exp_ms":{"stack_l":x_stack_l,"continuous":x_continuous}, "stack_dither":{"pix":d_pix,"interval":d_interval,"enable":d_enable}, "stack_lenhance":l_enhance, "heater_enable":heater_enable}}
        data = {"method": "set_setting", "params": {"exp_ms": {"stack_l": x_stack_l, "continuous": x_continuous},
                                                    "stack_dither": {"pix": d_pix, "interval": d_interval,
                                                                     "enable": d_enable}, "stack_lenhance": l_enhance}}
        self.send_message_param(data)
        time.sleep(2)  # to wait for filter change

    def stop_goto_target(self):
        if self.goto_state == "working":
            if self.below_horizon_dec_offset == 0:
                self.stop_slew()
            self.op_state = "fail"

    def is_goto(self):
        result = self.send_message_param_sync({"method": "iscope_get_app_state"})
        try:
            return result["result"]["View"]["stage"] == "AutoGoto"
        except:
            return False

    def goto_target(self, params):
        is_j2000 = params['is_j2000']
        in_ra = params['ra']
        in_dec = params['dec']
        parsed_coord = Util.parse_coordinate(is_j2000, in_ra, in_dec)
        in_ra = parsed_coord.ra.hour
        in_dec = parsed_coord.dec.deg
        target_name = params['target_name']
        self.logger.info("%s: going to target... %s %s %s, with dec offset %s", self.device_name, target_name, in_ra,
                         in_dec, self.below_horizon_dec_offset)
        if self.is_goto():
            self.logger.info("Failed: mount is in goto routine.")
            return "Failed: mount is in goto routine."

        self.op_watch = 'AutoGoto'
        if self.below_horizon_dec_offset == 0:
            data = {}
            data['method'] = 'iscope_start_view'
            params = {}
            params['mode'] = 'star'
            ra_dec = [in_ra, in_dec]
            params['target_ra_dec'] = ra_dec
            params['target_name'] = target_name
            params['lp_filter'] = False
            data['params'] = params
            self.actual_dec = in_dec
            self.send_message_param(data)
        else:
            # do the same, but when trying to center on target, need to implement ourselves to platesolve correctly to compensate for the dec offset
            self.goto_target_with_dec_offset_async(params)

    # {"method":"scope_goto","params":[1.2345,75.0]}
    def slew_to_ra_dec(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info("%s: slew to ra, dec ... %s %s, with dec_offset of %s", self.device_name, in_ra, in_dec,
                         self.below_horizon_dec_offset)
        if self.is_goto():
            self.logger.info("Failed: mount is in goto routine.")
            return "Failed: mount is in goto routine."
        data = {}
        data['method'] = 'scope_goto'
        params = [in_ra, in_dec + self.below_horizon_dec_offset]
        data['params'] = params
        self.goto_state = "Waiting"
        result = self.send_message_param_sync(data)
        if 'error' in result:
            self.logger.info("Error: %s", result)
            return False
        # wait till movement is finished
        while self.goto_state != "complete":
            if self.scheduler_state == "Stopping":
                return False
            time.sleep(2)
        return True

    def set_below_horizon_dec_offset(self, offset):
        if self.is_goto():
            self.logger.info("Failed: mount is in goto routine.")
            return "Failed: mount is in goto routine."
        # offset between 0 to 90
        dec_diff = offset - self.below_horizon_dec_offset
        if dec_diff == 0:
            return "No offset changed"
        else:
            old_offset = self.below_horizon_dec_offset
            old_dec = self.dec
            self.below_horizon_dec_offset = offset
            result = self.sync_target([self.ra, self.dec])
            if 'error' in result:
                self.below_horizon_dec_offset = old_offset
                self.sync_target([self.ra, old_dec])
                self.logger.info(result)
                self.logger.info("Failed to set dec offset. Move the mount up first?")
                return result

    def sync_target(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info("%s: sync to target... %s %s with dec_offset of %s", self.device_name, in_ra, in_dec,
                         self.below_horizon_dec_offset)
        if self.is_goto():
            self.logger.info("Failed: mount is in goto routine.")
            return "Failed: mount is in goto routine."
        data = {}
        data['method'] = 'scope_sync'
        data['params'] = [in_ra, in_dec + self.below_horizon_dec_offset]
        result = self.send_message_param_sync(data)
        if 'error' in result:
            self.logger.info("Failed to sync: %s", result)
        return result

    def stop_slew(self):
        self.logger.info("%s: stopping slew...", self.device_name)
        data = {}
        data['method'] = 'iscope_stop_view'
        params = {}
        params['stage'] = 'AutoGoto'
        data['params'] = params
        self.send_message_param(data)
        # TODO: need to handle this for our custom goto for below horizon too

    # {"method":"scope_speed_move","params":{"speed":4000,"angle":270,"dur_sec":10}}
    def move_scope(self, in_angle, in_speed, in_dur=3):
        self.logger.info("%s: moving slew angle: %s, speed: %s, dur: %s", self.device_name, in_angle, in_speed, in_dur)
        if self.is_goto():
            self.logger.info("Failed: mount is in goto routine.")
            return "Failed: mount is in goto routine."
        data = {}
        data['method'] = 'scope_speed_move'
        params = {}
        params['speed'] = in_speed
        params['angle'] = in_angle
        params['dur_sec'] = in_dur
        data['params'] = params
        self.send_message_param_sync(data)

    def start_auto_focus(self):
        self.json_message("start_auto_focuse")
        # todo: wait for focus complete instead of just simply sleep
        time.sleep(1)

    def try_auto_focus(self, try_count):
        focus_count = 0
        result = False
        while focus_count < try_count and result == False:
            self.logger.info("%s: focusing try %s of %s...", self.device_name, str(focus_count + 1), str(try_count))
            self.start_auto_focus()
            result = self.wait_end_op("AutoFocus")
            focus_count += 1
            if result != True:
                time.sleep(5)

        if result == True:
            self.logger.info("%s: Auto focus completed!", self.device_name)
            return True
        else:
            self.logger.info("%s: Auto focus failed!", self.device_name)
            return False

    def stop_stack(self):
        self.logger.info("%s: stop stacking...", self.device_name)
        data = {}
        data['method'] = 'iscope_stop_view'
        params = {}
        params['stage'] = 'Stack'
        data['params'] = params
        self.send_message_param(data)

    def play_sound(self, in_sound_id: int):
        self.logger.info("%s: playing sound...", self.device_name)
        req = {}
        req['method'] = 'play_sound'
        params = {}
        params['num'] = in_sound_id
        req['params'] = params
        self.send_message_param(req)
        time.sleep(1)

    # {"target_name":"test_target","ra":1.234, "dec":-12.34}
    # take into account self.below_horizon_dec_offset for platesolving, using low level move and custom plate solving logic
    def goto_target_with_dec_offset_async(self, params):
        # first, go to position (ra, cur_dec)
        if params["ra"] < 0:
            if self.last_sync_RA >= 0:
                target_ra = self.ra
                target_dec = self.dec
            else:
                target_ra = self.ra
                target_dec = self.dec
        else:
            target_ra = params["ra"]
            target_dec = params["dec"]
        self.logger.info("trying to go with explicit dec offset logic: %s %s %s", target_ra, target_dec,
                         self.below_horizon_dec_offset)

        result = self.slew_to_ra_dec([target_ra, target_dec])
        if result == True:
            self.set_target_name(params["target_name"])
            # repeat plate solve and adjust position as needed
            threading.Thread(target=lambda: self.auto_center_thread(target_ra, target_dec)).start()
            return True
        else:
            self.logger.info("Failed to slew")
            return False

    # after we goto_ra_dec, we can do a platesolve and refine until we are close enough
    def auto_center_thread(self, target_ra, target_dec):
        self.logger.info("In auto center logic...")
        self.cur_solve_RA = -9999.0
        self.cur_solve_Dec = -9999.0
        self.op_watch = "AutoGoto"
        self.op_state = "working"
        while self.scheduler_state != "Stopping" and self.op_state == "working":
            # wait a bit to ensure we have preview image data
            time.sleep(1)
            self.send_message_param({"method": "start_solve"})
            # reset it immediately so the other wather thread can update the solved position 
            self.cur_solve_RA = -9999.0
            self.cur_solve_Dec = -9999.0
            # if we have not platesolve yet, then repeat
            while self.cur_solve_RA < -1000:
                if self.scheduler_state == "Stopping" or self.op_state != "working":
                    self.logger.info("auto center thread stopped because the scheduler was requested to stop")
                    return
                time.sleep(1)
                continue
            # if we failed platesolve:
            if self.cur_solve_RA < 0:
                self.op_state = "fail"
                self.logger.info("auto center failed")
                return

            delta_ra = self.cur_solve_RA - target_ra
            delta_dec = self.cur_solve_Dec - target_dec

            distance_square = delta_ra * delta_ra + delta_dec * delta_dec
            if (distance_square < 1.0e-3):
                self.op_state = "complete"
                self.logger.info("auto center completed")
                return
            else:
                self.sync_target([self.cur_solve_RA, self.cur_solve_Dec])
                self.slew_to_ra_dec([target_ra, target_dec])
        self.logger.info("auto center thread stopped because the scheduler was requested to stop")
        self.op_state = "fail"
        return

    def start_stack(self, params={"gain": 80, "restart": True}):
        stack_gain = params["gain"]
        result = self.send_message_param_sync(
            {"method": "iscope_start_stack", "params": {"restart": params["restart"]}})
        self.logger.info(result)
        result = self.send_message_param_sync({"method": "set_control_value", "params": ["gain", stack_gain]})
        self.logger.info(result)
        return not "error" in result

    def get_last_image(self, params):
        album_result = self.send_message_param_sync({"method": "get_albums"})
        album_result = album_result["result"]
        parent_folder = album_result["path"]
        first_list = album_result["list"][0]
        is_subframe = params["is_subframe"]
        result_url = ""
        result_name = None
        self.logger.info("first_list: %s", first_list)
        for files in first_list["files"]:
            if (is_subframe and files["name"].endswith("-sub")) or (
                    not is_subframe and not files["name"].endswith("-sub")):
                result_url = files["thn"]
                result_name = files["name"]
                break
        if not params["is_thumb"]:
            result_url = result_url.partition("_thn.jpg")[0] + ".jpg"
        return {"url": "http://" + self.host + "/" + parent_folder + "/" + result_url,
                "name": result_name}

    # move from -90 to this latitude
    # speed 1000 for 20 seconds is 90 degrees
    # can move at most 10 secs each
    def move_up_dec_thread_fn(self):
        # move 10 degrees from Polaris
        total_move = 170
        subtotal_move = 0
        #        self.sync_target([0.0, -89.0])
        while subtotal_move < total_move:
            cur_move = min(45, total_move - subtotal_move)  # 45 = 90/20/10
            move_time = cur_move * 20.0 / 90.0
            self.move_scope(90, 1000, round(move_time))
            subtotal_move += cur_move
            time.sleep(move_time + 1)
            #       self.sync_target([0.0, 80.0])

    def action_start_up_sequence(self, params):
        tz_name = tzlocal.get_localzone_name()
        tz = tzlocal.get_localzone()
        now = datetime.now(tz)
        date_json = {}
        date_json["year"] = now.year
        date_json["mon"] = now.month
        date_json["day"] = now.day
        date_json["hour"] = now.hour
        date_json["min"] = now.minute
        date_json["sec"] = now.second
        date_json["time_zone"] = tz_name
        date_data = {}
        date_data['method'] = 'pi_set_time'
        date_data['params'] = [date_json]

        loc_data = {}
        loc_param = {}
        # special loc for south pole: (-90, 0)
        if params['lat'] == 0 and params[
            'lon'] == 0:  # special case of (0,0,) will use the ip address to estimate the location
            coordinates = Util.get_current_gps_coordinates()
            if coordinates is not None:
                latitude, longitude = coordinates
                self.logger.info(f"Your current GPS coordinates are:")
                self.logger.info(f"Latitude: {latitude}")
                self.logger.info(f"Longitude: {longitude}")
                params['lat'] = latitude
                params['lon'] = longitude
        loc_param['lon'] = params['lon']
        loc_param['lat'] = params['lat']
        loc_param['force'] = False
        loc_data['method'] = 'set_user_location'
        loc_data['params'] = loc_param
        lang_data = {}
        lang_data['method'] = 'set_setting'
        lang_data['params'] = {'lang': 'en'}

        self.logger.info("verify datetime string: %s", date_data)
        self.logger.info("verify location string: %s", loc_data)

        self.send_message_param_sync({"method": "pi_is_verified"})
        self.send_message_param_sync(date_data)
        self.send_message_param_sync(loc_data)
        self.send_message_param_sync(lang_data)

        # move the arm up using a thread runner
        # move 10 degrees from polaris
        move_up_dec_thread = threading.Thread(target=lambda: self.move_up_dec_thread_fn())
        move_up_dec_thread.start()

    # {"method":"set_sequence_setting","params":[{"group_name":"Kai_goto_target_name"}]}
    def set_target_name(self, name):
        req = {}
        req['method'] = 'set_sequence_setting'
        params = {}
        params['group_name'] = name
        req['params'] = [params]
        self.send_message_param_sync(req)

    def spectra_thread_fn(self, params):

        # unlike Mosaic, we can't depend on platesolve to find star, so all movement is by simple motor movement

        center_RA = params["ra"]
        center_Dec = params["dec"]
        is_j2000 = params['is_j2000']
        target_name = params["target_name"]
        session_length = params["session_time_sec"]
        stack_params = {"gain": params["gain"], "restart": True}
        spacing = [5.3, 6.2, 6.5, 7.1, 8.0, 8.9, 9.2, 9.8]
        is_LP = [False, False, True, False, False, False, True, False]
        num_segments = len(spacing)

        parsed_coord = Util.parse_coordinate(is_j2000, center_RA, center_Dec)
        center_RA = parsed_coord.ra.hour
        center_Dec = parsed_coord.dec.deg

        # 60s for the star
        exposure_time_per_segment = round((session_length - 60.0) / num_segments)
        if center_RA < 0:
            if self.last_sync_RA >= 0:
                center_RA = self.ra
                center_Dec = self.dec
                self.slew_to_ra_dec(self, [center_RA, center_Dec])
            else:
                center_RA = self.ra
                center_Dec = self.dec
        else:
            # move to target
            self.slew_to_ra_dec(self, [center_RA, center_Dec])

        # take one minute exposure for the star
        if self.scheduler_state != "Running":
            self.scheduler_state = "Stopped"
            self.scheduler_item_state = "Stopped"
            return
        self.set_target_name(target_name + "_star")
        if not self.start_stack(stack_params):
            return
        time.sleep(60)
        self.stop_stack()

        # capture spectra
        cur_dec = center_Dec
        for index in range(len(spacing)):
            if self.scheduler_state != "Running":
                self.scheduler_state = "Stopped"
                self.scheduler_item_state = "Stopped"
                return
            cur_dec = center_Dec + spacing[index]
            self.send_message_param_sync({"method": "set_setting", "params": {"stack_lenhance": is_LP[index]}})
            self.slew_to_ra_dec([center_RA, cur_dec])
            self.set_target_name(target_name + "_spec_" + str(index + 1))
            if not self.start_stack(stack_params):
                return
            count_down = exposure_time_per_segment
            while count_down > 0:
                if self.scheduler_state != "Running":
                    self.stop_stack()
                    self.scheduler_state = "Stopped"
                    self.scheduler_item_state = "Stopped"
                    return
                time.sleep(10)
                count_down -= 10
            self.stop_stack()

        self.logger.info("Finished spectra mosaic.")
        self.scheduler_item_state = "Stopped"

    # {"target_name":"kai_Vega", "ra":-1.0, "dec":-1.0, "is_use_lp_filter_too":true, "session_time_sec":600, "grating_lines":300}
    def start_spectra_item(self, params):
        if self.scheduler_state != "Running":
            self.logger.info("Run Scheduler is stopping")
            self.scheduler_state = "Stopped"
            return
        self.scheduler_item_state = "Running"
        self.mosaic_thread = threading.Thread(target=lambda: self.spectra_thread_fn(params))
        self.mosaic_thread.start()

    def mosaic_thread_fn(self, target_name, center_RA, center_Dec, is_use_LP_filter, session_time, nRA, nDec,
                         overlap_percent, gain, is_use_autofocus, selected_panels):
        spacing_result = Util.mosaic_next_center_spacing(center_RA, center_Dec, overlap_percent)
        delta_RA = spacing_result[0]
        delta_Dec = spacing_result[1]

        is_use_selected_panels = not selected_panels == ""
        if is_use_selected_panels:
            panel_set = selected_panels.split(';')

        # adjust mosaic center if num panels is even
        if nRA % 2 == 0:
            center_RA += delta_RA / 2
        if nDec % 2 == 0:
            center_Dec += delta_Dec / 2

        sleep_time_per_panel = round(session_time / nRA / nDec)

        cur_dec = center_Dec - int(nDec / 2) * delta_Dec
        for index_dec in range(nDec):
            self.cur_mosaic_nDec = index_dec+1
            spacing_result = Util.mosaic_next_center_spacing(center_RA, cur_dec, overlap_percent)
            delta_RA = spacing_result[0]
            cur_ra = center_RA - int(nRA / 2) * spacing_result[0]
            for index_ra in range(nRA):
                self.cur_mosaic_nRA = index_ra+1
                if self.scheduler_state != "Running":
                    self.logger.info("Mosaic mode was requested to stop. Stopping")
                    self.scheduler_state = "Stopped"
                    self.scheduler_item_state = "Stopped"
                    self.cur_mosaic_nDec = -1
                    self.cur_mosaic_nRA = -1
                    return
                
                # check if we are doing a subset of the panels
                panel_string = str(index_ra + 1) + str(index_dec + 1)
                if is_use_selected_panels and panel_string not in panel_set:
                    cur_ra += delta_RA
                    continue

                if nRA == 1 and nDec == 1:
                    save_target_name = target_name
                else:
                    save_target_name = target_name + "_" + panel_string
                self.logger.info("goto %s", (cur_ra, cur_dec))
                # set_settings(x_stack_l, x_continuous, d_pix, d_interval, d_enable, l_enhance, heater_enable):
                # TODO: Need to set correct parameters
                self.send_message_param_sync({"method": "set_setting", "params": {"stack_lenhance": False}})
                self.goto_target({'ra': cur_ra, 'dec': cur_dec, 'is_j2000': False, 'target_name': save_target_name})
                result = self.wait_end_op("AutoGoto")
                self.logger.info("Goto operation finished")

                time.sleep(3)

                if result == True:
                    self.send_message_param_sync(
                        {"method": "set_setting", "params": {"stack_lenhance": is_use_LP_filter}})

                    if is_use_autofocus == True:
                        result = self.try_auto_focus(2)
                    if result == False:
                        self.logger.info("Failed to auto focus, but will continue to next panel anyway.")
                        result = True
                    if result == True:
                        time.sleep(4)
                        if not self.start_stack({"gain": gain, "restart": True}):
                            return

                        for i in range(sleep_time_per_panel):
                            if self.scheduler_state != "Running":
                                self.logger.info("Scheduler was requested to stop. Stopping current mosaic.")
                                self.stop_stack()
                                self.scheduler_item_state = "Stopped"
                                self.scheduler_state = "Stopped"
                                return
                            time.sleep(1)

                        self.stop_stack()
                        self.logger.info("Stacking operation finished" + save_target_name)
                else:
                    self.logger.info("Goto failed.")

                cur_ra += delta_RA
            cur_dec += delta_Dec
        self.logger.info("Finished mosaic.")
        self.scheduler_item_state = "Stopped"
        self.cur_mosaic_nDec = -1
        self.cur_mosaic_nRA = -1

    def start_mosaic_item(self, params):
        if self.scheduler_state != "Running":
            self.logger.info("Run Scheduler is stopping")
            self.scheduler_state = "Stopped"
            return
        self.scheduler_item_state = "Running"
        target_name = params['target_name']
        center_RA = params['ra']
        center_Dec = params['dec']
        is_j2000 = params['is_j2000']
        is_use_LP_filter = params['is_use_lp_filter']
        session_time = params['session_time_sec']
        nRA = params['ra_num']
        nDec = params['dec_num']
        overlap_percent = params['panel_overlap_percent']
        gain = params['gain']
        if 'is_use_autofocus' in params:
            is_use_autofocus = params['is_use_autofocus']
        else:
            is_use_autofocus = False
        if not 'selected_panels' in params:
            selected_panels = ""
        else:
            selected_panels = params['selected_panels']

        # verify mosaic pattern
        if nRA < 1 or nDec < 0:
            self.logger.info("Mosaic size is invalid")
            self.scheduler_item_state = "Stopped"
            return

        if not isinstance(center_RA, str) and center_RA < 0:
            center_RA = self.ra
            center_Dec = self.dec
            is_j2000 = False

        parsed_coord = Util.parse_coordinate(is_j2000, center_RA, center_Dec)
        center_RA = parsed_coord.ra.hour
        center_Dec = parsed_coord.dec.deg

        # print input requests
        self.logger.info("received parameters:")
        self.logger.info("  target        : " + target_name)
        self.logger.info("  RA            : %s", center_RA)
        self.logger.info("  Dec           : %s", center_Dec)
        self.logger.info("  use LP filter : %s", is_use_LP_filter)
        self.logger.info("  session time  : %s", session_time)
        self.logger.info("  RA num panels : %s", nRA)
        self.logger.info("  Dec num panels: %s", nDec)
        self.logger.info("  overlap %%     : %s", overlap_percent)
        self.logger.info("  gain          : %s", gain)
        self.logger.info("  use autofocus : %s", is_use_autofocus)
        self.logger.info("  select panels : %s", selected_panels)

        self.mosaic_thread = threading.Thread(
            target=lambda: self.mosaic_thread_fn(target_name, center_RA, center_Dec, is_use_LP_filter, session_time,
                                                 nRA, nDec, overlap_percent, gain, is_use_autofocus, selected_panels))
        self.mosaic_thread.start()

    def get_schedule(self):
        self.schedule['state'] = self.scheduler_state
        return self.schedule

    def create_schedule(self):
        if self.scheduler_state == "Running":
            return "scheduler is still active"
        if self.scheduler_state == "Stopping":
            self.scheduler_state = "Stopped"
        self.schedule = {}
        self.schedule['state'] = self.scheduler_state
        self.schedule['list'] = []
        return self.schedule

    def add_schedule_item(self, params):
        if self.scheduler_state != "Stopped":
            return "scheduler is still active"
        if params['action'] == 'start_mosaic':
            mosaic_params = params['params']
            if not isinstance(mosaic_params['ra'], str):
                if mosaic_params['ra'] < 0:
                    mosaic_params['ra'] = self.ra
                    mosaic_params['dec'] = self.dec
                    mosaic_params['is_j2000'] = False
        params['id'] = str(uuid.uuid4())
        self.schedule['list'].append(params)
        return self.schedule

    # shortcut to start a new scheduler with only a mosaic request
    def start_mosaic(self, params):
        if self.scheduler_state != "Stopped":
            return "An existing scheduler is active. Returned with no action."
        self.create_schedule()
        schedule_item = {}
        schedule_item['action'] = "start_mosaic"
        schedule_item['params'] = params
        self.add_schedule_item(schedule_item)
        self.start_scheduler()
        return "Mosaic started."

    # shortcut to start a new scheduler with only a spectra request
    def start_spectra(self, params):
        if self.scheduler_state != "Stopped":
            return "An existing scheduler is active. Returned with no action."
        self.create_schedule()
        schedule_item = {}
        schedule_item['action'] = "start_spectra"
        schedule_item['params'] = params
        self.add_schedule_item(schedule_item)
        self.start_scheduler()

    def start_scheduler(self):
        if self.scheduler_state != "Stopped":
            return "An existing scheduler is active. Returned with no action."
        self.scheduler_thread = threading.Thread(target=lambda: self.scheduler_thread_fn(), daemon=True)
        self.scheduler_thread.name = f"SchedulerThread.{self.device_name}"
        self.scheduler_thread.start()
        return "Scheduler started"

    def scheduler_thread_fn(self):
        self.scheduler_state = "Running"
        self.play_sound(80)

        for item in self.schedule['list']:
            if self.scheduler_state != "Running":
                break
            self.schedule['current_item_id'] = item.get('id', 'UNKNOWN')
            action = item['action']
            if action == 'start_mosaic':
                self.start_mosaic_item(item['params'])
                while self.scheduler_item_state == "Running":
                    time.sleep(2)
            elif action == 'start_spectra':
                self.start_spectra_item(item['params'])
                while self.scheduler_item_state == "Running":
                    time.sleep(2)
            elif action == 'auto_focus':
                self.try_auto_focus(item['params']['try_count'])
            elif action == 'shutdown':
                self.scheduler_state = "Stopped"
                self.json_message("pi_shutdown")
                break
            # elif action == 'set_wheel_position' or action == 'pi_output_set2':
                
            elif action == 'wait_for':
                sleep_time = item['params']['timer_sec']
                sleep_count = 0
                while sleep_count < sleep_time and self.scheduler_state == "Running":
                    time.sleep(2)
                    sleep_count += 2
            elif action == 'wait_until':
                wait_until_time = item['params']['local_time'].split(":")
                time_hour = int(wait_until_time[0])
                time_minute = int(wait_until_time[1])
                while self.scheduler_state == "Running":
                    local_time = datetime.now()
                    if local_time.hour == time_hour and local_time.minute == time_minute:
                        break
                    time.sleep(2)
            else:
                request = {'method':action, 'params':item['params']}
                self.send_message_param_sync(request)

        self.scheduler_state = "Stopped"
        self.schedule['current_item_id'] = ""
        self.logger.info("Scheduler Stopped.")
        self.play_sound(82)

    def stop_scheduler(self):
        if self.scheduler_state == "Running":
            self.scheduler_state = "Stopping"
            self.stop_slew()
            self.stop_stack()
            self.play_sound(83)
        else:
            self.scheduler_state = "Stopping"
            self.logger.info("Scheduler is not running while trying to stop!")

    def wait_end_op(self, in_op_name):
        self.op_watch = in_op_name
        self.op_state = "working"

        while self.op_state == "working":
            time.sleep(1)
        return self.op_state == "complete"

    # def sleep_with_heartbeat(self, in_sleep_time):
    #     stacking_timer = 0
    #     while stacking_timer < in_sleep_time:         # stacking time per segment
    #         stacking_timer += 1
    #         time.sleep(1)
    #         print(self.device_name, ": session elapsed ", str(stacking_timer) + "s of " + str(in_sleep_time) + "s", end= "\r")

    # def parse_ra_to_float(self, ra_string):
    #     # Split the RA string into hours, minutes, and seconds
    #     hours, minutes, seconds = map(float, ra_string.split(':'))

    #     # Convert to decimal degrees
    #     ra_decimal = hours + minutes / 60 + seconds / 3600

    #     return ra_decimal

    def parse_dec_to_float(self, dec_string):
        # Split the Dec string into degrees, minutes, and seconds
        if dec_string[0] == '-':
            sign = -1
            dec_string = dec_string[1:]
        else:
            sign = 1
        degrees, minutes, seconds = map(float, dec_string.split(':'))

        # Convert to decimal degrees
        dec_decimal = sign * degrees + minutes / 60 + seconds / 3600

        return dec_decimal

    def start_watch_thread(self):
        # only bail if is_watch_events is true
        if self.is_watch_events:
            return
        else:
            self.is_watch_events = True

            for i in range(3, 0, -1):
                if self.reconnect():
                    self.logger.info(f'{self.device_name}: Connected')
                    break
                else:
                    self.logger.info(f'{self.device_name}: Connection Failed, is Seestar turned on?')
                    time.sleep(1)
            else:
                self.logger.info(
                    f'{self.device_name}: Could not establish connection to Seestar. Starting in offline mode')

            try:
                # Start up heartbeat and receive threads
                self.op_watch = ""

                self.get_msg_thread = threading.Thread(target=self.receive_message_thread_fn, daemon=True)
                self.get_msg_thread.name = f"ALPReceiveMessageThread.{self.device_name}"
                self.get_msg_thread.start()

                self.heartbeat_msg_thread = threading.Thread(target=self.heartbeat_message_thread_fn, daemon=True)
                self.heartbeat_msg_thread.name = f"ALPHeartbeatMessageThread.{self.device_name}"
                self.heartbeat_msg_thread.start()
            except Exception as ex:
                # todo : Disconnect socket and set is_watch_events false
                pass

    def end_watch_thread(self):
        # I think it should be is_watch_events instead of is_connected...
        if self.is_connected == True:
            self.logger.info("End watch thread!")
            self.is_watch_events = False
            self.get_msg_thread.join(timeout=7)
            self.heartbeat_msg_thread.join(timeout=7)
            self.s.close()
            self.is_connected = False


if __name__ == '__main__':
    try:
        if len(sys.argv) != 5:
            print(sys.argv[0], " <ip_address> <port> <device name> <device num>")
            sys.exit()
        seestar_core = Seestar(sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), is_debug=True)
        seestar_core.start_watch_thread()
        request = {}
        request['method'] = 'iscope_stop_view'
        print("sync response: ", seestar_core.send_message_param_sync(request))
        time.sleep(10)
        seestar_core.end_watch_thread()
    except KeyboardInterrupt:
        print('Interrupted')
        seestar_core.end_watch_thread()
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)

'''    
def main():
    global is_debug
    
    version_string = "1.0.0b1"
    print("seestar_run version: ", version_string)
    
    if len(sys.argv) != 11 and len(sys.argv) != 12:
        print("expected seestar_run <ip_address> <target_name> <ra> <dec> <is_use_LP_filter> <session_time> <RA panel size> <Dec panel size> <RA offset factor> <Dec offset factor>")
        sys.exit()
    
    in_host = sys.argv[1]
    target_name = sys.argv[2]
    try:
        center_RA = float(sys.argv[3])
    except ValueError:
        center_RA = parse_ra_to_float(sys.argv[3])
        
    try:
        center_Dec = float(sys.argv[4])
    except ValueError:
        center_Dec = parse_dec_to_float(sys.argv[4])
    
    is_use_LP_filter = sys.argv[5] == '1'
    session_time = int(sys.argv[6])
    nRA = int(sys.argv[7])
    nDec = int(sys.argv[8])
    mRA = float(sys.argv[9])
    mDec = float(sys.argv[10])
    is_debug = False

    if len(sys.argv) == 12:
        is_debug = sys.argv[11]=="Kai"
        
    print(in_host, target_name, center_RA, center_Dec, is_use_LP_filter, session_time, nRA, nDec, mRA, mDec)
    
    # verify mosaic pattern
    if nRA < 1 or nDec < 0:
        print("Mosaic size is invalid")
        sys.exit()
    
    print("nRA: %d", nRA)
    print("nDec:%d", nDec)
    
    in_port = 4700 
    delta_RA = 0.06
    delta_Dec = 0.9

    start_watch_thread(in_host, in_port)
        
    # flush the socket input stream for garbage
    #get_socket_msg()
    
    if center_RA < 0:
        # wait until we get a valid eq coordinate from the thread
        while ra == 0:
            time.sleep(1)              
        center_RA = ra
        center_Dec = dec
        
    # print input requests
    print("received parameters:")
    print("  ip address    : " + HOST)
    print("  target        : " + target_name)
    print("  RA            : ", center_RA)
    print("  Dec           : ", center_Dec)
    print("  use LP filter : ", is_use_LP_filter)
    print("  session time  : ", session_time)
    print("  RA num panels : ", nRA)
    print("  Dec num panels: ", nDec)
    print("  RA offset x   : ", mRA)
    print("  Dec offset x  : ", mDec)
    
    delta_RA *= mRA
    delta_Dec *= mDec
    
    # adjust mosaic center if num panels is even
    if nRA % 2 == 0:
        center_RA += delta_RA/2
    if nDec % 2 == 0:
        center_Dec += delta_Dec/2
            
  
    mosaic_index = 0
    cur_ra = center_RA-int(nRA/2)*delta_RA
    for index_ra in range(nRA):
        cur_dec = center_Dec-int(nDec/2)*delta_Dec
        for index_dec in range(nDec):
            if nRA == 1 and nDec == 1:
                save_target_name = target_name
            else:
                save_target_name = target_name+"_"+str(index_ra+1)+str(index_dec+1)
            print("goto ", (cur_ra, cur_dec))
            # set_settings(x_stack_l, x_continuous, d_pix, d_interval, d_enable, l_enhance, heater_enable):
            set_setting(10000,500,50,5,True,False,False)    # switch off LP filter to get more stars
            goto_target(cur_ra, cur_dec, save_target_name)
            result = wait_end_op("AutoGoto")
            print("Goto operation finished")
            
            time.sleep(3)
            
            if result == True:
                # set_settings(x_stack_l, x_continuous, d_pix, d_interval, d_enable, l_enhance, heater_enable):
                set_setting(10000,500,50,5,True,is_use_LP_filter,False)
                result = try_auto_focus()
                if result == True:
                    start_stack()    
                    sleep_with_heartbeat(session_time)
                    print()
                    stop_stack()
                    print("Stacking operation finished" + save_target_name)

            else:
                print("Goto failed.")
                
            cur_dec += delta_Dec
            mosaic_index += 1
        cur_ra += delta_RA

    print("Finishing seestar_run ...", end = " ")
    end_watch_thread()
    print("Finished")
    try:
        sys.exit(130)
    except SystemExit:
        os._exit(130)
    
    
    

# seestar_run <ip_address> <target_name> <ra> <dec> <is_use_LP_filter> <session_time> <RA panel size> <Dec panel size> <RA offset factor> <Dec offset factor>
# python seestar_run.py 192.168.110.30 'Castor' '7:24:32.5' '-41:24:23.5' 0 60 2 2 1.0 1.0
# python seestar_run.py 192.168.110.30 'Castor' '7:24:32.5' '+41:24:23.5' 0 60 2 2 1.0 1.0
# python seestar_run.py 192.168.110.30 'Castor' '7:24:32.5' '41:24:23.5' 0 60 2 2 1.0 1.0
# python seestar_run.py 192.168.110.30 'Castor' 7.4090278 41.4065278 0 60 2 2 1.0 1.0
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)
    
'''
