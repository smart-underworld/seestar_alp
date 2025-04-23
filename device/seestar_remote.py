import json

import requests

from device.abstract_device import AbstractDevice
from device.config import Config


class SeestarRemote(AbstractDevice):
    def __init__(
        self,
        logger,
        host: str,
        port: int,
        device_name: str,
        device_num: int,
        location: str,
        remote_offset: int,
        is_debug=False,
    ):
        logger.info(
            f"Initialize the new remote instance of Seestar: {host}:{port}, name:{device_name}, num:{device_num}, location:{location}, is_debug:{is_debug}"
        )
        # api_ip_address?
        # img_port?  todo : make this dynamic
        # port: int,
        # device_num: int,
        # location: str,
        # remote_id: int) -> SeestarRemote:  # type: ignore

        self.logger = logger
        self.host = host
        self.port = port
        self.device_name = device_name
        self.device_num = device_num
        self.location = location
        self.remote_offset = remote_offset
        self.remote_id = device_num - remote_offset
        self.is_debug = is_debug

        self.base_url = (
            f"http://{self.host}:{self.port}/api/v1/telescope/{self.remote_id}"
        )
        self.events_url = (
            f"http://{self.host}:7556/{self.remote_id}/events"  # TODO : fix the port!
        )

    def get_name(self):
        return self.device_name

    def disconnect(self):
        # xxx is this even necessary?
        self.logger.info("Disconnect the remote instance")

    def reconnect(self):
        # xxx is this even necessary?
        self.logger.info("Reconnect the remote instance")

    def get_event_state(self, params=None):
        return self._do_action_device("get_event_state", params)

    def send_message_param_sync(self, data):
        return self._do_action_device("method_sync", data)

    def goto_target(self, params):
        self.logger.info(f"Goto target the remote instance {params=}")
        return self._do_action_device("goto_target", params)

    def stop_goto_target(self):
        return self._do_action_device("stop_goto_target", {})

    def start_spectra(self, params):
        return self._do_action_device("start_spectra", params)

    def is_goto(self):
        return self._do_action_device("is_goto", {})

    @property
    def is_connected(self) -> bool:
        return self._is_remote_connected()

    @property
    def ra(self) -> float:
        return -1000.0

    @property
    def dec(self) -> float:
        return -1000.0

    def get_events(self):
        r = requests.get(self.events_url, stream=True)
        for line in r.iter_lines():
            yield line + b"\n"

    def is_goto_completed_ok(self):
        return self._do_action_device("is_goto_completed_ok", {})

    def set_below_horizon_dec_offset(self, offset):
        # XXX hmm....
        pass

    def stop_slew(self):
        return self.put_remote("abortslew", {})

    def move_scope(self, in_angle, in_speed, in_dur=3):
        # note: duration is ignored for now...
        return self.put_remote(
            "moveaxis",
            {
                "Axis": in_angle,
                "Rate": in_speed,
            },
        )

    def try_auto_focus(self, try_count):
        # TODO: make this an action. Ask others...
        pass

    def stop_stack(self):
        # TODO: hoist into common code?
        self.logger.info("%s: stop stacking...", self.device_name)
        data = {}
        data["method"] = "iscope_stop_view"
        params = {}
        params["stage"] = "Stack"
        data["params"] = params
        return self.send_message_param_sync(data)

    def play_sound(self, in_sound_id: int):
        return self._do_action_device("play_sound", {"id": in_sound_id})

    def start_stack(self, params={"gain": 80, "restart": True}):
        # TODO: method could be hoisted into abstract device
        self.logger.info("Start stack")
        stack_gain = params["gain"]
        result = self.send_message_param_sync(
            {"method": "iscope_start_stack", "params": {"restart": params["restart"]}}
        )
        self.logger.info(result)
        result = self.send_message_param_sync(
            {"method": "set_control_value", "params": ["gain", stack_gain]}
        )
        self.logger.info(result)
        return "error" not in result

    def action_set_dew_heater(self, params):
        return self._do_action_device("action_set_dew_heater", params)

    def action_set_exposure(self, params):
        return self._do_action_device("action_set_exposure", params)

    def action_start_up_sequence(self, params):
        return self._do_action_device("action_start_up_sequence", params)

    def get_schedule(self, params):
        return self._do_action_device("get_schedule", params)

    def create_schedule(self, params):
        return self._do_action_device("create_schedule", params)

    def add_schedule_item(self, params):
        return self._do_action_device("add_schedule_item", params)

    def insert_schedule_item_before(self, params):
        return self._do_action_device("insert_schedule_item_before", params)

    def replace_schedule_item(self, params):
        return self._do_action_device("replace_schedule_item", params)

    def remove_schedule_item(self, params):
        return self._do_action_device("remote_schedule_item", params)

    def start_mosaic(self, cur_params):
        return self._do_action_device("start_mosaic", cur_params)

    def start_scheduler(self, params):
        return self._do_action_device("start_scheduler", params)

    def stop_scheduler(self, params):
        return self._do_action_device("stop_scheduler", params)

    def send_message_param(self, params):
        return self._do_action_device("method_async", params)

    def end_watch_thread(self):
        return self.put_remote(
            "connected",
            {
                "Connected": False,
            },
        )

    def start_watch_thread(self):
        return self.put_remote(
            "connected",
            {
                "Connected": True,
            },
        )

    def put_remote(self, path: str, payload: dict):
        telescope_id = self.device_num
        url = f"{self.base_url}/{path}"
        try:
            r = requests.put(
                url,
                data={
                    "ClientID": 1,
                    "ClientTransactionID": 999,
                    **payload,
                },
                timeout=Config.timeout,
            )
            r.raise_for_status()
            response = r.json()
            return response
        except requests.exceptions.ConnectionError:
            self.logger.warn(
                f"Telescope {telescope_id} API is not online. (ConnectionError) {url=}"
            )
            return None
        except requests.exceptions.RequestException:
            self.logger.warn(
                f"Telescope {telescope_id} API is not online. (RequestException) {url=}"
            )
            return None

    def get_remote(self, path: str):
        telescope_id = self.device_num
        url = f"{self.base_url}/{path}"
        try:
            r = requests.get(url, timeout=Config.timeout)
            r.raise_for_status()
            response = r.json()
            # xxx : does this need to unwrap value?
            return response
        except requests.exceptions.ConnectionError:
            self.logger.warn(
                f"Telescope {telescope_id} API is not online. (ConnectionError) {url=}"
            )
            return None
        except requests.exceptions.RequestException:
            self.logger.warn(
                f"Telescope {telescope_id} API is not online. (RequestException) {url=}"
            )
            return None

    def _is_remote_connected(self):
        telescope_id = self.device_num
        response = self.get_remote("connected?ClientID=1&ClientTransactionID=999")
        if response:
            if response.get("ErrorNumber") == 1031 or not response.get("Value"):
                self.logger.warn(f"Telescope {telescope_id} API is not connected.")
                return False
            else:
                self.logger.debug(f"Telescope {telescope_id} API is online.")
                return True
        else:
            return False

    def _do_action_device(self, action: str, parameters):
        url = f"{self.base_url}/action"
        payload = {
            "Action": action,
            "Parameters": json.dumps(parameters),
            "ClientID": 1,
            "ClientTransactionID": 999,
        }
        if self._is_remote_connected():
            try:
                r = requests.put(url, json=payload, timeout=Config.timeout)
                out = r.json()
                return out.get("Value", {})  # todo : handle errors better!
            except Exception as e:
                self.logger.error(
                    f"do_action_device: Failed to send action to device {self.device_num}: {e}: message={payload}"
                )
