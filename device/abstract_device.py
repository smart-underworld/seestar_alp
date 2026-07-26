import collections
from abc import ABC, abstractmethod
from typing import Any, TypedDict, NotRequired, Literal


class StartStackParams(TypedDict):
    """Start stack parameters"""

    gain: int
    restart: bool


class MessageParams(TypedDict):
    """Message parameter"""

    id: NotRequired[int]
    method: str
    params: NotRequired[dict[str, Any] | list[Any]]
    result: NotRequired[str]


ScheduleState = Literal["working", "stopped", "stopping", "paused", "complete"]


class Schedule(TypedDict):
    version: float
    Event: str
    schedule_id: str
    list: collections.deque
    state: str
    is_stacking_paused: bool
    is_stacking: bool
    is_skip_requested: bool
    current_item_id: str
    item_number: int


class AbstractDevice(ABC):
    @abstractmethod
    def get_name(self) -> str:
        pass

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
    def reset_scheduler_cur_item(self, params=None):
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
    def start_spectra(self, params):
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
    def action_set_exposure(self, params):
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
    def insert_schedule_item_before(self, params):
        pass

    @abstractmethod
    def replace_schedule_item(self, params):
        pass

    @abstractmethod
    def remove_schedule_item(self, params):
        pass

    # @abstractmethod
    # def get_section_array_for_mosaic(self, device_id_list, params):
    #     pass

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
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @property
    @abstractmethod
    def ra(self):
        pass

    @property
    @abstractmethod
    def dec(self):
        pass

    @abstractmethod
    def send_message_param(self, params):
        pass

    @abstractmethod
    def start_watch_thread(self):
        pass

    @abstractmethod
    def end_watch_thread(self):
        pass

    @abstractmethod
    def get_events(self):
        # this is only used in some places...
        pass
