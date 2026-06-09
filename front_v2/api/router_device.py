from typing import Any

from fastapi import APIRouter, Body, HTTPException

from front_v2.device_client import (
    check_api_state,
    do_action,
    get_device_list,
    get_device_state,
    method_sync,
)
from front_v2.schemas.models import CommandRequest, CommandResponse

router = APIRouter(prefix="/api/v1")


@router.get("/devices")
def list_devices():
    return get_device_list()


@router.get("/devices/{dev_num}/status")
def device_status(dev_num: int):
    return get_device_state(dev_num)


@router.get("/devices/{dev_num}/connected")
def device_connected(dev_num: int):
    return {"device_num": dev_num, "connected": check_api_state(dev_num)}


@router.post("/devices/{dev_num}/command", response_model=CommandResponse)
def send_command(dev_num: int, body: CommandRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    # UI-level aliases that require translation to firmware methods/params.
    if body.method == "set_eq_mode":
        result = method_sync("scope_park", dev_num, params={"equ_mode": True})
    elif body.method == "set_alt_az_mode":
        result = method_sync("scope_park", dev_num, params={"equ_mode": False})
    elif body.method == "set_wheel_position_LP":
        result = method_sync("set_wheel_position", dev_num, params=[2])
    elif body.method == "set_wheel_position_IR_Cut":
        result = method_sync("set_wheel_position", dev_num, params=[1])
    elif body.method == "set_wheel_position_Dark":
        result = method_sync("set_wheel_position", dev_num, params=[0])
    # Firmware spells autofocus with a trailing 'e' — normalise both directions.
    elif body.method == "start_auto_focus":
        result = method_sync("start_auto_focuse", dev_num)
    elif body.method == "stop_auto_focus":
        result = method_sync("stop_auto_focuse", dev_num)
    # get_last_focuser_position is an alias — firmware only has get_focuser_position.
    elif body.method == "get_last_focuser_position":
        result = method_sync("get_focuser_position", dev_num)
    # grab/release control set the master_cli flag via set_setting.
    elif body.method == "grab_control":
        result = method_sync("set_setting", dev_num, params={"master_cli": True})
    elif body.method == "release_control":
        result = method_sync("set_setting", dev_num, params={"master_cli": False})
    # get_event_state is assembled by the Python device layer, not the firmware —
    # must use do_action, not method_sync (which would send it to firmware).
    elif body.method == "get_event_state":
        raw = do_action("get_event_state", dev_num, {})
        result = raw.get("Value") if isinstance(raw, dict) else raw
    # get_disk_volume is unreliable as a direct firmware method_sync; extract
    # storage from get_device_state which is always available.
    elif body.method == "get_disk_volume":
        raw = method_sync("get_device_state", dev_num)
        result = raw.get("storage") if isinstance(raw, dict) else raw
    else:
        result = method_sync(body.method, dev_num, **body.params)
    return CommandResponse(command=body.method, status="success", result=result)


@router.get("/devices/{dev_num}/position")
def device_position(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = method_sync("get_device_state", dev_num)
    return {
        "ra": result.get("mount", {}).get("ra_j2000")
        if isinstance(result, dict)
        else None,
        "dec": result.get("mount", {}).get("dec_j2000")
        if isinstance(result, dict)
        else None,
    }


@router.post("/devices/{dev_num}/startup")
def run_startup(dev_num: int, params: dict[str, Any] = Body(default={})):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("action_start_up_sequence", dev_num, params)
    return result or {}


@router.get("/devices/{dev_num}/balance-sensor")
def get_balance_sensor(dev_num: int):
    result = method_sync("get_device_state", dev_num)
    data = (result or {}).get("balance_sensor", {}).get("data", {})
    return {"x": data.get("x"), "y": data.get("y")}


@router.get("/devices/{dev_num}/events")
def get_events(dev_num: int):
    raw = do_action("get_event_state", dev_num, {})
    if not raw or "Value" not in raw:
        return {}
    value = raw["Value"]
    if not isinstance(value, dict):
        return {}
    # Single-device format: {"result": {"3PPA": {...}, ...}}
    if "result" in value and isinstance(value["result"], dict):
        return value["result"]
    # Multi-device format: {"devId": {"result": {...}}, ...}
    merged: dict = {}
    for dev_info in value.values():
        if isinstance(dev_info, dict) and isinstance(dev_info.get("result"), dict):
            merged.update(dev_info["result"])
    return merged


@router.post("/devices/{dev_num}/pa-refine")
def pa_refine(dev_num: int, body: dict[str, Any] = Body(default={})):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    action = body.get("action")
    if action == "start":
        result = do_action("start_plate_solve_loop", dev_num, {})
        value = result.get("Value", {}) if result else {}
        return value
    elif action == "stop":
        result = do_action("stop_plate_solve_loop", dev_num, {})
        value = result.get("Value", {}) if result else {}
        return value
    elif action == "data":
        result = do_action("get_pa_error", dev_num, {})
        if not result:
            raise HTTPException(status_code=502, detail="No data from device")
        value = result.get("Value", {})
        return {
            "error_az": value.get("pa_error_az", 0.0),
            "error_alt": value.get("pa_error_alt", 0.0),
        }
    raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


@router.post("/devices/{dev_num}/action")
def raw_action(dev_num: int, action: str, parameters: dict = {}):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action(action, dev_num, parameters)
    if result is None:
        raise HTTPException(status_code=502, detail="Device action failed")
    return result
