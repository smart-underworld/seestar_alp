
import os
import json
from fastapi import APIRouter
from fastapi.responses import JSONResponse, HTMLResponse

router = APIRouter()
STEP_COUNT_FILE = "data/step_count.json"

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# Load or initialize step state
def load_step_data():
    if os.path.exists(STEP_COUNT_FILE):
        with open(STEP_COUNT_FILE) as f:
            return json.load(f)
    return {"count": 0, "persist": False}

def save_step_data(data):
    with open(STEP_COUNT_FILE, "w") as f:
        json.dump(data, f)

@router.post("/api/step_tracking/add/{steps}")
async def add_steps(steps: int):
    data = load_step_data()
    data["count"] += steps
    if data.get("persist", False):
        save_step_data(data)
    return JSONResponse(data)

@router.get("/api/step_tracking/current")
async def current_steps():
    data = load_step_data()
    return HTMLResponse(f"<div class='alert alert-info'>Current steps: {data['count']}</div>")

@router.post("/api/step_tracking/reset")
async def reset_steps():
    data = load_step_data()
    data["count"] = 0
    save_step_data(data)
    return HTMLResponse("<div class='alert alert-warning'>Step count reset.</div>")

@router.post("/api/step_tracking/toggle_persistence")
async def toggle_persistence():
    data = load_step_data()
    data["persist"] = not data.get("persist", False)
    save_step_data(data)
    status = "enabled" if data["persist"] else "disabled"
    return HTMLResponse(f"<div class='alert alert-success'>Persistence {status}.</div>")
