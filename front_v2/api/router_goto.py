from fastapi import APIRouter, HTTPException

from front_v2.device_client import check_api_state, do_action, method_sync
from front_v2.schemas.models import GotoRequest

router = APIRouter(prefix="/api/v1")


@router.post("/devices/{dev_num}/goto")
def goto_target(dev_num: int, body: GotoRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")

    params = {
        "ra": body.ra,
        "dec": body.dec,
        "target_name": body.target_name,
        "is_j2000": body.is_j2000,
    }
    result = do_action("scope_goto", dev_num, params)
    if result is None:
        raise HTTPException(status_code=502, detail="Goto command failed")
    return result


@router.delete("/devices/{dev_num}/goto")
def cancel_goto(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("stop_goto", dev_num, {})
    return result or {"status": "ok"}


@router.get("/devices/{dev_num}/search")
def search_object(dev_num: int, q: str):
    result = method_sync("search_object", dev_num, query=q)
    return {"query": q, "result": result}
