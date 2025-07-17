import os
import json
import csv
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from calibration import run_calibration

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.post("/api/run_calibration", response_class=HTMLResponse)
async def api_run_calibration(request: Request):
    data = await request.form()

    try:
        move_angle = float(data.get("move_angle", 1.0))
        wait_time = float(data.get("wait_time", 1.0))
        max_retries = int(data.get("max_retries", 2))
    except (ValueError, TypeError):
        return HTMLResponse("<div class='alert alert-danger'>Invalid input parameters.</div>", status_code=400)

    result = run_calibration(move_angle, wait_time, max_retries)

    # Save result to JSON
    os.makedirs("data", exist_ok=True)
    with open("data/calibration_results.json", "w") as f:
        json.dump(result, f, indent=2)

    # Save result to CSV
    with open("data/calibration_results.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Axis", "Steps per Arcsecond"])
        writer.writerow(["RA", result['result']['steps_per_arcsecond_RA']])
        writer.writerow(["DEC", result['result']['steps_per_arcsecond_DEC']])
        writer.writerow(["Average", result['result']['avg_steps_per_arcsecond']])

    return templates.TemplateResponse("calibration_result_partial.html", {
        "request": request,
        "steps": result.get("steps"),
        "result": result.get("result")
    })

@router.get("/download/calibration_results.json")
async def download_json():
    path = "data/calibration_results.json"
    if os.path.exists(path):
        return FileResponse(path, filename="calibration_results.json", media_type="application/json")
    return HTMLResponse("<div class='alert alert-warning'>No JSON file found.</div>", status_code=404)

@router.get("/download/calibration_results.csv")
async def download_csv():
    path = "data/calibration_results.csv"
    if os.path.exists(path):
        return FileResponse(path, filename="calibration_results.csv", media_type="text/csv")
    return HTMLResponse("<div class='alert alert-warning'>No CSV file found.</div>", status_code=404)

@router.delete("/clear/calibration_results")
async def clear_calibration():
    removed = False
    for ext in ["json", "csv"]:
        path = f"data/calibration_results.{ext}"
        if os.path.exists(path):
            os.remove(path)
            removed = True
    if removed:
        return HTMLResponse("<div class='alert alert-success'>Calibration results cleared.</div>")
    return HTMLResponse("<div class='alert alert-info'>No calibration files to delete.</div>", status_code=404)
