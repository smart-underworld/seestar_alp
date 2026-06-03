from fastapi import APIRouter, HTTPException

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
    result = method_sync(body.method, dev_num, **body.params)
    return CommandResponse(command=body.method, status="success", result=result)


@router.get("/devices/{dev_num}/position")
def device_position(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = method_sync("get_device_state", dev_num)
    return {
        "ra": result.get("mount", {}).get("ra_j2000") if isinstance(result, dict) else None,
        "dec": result.get("mount", {}).get("dec_j2000") if isinstance(result, dict) else None,
    }


@router.post("/devices/{dev_num}/action")
def raw_action(dev_num: int, action: str, parameters: dict = {}):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action(action, dev_num, parameters)
    if result is None:
        raise HTTPException(status_code=502, detail="Device action failed")
    return result
