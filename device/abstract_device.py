from abc import ABC, abstractmethod
from typing import Any, TypedDict


class StartStackParams(TypedDict):
    """Start stack parameters"""
    gain: int
    restart: bool


class AbstractDevice(ABC):
    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def reconnect(self):
        pass

    @abstractmethod
    def get_event_state(self, params=None):
        pass

    @abstractmethod
    def send_message_param_sync(self, data: dict[str, Any]):
        pass

    @abstractmethod
    def goto_target(self, params):
        pass

    @abstractmethod
    def stop_goto_target(self):
        pass

    @abstractmethod
    def is_goto(self):
        pass

    @abstractmethod
    def is_goto_completed_ok(self):
        pass

    @abstractmethod
    def set_below_horizon_dec_offset(self, offset: float, target_dec: float):
        pass

    @abstractmethod
    def stop_slew(self):
        pass

    @abstractmethod
    def move_scope(self, in_angle: float, in_speed: float, in_dur: int = 3):
        pass

    @abstractmethod
    def try_auto_focus(self, try_count: int):
        pass

    @abstractmethod
    def stop_stack(self):
        pass

    @abstractmethod
    def play_sound(self, in_sound_id: int):
        pass

    @abstractmethod
    def start_stack(self, params: StartStackParams):
        pass

    @abstractmethod
    def action_set_dew_heater(self, params):
        pass

    @abstractmethod
    def action_start_up_sequence(self, params):
        pass

    @abstractmethod
    def get_schedule(self, params):
        pass

    @abstractmethod
    def create_schedule(self, params):
        pass

    @abstractmethod
    def add_schedule_item(self, params):
        pass

    @abstractmethod
    def get_section_array_for_mosaic(self, device_id_list, params):
        pass

    @abstractmethod
    def start_mosaic(self, cur_params):
        pass

    @abstractmethod
    def start_scheduler(self, params):
        pass

    @abstractmethod
    def stop_scheduler(self, params):
        pass

    # new types
    def is_connected(self) -> bool:
        pass

    def send_message_param(self, params):
        pass

    def start_spectra(self, params):
        pass

    def insert_schedule_item_before(self, params):
        pass

    def replace_schedule_item(self, params):
        pass

    def remove_schedule_item(self, params):
        pass

    def get_last_image(self, params):
        pass

    def adjust_mag_declination(self, params):
        pass

    def start_watch_thread(self):
        pass

    def end_watch_thread(self):
        pass

    def site_elevation(self):
        pass

    def site_latitude(self):
        pass

    def site_longitude(self):
        pass

    def is_slewing(self):
        pass

    def dec(self):
        pass

    def ra(self):
        pass

    def target_dec(self) -> float:
        pass

    def target_ra(self) -> float:
        pass

    def utcdate(self):
        pass

    def sync_target_dec(self, params):
        pass
