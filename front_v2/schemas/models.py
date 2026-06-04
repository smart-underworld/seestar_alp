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


class WsMessage(BaseModel):
    type: str
    payload: Any
