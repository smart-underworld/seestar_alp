import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from device.config import Config  # type: ignore
from front_v2.device_client import check_api_state, do_action, method_sync

router = APIRouter(prefix="/api/v1")


class LiveModeRequest(BaseModel):
    mode: str  # star | sun | moon | planet | scenery | none


class FocusRequest(BaseModel):
    inc: int  # relative step e.g. -50, -10, +10, +50


class ExposureRequest(BaseModel):
    exp_ms: int


class GainRequest(BaseModel):
    gain: int


class MoveRequest(BaseModel):
    angle: float = 0
    distance: float = 0
    force: float = 0


def _require_connected(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")


@router.post("/devices/{dev_num}/live/mode")
def start_live_mode(dev_num: int, body: LiveModeRequest):
    _require_connected(dev_num)
    if body.mode == "none":
        # stop view
        do_action("method_async", dev_num, {"method": "iscope_stop_view"})
        return {"status": "ok", "mode": "none"}
    result = do_action(
        "method_async",
        dev_num,
        {"method": "iscope_start_view", "params": {"mode": body.mode}},
    )
    return {"status": "ok", "mode": body.mode, "result": result}


@router.delete("/devices/{dev_num}/live/mode")
def stop_live_mode(dev_num: int):
    _require_connected(dev_num)
    do_action("method_async", dev_num, {"method": "iscope_stop_view"})
    return {"status": "ok"}


@router.get("/devices/{dev_num}/live/focus")
def get_focus(dev_num: int):
    _require_connected(dev_num)
    pos = method_sync("get_focuser_position", dev_num)
    return {"position": pos}


@router.post("/devices/{dev_num}/live/focus")
def move_focus(dev_num: int, body: FocusRequest):
    _require_connected(dev_num)
    current = method_sync("get_focuser_position", dev_num) or 0
    new_pos = int(current) + body.inc
    result = do_action(
        "method_sync",
        dev_num,
        {"method": "move_focuser", "params": {"step": new_pos, "ret_step": True}},
    )
    import pydash

    pos = pydash.get(result, "Value.result.step", new_pos)
    return {"position": pos}


@router.post("/devices/{dev_num}/live/auto-focus")
def auto_focus(dev_num: int):
    _require_connected(dev_num)
    do_action("method_async", dev_num, {"method": "start_auto_focus"})
    return {"status": "ok"}


@router.get("/devices/{dev_num}/live/exposure")
def get_exposure(dev_num: int):
    _require_connected(dev_num)
    result = method_sync("get_setting", dev_num) or {}
    exp_ms = result.get("exp_ms_continuous") or result.get("exp_ms_stack_l") or 10000
    gain = result.get("gain", 80)
    return {"exp_ms": exp_ms, "gain": gain}


@router.post("/devices/{dev_num}/live/exposure")
def set_exposure(dev_num: int, body: ExposureRequest):
    _require_connected(dev_num)
    do_action("set_setting", dev_num, {"exp_ms_continuous": body.exp_ms})
    return {"status": "ok", "exp_ms": body.exp_ms}


@router.post("/devices/{dev_num}/live/gain")
def set_gain(dev_num: int, body: GainRequest):
    _require_connected(dev_num)
    do_action("set_setting", dev_num, {"gain": body.gain})
    return {"status": "ok", "gain": body.gain}


@router.post("/devices/{dev_num}/live/move")
def move_telescope(dev_num: int, body: MoveRequest):
    _require_connected(dev_num)
    if body.distance == 0:
        do_action(
            "method_sync",
            dev_num,
            {
                "method": "scope_speed_move",
                "params": {"speed": 0, "angle": 0, "dur_sec": 3},
            },
        )
        return {"status": "ok", "speed": 0, "angle": 0}
    # distance arrives normalised 0–1 from the Svelte joystick; classic nipplejs
    # sent raw pixels (0–100), so multiply by 100 to restore the same speed range.
    speed = min(body.distance * 100 * 14.4 * body.force, 1440.0)
    do_action(
        "method_sync",
        dev_num,
        {
            "method": "scope_speed_move",
            "params": {"speed": speed, "angle": int(body.angle), "dur_sec": 3},
        },
    )
    return {"status": "ok", "speed": speed, "angle": int(body.angle)}


@router.get("/devices/{dev_num}/vid")
async def proxy_vid(dev_num: int):
    """Proxy the MJPEG stream from the imaging server through the FastAPI app.

    The imaging server (root_app.py / waitress) binds to Config.ip_address
    (default 127.0.0.1), so browsers accessing via a network hostname can't
    reach it directly.  This endpoint proxies the stream so the SPA only needs
    to reach the FastAPI port.
    """
    imgport = getattr(Config, "imgport", 7556)
    upstream = f"http://127.0.0.1:{imgport}/{dev_num}/vid"

    async def _stream():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", upstream) as resp:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        yield chunk
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            return

    return StreamingResponse(
        _stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/devices/{dev_num}/live/record")
def toggle_record(dev_num: int):
    _require_connected(dev_num)
    do_action(
        "method_async",
        dev_num,
        {"method": "iscope_start_stack", "params": {"restart": True}},
    )
    return {"status": "ok"}
