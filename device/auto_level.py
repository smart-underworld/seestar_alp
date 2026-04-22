"""Auto-level: fit tripod tilt + sensor offset from rotated balance-sensor samples.

The balance sensor is fixed to the rotating OTA, so a single reading conflates
the sensor's calibration offset (body frame) with the tripod's tilt (world
frame). Rotating through azimuth θ traces a sinusoid in sensor (x, y); a
joint least-squares fit cleanly decomposes the two.

Physical model — this module uses the mount's compass convention where
azimuth increases clockwise viewed from above (0° = N, +90° = E), which
reverses the math convention used by trig functions. With the sensor's
body frame oriented so +y is 90° clockwise from +x (or equivalently,
using math convention but negating the y channel), the model is:
    x(θ) = A·cos(θ − φ) + x₀  =  a·cos(θ) + b·sin(θ) + x₀
    y(θ) = -A·sin(θ − φ) + y₀ = -a·sin(θ) + b·cos(θ) + y₀
with a = A·cos(φ), b = A·sin(φ).

We solve the stacked system [[ cos θ_i,  sin θ_i, 1, 0], ...
                             [-sin θ_i,  cos θ_i, 0, 1], ...] · [a, b, x₀, y₀]
against the 2N measurement vector [x_i..., y_i...]. Then A = hypot(a, b)
and φ = atan2(b, a).

Historical note: a prior version of this model assumed math convention
(y = +A·sin(θ−φ)), which negated the y-channel contribution and caused
the two channels to fight each other on real hardware. The fit collapsed
to amplitude ≈ 0 regardless of true tilt. The current sign (y = -A·sin)
matches the physical sensor orientation and produces fits whose per-sample
residuals match the per-position sensor noise floor (~0.0005 sensor units).

Tilt magnitude in degrees uses small-angle physics: with the accelerometer
reading ~1 g_sensor_unit when level, hypot(raw_x, raw_y)/z ≈ sin(tilt) ≈ tilt
in radians. So tilt_deg = degrees(A / mean(z)).

`tilt_mount_az_deg` is the body-frame azimuth where the sensor's +x axis
projects maximally onto the tilt vector. Converting that to a world-frame
compass bearing ("uphill direction") requires one installation-dependent
sign choice — see `apply_sign_flip`.

Features beyond the basic fit:
  - Parameter covariance propagated to 1σ uncertainties on (A, φ) and
    the derived tilt in degrees. Captures how well-constrained the fit is.
  - Inverse-variance weighting when per-sample stdevs are provided — noisy
    positions contribute proportionally less to the fit.
  - Outlier rejection via MAD filter on joint-sample residuals (a single
    refit pass). Guards against bumps/vibrations during sampling.

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
    sensor_x_std: float | None = None
    """Per-position stdev of sensor_x (from the N raw reads averaged into
    sensor_x). Enables inverse-variance weighting in the joint fit."""
    sensor_y_std: float | None = None
    """Per-position stdev of sensor_y."""


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

    amplitude_std: float | None = None
    """1σ uncertainty on `amplitude` in sensor units (from parameter covariance)."""
    tilt_deg_std: float | None = None
    """1σ uncertainty on `tilt_deg` (= amplitude_std / mean_z, in degrees)."""
    tilt_mount_az_std_deg: float | None = None
    """1σ uncertainty on `tilt_mount_az_deg` in degrees (from covariance, Jacobian-propagated)."""
    dropped_indices: list[int] = field(default_factory=list, repr=False)
    """Indices of input samples dropped as outliers (empty if no rejection pass ran)."""


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


def _build_joint_design(theta_rad: np.ndarray) -> np.ndarray:
    """Construct the 2N×4 design matrix for the joint (x, y) sinusoid fit.

    Rows 0..N-1 are the x equations, rows N..2N-1 the y equations:
        x(θ) =  a·cos(θ) + b·sin(θ) + x₀
        y(θ) = -a·sin(θ) + b·cos(θ) + y₀
    """
    n = len(theta_rad)
    design = np.zeros((2 * n, 4))
    design[:n, 0] = np.cos(theta_rad)
    design[:n, 1] = np.sin(theta_rad)
    design[:n, 2] = 1.0
    design[n:, 0] = -np.sin(theta_rad)
    design[n:, 1] = np.cos(theta_rad)
    design[n:, 3] = 1.0
    return design


def _fit_joint(
    theta_rad: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    x_sigma: np.ndarray | None = None,
    y_sigma: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Joint 4-parameter weighted LSQ on stacked (x, y) equations.

    Returns (params, cov, rms_residual):
      - params: length-4 array [a, b, x0, y0]
      - cov: 4×4 parameter covariance matrix (σ² · (Dᵀ W D)⁻¹)
      - rms_residual: RMS of unweighted residuals, in data units

    When `x_sigma` / `y_sigma` are provided (per-sample stdevs), the fit
    uses inverse-variance weighting. Zero or missing entries fall back
    to the mean of the provided sigmas so they don't dominate the fit.
    """
    n = len(x)
    design = _build_joint_design(theta_rad)
    rhs = np.concatenate([x, y])

    # Build per-row weights = 1/σ. Missing or zero sigmas get replaced by
    # the mean of the valid sigmas so they contribute at nominal weight
    # rather than infinite (which would overfit that position).
    def _resolve_sigma(sig: np.ndarray | None, count: int) -> np.ndarray | None:
        if sig is None:
            return None
        arr = np.asarray(sig, dtype=float)
        valid = np.isfinite(arr) & (arr > 0)
        if not valid.any():
            return None
        fill = float(np.mean(arr[valid]))
        out = np.where(valid, arr, fill)
        return out

    sx = _resolve_sigma(x_sigma, n)
    sy = _resolve_sigma(y_sigma, n)
    if sx is not None or sy is not None:
        sx = sx if sx is not None else np.full(n, float(np.mean(sy)))
        sy = sy if sy is not None else np.full(n, float(np.mean(sx)))
        w = np.concatenate([1.0 / sx, 1.0 / sy])
    else:
        w = np.ones(2 * n)

    design_w = design * w[:, None]
    rhs_w = rhs * w
    params, *_ = np.linalg.lstsq(design_w, rhs_w, rcond=None)

    # Residuals in data units (unweighted) — this is what users care about.
    residual = design @ params - rhs
    rms = float(np.sqrt(np.mean(residual**2)))

    # Covariance: for weighted LSQ, cov(params) = σ² · (Dᵀ W D)⁻¹ where W
    # is diag(w²) and σ² is estimated from the weighted residuals. When
    # weights are true 1/σ, σ²_est ≈ 1 (modulo dof); when weights are
    # relative, σ²_est absorbs the absolute scale. This flavor handles
    # both cases correctly.
    dof = max(len(rhs) - 4, 1)
    residual_w = design_w @ params - rhs_w
    sigma2 = float(np.sum(residual_w ** 2) / dof)
    # Regularize against near-singular designs (e.g., < 4 distinct azimuths).
    try:
        cov = sigma2 * np.linalg.inv(design_w.T @ design_w)
    except np.linalg.LinAlgError:
        cov = np.full((4, 4), np.nan)
    return params, cov, rms


def _propagate_uncertainty_ab_to_Aphi(
    a: float, b: float, cov: np.ndarray,
) -> tuple[float, float]:
    """Propagate (a, b) covariance to 1σ on A=hypot(a,b) and φ=atan2(b,a).

    Returns (sigma_A, sigma_phi_rad). Zero-amplitude case returns (σ on A
    from the covariance trace, +inf) since phase is undefined at A=0.
    """
    A = math.hypot(a, b)
    cov_ab = cov[:2, :2]
    if A <= 1e-12:
        sigma_A = float(math.sqrt(max(cov_ab[0, 0] + cov_ab[1, 1], 0.0)))
        return sigma_A, float("inf")
    # Jacobians
    J_A = np.array([a / A, b / A])
    var_A = float(J_A @ cov_ab @ J_A)
    sigma_A = math.sqrt(max(var_A, 0.0))
    J_phi = np.array([-b / (A * A), a / (A * A)])
    var_phi = float(J_phi @ cov_ab @ J_phi)
    sigma_phi = math.sqrt(max(var_phi, 0.0))
    return sigma_A, sigma_phi


def _mad_outlier_mask(residual_2n: np.ndarray, threshold: float) -> np.ndarray:
    """Flag outliers from per-sample joint residuals using MAD.

    residual_2n is the length-2N residual vector (x rows then y rows).
    Returns a length-N boolean mask where True = keep. An "outlier" is a
    sample whose joint residual magnitude sqrt(r_x² + r_y²) is more than
    `threshold` robust-σ (1.4826·MAD) above the median.
    """
    n = len(residual_2n) // 2
    r_x = residual_2n[:n]
    r_y = residual_2n[n:]
    sample_res = np.sqrt(r_x * r_x + r_y * r_y)
    med = float(np.median(sample_res))
    mad = float(np.median(np.abs(sample_res - med)))
    if mad <= 0.0:
        return np.ones(n, dtype=bool)
    sigma_robust = 1.4826 * mad
    limit = med + threshold * sigma_robust
    return sample_res <= limit


def fit_auto_level(
    samples: list[AutoLevelSample],
    outlier_mad_threshold: float | None = 3.5,
) -> AutoLevelFit:
    """Decompose balance-sensor samples into tripod tilt + sensor offset.

    Joint weighted LSQ on the physical model (see module docstring). When
    per-sample stdevs are provided on the input samples, the fit uses
    inverse-variance weighting. When `outlier_mad_threshold` is set, a
    single MAD-based outlier rejection pass runs after the initial fit:
    samples whose joint residual magnitude exceeds the threshold (in robust
    σ units, using 1.4826·MAD as the σ estimate) are dropped and the fit
    is redone on the cleaned data. Pass `outlier_mad_threshold=None` to
    disable.
    """
    if len(samples) < 4:
        raise ValueError(f"need at least 4 samples to fit, got {len(samples)}")

    theta = np.radians(np.array([s.azimuth_deg for s in samples]))
    x = np.array([s.sensor_x for s in samples])
    y = np.array([s.sensor_y for s in samples])

    def _stds(field: str) -> np.ndarray | None:
        vals = [getattr(s, field) for s in samples]
        if all(v is None for v in vals):
            return None
        # Keep as float array with NaN for missing — _fit_joint handles it.
        return np.array([float("nan") if v is None else float(v) for v in vals])

    x_sigma = _stds("sensor_x_std")
    y_sigma = _stds("sensor_y_std")

    params, cov, rms = _fit_joint(theta, x, y, x_sigma, y_sigma)

    # Optional single-pass MAD outlier rejection, on the initial fit's
    # per-sample residuals. Only triggers when we have headroom (>4
    # surviving samples) and at least one outlier is found.
    dropped_indices: list[int] = []
    if outlier_mad_threshold is not None and len(samples) > 4:
        design = _build_joint_design(theta)
        residual = design @ params - np.concatenate([x, y])
        keep = _mad_outlier_mask(residual, outlier_mad_threshold)
        if (not keep.all()) and int(keep.sum()) >= 4:
            dropped_indices = [int(i) for i in np.where(~keep)[0]]
            theta_k = theta[keep]
            x_k = x[keep]
            y_k = y[keep]
            xs_k = x_sigma[keep] if x_sigma is not None else None
            ys_k = y_sigma[keep] if y_sigma is not None else None
            params, cov, rms = _fit_joint(theta_k, x_k, y_k, xs_k, ys_k)

    a, b, x0, y0 = (float(p) for p in params)
    amplitude = math.hypot(a, b)
    phase = _wrap_pm180(math.degrees(math.atan2(b, a)))

    sigma_A, sigma_phi_rad = _propagate_uncertainty_ab_to_Aphi(a, b, cov)

    # Small-angle derivation of tilt in degrees, using mean z if available.
    z_values = [s.sensor_z for s in samples if s.sensor_z is not None]
    mean_z = float(np.mean(z_values)) if z_values else 1.0
    if mean_z <= 1e-9:
        mean_z = 1.0
    tilt_deg = math.degrees(amplitude / mean_z)
    tilt_deg_std = math.degrees(sigma_A / mean_z) if math.isfinite(sigma_A) else None
    tilt_az_std_deg = (
        math.degrees(sigma_phi_rad)
        if math.isfinite(sigma_phi_rad) else None
    )

    # Diagnostic per-axis fits (kept for comparison and back-compat).
    x_fit = _fit_axis(theta, x)
    y_fit = _fit_axis(theta, y)

    # n_samples reports the count used by the fit (post-outlier-rejection).
    n_used = len(samples) - len(dropped_indices)

    return AutoLevelFit(
        amplitude=float(amplitude),
        tilt_mount_az_deg=float(phase),
        x_offset=float(x0),
        y_offset=float(y0),
        mean_z=mean_z,
        tilt_deg=float(tilt_deg),
        rms_residual=float(rms),
        n_samples=n_used,
        x_axis=x_fit,
        y_axis=y_fit,
        uphill_world_az_deg=None,
        amplitude_std=float(sigma_A) if math.isfinite(sigma_A) else None,
        tilt_deg_std=tilt_deg_std,
        tilt_mount_az_std_deg=tilt_az_std_deg,
        dropped_indices=dropped_indices,
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
        # Per-position stdev enables inverse-variance weighting on replay.
        def _std(vals: list[float]) -> float | None:
            if len(vals) < 2:
                return None
            m = sum(vals) / len(vals)
            var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
            return math.sqrt(var)
        samples.append(
            AutoLevelSample(
                azimuth_deg=pos["azimuth_deg"],
                sensor_x=sum(xs) / len(xs),
                sensor_y=sum(ys) / len(ys),
                sensor_z=(sum(zs) / len(zs)) if zs else None,
                angle=(sum(angles) / len(angles)) if angles else None,
                sensor_x_std=_std(xs),
                sensor_y_std=_std(ys),
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
