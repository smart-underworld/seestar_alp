import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Any

from front_v2.device_client import check_api_state, do_action

# Shared with the classic front: schedule/*.json files on the server
_SCHEDULE_DIR = Path(__file__).parent.parent.parent / "schedule"


def _safe_path(filename: str) -> Path:
    """Return a validated path inside _SCHEDULE_DIR; raise on traversal or bad extension."""
    name = Path(filename).name
    if not name or not name.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Filename must end in .json")
    return _SCHEDULE_DIR / name


router = APIRouter(prefix="/api/v1")


@router.get("/devices/{dev_num}/schedule")
def get_schedule(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("get_schedule", dev_num, {})
    if result and "Value" in result:
        return result["Value"]
    return result or {}


class ScheduleItemRequest(BaseModel):
    action: str
    params: Any = None  # dict for most actions; list for set_wheel_position


@router.post("/devices/{dev_num}/schedule/item")
def add_schedule_item(dev_num: int, body: ScheduleItemRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action(
        "add_schedule_item",
        dev_num,
        {
            "action": body.action,
            "params": body.params if body.params is not None else {},
        },
    )
    return result or {}


class InsertItemRequest(BaseModel):
    action: str
    params: Any = None  # dict for most actions; list for set_wheel_position
    before_id: str


@router.post("/devices/{dev_num}/schedule/item/insert")
def insert_schedule_item(dev_num: int, body: InsertItemRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action(
        "insert_schedule_item_before",
        dev_num,
        {
            "action": body.action,
            "params": body.params if body.params is not None else {},
            "before_id": body.before_id,
        },
    )
    return result or {}


@router.delete("/devices/{dev_num}/schedule")
def clear_schedule(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("create_schedule", dev_num, {})
    return result or {"status": "ok"}


@router.delete("/devices/{dev_num}/schedule/item/{item_id}")
def delete_schedule_item(dev_num: int, item_id: str):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("remove_schedule_item", dev_num, {"schedule_item_id": item_id})
    return result or {"status": "ok"}


@router.get("/devices/{dev_num}/schedule/export")
def export_schedule(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        do_action("export_schedule", dev_num, {"filepath": tmp_path})
        with open(tmp_path, "r") as f:
            content = f.read()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=schedule.json"},
    )


@router.post("/devices/{dev_num}/schedule/import")
async def import_schedule(dev_num: int, request: Request):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    content = await request.body()
    # Validate it's parseable JSON before writing
    try:
        json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="wb") as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        result = do_action(
            "import_schedule", dev_num, {"filepath": tmp_path, "is_retain_state": False}
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return result or {"status": "ok"}


@router.post("/devices/{dev_num}/schedule/state")
def toggle_schedule(dev_num: int, state: str):
    """state: 'start' | 'stop' | 'pause'"""
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    action_map = {
        "start": "start_scheduler",
        "stop": "stop_scheduler",
        "pause": "pause_scheduler",
    }
    action = action_map.get(state, f"schedule_{state}")
    result = do_action(action, dev_num, {})
    return result or {"status": "ok"}


# ---- Server-side schedule library ----------------------------------------
# Files are stored in schedule/ at the repo root, shared with the classic front.


@router.get("/schedules/library")
def list_schedule_library():
    """List .json schedule files saved on the server."""
    _SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [
            {"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime}
            for f in _SCHEDULE_DIR.glob("*.json")
        ],
        key=lambda x: x["modified"],
        reverse=True,
    )
    return {"files": files}


@router.post("/schedules/library")
async def save_schedule_library(request: Request, filename: str):
    """Save a schedule JSON body to a named file on the server."""
    path = _safe_path(filename)
    _SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    content = await request.body()
    try:
        json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    path.write_bytes(content)
    return {"filename": path.name}


@router.get("/schedules/library/{filename}")
def get_schedule_library(filename: str):
    """Return the raw JSON content of a saved schedule file."""
    path = _safe_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Schedule file not found")
    return Response(
        content=path.read_text(encoding="utf-8"), media_type="application/json"
    )


@router.delete("/schedules/library/{filename}")
def delete_schedule_library(filename: str):
    """Delete a named schedule file from the server."""
    path = _safe_path(filename)
    if path.exists():
        path.unlink()
    return {"status": "ok"}
