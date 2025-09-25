import threading
import uuid
from typing import Any

from seestar_device import Schedule
from seestar_util import Util
import json
import random
import collections
from json import JSONEncoder


class DequeEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, collections.deque):
            return list(obj)
        return JSONEncoder.default(self, obj)


class Seestar_Federation:
    def __new__(cls, *args, **kwargs):
        # print("Create a new instance of Seestar.")
        return super().__new__(cls)

    # <ip_address> <port> <device name> <device num>
    def __init__(self, logger, seestar_devices):
        logger.info("Initialize the new instance of Seestar federation")
        self.is_connected = True
        self.logger = logger
        self.seestar_devices = seestar_devices
        self.schedule: Schedule = {
            "version": 1.0,
            "list": collections.deque(),
            "state": "stopped",
            "schedule_id": str(uuid.uuid4()),
        }

        self.job_queue: Schedule = {
            "version": 1.0,
            "list": collections.deque(),
            "state": "stopped",
            "schedule_id": str(uuid.uuid4()),
        }

    def disconnect(self) -> None:
        return

    def reconnect(self) -> bool:
        return True

    def get_event_state(self, params: dict | None = None):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].get_event_state(params)
        return result

    def send_message_param_sync(self, data):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].send_message_param_sync(data)
        return result

    def goto_target(self, params):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].goto_target(params)
        return result

    def stop_goto_target(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = result[key] = self.seestar_devices[key].stop_goto_target()
        return result

    def is_goto(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = result[key] = self.seestar_devices[key].is_goto()
        return result

    def is_goto_completed_ok(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = result[key] = self.seestar_devices[
                    key
                ].is_goto_completed_ok()
        return result

    def set_below_horizon_dec_offset(self, offset):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].set_below_horizon_dec_offset(
                    offset
                )
        return result

    def stop_slew(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].stop_slew()
        return result

    # {"method":"scope_speed_move","params":{"speed":4000,"angle":270,"dur_sec":10}}
    def move_scope(self, in_angle, in_speed, in_dur=3):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].move_scope(
                    in_angle, in_speed, in_dur
                )
        return result

    def try_auto_focus(self, try_count):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                af_thread = threading.Thread(
                    target=lambda: self.seestar_devices[key].try_auto_focus(try_count)
                )
                af_thread.start()
                result[key] = "Auto focus started"
        return result

    def stop_stack(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].stop_stack()
        return result

    def play_sound(self, in_sound_id: int):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].play_sound(in_sound_id)
        return result

    def start_stack(self, params={"gain": 80, "restart": True}):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].start_stack(params)
        return result

    def action_set_dew_heater(self, params):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].action_set_dew_heater(params)
        return result

    def action_set_exposure(self, params):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].action_set_exposure(params)
        return result

    def action_start_up_sequence(self, params):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].action_start_up_sequence(params)
        return result

    def get_schedule(self, params):
        if "schedule_id" in params:
            if self.schedule["schedule_id"] == params["schedule_id"]:
                result = self.schedule.copy()
            else:
                result = {}
        else:
            result = self.schedule.copy()
        result["device"] = {}
        availiable_device_list = []

        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected and cur_device.is_client_master():
                device_schedule = cur_device.get_schedule(params)
                if "state" not in device_schedule:
                    continue
                if (
                    device_schedule["state"] == "stopped"
                    or device_schedule["state"] == "complete"
                ):
                    availiable_device_list.append(key)
                result["device"][key] = device_schedule
        result["available_device_list"] = availiable_device_list
        result["comment"] = "Test comment"
        return result

    def create_schedule(self, params):
        self.schedule = {
            "list": collections.deque(),
            "state": "stopped",
            "schedule_id": str(uuid.uuid4()),
        }
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
                    self.logger.warn(
                        "Failed. Must specify an proper coordinate for a federated schedule."
                    )
                    raise Exception(
                        "Failed. Must specify an proper coordinate for a federated schedule."
                    )
                    # mosaic_params["ra"] = self.ra
                    # mosaic_params["dec"] = self.dec
                    # mosaic_params["is_j2000"] = False
                mosaic_params["ra"] = round(mosaic_params["ra"], 4)
                mosaic_params["dec"] = round(mosaic_params["dec"], 4)
        item["schedule_item_id"] = str(uuid.uuid4())
        return item

    def add_schedule_item(self, params: dict[str, Any]) -> Schedule:
        new_item = self.construct_schedule_item(params)
        self.schedule["list"].append(new_item)
        return self.schedule
        ###
        item = params.copy()
        if item["action"] == "start_mosaic":
            mosaic_params = item["params"]
            if isinstance(mosaic_params["ra"], str):
                # try to trim the seconds to 1 decimal
                mosaic_params["ra"] = Util.trim_seconds(mosaic_params["ra"])
                mosaic_params["dec"] = Util.trim_seconds(mosaic_params["dec"])
            elif isinstance(mosaic_params["ra"], float):
                if mosaic_params["ra"] < 0:
                    self.logger.warn(
                        "Failed. Must specify an proper coordinate for a federated schedule."
                    )
                    raise Exception(
                        "Failed. Must specify an proper coordinate for a federated schedule."
                    )
                mosaic_params["ra"] = round(mosaic_params["ra"], 4)
                mosaic_params["dec"] = round(mosaic_params["dec"], 4)
        item["schedule_item_id"] = str(uuid.uuid4())
        self.schedule["list"].append(item)
        return self.schedule

    ###

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

        if not is_retain_state:
            self.schedule["schedule_id"] = str(uuid.uuid4())
            for item in self.schedule["list"]:
                item["schedule_item_id"] = str(uuid.uuid4())
            self.schedule["state"] = "stopped"
        return self.schedule

    # cur_params['selected_panels'] cur_params['ra_num'], cur_params['dec_num']
    # split selected panels into multiple sections. Given num_devices > 1 and num ra and dec is > 1
    def get_section_array_for_mosaic(self, device_id_list, params):
        num_devices = len(device_id_list)
        if num_devices == 0:
            raise Exception("there is no active device connected!")

        if "selected_panels" in params and params["selected_panels"] != "":
            panel_array = params["selected_panels"].split(";")
            num_panels = len(panel_array)
        else:
            num_panels = params["dec_num"] * params["ra_num"]
            panel_array = [""] * num_panels
            index = 0
            ra_num = params["ra_num"]
            dec_num = params["dec_num"]
            for n_dec in range(dec_num):
                for n_ra in range(ra_num):
                    panel_array[index] = f"{chr(n_ra+ord("A"))}{n_dec + 1}"
                    index += 1

        start_index = 0

        num_panels_per_device = int(num_panels / num_devices)
        result = {}
        for i in device_id_list:
            end_index = start_index + num_panels_per_device
            selected_panels = ";".join(panel_array[start_index:end_index])
            if len(selected_panels) > 0:
                result[i] = selected_panels
            start_index = end_index
        # take care of the reminder of the selected panels
        for i in device_id_list:
            if start_index >= num_panels:
                break
            result[i] = f"{result[i]};{panel_array[start_index]}"
            start_index += 1

        return result

    # shortcut to start a new scheduler with only a mosaic request
    def start_mosaic(self, cur_params):
        cur_schedule = self.get_schedule(cur_params)
        num_devices = len(cur_schedule["available_device_list"])
        if num_devices < 1:
            return {
                "error": "Failed: No available devices found to execute a schedule."
            }

        self.schedule = {
            "list": [],
            "state": "stopped",
            "schedule_id": str(uuid.uuid4()),
        }
        schedule_item = {"action": "start_mosaic", "params": cur_params}
        self.add_schedule_item(schedule_item)
        return self.start_scheduler(cur_params)

    def start_scheduler(self, params):
        if len(self.schedule["list"]) == 0:
            return {"error": "Failed: The schedule is empty."}

        root_schedule = self.get_schedule(params)
        available_devices = root_schedule["available_device_list"]
        random.shuffle(available_devices)

        if "max_devices" in params:
            available_devices = available_devices[: params["max_devices"]]

        num_devices = len(available_devices)
        if num_devices < 1:
            return {
                "error": "Failed: No available devices found to execute a schedule."
            }

        for key in available_devices:
            cur_device = self.seestar_devices[key]
            cur_device.create_schedule(params)

        for schedule_item in self.schedule["list"]:
            if "params" not in schedule_item:
                cur_params = {}
            else:
                cur_params = schedule_item["params"].copy()

            if schedule_item["action"] == "start_mosaic":
                # federation_mode : duplicate, by_panel or by_time
                if "federation_mode" not in cur_params:
                    cur_params["federation_mode"] = "duplicate"
                elif cur_params["federation_mode"] == "by_time":
                    cur_params["panel_time_sec"] = round(
                        cur_params["panel_time_sec"] / num_devices
                    )

                if cur_params["federation_mode"] == "by_panel":
                    section_dict = self.get_section_array_for_mosaic(
                        available_devices, cur_params
                    )
                    self.logger.info(f"federation mode split ->  {section_dict}")

                for key in available_devices:
                    cur_device = self.seestar_devices[key]
                    new_item = {}
                    new_item["action"] = "start_mosaic"
                    new_item["params"] = cur_params.copy()
                    if (
                        cur_params["federation_mode"] == "by_panel"
                        and key in section_dict
                    ):
                        new_item["params"]["selected_panels"] = section_dict[key]
                        self.logger.info(
                            f"federation mode by panels ->   key: {key}; panel: {new_item['params']['selected_panels']}"
                        )
                    cur_device.add_schedule_item(new_item)
            else:
                for key in available_devices:
                    cur_device = self.seestar_devices[key]
                    new_item = {}
                    new_item["action"] = schedule_item["action"]
                    cur_params = schedule_item["params"].copy()
                    new_item["params"] = cur_params
                    cur_device.add_schedule_item(new_item)

        for key in available_devices:
            cur_device = self.seestar_devices[key]
            cur_device.start_scheduler(params)

        return self.get_schedule(params)

    def stop_scheduler(self, params: dict):
        result = {}
        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected:
                result[key] = cur_device.stop_scheduler(params)
        return result
    
### start of federated job queue implementation

    def construct_schedule_sublist(self, params):
        result = []
        item = params.copy()
        if item["action"] == "start_mosaic":
            mosaic_params = item["params"]
            if isinstance(mosaic_params["ra"], str):
                # try to trim the seconds to 1 decimal
                mosaic_params["ra"] = Util.trim_seconds(mosaic_params["ra"])
                mosaic_params["dec"] = Util.trim_seconds(mosaic_params["dec"])
            elif isinstance(mosaic_params["ra"], float):
                if mosaic_params["ra"] < 0:
                    self.logger.warn(
                        "Failed. Must specify an proper coordinate for a federated schedule."
                    )
                    raise Exception(
                        "Failed. Must specify an proper coordinate for a federated schedule."
                    )
                    # mosaic_params["ra"] = self.ra
                    # mosaic_params["dec"] = self.dec
                    # mosaic_params["is_j2000"] = False
                mosaic_params["ra"] = round(mosaic_params["ra"], 4)
                mosaic_params["dec"] = round(mosaic_params["dec"], 4)

            max_devices = mosaic_params.get("max_devices", 1)
            if isinstance(max_devices, str):
                max_devices = int(max_devices)
            if max_devices < 1:
                max_devices = 1
            

            # federation_mode : duplicate, by_panel or by_time
            federation_mode = mosaic_params.get("federation_mode", "duplicate")
            del mosaic_params["federation_mode"]
            del mosaic_params["max_devices"]
            
            if federation_mode == 'duplicate':
                for count in range(max_devices):
                    new_item = item.copy()
                    new_item["schedule_item_id"] = str(uuid.uuid4())
                    result.append(new_item)

            elif federation_mode == "by_time":
                mosaic_params["panel_time_sec"] = round(
                    mosaic_params["panel_time_sec"] / max_devices
                )
                for count in range(max_devices):
                    new_item = item.copy()
                    new_item["schedule_item_id"] = str(uuid.uuid4())
                    result.append(new_item)

            elif federation_mode == "by_panel":
                tmp_device_id_list = [i+1 for i in range(max_devices)]
                section_dict = self.get_section_array_for_mosaic(
                    tmp_device_id_list, mosaic_params
                )
                self.logger.info(f"federation mode split ->  {section_dict}")

                for key in section_dict:
                    new_item = item.copy()
                    new_item["params"] = mosaic_params.copy()
                    new_item["params"]["selected_panels"] = section_dict[key]
                    new_item["schedule_item_id"] = str(uuid.uuid4())
                    result.append(new_item)
                    self.logger.info(
                        f"federation mode by panels ->   key: {key}; panel: {new_item['params']['selected_panels']}"
                    )
        else:
            self.logger.warn("Federated schedule will only support mosaic action.")
        return result

    def job_queue_append_to(self, params: dict[str, Any]) -> Schedule:
        new_list=self.construct_schedule_sublist(params)
        self.job_queue["list"].extend(new_list)
        return self.job_queue

    def job_queue_insert_before(self, params):
        targeted_item_id = params["before_id"]
        index = 0
        while index < len(self.job_queue["list"]):
            item = self.job_queue["list"][index]
            item_id = item.get("schedule_item_id", "UNKNOWN")
            if item_id == targeted_item_id:
                new_list = self.construct_schedule_sublist(params)
                new_index = index
                for new_item in new_list:
                    self.job_queue["list"].insert(new_index, new_item)

                break
            index += 1
        return self.job_queue

    def job_queue_get(self, params):
        if "schedule_id" in params:
            if self.job_queue["schedule_id"] == params["schedule_id"]:
                result = self.job_queue.copy()
            else:
                result = {}
        else:
            result = self.job_queue.copy()
        result["comment"] = "Test comment"
        return result
    
    def job_queue_get_next(self):
        if len(self.job_queue["list"]) == 0:
            return None
        
        next_item = self.job_queue["list"].popleft()
        return next_item
    
    def job_queue_has_next(self):
        return len(self.job_queue["list"]) > 0
    
