from typing import Any
from pydantic import BaseModel


class DeviceInfo(BaseModel):
    device_num: int
    name: str
    ip_address: str
    is_connected: bool


class DeviceStatus(BaseModel):
    device_num: int
    is_connected: bool
    backend_ready: bool = True
    view_state: str = ""
    mode: str = ""
    stage: str = ""
    target: str = ""
    stacked: Any = ""
    failed: Any = ""
    mount_mode: str = "Unknown"
    free_storage: str = "Unknown"
    wifi_signal: str = ""
    battery_capacity: Any = None
    temp: Any = None
    ra: Any = None
    dec: Any = None
    schedule: Any = None
    firmware_ver: str = ""
    focal_position: Any = None
    auto_power_off: bool = False
    heater_enable: bool = False
    balance_angle: Any = None
    compass_direction: Any = None
    charge_status: str = ""
    battery_temp: Any = None
    is_master: bool = True
    connected_clients: list = []
    schedule_state: str = ""


class CommandRequest(BaseModel):
    method: str
    params: dict[str, Any] = {}


class CommandResponse(BaseModel):
    command: str
    status: str
    result: Any = None


class SettingsSaveRequest(BaseModel):
    # Accepts the full flat settings payload that classic front/app.py POSTs.
    # All fields are optional so partial saves are supported.
    payload: dict[str, Any]


class GotoRequest(BaseModel):
    ra: str
    dec: str
    target_name: str = ""
    is_j2000: bool = True


class ImageRequest(BaseModel):
    ra: str | None = None
    dec: str | None = None
    target_name: str = ""
    exp_ms: int = 10000
    gain: int = 80
    count: int = 0


class MosaicRequest(BaseModel):
    target_name: str
    ra: str
    dec: str
    is_j2000: bool = True
    ra_num: int = 1
    dec_num: int = 1
    panel_overlap_percent: int = 10
    panel_time_sec: int = 3600
    gain: int = 80
    is_use_lp_filter: bool = False
    is_use_autofocus: bool = False
    num_tries: int = 1
    retry_wait_s: int = 300
    stack_type: str = "DeepSky"
    federation_mode: str | None = None
    max_devices: int | None = None


class GuestModeState(BaseModel):
    firmware_ver_int: int = 0
    guest_mode: bool = False
    client_master: bool = True
    master_index: int = -1
    client_list: list = []


class WsMessage(BaseModel):
    type: str
    payload: Any
