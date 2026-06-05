from fastapi import APIRouter, HTTPException

from front_v2.device_client import check_api_state, do_action, method_sync
from front_v2.schemas.models import GuestModeState

router = APIRouter(prefix="/api/v1")


@router.get("/devices/{dev_num}/guestmode", response_model=GuestModeState)
def get_guestmode(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")

    raw = method_sync("get_device_state", dev_num) or {}
    device = raw.get("device", {})
    fw = device.get("firmware_ver_int", 0)

    guest_mode = False
    is_master = True
    master_index = -1
    client_list: list = []

    if fw >= 2300:
        settings = raw.get("setting", {})
        guest_mode = settings.get("guest_mode", False) if fw >= 2400 else True
        if guest_mode:
            client = raw.get("client", {})
            is_master = client.get("is_master", True)
            master_index = client.get("master_index", -1)
            client_list = client.get("connected", [])

    return GuestModeState(
        firmware_ver_int=fw,
        guest_mode=guest_mode,
        client_master=is_master,
        master_index=master_index,
        client_list=client_list,
    )


@router.post("/devices/{dev_num}/guestmode/grab")
def grab_control(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("set_setting", dev_num, {"master_cli": True})
    return result or {"status": "ok"}


@router.post("/devices/{dev_num}/guestmode/release")
def release_control(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("set_setting", dev_num, {"master_cli": False})
    return result or {"status": "ok"}
