"""Reusable rotation-calibration science and session plumbing.

Shared by the REPL CLI (`scripts/trajectory/calibrate_rotation.py`)
and the web front end. The CLI keeps only its `input()` glue + menu
rendering; everything below is I/O-free enough to test without a
mount or a network.

Exposed API:

- Dataclasses: :class:`Sighting`, :class:`RotationSolution`,
  :class:`PriorInfo`.
- Constants: :data:`KEEP_MAX_AGE_S`, :data:`KEEP_MAX_DISTANCE_M` — the
  two thresholds behind the "clear or keep" heuristic.
- Pure helpers:
    - :func:`terrestrial_refraction_deg` — apparent el lift from
      atmospheric bending over a ground path.
    - :func:`predict_mount_azel` — (yaw, pitch, roll) + site +
      landmark → (az, el, slant) in the mount frame, with optional
      refraction lift.
    - :func:`solve_rotation` — LM fit of the mount rotation to a
      list of sightings. DoF is chosen by data amount by default.
    - :func:`write_calibration` — write
      ``device/mount_calibration.json`` with the schema consumers
      read today.
    - :func:`parse_calibrated_at` / :func:`inspect_prior` — surface
      the on-disk calibration's age + distance from the current
      GPS.
    - :func:`decide_clear_or_keep` — boolean verdict consumed by the
      REPL prompt and the web UI's default-checkbox state.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from device.target_frame import MountFrame
from scripts.trajectory.faa_dof import Landmark
from scripts.trajectory.observer import ObserverSite, haversine_m


# ---------- data model ----------------------------------------------


@dataclass(frozen=True)
class Sighting:
    """One landmark → encoder (az, el) record."""
    landmark: Landmark
    encoder_az_deg: float
    encoder_el_deg: float
    true_az_deg: float          # topocentric az of landmark (metadata)
    true_el_deg: float          # topocentric el of landmark (metadata)
    slant_m: float
    t_unix: float


@dataclass
class RotationSolution:
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    residual_rms_deg: float
    per_landmark: list[dict]


# ---------- constants ------------------------------------------------


KEEP_MAX_AGE_S = 6 * 3600
KEEP_MAX_DISTANCE_M = 10.0

_EARTH_R_M = 6_371_000.0


# ---------- prior inspection ----------------------------------------


@dataclass(frozen=True)
class PriorInfo:
    """Minimum of what we need to know about the on-disk calibration
    to decide whether to keep it as a seed."""
    path: Path
    observer_lat_deg: float | None
    observer_lon_deg: float | None
    observer_alt_m: float | None
    calibrated_at: datetime | None
    age_s: float | None
    distance_from_current_m: float | None

    @property
    def should_default_keep(self) -> bool:
        """Default state of the clear-or-keep prompt: keep when the
        prior is both fresh and local."""
        if self.age_s is None or self.distance_from_current_m is None:
            return False
        return (
            self.age_s < KEEP_MAX_AGE_S
            and self.distance_from_current_m < KEEP_MAX_DISTANCE_M
        )


def parse_calibrated_at(raw: str | None) -> datetime | None:
    """Parse the ``calibrated_at`` string emitted by the calibration
    writers. Handles both the legacy dash-tz form
    (``%Y-%m-%dT%H-%M-%S%z``) and standard ISO 8601. Returns an
    aware UTC datetime, or ``None`` if missing / malformed."""
    if not isinstance(raw, str) or not raw:
        return None
    candidates = (
        "%Y-%m-%dT%H-%M-%S%z",   # legacy: 2026-04-21T23-28-52-0700
        "%Y-%m-%dT%H:%M:%S%z",   # standard ISO 8601 with colons
        "%Y-%m-%dT%H:%M:%S.%f%z",
    )
    for fmt in candidates:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def inspect_prior(
    path: Path, current_lat: float, current_lon: float,
) -> PriorInfo | None:
    """Parse the prior calibration JSON (if any) and return age +
    distance metadata the clear-or-keep prompt uses. Returns ``None``
    when the file doesn't exist; returns a ``PriorInfo`` with mostly-
    ``None`` fields when the file exists but is unreadable / legacy."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return PriorInfo(path, None, None, None, None, None, None)
    obs = payload.get("observer") if isinstance(payload, dict) else None
    lat = lon = alt = None
    if isinstance(obs, dict):
        try:
            lat = float(obs.get("lat_deg")) if obs.get("lat_deg") is not None else None
            lon = float(obs.get("lon_deg")) if obs.get("lon_deg") is not None else None
            alt = float(obs.get("alt_m")) if obs.get("alt_m") is not None else None
        except (TypeError, ValueError):
            lat = lon = alt = None
    dt = parse_calibrated_at(
        payload.get("calibrated_at") if isinstance(payload, dict) else None,
    )
    now = datetime.now(timezone.utc)
    age = (now - dt).total_seconds() if dt is not None else None
    dist = (
        haversine_m(lat, lon, current_lat, current_lon)
        if lat is not None and lon is not None else None
    )
    return PriorInfo(
        path=path, observer_lat_deg=lat, observer_lon_deg=lon,
        observer_alt_m=alt, calibrated_at=dt, age_s=age,
        distance_from_current_m=dist,
    )


def decide_clear_or_keep(prior: PriorInfo | None) -> bool:
    """Return True if the prior should be kept by default, False if
    the smart-default is to clear it. Missing / unreadable / legacy
    priors default to clear (False) so an accidental run against an
    old compass calibration doesn't silently poison the seed."""
    if prior is None:
        return False
    return prior.should_default_keep


# ---------- geometry helpers ----------------------------------------


def _wrap_pm180(deg: float) -> float:
    d = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def terrestrial_refraction_deg(slant_m: float, k: float = 0.13) -> float:
    """Apparent el lift from atmospheric bending over a ground path.

    Standard terrestrial-refraction coefficient ``k ≈ 0.13`` (over land;
    higher over water). The geometric Earth-curvature drop over slant
    ``d`` is ``d² / (2R)`` metres; refraction cancels ``k`` of it, so the
    apparent angular lift above a straight-line line-of-sight is
    approximately ``k · d / (2R)`` radians.

    For the Dockweiler ground landmarks: Hyperion @ 5.5 km → 0.003°;
    Culver City @ 9.2 km → 0.005°. Below FAA 1E accuracy (~0.04°), so
    numerically tiny — applied here for correctness rather than
    measurable improvement.
    """
    if slant_m <= 0.0:
        return 0.0
    return math.degrees(k * slant_m / (2.0 * _EARTH_R_M))


def predict_mount_azel(
    yaw_deg: float, pitch_deg: float, roll_deg: float,
    site: ObserverSite, landmark: Landmark,
    *, apply_refraction: bool = True,
) -> tuple[float, float, float]:
    """Predict (az, el, slant) in the mount frame for ``landmark``
    under the given rotation. With ``apply_refraction=True`` the el
    is lifted by the terrestrial-refraction correction so the
    prediction matches what the scope actually sees."""
    mf = MountFrame.from_euler_deg(
        yaw_deg=yaw_deg, pitch_deg=pitch_deg, roll_deg=roll_deg, site=site,
    )
    az, el, slant = mf.ecef_to_mount_azel(landmark.ecef())
    if apply_refraction:
        el = el + terrestrial_refraction_deg(slant)
    return az, el, slant


# ---------- solver ---------------------------------------------------


def solve_rotation(
    sightings: list[Sighting],
    site: ObserverSite,
    *,
    yaw_seed_deg: float = 0.0,
    pitch_seed_deg: float = 0.0,
    roll_seed_deg: float = 0.0,
    dof: str = "auto",
) -> RotationSolution:
    """Least-squares fit of a mount-frame rotation to the sightings.

    ``dof``:
      - ``"auto"`` (default): fit yaw only when exactly one sighting
        is available (enables seeding landmark #2 without pitch/roll
        ambiguity), otherwise fit full 3-DOF (yaw, pitch, roll).
      - ``"yaw"``: force yaw-only. Useful as a sanity check.
      - ``"full"``: force 3-DOF even from a single sighting (under-
        determined but occasionally useful for regression tests).

    Residuals combine az and el errors with equal weight. The encoder
    az reported by the mount is in [-180, 180) — we wrap-diff the
    prediction against it to avoid 359° vs -1° issues. If the fit is
    ill-conditioned the solver still returns; the caller should check
    ``residual_rms_deg`` before trusting the result.
    """
    if len(sightings) < 1:
        raise ValueError("need at least 1 sighting to solve")
    if dof not in ("auto", "yaw", "full"):
        raise ValueError(f"unknown dof mode: {dof!r}")

    yaw_only = (dof == "yaw") or (dof == "auto" and len(sightings) == 1)

    def _resid(yaw: float, pitch: float, roll: float) -> np.ndarray:
        out = np.empty(2 * len(sightings), dtype=np.float64)
        for i, s in enumerate(sightings):
            pred_az, pred_el, _ = predict_mount_azel(
                yaw, pitch, roll, site, s.landmark,
            )
            d_az = _wrap_pm180(_wrap_pm180(pred_az) - _wrap_pm180(s.encoder_az_deg))
            d_el = pred_el - s.encoder_el_deg
            out[2 * i] = d_az
            out[2 * i + 1] = d_el
        return out

    if yaw_only:
        def residuals(x: np.ndarray) -> np.ndarray:
            return _resid(float(x[0]), pitch_seed_deg, roll_seed_deg)
        x0 = np.array([yaw_seed_deg], dtype=np.float64)
        result = least_squares(residuals, x0, method="lm")
        yaw = float(result.x[0])
        pitch, roll = pitch_seed_deg, roll_seed_deg
    else:
        def residuals(x: np.ndarray) -> np.ndarray:
            return _resid(float(x[0]), float(x[1]), float(x[2]))
        x0 = np.array(
            [yaw_seed_deg, pitch_seed_deg, roll_seed_deg], dtype=np.float64,
        )
        result = least_squares(residuals, x0, method="lm")
        yaw, pitch, roll = [float(v) for v in result.x]

    per_landmark: list[dict] = []
    sq_sum = 0.0
    n = 0
    for s in sightings:
        pred_az, pred_el, _ = predict_mount_azel(yaw, pitch, roll, site, s.landmark)
        r_az = _wrap_pm180(_wrap_pm180(pred_az) - _wrap_pm180(s.encoder_az_deg))
        r_el = pred_el - s.encoder_el_deg
        per_landmark.append({
            "oas": s.landmark.oas,
            "name": s.landmark.name,
            "lat_deg": s.landmark.lat_deg,
            "lon_deg": s.landmark.lon_deg,
            "height_amsl_m": s.landmark.height_amsl_m,
            "encoder_az_deg": s.encoder_az_deg,
            "encoder_el_deg": s.encoder_el_deg,
            "true_az_deg": s.true_az_deg,
            "true_el_deg": s.true_el_deg,
            "slant_m": s.slant_m,
            "predicted_az_deg": float(pred_az),
            "predicted_el_deg": float(pred_el),
            "residual_az_deg": float(r_az),
            "residual_el_deg": float(r_el),
        })
        sq_sum += r_az * r_az + r_el * r_el
        n += 2
    rms = float(np.sqrt(sq_sum / n)) if n else 0.0
    return RotationSolution(
        yaw_deg=yaw, pitch_deg=pitch, roll_deg=roll,
        residual_rms_deg=rms, per_landmark=per_landmark,
    )


# ---------- JSON writer ----------------------------------------------


def write_calibration(
    path: Path,
    sol: RotationSolution,
    site: ObserverSite,
    landmark_records: list[dict],
) -> None:
    """Write the calibration JSON every consumer reads.

    Schema keeps backward compatibility with the compass-tool format:
    yaw/pitch/roll + origin_offset_ecef_m are the minimum every loader
    honours. ``observer`` ties the calibration to the site that
    produced it; ``landmarks`` records per-point residuals for audit.
    """
    payload = {
        "calibration_method": "rotation_landmarks",
        "calibrated_at": time.strftime("%Y-%m-%dT%H-%M-%S%z"),
        "yaw_offset_deg": sol.yaw_deg,
        "pitch_offset_deg": sol.pitch_deg,
        "roll_offset_deg": sol.roll_deg,
        "origin_offset_ecef_m": [0.0, 0.0, 0.0],
        "residual_rms_deg": sol.residual_rms_deg,
        "n_landmarks": len(landmark_records),
        "observer": {
            "lat_deg": site.lat_deg,
            "lon_deg": site.lon_deg,
            "alt_m": site.alt_m,
            "source": "telescope_get_device_state",
        },
        "landmarks": landmark_records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
