"""Reusable rotation-calibration science and session plumbing.

Shared by the REPL CLI (`scripts/trajectory/calibrate_rotation.py`)
and the web front end. The CLI keeps only its `input()` glue + menu
rendering; everything below is I/O-free enough to test without a
mount or a network.

Exposed API:

- Dataclasses: :class:`Sighting`, :class:`RotationSolution`,
  :class:`PriorInfo`, :class:`CalibrationStatus`.
- Constants: :data:`KEEP_MAX_AGE_S`, :data:`KEEP_MAX_DISTANCE_M` — the
  two thresholds behind the "clear or keep" heuristic.
- Pure helpers:
    - :func:`terrestrial_refraction_deg`
    - :func:`predict_mount_azel`
    - :func:`solve_rotation`, :func:`write_calibration`
    - :func:`parse_calibrated_at`, :func:`inspect_prior`,
      :func:`decide_clear_or_keep`
- Session:
    - :class:`CalibrationSession` — thread-based mount driver for the
      browser calibration UI, modelled on `LiveTrackSession`.
    - :class:`CalibrationManager` — per-process singleton,
      telescope-keyed. Cross-checks with the live-tracker manager so
      the two flows can't drive the mount concurrently.
"""

from __future__ import annotations

import json
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from astropy.coordinates import EarthLocation
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


def pointing_uncertainty_deg(
    slant_m: float,
    horizontal_ft: float,
    vertical_ft: float,
    *,
    observer_sigma_m: float = 10.0,
) -> tuple[float, float]:
    """Propagate FAA landmark + observer GPS uncertainties to
    predicted (az, el) 1σ in degrees.

    Methodology (analytic, first-order small-angle):

        σ_az ≈ hypot(σ_h, σ_obs) / slant   [rad]
        σ_el ≈ hypot(σ_v, σ_obs) / slant   [rad]

    FAA DOF bounds are conventionally ~95% confidence, so we divide
    the published ± ft value by 2 to get a 1σ before combining with
    the observer GPS term (given as 1σ). The result is a true 1σ
    angular uncertainty suitable for ± display in the UI.

    The small-angle approximation holds to ≪ 1% for ground landmarks
    (σ/slant ≈ 3 × 10⁻³ for Hyperion); a Monte-Carlo cross-check
    lives in ``tests/test_calibrate_rotation.py`` and agrees with
    the analytic output within ~2% on 10 000 draws.

    ``nan`` ft inputs propagate to ``nan`` outputs — callers show
    those as "unknown" in the UI.
    """
    if slant_m <= 0.0 or not math.isfinite(slant_m):
        return (float("nan"), float("nan"))
    ft_to_m = 0.3048
    # Treat FAA bounds as 2σ → divide by 2 to get 1σ.
    sigma_h_m = (horizontal_ft * ft_to_m) / 2.0 if math.isfinite(horizontal_ft) else float("nan")
    sigma_v_m = (vertical_ft * ft_to_m) / 2.0 if math.isfinite(vertical_ft) else float("nan")
    obs = float(observer_sigma_m)
    if math.isfinite(sigma_h_m):
        sigma_az_rad = math.hypot(sigma_h_m, obs) / slant_m
        sigma_az_deg = math.degrees(sigma_az_rad)
    else:
        sigma_az_deg = float("nan")
    if math.isfinite(sigma_v_m):
        sigma_el_rad = math.hypot(sigma_v_m, obs) / slant_m
        sigma_el_deg = math.degrees(sigma_el_rad)
    else:
        sigma_el_deg = float("nan")
    return (sigma_az_deg, sigma_el_deg)


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


# ---------- CalibrationSession --------------------------------------


# Maximum per-command nudge, in degrees. Guards against a typo in the
# web UI driving the mount tens of degrees in one request.
MAX_NUDGE_PER_CMD_DEG = 5.0

# Arrive tolerance for the pre-slew to each landmark (coarse) vs.
# the nudge-to-beacon move (fine). Matches the CLI values.
ARRIVE_TOL_SLEW_DEG = 0.3
ARRIVE_TOL_NUDGE_DEG = 0.1


@dataclass
class _Command:
    """Worker-thread queue entry."""
    kind: str                       # "slew" | "nudge" | "sight" | "skip" | "commit" | "cancel"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalibrationStatus:
    """JSON-serialisable session snapshot for the browser."""
    active: bool
    phase: str                      # init / slewing / nudging / sighting / review / committed / cancelled / error
    target_idx: int
    n_targets: int
    current_landmark: dict | None    # {oas, name, true_az_deg, true_el_deg, slant_m, lit, accuracy_class}
    target_az_deg: float | None      # pending encoder target (drives the mount)
    target_el_deg: float | None
    encoder_az_deg: float | None     # last-read encoder (polled each cycle)
    encoder_el_deg: float | None
    solution: dict | None            # {yaw, pitch, roll, rms, per_landmark}
    errors: list[str]


class CalibrationSession:
    """Thread-backed calibration run. Mirrors LiveTrackSession: spawn
    a daemon worker, expose `start/stop/is_alive/status`, accept
    command posts (``nudge``, ``sight`` …) that flow through a
    thread-safe queue so HTTP handlers can return immediately.

    Workflow per target:
      1. Pre-slew to the landmark's predicted encoder (az, el) under
         any prior rotation supplied at construction time.
      2. Operator nudges via the HTTP `/nudge` endpoint; each nudge
         re-issues `move_to_ff` against the updated encoder target
         and reads the encoder back.
      3. Operator posts `/sight`; the session records the current
         encoder as a Sighting, refits (yaw-only for 1, full 3-DOF
         for ≥2), and auto-advances to the next landmark.

    The session ignores repeat commands that are queued faster than
    the mount can execute them (nudge coalescing keeps the latest
    pending target rather than backing up a queue of moves).
    """

    # Polling cadence for encoder reads when the mount is idle (to
    # keep the browser KPI strip responsive).
    IDLE_POLL_DT_S = 0.5

    def __init__(
        self,
        telescope_id: int,
        targets: list[tuple[Landmark, float, float, float]],
        site: ObserverSite,
        *,
        out_path: Path,
        prior_frame: MountFrame | None = None,
        alpaca_host: str = "127.0.0.1",
        alpaca_port: int | None = None,
        dry_run: bool = False,
    ) -> None:
        if not targets:
            raise ValueError("need at least 1 target")
        self.telescope_id = int(telescope_id)
        self.targets = list(targets)
        self.site = site
        self.out_path = Path(out_path)
        self._prior_frame = prior_frame
        self._alpaca_host = alpaca_host
        self._alpaca_port = alpaca_port
        self.dry_run = bool(dry_run)

        self._queue: queue.Queue[_Command] = queue.Queue()
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

        # Mutable state protected by _lock.
        self._phase = "init"
        self._target_idx = 0
        self._sightings: list[Sighting] = []
        self._solution: RotationSolution | None = None
        self._target_az: float | None = None
        self._target_el: float | None = None
        self._encoder_az: float | None = None
        self._encoder_el: float | None = None
        self._errors: list[str] = []

    # ---------- public lifecycle ----------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("calibration session already running")
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"CalibrationSession({self.telescope_id})",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_evt.set()
        self._queue.put(_Command("cancel"))
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> CalibrationStatus:
        from scripts.trajectory.faa_dof import (
            aiming_hint as _aim,
            faa_accuracy_ft as _acc,
        )

        def _nan_to_none(x: float) -> float | None:
            return None if not math.isfinite(x) else float(x)

        with self._lock:
            lm_info = None
            if 0 <= self._target_idx < len(self.targets):
                lm, az, el, slant = self.targets[self._target_idx]
                h_ft, v_ft = _acc(lm.accuracy_class)
                sigma_az, sigma_el = pointing_uncertainty_deg(slant, h_ft, v_ft)
                lm_info = {
                    "oas": lm.oas,
                    "name": lm.name,
                    "true_az_deg": float(az),
                    "true_el_deg": float(el),
                    "slant_m": float(slant),
                    "lit": bool(lm.lit),
                    "accuracy_class": lm.accuracy_class,
                    "aiming_hint": _aim(lm),
                    "sigma_az_deg": _nan_to_none(sigma_az),
                    "sigma_el_deg": _nan_to_none(sigma_el),
                }
            sol_info = None
            if self._solution is not None:
                sol_info = {
                    "yaw_deg": self._solution.yaw_deg,
                    "pitch_deg": self._solution.pitch_deg,
                    "roll_deg": self._solution.roll_deg,
                    "residual_rms_deg": self._solution.residual_rms_deg,
                    "per_landmark": list(self._solution.per_landmark),
                }
            return CalibrationStatus(
                active=self.is_alive(),
                phase=self._phase,
                target_idx=self._target_idx,
                n_targets=len(self.targets),
                current_landmark=lm_info,
                target_az_deg=self._target_az,
                target_el_deg=self._target_el,
                encoder_az_deg=self._encoder_az,
                encoder_el_deg=self._encoder_el,
                solution=sol_info,
                errors=list(self._errors),
            )

    # ---------- command posts ----------

    def nudge(self, d_az_deg: float, d_el_deg: float) -> None:
        d_az = max(-MAX_NUDGE_PER_CMD_DEG, min(MAX_NUDGE_PER_CMD_DEG, float(d_az_deg)))
        d_el = max(-MAX_NUDGE_PER_CMD_DEG, min(MAX_NUDGE_PER_CMD_DEG, float(d_el_deg)))
        self._queue.put(_Command("nudge", {"d_az": d_az, "d_el": d_el}))

    def sight(self) -> None:
        self._queue.put(_Command("sight"))

    def skip(self) -> None:
        self._queue.put(_Command("skip"))

    def commit(self) -> None:
        self._queue.put(_Command("commit"))

    def cancel(self) -> None:
        self._queue.put(_Command("cancel"))

    # ---------- worker thread ----------

    def _run(self) -> None:
        cli = None
        try:
            cli = self._connect_mount()
            self._set_phase("slewing")
            self._slew_to_target(cli, 0)
            if self._stop_evt.is_set():
                return
            self._set_phase("nudging")
            self._process_loop(cli)
        except Exception as exc:  # noqa: BLE001 — surface any worker failure
            with self._lock:
                self._errors.append(f"worker crashed: {exc}")
                self._phase = "error"
        finally:
            # Best-effort stop of any lingering motion.
            if cli is not None and not self.dry_run:
                try:
                    cli.method_sync("scope_speed_move",
                                    {"speed": 0, "angle": 0, "dur_sec": 0})
                except Exception:
                    pass

    def _connect_mount(self):
        """Import lazily so unit tests that stub AlpacaClient via the
        module-level symbol pick up the stub without a prior import
        side-effect."""
        from device.alpaca_client import AlpacaClient
        from device.config import Config
        port = self._alpaca_port if self._alpaca_port is not None else int(Config.port)
        cli = AlpacaClient(self._alpaca_host, port, self.telescope_id)
        if self.dry_run:
            return cli
        try:
            from device.velocity_controller import (
                ensure_scenery_mode, set_tracking,
            )
            ensure_scenery_mode(cli)
            set_tracking(cli, False)
        except Exception as exc:
            with self._lock:
                self._errors.append(f"scenery/tracking setup: {exc}")
        return cli

    def _process_loop(self, cli) -> None:
        """Dispatch commands until the queue is empty, then idle-poll
        the encoder. Returns when a CMD_CANCEL is processed (already
        handled inside the dispatcher, which sets phase to cancelled)."""
        while not self._stop_evt.is_set():
            try:
                cmd = self._queue.get(timeout=self.IDLE_POLL_DT_S)
            except queue.Empty:
                # Idle tick: refresh encoder status so the UI polling
                # loop stays live even when nothing else is happening.
                self._poll_encoder_nonfatal(cli)
                continue
            if cmd.kind == "cancel":
                self._set_phase("cancelled")
                return
            self._dispatch(cli, cmd)
            if self._phase in ("committed", "cancelled", "error"):
                return

    def _dispatch(self, cli, cmd: _Command) -> None:
        if cmd.kind == "nudge":
            self._on_nudge(cli, float(cmd.payload["d_az"]),
                           float(cmd.payload["d_el"]))
        elif cmd.kind == "sight":
            self._on_sight(cli)
        elif cmd.kind == "skip":
            self._on_skip(cli)
        elif cmd.kind == "commit":
            self._on_commit()

    def _on_nudge(self, cli, d_az: float, d_el: float) -> None:
        with self._lock:
            if self._target_az is None or self._target_el is None:
                # No pre-slew baseline yet; ignore.
                return
            self._target_az += d_az
            self._target_el += d_el
            target_az = self._target_az
            target_el = self._target_el
        # Coalesce: drain pending nudges queued behind this one, sum
        # their deltas, and issue a single move to the final target.
        while True:
            try:
                nxt = self._queue.get_nowait()
            except queue.Empty:
                break
            if nxt.kind != "nudge":
                # Put non-nudge command back on the queue front-ish; we
                # can't peek, so just enqueue. Order preservation
                # between the coalesced move and the subsequent command
                # is preserved by the move completing first.
                self._queue.put(nxt)
                break
            with self._lock:
                self._target_az += float(nxt.payload["d_az"])
                self._target_el += float(nxt.payload["d_el"])
                target_az = self._target_az
                target_el = self._target_el
        self._set_phase("nudging")
        if self.dry_run:
            with self._lock:
                self._encoder_az = target_az
                self._encoder_el = target_el
            return
        try:
            from device.velocity_controller import move_to_ff
            loc = EarthLocation.from_geodetic(0, 0, 0)
            cur_el = self._encoder_el if self._encoder_el is not None else target_el
            cur_az = self._encoder_az if self._encoder_az is not None else target_az
            new_el, new_az, _ = move_to_ff(
                cli,
                target_az_deg=target_az, target_el_deg=target_el,
                cur_az_deg=cur_az, cur_el_deg=cur_el, loc=loc,
                tag="[calibrate_web]", arrive_tolerance_deg=ARRIVE_TOL_NUDGE_DEG,
            )
            with self._lock:
                self._encoder_az = new_az
                self._encoder_el = new_el
        except Exception as exc:
            with self._lock:
                self._errors.append(f"nudge move_to_ff failed: {exc}")

    def _on_sight(self, cli) -> None:
        """Record the current encoder as a Sighting and refit."""
        self._poll_encoder_nonfatal(cli)
        with self._lock:
            if self._encoder_az is None or self._encoder_el is None:
                self._errors.append("cannot sight: no encoder read yet")
                return
            if not (0 <= self._target_idx < len(self.targets)):
                return
            lm, true_az, true_el, slant = self.targets[self._target_idx]
            s = Sighting(
                landmark=lm,
                encoder_az_deg=float(self._encoder_az),
                encoder_el_deg=float(self._encoder_el),
                true_az_deg=float(true_az),
                true_el_deg=float(true_el),
                slant_m=float(slant),
                t_unix=time.time(),
            )
            self._sightings.append(s)
            sightings = list(self._sightings)
            next_idx = self._target_idx + 1
        # Fit outside the lock.
        try:
            sol = solve_rotation(sightings, self.site)
            with self._lock:
                self._solution = sol
        except ValueError as exc:
            with self._lock:
                self._errors.append(f"solve_rotation failed: {exc}")

        with self._lock:
            self._target_idx = next_idx
        if next_idx >= len(self.targets):
            self._set_phase("review")
        else:
            self._slew_to_target(cli, next_idx)
            self._set_phase("nudging")

    def _on_skip(self, cli) -> None:
        with self._lock:
            remaining = len(self.targets) - (self._target_idx + 1)
            already_sighted = len(self._sightings)
            projected = already_sighted + remaining
        if projected < 2:
            with self._lock:
                self._errors.append(
                    "cannot skip: would leave fewer than 2 sightings"
                )
            return
        with self._lock:
            next_idx = self._target_idx + 1
            self._target_idx = next_idx
        if next_idx >= len(self.targets):
            self._set_phase("review")
        else:
            self._slew_to_target(cli, next_idx)
            self._set_phase("nudging")

    def _on_commit(self) -> None:
        with self._lock:
            sol = self._solution
            sightings = list(self._sightings)
        if sol is None or len(sightings) < 2:
            with self._lock:
                self._errors.append("cannot commit: need ≥ 2 sightings")
            return
        try:
            write_calibration(self.out_path, sol, self.site, sol.per_landmark)
        except Exception as exc:
            with self._lock:
                self._errors.append(f"write_calibration failed: {exc}")
                self._phase = "error"
            return
        self._set_phase("committed")

    def _slew_to_target(self, cli, idx: int) -> None:
        """Drive the mount to the predicted encoder (az, el) for
        ``targets[idx]``. Updates pending target + current encoder."""
        if not (0 <= idx < len(self.targets)):
            return
        lm, _true_az, _true_el, _slant = self.targets[idx]
        prior_frame = self._prior_frame or MountFrame.from_identity_enu(self.site)
        pred_az, pred_el, _ = prior_frame.ecef_to_mount_azel(lm.ecef())
        pred_az_wrapped = ((pred_az + 180.0) % 360.0) - 180.0

        # Pre-flight sun-avoidance check. Uses the landmark's TRUE
        # topocentric (az, el) — `_true_az` / `_true_el` were computed
        # from the site + landmark position earlier in the pipeline and
        # are in sky frame regardless of calibration state. This is
        # authoritative for sun-separation and avoids any dependence on
        # the (possibly wrong) prior frame. Stop the worker on failure
        # so `_run()` bails before transitioning to the nudging phase.
        from device.sun_safety import is_sun_safe as _is_sun_safe
        sun_safe, sun_reason = _is_sun_safe(
            float(_true_az) % 360.0, float(_true_el),
        )
        if not sun_safe:
            with self._lock:
                self._errors.append(
                    f"{sun_reason} (landmark {getattr(lm, 'oas', '?')})"
                )
                self._phase = "error"
            self._stop_evt.set()
            return

        with self._lock:
            self._target_az = pred_az_wrapped
            self._target_el = pred_el
        self._set_phase("slewing")
        if self.dry_run:
            with self._lock:
                self._encoder_az = pred_az_wrapped
                self._encoder_el = pred_el
            return
        try:
            from device.velocity_controller import move_to_ff
            loc = EarthLocation.from_geodetic(0, 0, 0)
            cur_el, cur_az = self._read_encoder_nonfatal(cli)
            if cur_el is None or cur_az is None:
                cur_el, cur_az = pred_el, pred_az_wrapped
            new_el, new_az, _ = move_to_ff(
                cli,
                target_az_deg=pred_az_wrapped, target_el_deg=pred_el,
                cur_az_deg=cur_az, cur_el_deg=cur_el, loc=loc,
                tag="[calibrate_web]", arrive_tolerance_deg=ARRIVE_TOL_SLEW_DEG,
            )
            with self._lock:
                self._encoder_az = new_az
                self._encoder_el = new_el
        except Exception as exc:
            with self._lock:
                self._errors.append(f"slew to {lm.oas} failed: {exc}")

    # ---------- helpers ----------

    def _set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = phase

    def _read_encoder_nonfatal(self, cli) -> tuple[float | None, float | None]:
        if self.dry_run:
            with self._lock:
                return self._encoder_el, self._encoder_az
        try:
            from device.velocity_controller import measure_altaz_timed
            alt, az, _ = measure_altaz_timed(
                cli, EarthLocation.from_geodetic(0, 0, 0),
            )
            return float(alt), float(az)
        except Exception:
            return None, None

    def _poll_encoder_nonfatal(self, cli) -> None:
        el, az = self._read_encoder_nonfatal(cli)
        if el is None or az is None:
            return
        with self._lock:
            self._encoder_az = az
            self._encoder_el = el


# ---------- CalibrationManager ---------------------------------------


class CalibrationManager:
    """Process singleton keyed by telescope id. Mirrors
    :class:`device.live_tracker.LiveTrackManager`."""

    def __init__(self) -> None:
        self._sessions: dict[int, CalibrationSession] = {}
        self._lock = threading.Lock()

    def get(self, telescope_id: int) -> CalibrationSession | None:
        with self._lock:
            return self._sessions.get(int(telescope_id))

    def is_running(self, telescope_id: int) -> bool:
        s = self.get(telescope_id)
        return s is not None and s.is_alive()

    def start(self, session: CalibrationSession) -> CalibrationSession:
        tid = session.telescope_id
        # Refuse if the live tracker is driving the same mount. The
        # import is lazy so tests that stub either module don't pull
        # the other unnecessarily.
        try:
            from device.live_tracker import get_manager as _get_tracker_mgr
            tracker = _get_tracker_mgr().get(tid)
            if tracker is not None and tracker.is_alive():
                raise RuntimeError(
                    f"telescope {tid} is live-tracking; stop first"
                )
        except ImportError:
            pass
        with self._lock:
            existing = self._sessions.get(tid)
            if existing is not None and existing.is_alive():
                raise RuntimeError(
                    f"telescope {tid} already calibrating; stop first"
                )
            self._sessions[tid] = session
        session.start()
        return session

    def stop(self, telescope_id: int) -> CalibrationStatus | None:
        s = self.get(telescope_id)
        if s is None:
            return None
        s.stop()
        return s.status()

    def status(self, telescope_id: int) -> CalibrationStatus | None:
        s = self.get(telescope_id)
        return s.status() if s is not None else None


_MANAGER: CalibrationManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_calibration_manager() -> CalibrationManager:
    """Process-level singleton. Matches the
    ``device.live_tracker.get_manager`` pattern."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = CalibrationManager()
        return _MANAGER
