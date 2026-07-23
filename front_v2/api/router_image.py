from fastapi import APIRouter, HTTPException

from front_v2.device_client import check_api_state, do_action
from front_v2.schemas.models import ImageRequest

router = APIRouter(prefix="/api/v1")


@router.post("/devices/{dev_num}/image/start")
def start_imaging(dev_num: int, body: ImageRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")

    params = {
        "exp_ms": body.exp_ms,
        "gain": body.gain,
        "count": body.count,
        "restart": True,
    }
    if body.ra and body.dec:
        params["ra"] = body.ra
        params["dec"] = body.dec
    if body.target_name:
        params["target_name"] = body.target_name

    result = do_action("start_stack", dev_num, params)
    if result is None or result.get("ErrorNumber", 0) != 0:
        detail = (result or {}).get("ErrorMessage") or "Start imaging failed"
        raise HTTPException(status_code=502, detail=detail)
    return result


@router.post("/devices/{dev_num}/image/stop")
def stop_imaging(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("stop_stack", dev_num, {})
    return result or {"status": "ok"}


@router.get("/devices/{dev_num}/image/status")
def image_status(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("get_view_state", dev_num, {})
    return result or {}
