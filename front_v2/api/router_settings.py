from fastapi import APIRouter, HTTPException

from front_v2.device_client import check_api_state, get_device_settings, save_device_settings
from front_v2.schemas.models import SettingsSaveRequest

router = APIRouter(prefix="/api/v1")


@router.get("/devices/{dev_num}/settings")
def read_settings(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    return get_device_settings(dev_num)


@router.post("/devices/{dev_num}/settings")
def write_settings(dev_num: int, body: SettingsSaveRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    results = save_device_settings(dev_num, body.payload)
    return {"status": "ok", "results": results}
