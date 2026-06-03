"""
Thin async-friendly client for the local Alpaca device server.

Mirrors the helpers in front/app.py (do_action_device, method_sync,
get_device_state, get_device_settings) without importing that 5 000-line
module.  All calls are synchronous HTTP to localhost — same as classic.
"""

import json
import logging
from typing import Any

import pydash
import requests

from device.config import Config  # type: ignore

logger = logging.getLogger(__name__)


def _base_url() -> str:
    host = Config.ip_address if Config.ip_address != "0.0.0.0" else "127.0.0.1"
    return f"http://{host}:{Config.port}"


def _imgport_url() -> str:
    host = Config.ip_address if Config.ip_address != "0.0.0.0" else "127.0.0.1"
    return f"http://{host}:{Config.imgport}"


def check_api_state(dev_num: int) -> bool:
    url = f"{_base_url()}/api/v1/telescope/{dev_num}/connected?ClientID=1&ClientTransactionID=999"
    try:
        r = requests.get(url, timeout=2)
        return r.json().get("Value", False)
    except Exception:
        return False


def do_action(action: str, dev_num: int, parameters: dict) -> dict | None:
    url = f"{_base_url()}/api/v1/telescope/{dev_num}/action"
    payload = {
        "Action": action,
        "Parameters": json.dumps(parameters),
        "ClientID": 1,
        "ClientTransactionID": 999,
    }
    try:
        r = requests.put(url, json=payload, timeout=Config.timeout)
        return r.json()
    except Exception as exc:
        logger.error("do_action %s dev=%d: %s", action, dev_num, exc)
        return None


def method_sync(method: str, dev_num: int, **kwargs) -> Any:
    out = do_action("method_sync", dev_num, {"method": method, **kwargs})
    if not out:
        return None
    value = out.get("Value")
    if not value:
        return None
    # Unwrap single-key federation wrapper if present.
    if isinstance(value, dict) and "result" not in value and "error" not in value and len(value) == 1:
        inner = next(iter(value.values()))
        if isinstance(inner, dict):
            value = inner
    if value.get("error"):
        logger.warning("method_sync %s: %s", method, value["error"])
        return {"command": method, "status": "error", "result": value["error"]}
    return value.get("result")


def get_device_state(dev_num: int) -> dict:
    """Return a normalised status dict matching DeviceStatus schema."""
    if not check_api_state(dev_num):
        return {"device_num": dev_num, "is_connected": False}

    result = method_sync("get_device_state", dev_num)
    status = method_sync("get_view_state", dev_num)

    view_state = pydash.get(status, "View.state", "Idle")
    mode = pydash.get(status, "View.mode", "")
    stage = pydash.get(status, "View.stage", "")
    target = pydash.get(status, "View.target_name", "")

    stack_state = pydash.get(status, "View.Stack.state")
    stacked = pydash.get(status, "View.Stack.stacked_frame", "") if stack_state == "working" else ""
    failed = pydash.get(status, "View.Stack.dropped_frame", "") if stack_state == "working" else ""

    free_storage = "Unknown"
    mount_mode = "Unknown"
    battery_capacity = None
    temp = None
    ra = None
    dec = None
    schedule = None

    if result:
        eq_mode = pydash.get(result, "mount.equ_mode", False)
        mount_mode = "Equatorial" if eq_mode else "Alt Azimuth"
        storage = pydash.get(result, "storage")
        if isinstance(storage, list) and storage:
            free_mb = pydash.get(storage[0], "storage_free_mb", 0)
            total_mb = pydash.get(storage[0], "storage_total_mb", 1)
            free_storage = f"{free_mb / 1024:.1f} GB / {total_mb / 1024:.1f} GB"
        battery_capacity = pydash.get(result, "pi_status.battery_capacity")
        temp = pydash.get(result, "pi_status.temp")
        ra = pydash.get(result, "mount.ra_j2000")
        dec = pydash.get(result, "mount.dec_j2000")

    schedule_raw = do_action("get_schedule", dev_num, {})
    if schedule_raw:
        schedule = pydash.get(schedule_raw, "Value.result")

    return {
        "device_num": dev_num,
        "is_connected": True,
        "view_state": view_state,
        "mode": mode,
        "stage": stage,
        "target": target,
        "stacked": stacked,
        "failed": failed,
        "mount_mode": mount_mode,
        "free_storage": free_storage,
        "battery_capacity": battery_capacity,
        "temp": temp,
        "ra": ra,
        "dec": dec,
        "schedule": schedule,
    }


def get_device_settings(dev_num: int) -> dict:
    """
    Return merged settings dict.  Supports both get_setting and get_stack_setting
    read paths per AGENTS.md compatibility requirement.
    """
    settings_result = method_sync("get_setting", dev_num) or {}
    stack_settings_result = method_sync("get_stack_setting", dev_num) or {}

    stack_settings_error = (
        not isinstance(stack_settings_result, dict)
        or "error" in stack_settings_result
    )

    merged_stack = {}
    stack_from_get_setting = pydash.get(settings_result, "stack", {})
    if isinstance(stack_from_get_setting, dict):
        merged_stack.update(stack_from_get_setting)
    if not stack_settings_error and isinstance(stack_settings_result, dict):
        merged_stack.update(stack_settings_result)

    return {
        "raw": settings_result,
        "stack": merged_stack,
        "merged": {**settings_result, **merged_stack},
    }


def save_device_settings(dev_num: int, payload: dict) -> dict | None:
    """
    Save settings using all three save variants per AGENTS.md.
    payload is the flat settings dict from the request body.
    """
    stack_keys = {
        k for k in payload
        if k.startswith("stack_") or k in ("exp_ms_stack_l", "exp_ms_continuous")
    }
    stack_payload = {k: payload[k] for k in stack_keys if k in payload}
    base_payload = {k: v for k, v in payload.items() if k not in stack_keys}

    results = {}
    if base_payload:
        results["set_setting"] = do_action("set_setting", dev_num, base_payload)
    if stack_payload:
        results["set_stack_setting"] = do_action("set_stack_setting", dev_num, stack_payload)
        results["set_stack_settings"] = do_action(
            "set_stack_settings", dev_num, {"stack": stack_payload}
        )
    return results


def get_device_list() -> list[dict]:
    """Return all configured seestars with their connection state."""
    devices = []
    for seestar in Config.seestars:
        dev_num = seestar["device_num"]
        connected = check_api_state(dev_num)
        devices.append({
            "device_num": dev_num,
            "name": seestar.get("name", f"Seestar {dev_num}"),
            "ip_address": seestar.get("ip_address", ""),
            "is_connected": connected,
        })
    return devices
