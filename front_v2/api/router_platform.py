import os
import platform
import subprocess
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1")


def _detect_platform() -> str:
    plat = platform.system()
    if plat != "Linux":
        return plat

    try:
        with open("/proc/cpuinfo") as cpuinfo_file:
            cpuinfo = cpuinfo_file.read()
            if "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo:
                return "raspberry_pi"
    except FileNotFoundError:
        pass

    if os.path.exists("/sys/firmware/devicetree/base/model"):
        try:
            with open("/sys/firmware/devicetree/base/model") as model_file:
                if "raspberry pi" in model_file.read().lower():
                    return "raspberry_pi"
        except FileNotFoundError:
            pass

    return plat


_PLATFORM = _detect_platform()

_COMMANDS: dict[str, tuple[list[str], str]] = {
    "restart_alp": (
        ["sudo", "systemctl", "restart", "seestar.service"],
        "SSC/Alp service restarting.",
    ),
    "restart_indi": (
        ["sudo", "systemctl", "restart", "INDI.service"],
        "INDI service restarting.",
    ),
    "reboot_rpi": (["sudo", "reboot"], "System rebooting."),
    "shutdown_rpi": (["sudo", "shutdown", "-h", "now"], "System shutting down."),
}


def _background_run(args: list[str]):
    time.sleep(2)
    subprocess.run(args, capture_output=False, text=True)


class PlatformActionRequest(BaseModel):
    command: str


@router.get("/platform")
def get_platform():
    return {"platform": _PLATFORM}


@router.post("/platform/action")
def run_platform_action(body: PlatformActionRequest):
    if _PLATFORM != "raspberry_pi":
        raise HTTPException(status_code=403, detail="Not available on this platform")

    entry = _COMMANDS.get(body.command)
    if entry is None:
        raise HTTPException(status_code=400, detail=f"Unknown command: {body.command}")

    args, message = entry
    threading.Thread(target=lambda: _background_run(args)).start()
    return {"status": "ok", "message": message}
