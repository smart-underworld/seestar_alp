import io
import os
import platform
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from device.config import Config  # type: ignore

router = APIRouter(prefix="/api/v1")


def _build_bundle(
    description: str, dev_num: int, include_seestar_logs: bool
) -> io.BytesIO:
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zf:
        # Problem description supplied by the user
        zf.writestr("problem_description.txt", description)

        # SSC log files
        cwd = Path(os.getcwd())
        log_prefix = getattr(Config, "log_prefix", "") or ""
        pfx = cwd.joinpath(log_prefix) if log_prefix else cwd
        for f in pfx.glob("alpyca.log*"):
            try:
                zf.writestr(f.name, f.read_bytes())
            except Exception:
                pass

        # config.toml
        cfg_path = cwd / "device" / "config.toml"
        if not cfg_path.exists():
            cfg_path = cwd / "config.toml"
        if cfg_path.exists():
            try:
                zf.writestr("config.toml", cfg_path.read_bytes())
            except Exception:
                pass

        # OS info
        zf.writestr("OS_name.txt", platform.system())
        zf.writestr("platform_info.txt", platform.platform())

        # Python version
        py = shutil.which("python") or shutil.which("python3")
        if py:
            try:
                out = subprocess.check_output(
                    [py, "--version"], stderr=subprocess.STDOUT
                )
                zf.writestr("python_version.txt", out)
            except Exception:
                pass

        # pip freeze
        pip = shutil.which("pip") or shutil.which("pip3")
        if pip:
            try:
                out = subprocess.check_output([pip, "freeze"], stderr=subprocess.STDOUT)
                zf.writestr("pip_freeze.txt", out)
            except Exception:
                pass

        # systemd journals (Linux only)
        if platform.system() == "Linux":
            for unit in ("seestar", "INDI"):
                try:
                    out = subprocess.check_output(
                        ["journalctl", "-b", "-u", unit],
                        stderr=subprocess.DEVNULL,
                    )
                    zf.writestr(f"{unit}_journal.txt", out)
                except Exception:
                    pass

        # Environment variables
        env_content = "\n".join(f"{k}={v}" for k, v in os.environ.items())
        zf.writestr("env.txt", env_content)

        # Seestar device logs (optional)
        if include_seestar_logs:
            try:
                from device import telescope  # type: ignore  # noqa: PLC0415

                if dev_num in telescope.seestar_logcollector:
                    collector = telescope.get_seestar_logcollector(dev_num)
                    zip_data = collector.get_logs_sync()
                    zf.writestr(f"seestar_{dev_num}_logs.zip", zip_data)
            except Exception:
                pass

    zip_buffer.seek(0)
    return zip_buffer


@router.post("/support-bundle")
def generate_support_bundle(body: dict[str, Any] = Body(...)):
    description = (
        str(body.get("description", "")).strip() or "(no description provided)"
    )
    dev_num = int(body.get("dev_num", 1))
    include_seestar_logs = bool(body.get("include_seestar_logs", False))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"seestar_alp_support_{timestamp}.zip"

    zip_buffer = _build_bundle(description, dev_num, include_seestar_logs)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
