from fastapi import APIRouter, HTTPException

from front_v2.device_client import check_api_state, do_action
from front_v2.schemas.models import MosaicRequest

router = APIRouter(prefix="/api/v1")


@router.post("/devices/{dev_num}/mosaic/start")
def start_mosaic(dev_num: int, body: MosaicRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")

    params: dict = {
        "target_name": body.target_name,
        "ra": body.ra,
        "dec": body.dec,
        "is_j2000": body.is_j2000,
        "ra_num": body.ra_num,
        "dec_num": body.dec_num,
        "panel_overlap_percent": body.panel_overlap_percent,
        "panel_time_sec": body.panel_time_sec,
        "gain": body.gain,
        "is_use_lp_filter": body.is_use_lp_filter,
        "is_use_autofocus": body.is_use_autofocus,
        "num_tries": body.num_tries,
        "retry_wait_s": body.retry_wait_s,
        "stack_type": body.stack_type,
    }

    if body.end_local_time:
        params["end_local_time"] = body.end_local_time
    if body.federation_mode is not None:
        params["federation_mode"] = body.federation_mode
    if body.max_devices is not None:
        params["max_devices"] = body.max_devices

    result = do_action("start_mosaic", dev_num, params)
    if result is None:
        raise HTTPException(status_code=502, detail="Start mosaic failed")
    return result
