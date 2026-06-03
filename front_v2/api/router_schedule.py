from fastapi import APIRouter, HTTPException
from typing import Any

from front_v2.device_client import check_api_state, do_action

router = APIRouter(prefix="/api/v1")


@router.get("/devices/{dev_num}/schedule")
def get_schedule(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("get_schedule", dev_num, {})
    return result or {}


@router.post("/devices/{dev_num}/schedule/item")
def add_schedule_item(dev_num: int, action: str, params: dict[str, Any] = {}):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("add_schedule_item", dev_num, {"action": action, "params": params})
    return result or {}


@router.delete("/devices/{dev_num}/schedule")
def clear_schedule(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("clear_schedule", dev_num, {})
    return result or {"status": "ok"}


@router.delete("/devices/{dev_num}/schedule/item/{item_id}")
def delete_schedule_item(dev_num: int, item_id: str):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("delete_schedule_item", dev_num, {"id": item_id})
    return result or {"status": "ok"}


@router.post("/devices/{dev_num}/schedule/state")
def toggle_schedule(dev_num: int, state: str):
    """state: 'start' | 'stop' | 'pause'"""
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action(f"schedule_{state}", dev_num, {})
    return result or {"status": "ok"}
