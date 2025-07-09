import socket
import json
import time
from datetime import datetime
import threading
import os
import math
import uuid
from time import sleep
import collections
from typing import Optional, Any, TypedDict, NotRequired

import pydash
from blinker import signal
import geomag

import numpy as np
from json import JSONEncoder


import tzlocal
from pyhocon import ConfigFactory

from device.abstract_device import MessageParams, StartStackParams, Schedule
from device.config import Config
from device.version import Version  # type: ignore
from device.seestar_util import Util
from device.event_callbacks import *

from collections import OrderedDict

from astropy.coordinates import EarthLocation, AltAz
import astropy.units as u


class ThreePPA(TypedDict):
    eq_offset_alt: float
    eq_offset_az: float


class EventState(TypedDict):
    scheduler: Schedule
    threePPA: ThreePPA


class SchedulerItemState(TypedDict):
    type: str
    schedule_item_id: str
    action: str
    target_name: NotRequired[str]
    item_total_time_s: NotRequired[float]
    item_remaining_time_s: NotRequired[float]


class FixedSizeOrderedDict(OrderedDict):
    def __init__(self, *args, maxsize=None, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        if self.maxsize is not None and len(self) >= self.maxsize:
            self.popitem(last=False)  # Remove the oldest item
        super().__setitem__(key, value)


class DequeEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, collections.deque):
            return list(obj)
        return JSONEncoder.default(self, obj)


class Seestar:
    def __new__(cls, *args, **kwargs):
        # print("Create a new instance of Seestar.")
        return super().__new__(cls)

    # <ip_address> <port> <device name> <device num>
    def __init__(
        self,
        logger,
        host: str,
        port: int,
        device_name: str,
        device_num: int,
        is_EQ_mode: bool,
        is_debug=False,
    ):
        logger.info(
            f"Initialize the new instance of Seestar: {host}:{port}, name:{device_name}, num:{device_num}, is_EQ_mode:{is_EQ_mode}, is_debug:{is_debug}"
        )

        self.host: str = host
        self.port: int = port
        self.device_name: str = device_name
        self.device_num: int = device_num
        self.cmdid: int = 10000
        self.site_latitude: float = Config.init_lat
        self.site_longitude: float = Config.init_long
        self.site_elevation: float = 0
        self.ra: float = 0.0
        self.dec: float = 0.0
        self.is_watch_events: bool = (
            False  # Tracks if device has been started even if it never connected
        )
        self.s: Optional[socket.socket] = None
        self.get_msg_thread: Optional[threading.Thread] = None
        self.heartbeat_msg_thread: Optional[threading.Thread] = None
        self.is_debug: bool = is_debug
        self.response_dict: OrderedDict[int, dict] = FixedSizeOrderedDict(max=100)
        self.logger = logger
        self.is_connected: bool = False
        self.is_slewing: bool = False
        self.target_dec: float = 0
        self.target_ra: float = 0
        self.utcdate = time.time()
        self.firmware_ver_int: int = 0

        self.event_callbacks: list[EventCallback] = []

        self.mosaic_thread: Optional[threading.Thread] = None
        self.scheduler_thread: Optional[threading.Thread] = None
        self.schedule: Schedule = {
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
        self.lock = threading.RLock()
        self.is_cur_scheduler_item_working: bool = False

        self.event_state: dict[str, Any] = {}
        self.update_scheduler_state_obj({}, result=0)

        self.cur_pa_error_x: float = None
        self.cur_pa_error_y: float = None
        self.site_altaz_frame = None

        self.connect_count: int = 0
        self.view_state: dict = {}  # todo : wrap this in a lock!

        # self.event_queue = queue.Queue()
        self.event_queue = collections.deque(maxlen=20)
        self.eventbus = signal(f"{self.device_name}.eventbus")
        self.is_EQ_mode: bool = is_EQ_mode
        # self.trace = MessageTrace(self.device_num, self.port)

    # scheduler state example: {"state":"working", "schedule_id":"abcdefg",
    #       "result":0, "error":"dummy error",
    #       "cur_schedule_item":{   "type":"mosaic", "schedule_item_GUID":"abcde", "state":"working",
    #                               "stack_status":{"target_name":"test_target", "stack_count": 23, "rejected_count": 2},
    #                               "item_elapsed_time_s":123, "item_remaining_time":-1}
    #       }

    def __repr__(self) -> str:
        return f"{type(self).__name__}(host={self.host}, port={self.port})"

    def get_name(self) -> str:
        return self.device_name

    def update_scheduler_state_obj(self, item_state: SchedulerItemState, result=0):
        self.event_state["scheduler"] = {
            "Event": "Scheduler",
            "schedule_id": self.schedule["schedule_id"],
            "state": self.schedule["state"],
            "item_number": self.schedule["item_number"],
            "cur_scheduler_item": item_state,
            "is_stacking": self.schedule["is_stacking"],
            "is_stacking_paused": self.schedule["is_stacking_paused"],
            "result": result,
        }
        self.logger.info(f"scheduler event state: {self.event_state['scheduler']}")

    def heartbeat(
        self,
    ):  # I noticed a lot of pairs of test_connection followed by a get if nothing was going on
        #    json_message("test_connection")
        self.json_message("scope_get_equ_coord", id=420)

    def send_message(self, data):
        try:
            if self.s is None:
                self.logger.warn("socket not initialized!")
                time.sleep(3)
                return False
            # todo : don't send if not connected or socket is null?
            self.s.sendall(
                data.encode()
            )  # TODO: would utf-8 or unicode_escaped help here
            return True
        except socket.timeout:
            return False
        except socket.error as e:
            # Don't bother trying to recover if watch events is False
            self.logger.debug(f"Send socket error: {e}")
            self.disconnect()
            if self.is_watch_events and self.reconnect():
                return self.send_message(data)
            return False
        except:
            self.logger.error("General error trying to send message: ", data)
            return False

    def socket_force_close(self) -> None:
        if self.s:
            try:
                self.s.close()
                self.s = None
            except:
                pass

    def disconnect(self) -> None:
        # Disconnect tries to clean up the socket if it exists
        self.is_connected = False
        self.socket_force_close()

    def send_udp_intro(self) -> None:
        # {"id":1,"method":"scan_iscope","params":""}
        try:
            # Create a UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_port = 4720
            # Enable broadcast option
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(1.0)  # Timeout in seconds

            addr = (self.host, udp_port)
            # Send the message to the broadcast address
            message = {"id": 1, "method": "scan_iscope", "params": ""}
            message_payload = json.dumps(message).encode()
            self.logger.info(
                f"UDP: Sending broadcast message: {message_payload} on port {udp_port}"
            )
            sock.sendto(message_payload, addr)

            while True:
                try:
                    # Listen for incoming messages
                    data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
                    self.logger.info(
                        f"UDP: Received message from {addr}: {data.decode()}"
                    )
                except socket.timeout:
                    self.logger.info("UDP: No more responses received.")
                    break

        except Exception as e:
            self.logger.info(f"Error sending broadcast message: {e}")

        finally:
            # Close the socket
            sock.close()

    def reconnect(self) -> bool:
        if self.is_connected:
            return True

        try:
            self.logger.info(f"RECONNECTING {self.device_name}")

            self.disconnect()

            # send a udp message to satisfy seestar's guest mode to gain control properly
            self.send_udp_intro()

            # note: the below isn't thread safe!  (Reconnect can be called from different threads.)
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.settimeout(Config.timeout)
            self.s.connect((self.host, self.port))
            # self.s.settimeout(None)
            self.is_connected = True
            return True
        except socket.error:
            # Let's just delay a fraction of a second to avoid reconnecting too quickly
            self.is_connected = False
            sleep(1)
            return False
        except Exception:
            self.is_connected = False
            sleep(1)
            return False

    def get_socket_msg(self) -> str | None:
        try:
            if self.s is None:
                self.logger.warn("socket not initialized!")
                time.sleep(3)
                return None
            data = self.s.recv(1024 * 60)  # comet data is >50kb
        except socket.timeout:
            self.logger.warn("Socket timeout")
            return None
        except socket.error as e:
            # todo : if general socket error, close socket, and kick off reconnect?
            # todo : no route to host...
            self.logger.debug(f"Read socket error: {e}")
            # todo : handle message failure
            self.disconnect()
            if self.is_watch_events and self.reconnect():
                return self.get_socket_msg()
            return None

        data = data.decode("utf-8")
        if len(data) == 0:
            return None

        return data

    def update_equ_coord(self, parsed_data):
        if parsed_data["method"] == "scope_get_equ_coord" and "result" in parsed_data:
            data_result = parsed_data["result"]
            self.ra = float(data_result["ra"])
            self.dec = float(data_result["dec"])

    def update_view_state(self, parsed_data):
        if parsed_data["method"] == "get_view_state" and "result" in parsed_data:
            view = parsed_data["result"].get("View")
            if view:
                self.view_state = view
                # also todo : also update view_state_timestamp
            # else:
            #    self.view_state = {}

    def heartbeat_message_thread_fn(self) -> None:
        while self.is_watch_events:
            threading.current_thread().last_run = datetime.now()

            if not self.is_connected and not self.reconnect():
                sleep(5)
                continue

            self.heartbeat()
            time.sleep(3)

    def request_plate_solve_for_BPA(self) -> None:
        # wait 1s before making the request to ease congestion
        time.sleep(1)
        tmp = self.send_message_param_sync({"method": "start_solve"})
        self.logger.info(f"requested plate solve for BPA: {tmp}")

    def receive_message_thread_fn(self) -> None:
        msg_remainder = ""
        while self.is_watch_events:
            threading.current_thread().last_run = datetime.now()
            # print("checking for msg")
            data = self.get_socket_msg()
            if data:
                msg_remainder += data
                first_index = msg_remainder.find("\r\n")

                while first_index >= 0:
                    first_msg = msg_remainder[0:first_index]
                    msg_remainder = msg_remainder[first_index + 2 :]
                    try:
                        parsed_data = json.loads(first_msg)
                    except Exception as e:
                        self.logger.exception(e)
                        # We just bail for now...
                        break

                    if "jsonrpc" in parsed_data:
                        # {"jsonrpc":"2.0","Timestamp":"9507.244805160","method":"scope_get_equ_coord","result":{"ra":17.093056,"dec":34.349722},"code":0,"id":83}
                        if parsed_data["method"] == "scope_get_equ_coord":
                            self.logger.debug(f"{parsed_data}")
                            self.update_equ_coord(parsed_data)
                        else:
                            self.logger.debug(f"{parsed_data}")
                        if parsed_data["method"] == "get_view_state":
                            self.update_view_state(parsed_data)
                        # keep a running queue of last 100 responses for sync call results
                        self.response_dict[parsed_data["id"]] = parsed_data

                    elif "Event" in parsed_data:
                        # add parsed_data
                        self.event_queue.append(parsed_data)
                        self.eventbus.send(parsed_data)

                        # xxx: make this a common method....
                        if Config.log_events_in_info:
                            self.logger.info(f"received : {parsed_data}")
                        else:
                            self.logger.debug(f"received : {parsed_data}")
                        event_name = parsed_data["Event"]
                        self.event_state[event_name] = parsed_data

                        # {'Event': 'EqModePA', 'Timestamp': '740.411562378', 'state': 'working', 'lapse_ms': 0, 'route': []}
                        # {'Event': 'EqModePA', 'Timestamp': '6359.231750447', 'state': 'fail', 'error': 'fail to operate', 'code': 207, 'lapse_ms': 80471, 'route': []}
                        # {'Event': 'EqModePA', 'Timestamp': '876.787472028', 'state': 'complete', 'lapse_ms': 80653, 'total': 2.256415, 'x': -1.041047, 'y': -2.001906, 'route': []}

                        if event_name == "EqModePA" and "state" in parsed_data:
                            if parsed_data["state"] == "working":
                                self.cur_pa_error_x = None
                                self.cur_pa_error_y = None
                            elif parsed_data["state"] == "fail":
                                self.cur_pa_error_x = None
                                self.cur_pa_error_y = None
                            elif parsed_data["state"] == "complete":
                                self.cur_pa_error_x = parsed_data["x"]
                                self.cur_pa_error_y = parsed_data["y"]
                        elif event_name == "Simu_Stack":     # The stack event is normally received in the imaging code, but the simulator will send them here
                            # Stack event is used to update the stack status from the simulator
                            if "stack_status" in parsed_data:
                                self.event_state["Stack"]  = {
                                    "Event": "Stack",
                                    "stacked_frame": parsed_data["stacked_frame"],
                                    "dropped_frame": parsed_data["dropped_frame"]
                                }
                            self.event_state.pop("Simu_Stack", None)  # Remove the Simu_Stack event to avoid confusion

                        for cb in self.event_callbacks:
                            if (
                                event_name in cb.fireOnEvents()
                                or "event_*" in cb.fireOnEvents()
                            ):
                                cb.eventFired(self, parsed_data)
                        # else:
                        #    self.logger.debug(f"Received event {event_name} : {data}")

                    first_index = msg_remainder.find("\r\n")
            time.sleep(0.1)

    def json_message(self, instruction: str, **kwargs):
        data = {"id": self.cmdid, "method": instruction, **kwargs}
        self.cmdid += 1
        json_data = json.dumps(data)
        if instruction == "scope_get_equ_coord":
            self.logger.debug(f"sending: {json_data}")
        else:
            self.logger.debug(f"sending: {json_data}")
        self.send_message(json_data + "\r\n")

    def send_message_param(self, data: MessageParams) -> int:
        cur_cmdid = data.get("id") or self.cmdid
        data["id"] = cur_cmdid
        self.cmdid += 1  # can this overflow?  not in JSON...
        json_data = json.dumps(data)
        if "method" in data and data["method"] == "scope_get_equ_coord":
            self.logger.debug(f"sending: {json_data}")
        else:
            self.logger.debug(f"sending: {json_data}")

        self.send_message(json_data + "\r\n")
        return cur_cmdid

    def shut_down_thread(self, data):
        self.play_sound(13)
        self.mark_op_state("ScopeHome", "working")
        response = self.send_message_param_sync({"method": "scope_park"})
        self.logger.info(f"Parking before shutdown...{response}")
        result = self.wait_end_op("ScopeHome")
        self.logger.info(f"Parking result...{result}")
        self.logger.info(
            f"About to send shutdown or reboot command to Seestar...{response}"
        )
        self.send_message_param(data)

    def send_message_param_sync(self, data: MessageParams):
        if data["method"] == "pi_shutdown" or data["method"] == "pi_reboot":
            threading.Thread(
                name=f"shutdown-thread:{self.device_name}",
                target=lambda: self.shut_down_thread(data),
            ).start()
            return {
                "method": data["method"],
                "result": "Sent command async for these types of commands.",
            }
        else:
            cur_cmdid = self.send_message_param(data)

        start = time.time()
        last_slow = start
        while cur_cmdid not in self.response_dict:
            now = time.time()
            if now - last_slow > 2:
                elapsed = now - start
                last_slow = now
                if elapsed > 10:
                    self.logger.error(
                        f"Failed to wait for message response.  {elapsed} seconds. {cur_cmdid=} {data=}"
                    )
                    data["result"] = "Error: Exceeded allotted wait time for result"
                    return data
                else:
                    self.logger.warn(
                        f"SLOW message response.  {elapsed} seconds. {cur_cmdid=} {data=}"
                    )
                    # todo : dump out stats.  last run time on threads, connection status, etc.
            time.sleep(0.5)
        self.logger.debug(f"response is {self.response_dict[cur_cmdid]}")
        return self.response_dict[cur_cmdid]

    def get_event_state(self, params=None):
        self.event_state["scheduler"]["Event"] = "Scheduler"
        self.event_state["scheduler"]["state"] = self.schedule["state"]
        self.event_state["scheduler"]["is_stacking"] = self.schedule.get(
            "is_stacking", False
        )
        self.event_state["scheduler"]["is_stacking_paused"] = self.schedule.get(
            "is_stacking_paused", False
        )

        if "3PPA" in self.event_state:
            self.event_state["3PPA"]["eq_offset_alt"] = self.cur_pa_error_y
            self.event_state["3PPA"]["eq_offset_az"] = self.cur_pa_error_x
        if params is not None and "event_name" in params:
            event_name = params["event_name"]
            if event_name in self.event_state:
                result = self.event_state[event_name]
            else:
                result = {}
        else:
            result = self.event_state
        return self.json_result("get_event_state", 0, result)

    # return if this device can control as master
    def is_client_master(self):
        client_master = True  # Assume master for older firmware
        if "Client" in self.event_state:
            client_master = self.event_state["Client"].get("is_master", True)
        return client_master

    def get_altaz_from_eq(self, in_ra, in_dec, obs_time):
        if self.site_altaz_frame is None:
            self.logger.warn("SCC has a rouge thread trying to call BPA error!")
            return [9999.9, 9999.9]
        radec = Util.parse_coordinate(is_j2000=False, in_ra=in_ra, in_dec=in_dec)
        # Convert RA/Dec to Alt/Az
        altaz = radec.transform_to(
            AltAz(obstime=obs_time, location=self.site_altaz_frame)
        )
        self.logger.info(f"coord in az-alt: {altaz.az.deg}, {altaz.alt.deg}")
        return [altaz.alt.deg, altaz.az.deg]

    def get_pa_error(self, param):
        if self.cur_pa_error_x is None or self.cur_pa_error_y is None:
            return {"pa_error_alt": 9999.9, "pa_error_az": 9999.9}
        else:
            return {
                "pa_error_alt": self.cur_pa_error_y,
                "pa_error_az": self.cur_pa_error_x,
            }

    def set_setting(
        self,
        x_stack_l,
        x_continuous,
        d_pix,
        d_interval,
        d_enable,
        l_enhance,
        is_frame_calibrated,
        auto_af=False,
        stack_after_goto=False,
    ):
        # auto_af was introduced in recent firmware that seems to perform autofocus after a goto.
        result = self.send_message_param_sync(
            {"method": "set_setting", "params": {"auto_af": auto_af}}
        )
        self.logger.info(f"trying to set auto_af: {result}")

        # stack_after_goto is in 2.1+ firmware. Disable if possible
        result = self.send_message_param_sync(
            {"method": "set_setting", "params": {"stack_after_goto": stack_after_goto}}
        )
        self.logger.info(f"trying to set stack_after_goto: {result}")

        # TODO:
        #   heater_enable failed.
        #   lenhace should be by itself as it moves the wheel and thus need to wait a bit
        #    data = {"id":cmdid, "method":"set_setting", "params":{"exp_ms":{"stack_l":x_stack_l,"continuous":x_continuous}, "stack_dither":{"pix":d_pix,"interval":d_interval,"enable":d_enable}, "stack_lenhance":l_enhance, "heater_enable":heater_enable}}
        data: MessageParams = {
            "method": "set_setting",
            "params": {"exp_ms": {"stack_l": x_stack_l, "continuous": x_continuous}},
            "stack_lenhance": l_enhance,
            "auto_3ppa_calib": True,
            "auto_power_off": False,
        }

        result = self.send_message_param_sync(data)
        self.logger.info(f"result for set setting: {result}")

        result = self.send_message_param_sync(
            {
                "method": "set_setting",
                "params": {
                    "stack_dither": {
                        "pix": d_pix,
                        "interval": d_interval,
                        "enable": d_enable,
                    }
                },
            }
        )
        self.logger.info(f"result for set setting for dither: {result}")

        result = self.send_message_param_sync(
            {
                "method": "set_setting",
                "params": {"stack": {"dbe": False}, "frame_calib": is_frame_calibrated},
            }
        )
        self.logger.info(
            f"result for set setting for dbe and auto frame_calib: {result}"
        )

        response = self.send_message_param_sync({"method": "get_setting"})
        self.logger.info(f"get setting response: {response}")

        time.sleep(2)  # to wait for filter change
        return result

    def stop_goto_target(self):
        if self.is_goto():
            return self.stop_slew()
        return "goto stopped already: no action taken"

    def mark_goto_status_as_start(self):
        self.mark_op_state("AutoGoto", "start")

    def mark_goto_status_as_stopped(self):
        self.mark_op_state("AutoGoto", "stopped")

    def is_goto(self):
        try:
            event_watch = "AutoGoto"
            self.logger.debug(
                f"{event_watch} status is {self.event_state[event_watch]['state']}"
            )
            return (
                self.event_state[event_watch]["state"] == "working"
                or self.event_state[event_watch]["state"] == "start"
            )
        except:
            return False

    def is_goto_completed_ok(self):
        try:
            return self.event_state["AutoGoto"]["state"] == "complete"
        except:
            return False

    # synchronise call. Will return only if there's result
    def goto_target(self, params):
        if self.is_goto():
            self.logger.info("Failed to goto target: mount is in goto routine.")
            return False
        self.mark_goto_status_as_start()

        is_j2000 = params["is_j2000"]
        in_ra = params["ra"]
        in_dec = params["dec"]
        parsed_coord = Util.parse_coordinate(is_j2000, in_ra, in_dec)
        in_ra = parsed_coord.ra.hour
        in_dec = parsed_coord.dec.deg
        target_name = params.get("target_name", "unknown")
        self.logger.info(
            "%s: going to target... %s %s %s",
            self.device_name,
            target_name,
            in_ra,
            in_dec,
        )

        data: MessageParams = {
            "method": "iscope_start_view",
            "params": {
                "mode": "star",
                "target_ra_dec": [in_ra, in_dec],
                "target_name": target_name,
                "lp_filter": False,
            },
        }
        self.mark_op_state("goto_target", "stopped")

        result = self.send_message_param_sync(data)
        return "error" not in result

    # {"method":"scope_goto","params":[1.2345,75.0]}
    def _slew_to_ra_dec(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info(f"slew to {in_ra}, {in_dec}")
        data: MessageParams = {"method": "scope_goto", "params": [in_ra, in_dec]}
        self.mark_op_state("goto_target", "stopped")
        result = self.send_message_param_sync(data)
        if "error" in result:
            self.logger.warn("Error while trying to move: %s", result)
            return False

        return self.wait_end_op("goto_target")

    def sync_target(self, params):
        if self.schedule["state"] != "stopped" or self.schedule["state"] != "complete":
            msg = f"Cannot sync target while scheduler is active: {self.schedule['state']}"
            self.logger.warn(msg)
            return msg
        else:
            return self._sync_target(params)

    def _sync_target(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info("%s: sync to target... %s %s", self.device_name, in_ra, in_dec)
        data: MessageParams = {"method": "scope_sync", "params": [in_ra, in_dec]}
        result = self.send_message_param_sync(data)
        if "error" in result:
            self.logger.info(f"Failed to sync: {result}")
        else:
            sleep(2)
        return result

    def stop_slew(self):
        self.logger.info("%s: stopping slew...", self.device_name)
        data: MessageParams = {
            "method": "iscope_stop_view",
            "params": {"stage": "AutoGoto"},
        }
        return self.send_message_param_sync(data)

    # {"method":"scope_speed_move","params":{"speed":4000,"angle":270,"dur_sec":10}}
    def move_scope(self, in_angle: int, in_speed: int, in_dur=3):
        self.logger.debug(
            "%s: moving slew angle: %s, speed: %s, dur: %s",
            self.device_name,
            in_angle,
            in_speed,
            in_dur,
        )
        if self.is_goto():
            self.logger.warn("Failed to move scope: mount is in goto routine.")
            return False
        data: MessageParams = {
            "method": "scope_speed_move",
            "params": {"speed": in_speed, "angle": in_angle, "dur_sec": in_dur},
        }
        self.send_message_param_sync(data)
        return True

    def _start_auto_focus(self):
        self.logger.info("start auto focus...")
        result = self.send_message_param_sync({"method": "start_auto_focuse"})
        if "error" in result:
            self.logger.error("Faild to start auto focus: %s", result)
            return False
        return True

    def try_auto_focus(self, try_count: int) -> bool:
        self.logger.info("trying auto_focus...")
        focus_count = 0
        result = False
        self.mark_op_state("AutoFocus", "working")
        while focus_count < try_count:
            focus_count += 1
            self.logger.info(
                "%s: focusing try %s of %s...",
                self.device_name,
                str(focus_count),
                str(try_count),
            )
            if focus_count > 1:
                time.sleep(5)
            if self._start_auto_focus():
                result = self.wait_end_op("AutoFocus")
                if result:
                    break
        # give extra time to settle focuser
        time.sleep(2)
        self.logger.info(f"auto_focus completed with result {result}")
        if result:
            self.event_state["AutoFocus"]["state"] = "complete"
        else:
            self.event_state["AutoFocus"]["state"] = "fail"
        return result

    def _try_dark_frame(self):
        self.logger.info("start dark frame measurement...")
        self.mark_op_state("DarkLibrary", "working")
        result = self.send_message_param_sync({"method": "iscope_stop_view"})

        # seem like there's a side effect here of autofocus state was set to "cancel" after stop view
        time.sleep(1)
        if "AutoFocus" in self.event_state:
            self.event_state["AutoFocus"]["state"] = "complete"

        result = self.send_message_param_sync({"method": "start_create_dark"})
        if "error" in result:
            self.logger.error("Faild to start create darks: %s", result)
            return False
        response = self.send_message_param_sync(
            {"method": "set_control_value", "params": ["gain", Config.init_gain]}
        )
        self.logger.info(f"dark frame measurement setting gain response: {response}")
        result = self.wait_end_op("DarkLibrary")

        if result:
            response = self.send_message_param_sync(
                {"method": "iscope_stop_view", "params": {"stage": "Stack"}}
            )
            self.logger.info(
                f"Response from stop stack after dark frame measurement: {response}"
            )
            time.sleep(1)
        else:
            self.logger.warn("Create dark frame data failed.")
        return result

    def stop_stack(self):
        self.logger.info("%s: stop stacking...", self.device_name)
        data: MessageParams = {
            "method": "iscope_stop_view",
            "params": {"stage": "Stack"},
        }
        self.schedule["is_stacking"] = False
        return self.send_message_param_sync(data)

    def play_sound(self, in_sound_id: int):
        self.logger.info("%s: playing sound...", self.device_name)
        req: MessageParams = {"method": "play_sound", "params": {"num": in_sound_id}}
        result = self.send_message_param_sync(req)
        time.sleep(1)
        return result

    def apply_rotation(self, matrix, degrees):
        # Convert degrees to radians
        radians = math.radians(degrees)

        # Define the rotation matrix
        rotation_matrix = np.array(
            [
                [math.cos(radians), -math.sin(radians)],
                [math.sin(radians), math.cos(radians)],
            ]
        )

        # Multiply the original matrix by the rotation matrix
        rotated_matrix = np.dot(rotation_matrix, matrix)

        return rotated_matrix

    def adjust_mag_declination(self, params):
        adjust_mag_dec = params.get("adjust_mag_dec", False)
        fudge_angle = params.get("fudge_angle", 0.0)
        self.logger.info(
            f"adjusting device's compass bearing to account for the magnetic declination at device's position. Adjust:{adjust_mag_dec}, Fudge Angle: {fudge_angle}"
        )
        response = self.send_message_param_sync(
            {"method": "get_device_state", "params": {"keys": ["location_lon_lat"]}}
        )
        result = response["result"]
        loc = result["location_lon_lat"]

        response = self.send_message_param_sync({"method": "get_sensor_calibration"})
        compass_data = response["result"]["compassSensor"]
        x11 = compass_data["x11"]
        y11 = compass_data["y11"]
        x12 = compass_data["x12"]
        y12 = compass_data["y12"]

        total_angle = fudge_angle
        if adjust_mag_dec:
            mag_dec = geomag.declination(loc[1], loc[0])
            self.logger.info(
                f"mag declination for {loc[1]}, {loc[0]} is {mag_dec} degrees"
            )
            total_angle += mag_dec

        # Convert the 2x2 matrix into a set of points (pairs of coordinates)
        # We treat each column of the matrix as a point (x, y)
        in_matrix = np.array(
            [
                [x11, x12],  # First column: (x1, y1)
                [y11, y12],
            ]
        )  # Second column: (x2, y2)

        out_matrix = self.apply_rotation(in_matrix, total_angle)

        # Convert the rotated points back into matrix form
        x11 = out_matrix[0, 0]
        y11 = out_matrix[1, 0]
        x12 = out_matrix[0, 1]
        y12 = out_matrix[1, 1]

        params = {
            "compassSensor": {
                "x": compass_data["x"],
                "y": compass_data["y"],
                "z": compass_data["z"],
                "x11": x11,
                "x12": x12,
                "y11": y11,
                "y12": y12,
            }
        }
        self.logger.info("sending adjusted compass sensor data:", params)
        response = self.send_message_param_sync(
            {"method": "set_sensor_calibration", "params": params}
        )
        result_text = (
            f"Adjusted compass calibration to offset by total of {total_angle} degrees."
        )
        self.logger.info(result_text)
        response["result"] = result_text
        return response

    def start_stack(self, params=None):
        if params is None:
            params = {"gain": Config.init_gain, "restart": True}
        result = self.send_message_param_sync(
            {"method": "iscope_start_stack", "params": {"restart": params["restart"]}}
        )
        if "error" in result:
            # try again:
            self.logger.warn("Failed to start stack. Trying again...")
            time.sleep(2)
            result = self.send_message_param_sync(
                {
                    "method": "iscope_start_stack",
                    "params": {"restart": params["restart"]},
                }
            )
            if "error" in result:
                self.logger.error("Failed to start stack: %s", result)
                return False
        self.logger.info(result)
        self.schedule["is_stacking"] = True
        if "gain" in params:
            stack_gain = params["gain"]
            result = self.send_message_param_sync(
                {"method": "set_control_value", "params": ["gain", stack_gain]}
            )
            self.logger.info(result)
        return "error" not in result

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
                not is_subframe and not files["name"].endswith("-sub")
            ):
                result_url = files["thn"]
                result_name = files["name"]
                break
        if not params["is_thumb"]:
            result_url = result_url.partition("_thn.jpg")[0] + ".jpg"
        return {
            "url": "http://" + self.host + "/" + parent_folder + "/" + result_url,
            "name": result_name,
        }

    def stop_plate_solve_loop(self):
        self.logger.info("stop plate solve loop...")
        self.send_message_param_sync({"method": "stop_polar_align"})
        return True

    # move to a good starting point position specified by lat and lon
    # scheduler state example: {"state":"working", "schedule_id":"abcdefg",
    #       "result":0, "error":"dummy error",
    #       "cur_schedule_item":{   "type":"mosaic", "schedule_item_GUID":"abcde", "state":"working",
    #                               "stack_status":{"target_name":"test_target", "stack_count": 23, "rejected_count": 2},
    #                               "item_elapsed_time_s":123, "item_remaining_time":-1}
    #       }

    def start_up_thread_fn(self, params, is_from_schedule=False):
        try:
            self.schedule["state"] = "working"
            self.logger.info("start up sequence begins ...")
            self.play_sound(80)
            self.schedule["item_number"] = (
                0  # there is really just one item in this container schedule, with many sub steps
            )
            item_state: SchedulerItemState = {
                "type": "start_up_sequence",
                "schedule_item_id": "Not Applicable",
                "action": "set configurations",
            }
            self.update_scheduler_state_obj(item_state)
            tz_name = tzlocal.get_localzone_name()
            tz = tzlocal.get_localzone()
            now = datetime.now(tz)
            date_json = {
                "year": now.year,
                "mon": now.month,
                "day": now.day,
                "hour": now.hour,
                "min": now.minute,
                "sec": now.second,
                "time_zone": tz_name,
            }
            date_data: MessageParams = {"method": "pi_set_time", "params": [date_json]}
            failed_default_PA = False

            do_raise_arm = params.get("move_arm", False)
            do_AF = params.get("auto_focus", False)
            do_3PPA = params.get("3ppa", False)
            do_dark_frames = params.get("dark_frames", False)
            dec_pos_index = params.get("dec_pos_index", 3)

            if do_3PPA and not self.is_EQ_mode:
                self.logger.warn("Cannot do 3PPA without EQ mode. Will skip 3PPA.")
                do_3PPA = False

            self.logger.info(
                f"begin start_up sequence with seestar_alp version {Version.app_version()}"
            )

            loc_param = {}
            # special case of (0,0) will use the ip address to estimate the location
            has_latlon = "lat" in params and "lon" in params
            if not has_latlon or (params["lat"] == 0 and params["lon"] == 0):
                if (has_latlon and params["lat"] == 0 and params["lon"] == 0) or (
                    Config.init_lat == 0 and Config.init_long == 0
                ):
                    coordinates = Util.get_current_gps_coordinates()
                    if coordinates is not None:
                        latitude, longitude = coordinates
                        self.logger.info("Your current GPS coordinates are:")
                        self.logger.info(f"Latitude: {latitude}")
                        self.logger.info(f"Longitude: {longitude}")
                        Config.init_lat = latitude
                        Config.init_long = longitude
            else:
                Config.init_lat = params["lat"]
                Config.init_long = params["lon"]

            # reset the site location frame for refining polar alignments
            self.site_altaz_frame = EarthLocation(
                lat=Config.init_lat * u.deg,
                lon=Config.init_long * u.deg,
                height=10 * u.m,
            )

            loc_param["lat"] = Config.init_lat
            loc_param["lon"] = Config.init_long
            loc_param["force"] = True
            loc_data: MessageParams = {
                "method": "set_user_location",
                "params": loc_param,
            }
            lang_data: MessageParams = {
                "method": "set_setting",
                "params": {"lang": "en"},
            }

            self.logger.info("verify datetime string: %s", date_data)
            self.logger.info("verify location string: %s", loc_data)

            response = self.send_message_param_sync({"method": "pi_is_verified"})
            self.logger.info(f"pi_is_verified response: {response}")

            msg = f"Setting location to {Config.init_lat}, {Config.init_long}"
            self.logger.info(msg)
            self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg

            self.logger.info(self.send_message_param_sync(date_data))
            response = self.send_message_param_sync(loc_data)
            if "error" in response:
                self.logger.error(f"Failed to set location: {response}")
            else:
                self.logger.info(f"response from set location: {response}")
            self.send_message_param_sync(lang_data)

            self.set_setting(
                Config.init_expo_stack_ms,
                Config.init_expo_preview_ms,
                Config.init_dither_length_pixel,
                Config.init_dither_frequency,
                Config.init_dither_enabled,
                Config.init_activate_LP_filter,
                Config.is_frame_calibrated,
            )

            is_dew_on = Config.init_dew_heater_power > 0
            self.send_message_param_sync(
                {
                    "method": "pi_output_set2",
                    "params": {
                        "heater": {
                            "state": is_dew_on,
                            "value": Config.init_dew_heater_power,
                        }
                    },
                }
            )

            # save frames setting
            self.send_message_param_sync(
                {
                    "method": "set_stack_setting",
                    "params": {
                        "save_discrete_ok_frame": Config.init_save_good_frames,
                        "save_discrete_frame": Config.init_save_all_frames,
                    },
                }
            )

            response = self.send_message_param_sync({"method": "get_device_state"})
            # make sure we have the right firmware version here
            self.firmware_ver_int = response["result"]["device"]["firmware_ver_int"]
            self.logger.info(f"Firmware version: {self.firmware_ver_int}")
            if self.firmware_ver_int < 2427:
                msg = "Your firmware version is too old. Please update to at least 4.27 or use the older version of the app (e.g., 2.5.x)"
                self.logger.error(msg)
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                self.schedule["state"] = "stopping"
                return

            result = True

            #
            # This park is superfluous and is not needed for the native EQ Polar Align.
            # Native Polar Align knows exactly where the scope is and you can restart
            # from any open position. It will open to the expected starting point and initiate
            # the PA routine.  If this is needed for the 'move arm' workaround, feel free to relocate
            # it there.  Running multiple PA routines is still beneficial  Waiting for the scope to park
            # and then rotate 270 degrees counter-clockwise is unproductive and a waste of time.
            #
            # if self.is_EQ_mode:
            #    msg = "park the scope in preparation for EQ mode"
            # else:
            #    msg = "park the scope in preparation for AltAz mode"
            #
            # self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
            # self.logger.info(msg)
            #
            # response = self.send_message_param_sync(
            #    {"method": "scope_park", "params": {"equ_mode": self.is_EQ_mode}}
            # )
            # result = self.wait_end_op("ScopeHome")
            # if not result:
            #    msg = "Failed to park the mount."
            #    self.logger.warn(msg)
            #    self.schedule["state"] = "stopping"
            #    self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
            #    return
            #
            # time.sleep(2)

            if do_3PPA:
                msg = "perform PA Alignment"
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                self.logger.info(msg)
                time.sleep(1.0)
                response = self.send_message_param_sync(
                    {
                        "method": "start_polar_align",
                        "params": {"restart": True, "dec_pos_index": dec_pos_index},
                    }
                )

                self.mark_op_state("EqModePA", "working")
                result = self.wait_end_op("EqModePA")
                self.mark_op_state("EqModePA", "complete")
                if not result:
                    msg = "Failed to perform polar alignment. Will try again after we adjust the arm by scope_aim parameters"
                    self.logger.warn(msg)
                    self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                    failed_default_PA = True
                else:
                    failed_default_PA = False

            if self.schedule["state"] != "working":
                return

            if do_raise_arm:
                # move the arm up using a thread runner
                # move 10 degrees from polaris
                # first check if a device specific setting is available

                for device in Config.seestars:
                    if device["device_num"] == self.device_num:
                        break

                lat = Config.move_arm_lat_sec
                lon = Config.move_arm_lon_sec

                if "move_arm_lat_sec" in params:
                    lat = params["move_arm_lat_sec"]
                else:
                    lat = device.get("move_arm_lat_sec", lat)

                if "move_arm_lon_sec" in params:
                    lon = params["move_arm_lon_sec"]
                else:
                    lon = device.get("move_arm_lon_sec", lon)

                msg = f"moving scope's aim toward a clear patch of sky using move_arm settings in seconds {lat}, {lon}"
                self.logger.info(msg)
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg

                time_countdown = abs(lat)
                if lat < 0:
                    lat_angle = 270
                else:
                    lat_angle = 90
                while time_countdown > 0:
                    tmp = self.send_message_param_sync(
                        {
                            "method": "scope_speed_move",
                            "params": {"speed": 5000, "angle": lat_angle, "dur_sec": 2},
                        }
                    )
                    self.logger.info(f"move scope 90 degrees: {tmp}")
                    time.sleep(min(1, time_countdown))
                    time_countdown -= 1
                self.send_message_param_sync(
                    {
                        "method": "scope_speed_move",
                        "params": {"speed": 0, "angle": lat_angle, "dur_sec": 0},
                    }
                )
                time.sleep(1)

                time_countdown = abs(lon)
                if lon < 0:
                    lon_angle = 0
                else:
                    lon_angle = 180
                while time_countdown > 0:
                    tmp = self.send_message_param_sync(
                        {
                            "method": "scope_speed_move",
                            "params": {"speed": 5000, "angle": lon_angle, "dur_sec": 2},
                        }
                    )
                    self.logger.info(f"move scope 180 degrees: {tmp}")
                    time.sleep(min(1, time_countdown))
                    time_countdown -= 1
                self.send_message_param_sync(
                    {
                        "method": "scope_speed_move",
                        "params": {"speed": 0, "angle": lon_angle, "dur_sec": 0},
                    }
                )
                time.sleep(1)

            if self.schedule["state"] != "working":
                return

            if do_AF:
                if not do_raise_arm or not do_3PPA:
                    self.logger.warn(
                        "start up sequence will put the scope in park position. Therefore, without do_raise_arm or polar alignment, auto focus will not be possible. Skipping."
                    )

                else:
                    # need to make sure we are in star mode
                    if (
                        "View" not in self.event_state
                        or "mode" not in self.event_state["View"]
                        or self.event_state["View"]["mode"] != "star"
                    ):
                        result = self.send_message_param_sync(
                            {"method": "iscope_start_view", "params": {"mode": "star"}}
                        )
                        self.logger.info(f"start star mode: {result}")
                        time.sleep(2)
                    msg = "auto focus"
                    self.logger.info(msg)
                    self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                    result = self.try_auto_focus(2)
                    if not result:
                        msg = "Auto focus was unsuccessful."
                        self.logger.warn(msg)
                        self.schedule["state"] = "stopping"
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "action"
                        ] = msg
                        return

            if self.schedule["state"] != "working":
                return

            if do_dark_frames:
                msg = "dark frame measurement"
                self.logger.info(msg)
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                result = self._try_dark_frame()
                if not result:
                    msg = "Failed to take dark frame data."
                    self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                    self.logger.warn(msg)
                    self.schedule["state"] = "stopping"
                    return
                else:
                    time.sleep(1)

            if do_3PPA and do_raise_arm and failed_default_PA:
                msg = "perform PA Alignment"
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                self.logger.info(msg)
                time.sleep(1.0)
                response = self.send_message_param_sync(
                    {
                        "method": "start_polar_align",
                        "params": {
                            "restart": do_raise_arm is False,
                            "dec_pos_index": dec_pos_index,
                        },
                    }
                )

                self.mark_op_state("EqModePA", "working")
                result = self.wait_end_op("EqModePA")
                if not result:
                    msg = "Failed to perform polar alignment."
                    self.logger.warn(msg)
                    self.schedule["state"] = "stopping"
                    self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                    return

            # TODO: need to go to PA refinement mode, and then wait until stop_PA is called

            if self.schedule["state"] != "working":
                return

            self.logger.info(f"Start-up sequence result: {result}")
            self.event_state["scheduler"]["cur_scheduler_item"]["action"] = "complete"

        finally:
            time.sleep(1)
            if (
                "View" not in self.event_state
                or "mode" not in self.event_state["View"]
                or self.event_state["View"]["mode"] != "star"
            ):
                self.send_message_param_sync(
                    {"method": "iscope_start_view", "params": {"mode": "star"}}
                )
                time.sleep(2)
            if self.schedule["state"] == "stopping":
                self.schedule["state"] = "stopped"
                self.play_sound(82)
            elif not is_from_schedule:
                self.schedule["state"] = "complete"
                self.play_sound(82)

    def pause_scheduler(self, params):
        self.logger.info("pausing scheduler...")
        if (
            self.schedule["state"] == "working"
            and self.schedule["is_stacking"]
            and not self.schedule["is_stacking_paused"]
        ):
            self.schedule["is_stacking_paused"] = True
            self.logger.info(
                "confirmed scheduler is stacking, so stop for further instrctions."
            )
            return self.stop_stack()
        else:
            self.logger.warn("scheduler is not stacking, so nothing to pause")
            return self.json_result("pause_scheduler", -1, "Scheduler is not stacking.")

    def continue_scheduler(self, params):
        self.logger.info("continue scheduler...")
        if (
            self.schedule["state"] == "working"
            and not self.schedule["is_stacking"]
            and self.schedule["is_stacking_paused"]
        ):
            self.schedule["is_stacking_paused"] = False
            self.logger.info(
                "confirmed scheduler was paused stacking, so continue stacking now.."
            )
            result = self.start_stack({"restart": False})
            if result:
                return self.json_result("continue_scheduler", 0, "")
            else:
                return self.json_result(
                    "continue_scheduler", -1, "Failed to continue stacking."
                )
        else:
            self.logger.warn("scheduler was not paused, so nothing to do")
            return self.json_result(
                "pause_scheduler", -1, "Scheduler was not paused stacking."
            )

    def skip_scheduler_cur_item(self, params):
        self.logger.info("skipping scheduler item...")
        if (
            self.schedule["state"] == "working"
            and not self.schedule["is_skip_requested"]
        ):
            cur_item_num = self.schedule["item_number"]
            self.logger.info(
                f"confirmed scheduler is working, so skip current item {cur_item_num} by stopping the scheduler first."
            )
            self.schedule["is_skip_requested"] = True
            self.schedule["is_stacking_paused"] = False
            self.schedule["is_stacking"] = False
            return self.json_result(
                "skip_scheduler_cur_item", 0, "Requested to skip current item."
            )

        else:
            msg = "scheduler is not working or skip was already requested, so nothing to skip"
            self.logger.warn(msg)
            return self.json_result("skip_scheduler_cur_item", -1, msg)

    def action_set_dew_heater(self, params):
        response = self.send_message_param_sync(
            {
                "method": "pi_output_set2",
                "params": {
                    "heater": {"state": params["heater"] > 0, "value": params["heater"]}
                },
            }
        )
        return response

    def action_set_exposure(self, params):
        set_response = self.send_message_param_sync(
            {"method": "set_setting", "params": {"exp_ms": {"stack_l": params["exp"]}}}
        )
        dark_response = self.send_message_param_sync({"method": "start_create_dark"})
        response = {
            "set_response": set_response,
            "dark_response": dark_response,
        }
        return response

    def action_start_up_sequence(self, params):
        if self.schedule["state"] != "stopped" and self.schedule["state"] != "complete":
            return self.json_result(
                "start_up_sequence", -1, "Device is busy. Try later."
            )
        response = self.send_message_param_sync(
            {"method": "set_setting", "params": {"master_cli": True}}
        )
        self.logger.info(f"set master_cli response: {response}")
        if not self.is_client_master():
            self.json_result(
                "start_up_sequence",
                -1,
                "Alp is not the device controller. Will try to grab control first.",
            )
            return self.json_result(
                "Need to be master client to start up sequence.",
                -1,
                "Need to be master client to start up sequence.",
            )

        move_up_dec_thread = threading.Thread(
            name=f"start-up-thread:{self.device_name}",
            target=lambda: self.start_up_thread_fn(params, False),
        )
        move_up_dec_thread.start()
        return self.json_result("start_up_sequence", 0, "Sequence started.")

    # {"method":"set_sequence_setting","params":[{"group_name":"Kai_goto_target_name"}]}
    def set_target_name(self, name):
        req: MessageParams = {"method": "set_sequence_setting"}
        params = {"group_name": name}
        req["params"] = [params]
        return self.send_message_param_sync(req)

    # scheduler state example: {"state":"working", "schedule_id":"abcdefg",
    #       "result":0, "error":"dummy error",
    #       "cur_schedule_item":{   "type":"mosaic", "schedule_item_GUID":"abcde",
    #                               "stack_status":{"target_name":"test_target", "action":"blah blah", "stack_count": 23, "rejected_count": 2},
    #                               "item_elapsed_time_s":123, "item_remaining_time_s":-1}
    #       }

    def spectra_thread_fn(self, params):
        try:
            # unlike Mosaic, we can't depend on platesolve to find star, so all movement is by simple motor movement
            center_RA = params["ra"]
            center_Dec = params["dec"]
            is_j2000 = params["is_j2000"]
            target_name = params["target_name"]
            exposure_time_per_segment = params["panel_time_sec"]
            stack_params: StartStackParams = {"gain": params["gain"], "restart": True}
            spacing = [5.3, 6.2, 6.5, 7.1, 8.0, 8.9, 9.2, 9.8]
            is_LP = [False, False, True, False, False, False, True, False]
            num_segments = len(spacing)

            parsed_coord = Util.parse_coordinate(is_j2000, center_RA, center_Dec)
            center_RA = parsed_coord.ra.hour
            center_Dec = parsed_coord.dec.deg

            # 60s for the star
            time_remaining = exposure_time_per_segment * num_segments - 60.0

            item_state: SchedulerItemState = {
                "type": "spectra",
                "schedule_item_id": self.schedule["current_item_id"],
                "target_name": target_name,
                "action": "slew to target",
                "item_total_time_s": exposure_time_per_segment,
                "item_remaining_time_s": time_remaining,
            }
            self.update_scheduler_state_obj(item_state)

            if center_RA < 0:
                center_RA = self.ra
                center_Dec = self.dec
            else:
                # move to target
                self._slew_to_ra_dec([center_RA, center_Dec])

            # take one minute exposure for the star
            if self.schedule["state"] != "working":
                self.schedule["state"] = "stopped"
                return
            self.set_target_name(target_name + "_star")
            if not self.start_stack(stack_params):
                return
            self.event_state["scheduler"]["cur_scheduler_item"]["action"] = (
                "stack for reference star for 60 seconds"
            )
            time.sleep(60)
            self.stop_stack()
            time_remaining -= 60
            self.event_state["scheduler"]["cur_scheduler_item"][
                "item_remaining_time_s"
            ] = time_remaining

            # capture spectra
            cur_dec = center_Dec
            for index in range(len(spacing)):
                if self.schedule["state"] != "working":
                    self.schedule["state"] = "stopped"
                    return
                cur_dec = center_Dec + spacing[index]
                self.send_message_param_sync(
                    {
                        "method": "set_setting",
                        "params": {"stack_lenhance": is_LP[index]},
                    }
                )
                self._slew_to_ra_dec([center_RA, cur_dec])
                self.set_target_name(target_name + "_spec_" + str(index + 1))
                if not self.start_stack(stack_params):
                    return
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = (
                    f"stack for spectra at spacing index {index}"
                )
                count_down = exposure_time_per_segment
                while count_down > 0:
                    if self.schedule["state"] != "working":
                        self.stop_stack()
                        self.schedule["state"] = "stopped"
                        return
                    elif self.schedule["is_skip_requested"]:
                        self.logger.info("requested to skip. Stopping spectra_thread.")
                        return
                    time_remaining -= count_down
                    time.sleep(10)
                    count_down -= 10
                    time_remaining -= 10
                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "item_remaining_time_s"
                    ] = time_remaining
                self.stop_stack()

            self.logger.info("Finished spectra mosaic.")
            self.event_state["scheduler"]["cur_scheduler_item"][
                "item_remaining_time_s"
            ] = 0
            self.event_state["scheduler"]["cur_scheduler_item"]["action"] = "complete"
        finally:
            self.is_cur_scheduler_item_working = False

    # {"target_name":"kai_Vega", "ra":-1.0, "dec":-1.0, "is_use_lp_filter_too":true, "panel_time_sec":600, "grating_lines":300}
    def start_spectra_item(self, params):
        self.is_cur_scheduler_item_working = False
        if self.schedule["state"] != "working":
            self.logger.info("Run Scheduler is stopping")
            self.schedule["state"] = "stopped"
            return
        self.is_cur_scheduler_item_working = True
        self.mosaic_thread = threading.Thread(
            name=f"spectra-thread:{self.device_name}",
            target=lambda: self.spectra_thread_fn(params),
        )
        self.mosaic_thread.start()
        return "spectra mosiac started"

    def mosaic_goto_inner_worker(
        self,
        cur_ra: float,
        cur_dec: float,
        save_target_name: str,
        is_use_autofocus: bool,
        is_use_LP_filter: bool,
    ) -> bool:
        result = self.goto_target(
            {
                "ra": cur_ra,
                "dec": cur_dec,
                "is_j2000": False,
                "target_name": save_target_name,
            }
        )
        if result:
            result = self.wait_end_op("goto_target")

        self.logger.info(f"Goto operation finished with result code: {result}")
        if not result:
            self.logger.info("Goto failed.")
            return False

        time.sleep(3)

        self.send_message_param_sync(
            {"method": "set_setting", "params": {"stack_lenhance": is_use_LP_filter}}
        )
        if is_use_autofocus:
            self.event_state["scheduler"]["cur_scheduler_item"]["action"] = (
                "auto focusing"
            )
            result = self.try_auto_focus(2)
        if not result:
            self.logger.info(
                "Failed to auto focus, but will continue to image panel anyway."
            )
            result = True
        return result

    def mosaic_thread_fn(
        self,
        target_name,
        center_RA,
        center_Dec,
        is_use_LP_filter,
        panel_time_sec,
        nRA,
        nDec,
        overlap_percent,
        gain,
        is_use_autofocus,
        selected_panels,
        num_tries,
        retry_wait_s,
    ):
        try:
            spacing_result = Util.mosaic_next_center_spacing(
                center_RA, center_Dec, overlap_percent
            )
            delta_RA = spacing_result[0]
            delta_Dec = spacing_result[1]

            num_panels = nRA * nDec
            is_use_selected_panels = not selected_panels == ""
            if is_use_selected_panels:
                panel_set = selected_panels.split(";")
                num_panels = len(panel_set)
            else:
                panel_set = []

            # adjust mosaic center if num panels is even
            if nRA % 2 == 0:
                center_RA += delta_RA / 2
            if nDec % 2 == 0:
                center_Dec += delta_Dec / 2

            sleep_time_per_panel = round(panel_time_sec)

            item_remaining_time_s = sleep_time_per_panel * num_panels
            item_state: SchedulerItemState = {
                "type": "mosaic",
                "schedule_item_id": self.schedule["current_item_id"],
                "target_name": target_name,
                "action": "start",
                "item_total_time_s": item_remaining_time_s,
                "item_remaining_time_s": item_remaining_time_s,
            }
            self.update_scheduler_state_obj(item_state)

            cur_dec = center_Dec - int(nDec / 2) * delta_Dec
            for index_dec in range(nDec):
                spacing_result = Util.mosaic_next_center_spacing(
                    center_RA, cur_dec, overlap_percent
                )
                delta_RA = spacing_result[0]
                cur_ra = center_RA - int(nRA / 2) * spacing_result[0]
                for index_ra in range(nRA):
                    if self.schedule["state"] != "working":
                        self.logger.info("Mosaic mode was requested to stop. Stopping")
                        self.schedule["state"] = "stopped"
                        return
                    if self.schedule["is_skip_requested"]:
                        self.logger.info(
                            "current mosaic was requested to skip. Stopping at current mosaic."
                        )
                        return

                    # check if we are doing a subset of the panels
                    panel_string = str(index_ra + 1) + str(index_dec + 1)
                    if is_use_selected_panels and panel_string not in panel_set:
                        cur_ra += delta_RA
                        continue

                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "cur_ra_panel_num"
                    ] = index_ra + 1
                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "cur_dec_panel_num"
                    ] = index_dec + 1

                    if nRA == 1 and nDec == 1:
                        save_target_name = target_name
                    else:
                        save_target_name = target_name + "_" + panel_string

                    self.logger.info(
                        "Stacking operation started for " + save_target_name
                    )
                    self.logger.info(
                        "mosaic goto for panel %s, to location %s",
                        panel_string,
                        (cur_ra, cur_dec),
                    )

                    # set_settings(x_stack_l, x_continuous, d_pix, d_interval, d_enable, l_enhance, heater_enable):
                    # TODO: Need to set correct parameters
                    self.send_message_param_sync(
                        {"method": "set_setting", "params": {"stack_lenhance": False}}
                    )

                    for try_index in range(num_tries):
                        try_count = try_index + 1
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "action"
                        ] = f"attempt #{try_count} slewing to target panel centered at {cur_ra:.2f}, {cur_dec:.2f}"
                        self.logger.info(
                            f"Trying to readch target, attempt #{try_count}"
                        )
                        result = self.mosaic_goto_inner_worker(
                            cur_ra,
                            cur_dec,
                            save_target_name,
                            is_use_autofocus,
                            is_use_LP_filter,
                        )
                        if result:
                            break
                        else:
                            if try_count < num_tries:
                                # wait as requested before the next try
                                for i in range(round(retry_wait_s / 5)):
                                    if self.schedule["state"] != "working":
                                        self.logger.info(
                                            "Scheduler was requested to stop. Stopping at current mosaic."
                                        )
                                        self.event_state["scheduler"][
                                            "cur_scheduler_item"
                                        ][
                                            "action"
                                        ] = "Scheduler was requested to stop. Stopping at current mosaic."
                                        self.schedule["state"] = "stopped"
                                        return
                                    else:
                                        waited_time = i * 5
                                        msg = f"waited {waited_time}s of requested {retry_wait_s}s before retry GOTO target."
                                        self.logger.info(msg)
                                        self.event_state["scheduler"][
                                            "cur_scheduler_item"
                                        ]["action"] = msg
                                    time.sleep(5)

                    # if we failed goto
                    if not result:
                        msg = f"Failed to goto target after {num_tries} tries."
                        self.logger.warn(msg)
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "action"
                        ] = msg

                        cur_ra += delta_RA
                        continue

                    msg = f"stacking the panel for {sleep_time_per_panel} seconds"
                    self.logger.info(msg)
                    self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg

                    # be sure we are using the right target name before we stack
                    self.set_target_name(save_target_name)

                    if not self.start_stack({"gain": gain, "restart": True}):
                        msg = "Failed to start stacking."
                        self.logger.warn(msg)
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "action"
                        ] = msg

                        cur_ra += delta_RA
                        continue

                    panel_remaining_time_s = sleep_time_per_panel
                    for i in range(round(sleep_time_per_panel / 5)):
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "panel_remaining_time_s"
                        ] = panel_remaining_time_s
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "item_remaining_time_s"
                        ] = item_remaining_time_s
                        threading.current_thread().last_run = datetime.now()

                        if self.schedule["state"] != "working":
                            self.logger.info(
                                "Scheduler was requested to stop. Stopping at current mosaic."
                            )
                            self.event_state["scheduler"]["cur_scheduler_item"][
                                "action"
                            ] = "Scheduler was requested to stop. Stopping at current mosaic."
                            self.stop_stack()
                            self.schedule["state"] = "stopped"
                            self.event_state["scheduler"]["cur_scheduler_item"][
                                "panel_remaining_time_s"
                            ] = 0
                            self.event_state["scheduler"]["cur_scheduler_item"][
                                "item_remaining_time_s"
                            ] = 0
                            return
                        elif self.schedule["is_skip_requested"]:
                            self.logger.info(
                                "current mosaic stacking was requested to skip. Stopping at current mosaic."
                            )
                            return

                        time.sleep(5)
                        panel_remaining_time_s -= 5
                        item_remaining_time_s -= 5
                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "panel_remaining_time_s"
                    ] = 0
                    self.stop_stack()
                    msg = "Stacking operation finished " + save_target_name
                    self.logger.info(msg)
                    self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                    cur_ra += delta_RA
                cur_dec += delta_Dec
            self.logger.info("Finished mosaic.")
            self.event_state["scheduler"]["cur_scheduler_item"][
                "item_remaining_time_s"
            ] = 0
            self.event_state["scheduler"]["cur_scheduler_item"]["action"] = "complete"
        finally:
            self.is_cur_scheduler_item_working = False

    def start_mosaic_item(self, params: dict[str, Any]) -> None:
        self.is_cur_scheduler_item_working = False

        if self.schedule["state"] != "working":
            self.logger.info("Run Scheduler is stopping")
            self.schedule["state"] = "stopped"
            return

        target_name = params["target_name"]
        center_RA = params["ra"]
        center_Dec = params["dec"]
        is_j2000 = params["is_j2000"]
        is_use_LP_filter = params["is_use_lp_filter"]
        if "panel_time_sec" not in params:
            self.logger.error(
                "Mosaic schedule spec has changed. Use panel_time_sec instad of session_time_sec to specify length of capture."
            )
            panel_time_sec = params["session_time_sec"]
        else:
            panel_time_sec = params["panel_time_sec"]
        nRA = params["ra_num"]
        nDec = params["dec_num"]
        overlap_percent = params["panel_overlap_percent"]
        gain = params["gain"]
        if "is_use_autofocus" in params:
            is_use_autofocus = params["is_use_autofocus"]
        else:
            is_use_autofocus = False
        if "selected_panels" not in params:
            selected_panels = ""
        else:
            selected_panels = params["selected_panels"]
        num_tries = params.get("num_tries", 1)
        retry_wait_s = params.get("retry_wait_s", 300)

        # verify mosaic pattern
        if nRA < 1 or nDec < 0:
            self.logger.info(
                "Mosaic size is invalid. Moving to next schedule item if any."
            )
            return

        if not isinstance(center_RA, str) and center_RA == -1 and center_Dec == -1:
            center_RA = self.ra
            center_Dec = self.dec
            is_j2000 = False

        parsed_coord = Util.parse_coordinate(is_j2000, center_RA, center_Dec)
        center_RA = parsed_coord.ra.hour
        center_Dec = parsed_coord.dec.deg

        response = self.send_message_param_sync({"method": "get_setting"})
        result = response["result"]
        self.logger.info(f"get_setting response: {result}")

        # print input requests
        self.logger.info("received parameters:")
        self.logger.info(f"Firmware version: {self.firmware_ver_int}")
        self.logger.info("  target        : " + target_name)
        self.logger.info("  RA            : %s", center_RA)
        self.logger.info("  Dec           : %s", center_Dec)
        self.logger.info("  from RA       : %s", self.ra)
        self.logger.info("  from Dec      : %s", self.dec)
        self.logger.info("  use LP filter : %s", is_use_LP_filter)
        self.logger.info("  panel time (s): %s", panel_time_sec)
        self.logger.info("  RA num panels : %s", nRA)
        self.logger.info("  Dec num panels: %s", nDec)
        self.logger.info("  overlap %%    : %s", overlap_percent)
        self.logger.info("  gain          : %s", gain)
        self.logger.info("  exposure time : %s", result["exp_ms"]["stack_l"])
        self.logger.info("  dither pixLen : %s", result["stack_dither"]["pix"])
        self.logger.info("  dither interv : %s", result["stack_dither"]["interval"])
        self.logger.info("  use autofocus : %s", is_use_autofocus)
        self.logger.info("  select panels : %s", selected_panels)
        self.logger.info("  # goto tries  : %s", num_tries)
        self.logger.info("  retry wait sec: %s", retry_wait_s)

        self.is_cur_scheduler_item_working = True
        self.mosaic_thread = threading.Thread(
            target=lambda: self.mosaic_thread_fn(
                target_name,
                center_RA,
                center_Dec,
                is_use_LP_filter,
                panel_time_sec,
                nRA,
                nDec,
                overlap_percent,
                gain,
                is_use_autofocus,
                selected_panels,
                num_tries,
                retry_wait_s,
            )
        )
        self.mosaic_thread.name = f"MosaicThread:{self.device_name}"
        self.mosaic_thread.start()
        return

    def get_schedule(self, params):
        if "schedule_id" in params:
            if self.schedule["schedule_id"] != params["schedule_id"]:
                return {}

        return self.schedule

    def create_schedule(self, params):
        if self.schedule["state"] == "working":
            return "scheduler is still active"
        if self.schedule["state"] == "stopping":
            self.schedule["state"] = "stopped"

        if "schedule_id" in params:
            schedule_id = params["schedule_id"]
        else:
            schedule_id = str(uuid.uuid4())

        self.schedule["schedule_id"] = schedule_id
        self.schedule["state"] = "stopped"
        self.schedule["list"].clear()
        return self.schedule

    def construct_schedule_item(self, params):
        item = params.copy()
        if item["action"] == "start_mosaic":
            mosaic_params = item["params"]
            if isinstance(mosaic_params["ra"], str):
                # try to trim the seconds to 1 decimal
                mosaic_params["ra"] = Util.trim_seconds(mosaic_params["ra"])
                mosaic_params["dec"] = Util.trim_seconds(mosaic_params["dec"])
            elif isinstance(mosaic_params["ra"], float):
                if mosaic_params["ra"] < 0:
                    mosaic_params["ra"] = self.ra
                    mosaic_params["dec"] = self.dec
                    mosaic_params["is_j2000"] = False
                mosaic_params["ra"] = round(mosaic_params["ra"], 4)
                mosaic_params["dec"] = round(mosaic_params["dec"], 4)
        item["schedule_item_id"] = str(uuid.uuid4())
        return item

    def add_schedule_item(self, params) -> Schedule:
        new_item = self.construct_schedule_item(params)
        self.schedule["list"].append(new_item)
        return self.schedule

    def replace_schedule_item(self, params):
        targeted_item_id = params["item_id"]
        index = 0
        if self.schedule["state"] == "working":
            active_schedule_item_id = self.schedule["current_item_id"]
            reached_cur_item = False
            while index < len(self.schedule["list"]) and not reached_cur_item:
                item_id = self.schedule["list"][index].get(
                    "schedule_item_id", "UNKNOWN"
                )
                if item_id == targeted_item_id:
                    self.logger.warn(
                        "Cannot insert schedule item that has already been executed"
                    )
                    return self.schedule
                if item_id == active_schedule_item_id:
                    reached_cur_item = True

        while index < len(self.schedule["list"]):
            item = self.schedule["list"][index]
            item_id = item.get("schedule_item_id", "UNKNOWN")
            if item_id == targeted_item_id:
                new_item = self.construct_schedule_item(params)
                self.schedule["list"][index] = new_item
                break
            index += 1
        return self.schedule

    def insert_schedule_item_before(self, params):
        targeted_item_id = params["before_id"]
        index = 0
        if self.schedule["state"] == "working":
            active_schedule_item_id = self.schedule["current_item_id"]
            reached_cur_item = False
            while index < len(self.schedule["list"]) and not reached_cur_item:
                item_id = self.schedule["list"][index].get(
                    "schedule_item_id", "UNKNOWN"
                )
                if item_id == targeted_item_id:
                    self.logger.warn(
                        "Cannot insert schedule item that has already been executed"
                    )
                    return self.schedule
                if item_id == active_schedule_item_id:
                    reached_cur_item = True
                index += 1
        while index < len(self.schedule["list"]):
            item = self.schedule["list"][index]
            item_id = item.get("schedule_item_id", "UNKNOWN")
            if item_id == targeted_item_id:
                new_item = self.construct_schedule_item(params)
                self.schedule["list"].insert(index, new_item)
                break
            index += 1
        return self.schedule

    def remove_schedule_item(self, params):
        targeted_item_id = params["schedule_item_id"]
        index = 0
        if self.schedule["state"] == "working":
            active_schedule_item_id = self.schedule["current_item_id"]
            reached_cur_item = False
            while index < len(self.schedule["list"]) and not reached_cur_item:
                item_id = self.schedule["list"][index].get(
                    "schedule_item_id", "UNKNOWN"
                )
                if item_id == targeted_item_id:
                    self.logger.warn(
                        "Cannot remove schedule item that has already been executed"
                    )
                    return self.schedule
                if item_id == active_schedule_item_id:
                    reached_cur_item = True
                index += 1
        while index < len(self.schedule["list"]):
            item = self.schedule["list"][index]
            item_id = item.get("schedule_item_id", "UNKNOWN")
            if item_id == targeted_item_id:
                self.schedule["list"].remove(item)
                break
            index += 1
        return self.schedule

    def export_schedule(self, params):
        filepath = params["filepath"]
        with open(filepath, "w") as fp:
            json.dump(self.schedule, fp, indent=4, cls=DequeEncoder)
        return self.schedule

    def import_schedule(self, params):
        if self.schedule["state"] != "stopped" and self.schedule["state"] != "complete":
            return self.json_result(
                "import_schedule",
                -1,
                "An existing scheduler is active. Returned with no action.",
            )
        filepath = params["filepath"]
        is_retain_state = params["is_retain_state"]
        with open(filepath, "r") as f:
            self.schedule = json.load(f)
        self.schedule["list"] = collections.deque(self.schedule["list"])

        # ensure all required fields are present and set to default values
        self.schedule["version"] = "1.0"
        self.schedule["Event"] = "Scheduler"
        self.schedule["state"] = "stopped"
        self.schedule["is_stacking_paused"] = False
        self.schedule["is_stacking"] = False
        self.schedule["is_skip_requested"] = False
        self.schedule["current_item_id"] = ""
        self.schedule["item_number"] = 9999

        if not is_retain_state:
            self.schedule["schedule_id"] = str(uuid.uuid4())
            for item in self.schedule["list"]:
                item["schedule_item_id"] = str(uuid.uuid4())
            self.schedule["state"] = "stopped"
        return self.schedule

    # shortcut to start a new scheduler with only a mosaic request
    def start_mosaic(self, params):
        if self.schedule["state"] != "stopped" and self.schedule["state"] != "complete":
            return self.json_result(
                "start_mosaic",
                -1,
                "An existing scheduler is active. Returned with no action.",
            )
        self.create_schedule(params)
        schedule_item = {"action": "start_mosaic", "params": params}
        self.add_schedule_item(schedule_item)
        return self.start_scheduler(params)

    # shortcut to start a new scheduler with only a spectra request
    def start_spectra(self, params):
        if self.schedule["state"] != "stopped" and self.schedule["state"] != "complete":
            return self.json_result(
                "start_spectra",
                -1,
                "An existing scheduler is active. Returned with no action.",
            )
        self.create_schedule(params)
        schedule_item = {"action": "start_spectra", "params": params}
        self.add_schedule_item(schedule_item)
        return self.start_scheduler(params)

    def json_result(self, command_name, code, result):
        if code != 0:
            self.logger.warn(
                f"Returning not normal result for command {command_name}, code: {code}, result: {result}."
            )
        else:
            self.logger.debug(
                f"Returning result for command {command_name}, code: {code}, result: {result}."
            )

        return {
            "jsonrpc": "2.0",
            "TimeStamp": time.time(),
            "command": command_name,
            "code": code,
            "result": result,
        }

    def adjust_focus(self, num_steps):
        response = self.send_message_param_sync({"method": "get_focuser_position"})
        cur_step_value = response["result"]
        self.logger.info(
            f"Adjusting focus by {num_steps} steps from current value of {cur_step_value}"
        )
        response = self.send_message_param_sync(
            {
                "method": "move_focuser",
                "params": {"step": cur_step_value + num_steps, "ret_step": True},
            }
        )
        time.sleep(2)
        response = self.send_message_param_sync({"method": "get_focuser_position"})
        cur_step_value = response["result"]
        result = f"Final focus position: {cur_step_value}"
        self.logger.info(result)
        return result

    def reset_scheduler_cur_item(self, params=None):
        self.event_state["scheduler"] = {
            "cur_scheduler_item": {"type": "", "schedule_item_id": "", "action": ""}
        }
        return

    def start_scheduler(self, params):
        if (
            "schedule_id" in params
            and params["schedule_id"] != self.schedule["schedule_id"]
        ):
            return self.json_result(
                "start_scheduler",
                0,
                f"Schedule with id {params['schedule_id']} did not match this device's schedule. Returned with no action.",
            )
        if not self.is_client_master():
            return self.json_result(
                "start_scheduler",
                -1,
                "This device cannot be controlled. Grab the control first.",
            )
        if self.schedule["state"] != "stopped" and self.schedule["state"] != "complete":
            return self.json_result(
                "start_scheduler",
                -1,
                "An existing scheduler is active. Returned with no action.",
            )

        if "start_item" in params:
            self.schedule["item_number"] = params["start_item"]
        else:
            self.schedule["item_number"] = 1

        self.scheduler_thread = threading.Thread(
            target=lambda: self.scheduler_thread_fn(), daemon=True
        )
        self.scheduler_thread.name = f"SchedulerThread:{self.device_name}"
        self.scheduler_thread.start()

        return self.schedule

    # scheduler state example: {"state":"working", "schedule_id":"abcdefg",
    #       "result":0, "error":"dummy error",
    #       "cur_schedule_item":{   "type":"mosaic", "schedule_item_GUID":"abcde", "state":"working",
    #                               "stack_status":{"target_name":"test_target", "stack_count": 23, "rejected_count": 2},
    #                               "item_elapsed_time_s":123, "item_remaining_time":-1}
    #       }

    def scheduler_thread_fn(self):
        def update_time():
            threading.current_thread().last_run = datetime.now()

        self.logger.info(
            f"start run scheduler with seestar_alp version {Version.app_version}"
        )

        self.schedule["state"] = "working"
        self.schedule["is_stacking"] = False
        self.schedule["is_stacking_paused"] = False
        issue_shutdown = False
        self.play_sound(80)
        self.logger.info(
            f"schedule started from item {self.schedule['item_number']}..."
        )
        index = self.schedule["item_number"] - 1
        while index < len(self.schedule["list"]):
            update_time()
            if self.schedule["state"] != "working":
                break
            cur_schedule_item = self.schedule["list"][index]
            self.schedule["current_item_id"] = cur_schedule_item.get(
                "schedule_item_id", "UNKNOWN"
            )
            self.schedule["item_number"] = index + 1
            action = cur_schedule_item["action"]
            if action == "start_mosaic":
                self.start_mosaic_item(cur_schedule_item["params"])
                while self.is_cur_scheduler_item_working:
                    update_time()
                    time.sleep(2)
            elif action == "start_spectra":
                self.start_spectra_item(cur_schedule_item["params"])
                while self.is_cur_scheduler_item_working:
                    update_time()
                    time.sleep(2)
            elif action == "auto_focus":
                item_state: SchedulerItemState = {
                    "type": "auto_focus",
                    "schedule_item_id": self.schedule["current_item_id"],
                    "action": "auto focus",
                }
                self.update_scheduler_state_obj(item_state)
                self.try_auto_focus(cur_schedule_item["params"]["try_count"])
            elif action == "adjust_focus":
                item_state: SchedulerItemState = {
                    "type": "adjust_focus",
                    "schedule_item_id": self.schedule["current_item_id"],
                    "action": "adjust focus",
                }
                self.update_scheduler_state_obj(item_state)
                self.adjust_focus(cur_schedule_item["params"]["steps"])
            elif action == "shutdown":
                item_state: SchedulerItemState = {
                    "type": "shut_down",
                    "schedule_item_id": self.schedule["current_item_id"],
                    "action": "shut down",
                }
                self.update_scheduler_state_obj(item_state)
                self.schedule["state"] = "stopped"
                issue_shutdown = True
                break
            elif action == "wait_for":
                sleep_time = cur_schedule_item["params"]["timer_sec"]
                item_state: SchedulerItemState = {
                    "type": "wait_for",
                    "schedule_item_id": self.schedule["current_item_id"],
                    "action": f"wait for {sleep_time} seconds",
                    "remaining s": sleep_time,
                }
                self.update_scheduler_state_obj(item_state)
                sleep_count = 0
                while sleep_count < sleep_time and self.schedule["state"] == "working":
                    if self.schedule["is_skip_requested"]:
                        self.logger.info("requested to skip. Stopping wait_for.")
                        break
                    update_time()
                    time.sleep(5)
                    sleep_count += 5
                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "remaining s"
                    ] = sleep_time - sleep_count

            elif action == "wait_until":
                wait_until_time = cur_schedule_item["params"]["local_time"].split(":")
                wait_until_hour = int(wait_until_time[0])
                wait_until_minute = int(wait_until_time[1])
                local_time = local_time = datetime.now()
                item_state: SchedulerItemState = {
                    "type": "wait_until",
                    "schedule_item_id": self.schedule["current_item_id"],
                    "action": f"wait until local time of {cur_schedule_item['params']['local_time']}",
                }
                self.update_scheduler_state_obj(item_state)
                while self.schedule["state"] == "working":
                    update_time()
                    local_time = datetime.now()
                    if (
                        local_time.hour == wait_until_hour
                        and local_time.minute == wait_until_minute
                    ):
                        break
                    elif self.schedule["is_skip_requested"]:
                        self.logger.info("requested to skip. Stopping wait_until.")
                        break
                    time.sleep(5)
                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "current time"
                    ] = f"{local_time.hour:02d}:{local_time.minute:02d}"
            elif action == "start_up_sequence":
                item_state: SchedulerItemState = {
                    "type": "start up",
                    "schedule_item_id": self.schedule["current_item_id"],
                    "action": "start up",
                }
                self.update_scheduler_state_obj(item_state)
                # self.start_up_thread_fn(cur_schedule_item['params'])
                startup_thread = threading.Thread(
                    name=f"start-up-thread:{self.device_name}",
                    target=lambda: self.start_up_thread_fn(
                        cur_schedule_item["params"], True
                    ),
                )
                startup_thread.start()
                time.sleep(2)
                while startup_thread.is_alive():
                    update_time()
                    time.sleep(2)
            elif action == "action_set_dew_heater":
                self.logger.info(
                    f"Trying to set dew heater to {cur_schedule_item['params']}"
                )
                self.action_set_dew_heater(cur_schedule_item["params"])
            elif action == "action_set_exposure":
                self.logger.info(
                    f"Trying to set exposure to {cur_schedule_item['params']}"
                )
                self.action_set_exposure(cur_schedule_item["params"])
            else:
                if "params" in cur_schedule_item:
                    request: MessageParams = {
                        "method": action,
                        "params": cur_schedule_item["params"],
                    }
                else:
                    request: MessageParams = {"method": action}
                self.send_message_param_sync(request)
            index += 1
            self.schedule["is_skip_requested"] = False

        if self.schedule["state"] != "stopped":
            self.schedule["state"] = "complete"
        self.schedule["current_item_id"] = ""
        self.schedule["item_number"] = 0
        self.logger.info("Scheduler finished.")
        self.play_sound(82)
        if issue_shutdown:
            time.sleep(20)
            self.send_message_param_sync({"method": "pi_shutdown"})

    def stop_scheduler(self, params={}):
        if (
            "schedule_id" in params
            and self.schedule["schedule_id"] != params["schedule_id"]
        ):
            return self.json_result(
                "stop_scheduler",
                0,
                f"Schedule with id {params['schedule_id']} did not match this device's schedule. Returned with no action.",
            )

        if self.schedule["state"] == "working":
            self.schedule["state"] = "stopping"
            self.stop_slew()
            self.stop_stack()
            self.play_sound(83)
            self.schedule["state"] = "stopped"
            self.schedule["is_stacking"] = False
            return self.json_result(
                "stop_scheduler", 0, "Scheduler stopped successfully."
            )

        elif self.schedule["state"] == "complete":
            return self.json_result(
                "stop_scheduler", -4, "scheduler has already in complete state"
            )
        elif self.schedule["state"] == "stopped":
            return self.json_result(
                "stop_scheduler", -3, "Scheduler is not running while trying to stop!"
            )
        else:
            return self.json_result(
                "stop_scheduler",
                -5,
                f"scheduler is in unaccounted for state: {self.schedule['state']}",
            )

    def mark_op_state(self, in_op_name, state="stopped"):
        self.event_state[in_op_name] = {"state": state}

    def wait_end_op(self, in_op_name):
        self.logger.info(f"Waiting for {in_op_name} to finish.")
        if in_op_name == "goto_target":
            self.mark_goto_status_as_start()
            while self.is_goto():
                time.sleep(1)
            result = self.is_goto_completed_ok()
        else:
            # self.event_state[in_op_name] = {"state":"stopped"}
            while in_op_name not in self.event_state or (
                self.event_state[in_op_name]["state"] != "complete"
                and self.event_state[in_op_name]["state"] != "fail"
            ):
                time.sleep(1)
            result = self.event_state[in_op_name]["state"] == "complete"

        self.logger.info(f"Finished waiting for {in_op_name}. Result: {result}")
        return result

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
        if dec_string[0] == "-":
            sign = -1
            dec_string = dec_string[1:]
        else:
            sign = 1
        degrees, minutes, seconds = map(float, dec_string.split(":"))

        # Convert to decimal degrees
        dec_decimal = sign * degrees + minutes / 60 + seconds / 3600

        return dec_decimal

    def guest_mode_init(self):
        self.logger.info("guest_mode_init")
        if self.firmware_ver_int > 2300:
            # Indiscriminately try to grab the master cli
            self.send_message_param_sync(
                {
                    "method": "set_setting",
                    "params": {"master_cli": Config.init_guest_mode},
                }
            )
            # Set the cli name to the hostname of the machine
            host = socket.gethostname()
            if not host:
                host = "SSC"
            self.send_message_param_sync(
                {"method": "set_setting", "params": {"cli_name": f"{host}"}}
            )

    def event_callbacks_init(self, initial_state):
        self.logger.info(f"event_callback_init({self}, {initial_state})")
        self.event_callbacks: list[EventCallback] = [
            BatteryWatch(self, initial_state),
            # SensorTempWatch(self, initial_state)
        ]

        # read files in user_triggers subdir, and read json
        user_hooks = []
        for filename in os.listdir("user_hooks"):
            if filename.endswith(".conf") or filename.endswith(".hcon"):
                filepath = os.path.join("user_hooks", filename)
                try:
                    user_hooks.append(ConfigFactory.parse_file(filepath))
                except Exception:
                    self.logger.warn(
                        "Unable to decode user_hooks/{filename} - parsing error"
                    )
        for hook in user_hooks:
            if "events" in hook and "execute" in hook:
                self.event_callbacks.append(UserScriptEvent(self, initial_state, hook))

    def start_watch_thread(self):
        # only bail if is_watch_events is true
        if self.is_watch_events:
            return
        else:
            self.is_watch_events = True

            for i in range(3, 0, -1):
                if self.reconnect():
                    self.logger.info(f"{self.device_name} Connected")
                    break
                else:
                    self.logger.info(
                        f"{self.device_name} Connection Failed, is Seestar turned on?"
                    )
                    time.sleep(1)
            else:
                self.logger.info(
                    f"{self.device_name}: Could not establish connection to Seestar. Starting in offline mode"
                )

            try:
                # Start up heartbeat and receive threads

                self.get_msg_thread = threading.Thread(
                    target=self.receive_message_thread_fn, daemon=True
                )
                self.get_msg_thread.name = f"IncomingMsgThread:{self.device_name}"
                self.get_msg_thread.start()

                self.heartbeat_msg_thread = threading.Thread(
                    target=self.heartbeat_message_thread_fn, daemon=True
                )
                self.heartbeat_msg_thread.name = (
                    f"HeartbeatMsgThread:{self.device_name}"
                )
                # self.heartbeat_msg_thread.start()

                initial_state = self.send_message_param_sync(
                    {"method": "get_device_state"}
                )
                # move start of heartbeat thread to here to avoid error with simulator
                self.heartbeat_msg_thread.start()

                self.guest_mode_init()
                self.event_callbacks_init(initial_state["result"])

            except Exception:
                # todo : Disconnect socket and set is_watch_events false
                # print(f"XXXX Exception {ex}")
                pass

    def end_watch_thread(self):
        # I think it should be is_watch_events instead of is_connected...
        if self.is_connected:
            self.logger.info("End watch thread!")
            self.is_watch_events = False
            self.get_msg_thread.join(timeout=7)
            self.heartbeat_msg_thread.join(timeout=7)
            self.s.close()
            self.is_connected = False

    def get_events(self):
        while True:
            try:
                if len(self.event_queue) == 0:
                    time.sleep(0.1)
                    continue
                event = self.event_queue.popleft()
                try:
                    del event["Timestamp"]  # Safety first...
                except Exception:
                    pass
                # print(f"Fetched event {self.device_name}")
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]
                frame = (
                    b"data: <pre>"
                    + ts.encode("utf-8")
                    + b": "
                    + json.dumps(event).encode("utf-8")
                    + b"</pre>\n\n"
                )
                event_name = pydash.get(event, "Event")
                match event_name:
                    case "FocuserMove":
                        frame += (
                            b"event: focusMove\ndata: "
                            + str(event["position"]).encode("utf-8")
                            + b"\n\n"
                        )
                    case "PiStatus":
                        if "temp" in event:
                            frame += (
                                b"event: temp\ndata: "
                                + str(event["temp"]).encode("utf-8")
                                + b"\n\n"
                            )
                        if "battery_capacity" in event:
                            frame += (
                                b"event: battery_capacity\ndata: "
                                + str(event["battery_capacity"]).encode("utf-8")
                                + b"\n\n"
                            )
                    case "AviRecord":
                        avi_state = event.get("state", "cancel")
                        frame += (
                            b"event: video_record_status\ndata: "
                            + avi_state.encode("utf-8")
                            + b"\n\n"
                        )

                print(f"Event: {event_name}: {event}")

                yield frame
            except GeneratorExit:
                break
            except:
                time.sleep(1)
