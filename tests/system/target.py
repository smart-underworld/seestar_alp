"""Target selection, precondition checks, and scratch config.toml generation
for the tests/system/ suite (drives seestar_alp against a real Seestar or the
QEMU sandbox from seestar-api-research)."""

import socket
from dataclasses import dataclass
from pathlib import Path

import tomlkit


class PreconditionError(RuntimeError):
    """Raised when the target isn't ready to be driven, with an actionable message."""


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def probe_tcp_port(host: str, port: int, label: str, timeout: float = 3.0) -> None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        raise PreconditionError(
            f"Cannot reach {label} at {host}:{port} ({exc}). Is the sandbox/device "
            f"running and are ports forwarded?"
        ) from exc


def check_sandbox_renderer_fresh(shared_dir: Path) -> None:
    """Verify the synthetic-sky renderer has produced output at least once.

    Only checks existence, not recency: sim.renderd re-renders solve.fits
    only in response to a pointing change (it watches pointing.json's `seq`
    field), so an idle-but-running renderer can leave a solve.fits that's
    hours old with no pointing activity to trigger a fresh render. A stale
    file is not evidence the renderer is down — only a missing file is.
    Actual renderer liveness during a run is proven by the goto/3PPA test
    itself succeeding (or timing out with a clear failure otherwise).
    """
    solve_fits = Path(shared_dir) / "solve.fits"
    if not solve_fits.exists():
        raise PreconditionError(
            f"{solve_fits} does not exist. Goto/3PPA against the sandbox is "
            f"closed-loop and needs the synthetic-sky renderer running on the "
            f"host first:\n"
            f"  python3 -m sim.renderd --shared {shared_dir} --model S50 "
            f"--catalog sim/data/stars.npy\n"
            f"(run from the seestar-api-research/sandbox checkout)"
        )


@dataclass
class SystemTestTarget:
    kind: str  # "sandbox" | "real"
    host: str
    pem_path: str
    goto_target_name: str
    goto_ra: str
    goto_dec: str
    capture_duration_s: int
    renderer_shared_dir: Path | None


def build_config_toml(
    target: SystemTestTarget,
    frontend: str,
    uiport: int,
    imgport: int,
    alpaca_port: int,
) -> str:
    doc = tomlkit.document()
    doc["title"] = "seestar_alp system test scratch config"

    doc["network"] = {
        "ip_address": "127.0.0.1",
        "port": alpaca_port,
        "imgport": imgport,
        "stport": 8090,
        "sthost": "localhost",
        "rtsp_udp": False,
    }
    doc["webui_settings"] = {
        "uiport": uiport,
        "uitheme": "dark",
        "confirm": False,
        "frontend": frontend,
    }
    doc["server"] = {
        "location": "System test",
        "verbose_driver_exceptions": True,
    }
    doc["seestar_initialization"] = {
        "save_good_frames": False,
        "save_all_frames": False,
        "lat": 37.12,
        "long": -123.45,
        "gain": 80,
        "exposure_length_preview_ms": 500,
        "exposure_length_stack_ms": 10000,
        "dither_enabled": True,
        "dither_length_pixel": 50,
        "dither_frequency": 10,
        "activate_LP_filter": False,
        "dew_heater_power": 0,
        "guest_mode_init": True,
        "battery_low_limit": 3,
        "dec_pos_index": 3,
        "is_frame_calibrated": True,
        "interop_pem": str(target.pem_path),
    }
    doc["logging"] = {
        "log_level": "INFO",
        "log_prefix": "",
        "log_to_stdout": False,
        "max_size_mb": 5,
        "num_keep_logs": 3,
        "log_events_in_info": True,
    }
    doc["seestars"] = [
        {
            "name": "SystemTestScope",
            "ip_address": target.host,
            "device_num": 1,
        }
    ]
    return tomlkit.dumps(doc)
