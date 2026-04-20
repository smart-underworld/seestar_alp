"""Auto-level: fit tripod tilt + sensor offset from rotated balance-sensor samples.

The balance sensor is fixed to the rotating OTA, so a single reading conflates
the sensor's calibration offset (body frame) with the tripod's tilt (world
frame). Rotating through azimuth θ traces a sinusoid in sensor (x, y); a
joint least-squares fit cleanly decomposes the two.

Physical model (body frame: sensor +y is 90° CCW from sensor +x):
    x(θ) = A·cos(θ − φ) + x₀ =  a·cos(θ) + b·sin(θ) + x₀
    y(θ) = A·sin(θ − φ) + y₀ =  a·sin(θ) − b·cos(θ) + y₀
with a = A·cos(φ), b = A·sin(φ).

We solve the stacked system [[cos θ_i,  sin θ_i, 1, 0], ...
                             [sin θ_i, -cos θ_i, 0, 1], ...] · [a, b, x₀, y₀]
against the 2N measurement vector [x_i..., y_i...]. Then A = hypot(a, b)
and φ = atan2(b, a).

Tilt magnitude in degrees uses small-angle physics: with the accelerometer
reading ~1 g_sensor_unit when level, hypot(raw_x, raw_y)/z ≈ sin(tilt) ≈ tilt
in radians. So tilt_deg = degrees(A / mean(z)).

`tilt_mount_az_deg` is the body-frame azimuth where the sensor's +x axis
projects maximally onto the tilt vector. Converting that to a world-frame
compass bearing ("uphill direction") requires one installation-dependent
sign choice — see `apply_sign_flip`.

Azimuth convention: all commanded and reported azimuths are in the
half-open interval [-180°, +180°) — -180 is included, +180 wraps to -180.
0° = North, +90° = East, ±180° = South, -90° = West.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np


@dataclass
class AutoLevelSample:
    azimuth_deg: float
    sensor_x: float
    sensor_y: float
    sensor_z: float | None = None
    angle: float | None = None


@dataclass
class AxisFit:
    amplitude: float
    phase_deg: float
    offset: float
    rms_residual: float


@dataclass
class AutoLevelFit:
    amplitude: float
    """Tilt magnitude in sensor units (gravity-normalized; ~1.0 at 57.3° tilt)."""

    tilt_mount_az_deg: float
    """Mount-frame azimuth of the body-frame tilt vector (φ = atan2(b, a)).

    Reported in [-180°, +180°) — -180 inclusive, +180 wraps to -180.
    This is the azimuth at which sensor +x aligns with the tilt projection.
    It is unambiguous but NOT the world-frame uphill bearing — that requires
    an installation-dependent sign choice (see `apply_sign_flip`).
    """

    x_offset: float
    y_offset: float
    """Sensor calibration offsets — what the sensor reads when perfectly level."""

    mean_z: float
    """Mean sensor z used for the small-angle scale factor. 1.0 if z was not recorded."""

    tilt_deg: float
    """Tilt magnitude in degrees, from degrees(A / mean_z)."""

    rms_residual: float
    n_samples: int
    x_axis: AxisFit = field(repr=False)
    y_axis: AxisFit = field(repr=False)
    uphill_world_az_deg: float | None = None
    """Only populated after `apply_sign_flip` is called with a stored sign."""


def _wrap_pm180(deg: float) -> float:
    """Wrap an angle in degrees to [-180, 180): -180 inclusive, +180 exclusive."""
    return ((deg + 180.0) % 360.0) - 180.0


def _fit_axis(theta_rad: np.ndarray, values: np.ndarray) -> AxisFit:
    """Diagnostic single-axis fit: v(θ) = a·cos(θ) + b·sin(θ) + c."""
    n = len(values)
    design = np.column_stack([np.cos(theta_rad), np.sin(theta_rad), np.ones(n)])
    params, *_ = np.linalg.lstsq(design, values, rcond=None)
    a, b, c = params
    residual = design @ params - values
    return AxisFit(
        amplitude=float(math.hypot(a, b)),
        phase_deg=float(math.degrees(math.atan2(b, a))),
        offset=float(c),
        rms_residual=float(np.sqrt(np.mean(residual**2))),
    )


def _fit_joint(theta_rad: np.ndarray, x: np.ndarray, y: np.ndarray
               ) -> tuple[float, float, float, float, float]:
    """Joint 4-parameter LSQ on stacked (x, y) equations.

    Returns (a, b, x0, y0, rms_residual) where a = A·cos(φ), b = A·sin(φ).
    """
    n = len(x)
    design = np.zeros((2 * n, 4))
    # x equations
    design[:n, 0] = np.cos(theta_rad)   # a · cos(θ)
    design[:n, 1] = np.sin(theta_rad)   # b · sin(θ)
    design[:n, 2] = 1.0                 # x0
    # y equations: y = a·sin(θ) − b·cos(θ) + y0
    design[n:, 0] = np.sin(theta_rad)   # a · sin(θ)
    design[n:, 1] = -np.cos(theta_rad)  # b · (−cos(θ))
    design[n:, 3] = 1.0                 # y0
    rhs = np.concatenate([x, y])
    params, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    a, b, x0, y0 = params
    residual = design @ params - rhs
    rms = float(np.sqrt(np.mean(residual**2)))
    return float(a), float(b), float(x0), float(y0), rms


def fit_auto_level(samples: list[AutoLevelSample]) -> AutoLevelFit:
    if len(samples) < 4:
        raise ValueError(f"need at least 4 samples to fit, got {len(samples)}")

    theta = np.radians(np.array([s.azimuth_deg for s in samples]))
    x = np.array([s.sensor_x for s in samples])
    y = np.array([s.sensor_y for s in samples])

    a, b, x0, y0, rms = _fit_joint(theta, x, y)
    amplitude = math.hypot(a, b)
    phase = _wrap_pm180(math.degrees(math.atan2(b, a)))

    # Small-angle derivation of tilt in degrees, using mean z if available.
    z_values = [s.sensor_z for s in samples if s.sensor_z is not None]
    mean_z = float(np.mean(z_values)) if z_values else 1.0
    if mean_z <= 1e-9:
        mean_z = 1.0
    tilt_deg = math.degrees(amplitude / mean_z)

    # Diagnostic per-axis fits (kept for comparison and back-compat).
    x_fit = _fit_axis(theta, x)
    y_fit = _fit_axis(theta, y)

    return AutoLevelFit(
        amplitude=float(amplitude),
        tilt_mount_az_deg=float(phase),
        x_offset=float(x0),
        y_offset=float(y0),
        mean_z=mean_z,
        tilt_deg=float(tilt_deg),
        rms_residual=float(rms),
        n_samples=len(samples),
        x_axis=x_fit,
        y_axis=y_fit,
        uphill_world_az_deg=None,
    )


def apply_sign_flip(fit: AutoLevelFit, flip: bool) -> AutoLevelFit:
    """Return a copy of `fit` with `uphill_world_az_deg` populated.

    `flip` is the installation-dependent sign choice: False means
    tilt_mount_az is already the uphill direction in the world frame
    (after compass-to-mount alignment); True rotates it by 180°.
    """
    uphill = fit.tilt_mount_az_deg if not flip else _wrap_pm180(fit.tilt_mount_az_deg + 180.0)
    return replace(fit, uphill_world_az_deg=float(uphill))


_COMPASS_16 = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]


def azimuth_to_compass(az_deg: float) -> str:
    """Convert azimuth (0=N, +90=E, ±180=S, -90=W) to a 16-point compass label.

    Accepts any numeric degrees; input is normalized internally so callers
    can pass either the [-180, +180) mount convention or legacy 0-360 values.
    """
    idx = int(round((az_deg % 360.0) / 22.5)) % 16
    return _COMPASS_16[idx]


def planned_azimuths(num_samples: int, start_deg: float = 0.0) -> list[float]:
    """Return num_samples evenly-spaced azimuths in [-180°, +180°).

    Starting at `start_deg` and stepping by 360/num_samples, with each
    commanded azimuth wrapped into the [-180, +180) half-open interval
    (-180 inclusive, +180 wraps to -180).
    """
    if num_samples < 1:
        raise ValueError("num_samples must be >= 1")
    step = 360.0 / num_samples
    return [_wrap_pm180(start_deg + i * step) for i in range(num_samples)]


@dataclass
class LevelingGuidance:
    is_level: bool
    tilt_deg: float
    tilt_sensor_units: float
    tilt_mount_az_deg: float
    uphill_world_az_deg: float | None
    uphill_compass: str | None
    message: str


def build_guidance(
    fit: AutoLevelFit,
    tolerance_deg: float = 0.1,
) -> LevelingGuidance:
    """Produce a human-facing message from a fit result.

    If `fit.uphill_world_az_deg` is set (via `apply_sign_flip`), the message
    names the compass side to raise. Otherwise it names only the mount-frame
    azimuth and instructs the user to anchor the sign.
    """
    is_level = fit.tilt_deg < tolerance_deg
    uphill = fit.uphill_world_az_deg
    compass = azimuth_to_compass(uphill) if uphill is not None else None

    if is_level:
        msg = "Tripod is level within tolerance."
    elif uphill is not None and compass is not None:
        msg = (
            f"Tripod tilts {fit.tilt_deg:.2f}°. Uphill is toward world-az "
            f"{uphill:.0f}° ({compass}). Raise the tripod leg on the {compass} side."
        )
    else:
        msg = (
            f"Tripod tilts {fit.tilt_deg:.2f}° along mount-az "
            f"{fit.tilt_mount_az_deg:.0f}°. Sign not yet anchored — slew the scope "
            f"to mount-az {fit.tilt_mount_az_deg:.0f}° and visually identify "
            f"whether that side is high or low."
        )

    return LevelingGuidance(
        is_level=is_level,
        tilt_deg=fit.tilt_deg,
        tilt_sensor_units=fit.amplitude,
        tilt_mount_az_deg=fit.tilt_mount_az_deg,
        uphill_world_az_deg=uphill,
        uphill_compass=compass,
        message=msg,
    )


# ---------------------------------------------------------------------------
# Run log I/O (JSON schema v1)
# ---------------------------------------------------------------------------

RUN_LOG_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def save_run(
    path: str | Path,
    meta: dict[str, Any],
    positions: list[dict[str, Any]],
) -> None:
    """Write a run log to JSON atomically.

    Called incrementally: rewrites the file after each position completes.
    `meta` must include keys: run_id, started_at, config (dict).
    `finished_at` is filled in on each write to the latest timestamp.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": RUN_LOG_VERSION,
        "run_id": meta.get("run_id"),
        "started_at": meta.get("started_at"),
        "finished_at": _now_iso(),
        "config": meta.get("config", {}),
        "positions": positions,
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(p)


def load_run(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[AutoLevelSample]]:
    """Load a run log, returning (meta, positions, samples).

    `samples` is a list of AutoLevelSample aggregated from each position's
    raw reads (means of x/y/z/angle) so callers can plug directly into
    fit_auto_level.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("version") != RUN_LOG_VERSION:
        raise ValueError(
            f"unsupported run log version {payload.get('version')}, expected {RUN_LOG_VERSION}"
        )
    meta = {
        "run_id": payload.get("run_id"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "config": payload.get("config", {}),
    }
    positions = payload.get("positions", [])
    samples: list[AutoLevelSample] = []
    for pos in positions:
        reads = pos.get("reads", [])
        if not reads:
            continue
        xs = [r["x"] for r in reads]
        ys = [r["y"] for r in reads]
        zs = [r["z"] for r in reads if r.get("z") is not None]
        angles = [r["angle"] for r in reads if r.get("angle") is not None]
        samples.append(
            AutoLevelSample(
                azimuth_deg=pos["azimuth_deg"],
                sensor_x=sum(xs) / len(xs),
                sensor_y=sum(ys) / len(ys),
                sensor_z=(sum(zs) / len(zs)) if zs else None,
                angle=(sum(angles) / len(angles)) if angles else None,
            )
        )
    return meta, positions, samples


def positions_to_rows(positions: list[dict[str, Any]]) -> list[dict[str, float]]:
    """Summarize each position into mean/stdev rows for display."""
    rows: list[dict[str, float]] = []
    for pos in positions:
        reads = pos.get("reads", [])
        if not reads:
            continue
        def _stats(key: str) -> tuple[float | None, float | None]:
            vals = [r[key] for r in reads if r.get(key) is not None]
            if not vals:
                return None, None
            m = sum(vals) / len(vals)
            if len(vals) >= 2:
                var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
                return m, math.sqrt(var)
            return m, None
        row: dict[str, Any] = {
            "az": pos["azimuth_deg"],
            "n": len(reads),
        }
        for k in ("x", "y", "z", "angle", "heading"):
            mean, std = _stats(k)
            row[f"{k}_mean"] = mean
            row[f"{k}_std"] = std
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Sample-collection orchestrator (legacy; script now drives this inline)
# ---------------------------------------------------------------------------

MoveToAzFn = Callable[[float, float], None]
ReadSensorFn = Callable[[], tuple[float, float, float | None]]
StopRequestedFn = Callable[[], bool]


def collect_samples(
    move_to_az: MoveToAzFn,
    read_sensor: ReadSensorFn,
    *,
    num_samples: int = 12,
    altitude_deg: float = 0.0,
    start_az_deg: float = 0.0,
    settle_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[int, int, float], None] | None = None,
    stop_requested: StopRequestedFn | None = None,
) -> list[AutoLevelSample]:
    """Drive the measurement loop using injected hardware callbacks.

    Retained for compatibility with existing tests. The CLI script in
    scripts/auto_level.py drives this loop inline to capture richer
    per-position data for logging.

    read_sensor() returns (x, y, angle_or_None); z is not captured by this
    simple helper. For z-aware sampling, see the script.
    """
    azimuths = planned_azimuths(num_samples, start_az_deg)
    samples: list[AutoLevelSample] = []
    for i, az in enumerate(azimuths):
        if stop_requested is not None and stop_requested():
            break
        move_to_az(az, altitude_deg)
        if settle_seconds > 0:
            sleep(settle_seconds)
        sx, sy, angle = read_sensor()
        samples.append(
            AutoLevelSample(azimuth_deg=az, sensor_x=sx, sensor_y=sy, angle=angle)
        )
        if progress is not None:
            progress(i + 1, num_samples, az)
    return samples


# Back-compat alias: older code may reference AutoLevelFit.uphill_az_deg.
# Expose it as a read-only property mapped to tilt_mount_az_deg.
def _uphill_az_deg(self: AutoLevelFit) -> float:
    return self.tilt_mount_az_deg


AutoLevelFit.uphill_az_deg = property(_uphill_az_deg)  # type: ignore[attr-defined]


__all__ = [
    "AutoLevelSample",
    "AxisFit",
    "AutoLevelFit",
    "LevelingGuidance",
    "fit_auto_level",
    "apply_sign_flip",
    "azimuth_to_compass",
    "planned_azimuths",
    "build_guidance",
    "collect_samples",
    "save_run",
    "load_run",
    "positions_to_rows",
    "RUN_LOG_VERSION",
]
