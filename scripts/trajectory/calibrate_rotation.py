"""Interactive 3-DOF rotation-matrix calibration against FAA landmarks.

Solves the topocentric → mount rotation (yaw/pitch/roll) by sighting
two FAA-registered obstruction landmarks whose ECEF positions are
known from the Digital Obstruction File. Default targets for the
Dockweiler Beach site are the Hyperion beacon stack (lit) and the
Culver City tower (unlit; daylight only). If those aren't visible
from the observer's location, the DOF zip is fetched and the top-10
visible landmarks within 20 km are offered instead.

Workflow per landmark:

    1. Print predicted true (az, el) from the current MountFrame.
    2. Slew there via `move_to_ff` (or reuse current pose if already
       calibrated and close enough).
    3. Interactive nudge loop — user drives the mount to put the
       beacon on the imager crosshair:

           cmd> h +0.5    # bump encoder az target +0.5°
           cmd> v -0.2    # bump encoder el target -0.2°
           cmd> show      # print current encoder az/el
           cmd> ok        # record and advance
           cmd> skip      # skip this target
           cmd> quit      # abort without writing

    4. Record the landed encoder (az, el) as the sighting.

After all sightings, Levenberg–Marquardt solves for (yaw, pitch, roll)
that minimises the sum of squared angular residuals between predicted
mount-frame (az, el) and the recorded encoder values. The result goes
to `device/mount_calibration.json` with the standard field names plus
an `observer` block and a diagnostic `landmarks` array.

Usage:

    .venv/bin/python -m scripts.trajectory.calibrate_rotation \\
        --altitude-m 2

    # Solver-only (no mount motion), replay a saved session JSON:
    .venv/bin/python -m scripts.trajectory.calibrate_rotation \\
        --no-move --sightings saved.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy.coordinates import EarthLocation
from scipy.optimize import least_squares

from device.alpaca_client import AlpacaClient
from device.target_frame import MountFrame
from device.velocity_controller import (
    ensure_scenery_mode,
    measure_altaz_timed,
    move_to_ff,
    set_tracking,
)
from scripts.trajectory.faa_dof import (
    DEFAULT_LANDMARKS,
    Landmark,
    fetch_nearby_landmarks,
    filter_visible,
)
from scripts.trajectory.observer import (
    ObserverSite,
    build_site,
    fetch_telescope_lonlat,
    haversine_m,
    lookup_elevation,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAL_PATH = _REPO_ROOT / "device" / "mount_calibration.json"


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


# ---------- solver ---------------------------------------------------


_EARTH_R_M = 6_371_000.0


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


def _predict_mount_azel(
    yaw_deg: float, pitch_deg: float, roll_deg: float,
    site: ObserverSite, landmark: Landmark,
    *, apply_refraction: bool = True,
) -> tuple[float, float, float]:
    """Predict (az, el, slant) in mount frame for the landmark under
    the given rotation. With ``apply_refraction=True`` the el is lifted
    by the terrestrial-refraction correction so the prediction matches
    what the scope actually sees."""
    mf = MountFrame.from_euler_deg(
        yaw_deg=yaw_deg, pitch_deg=pitch_deg, roll_deg=roll_deg, site=site,
    )
    az, el, slant = mf.ecef_to_mount_azel(landmark.ecef())
    if apply_refraction:
        el = el + terrestrial_refraction_deg(slant)
    return az, el, slant


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
      - ``"auto"`` (default): fit yaw only when exactly one sighting is
        available (enables seeding landmark #2 without pitch/roll
        ambiguity), otherwise fit full 3-DOF (yaw, pitch, roll).
      - ``"yaw"``: force yaw-only. Useful as a sanity check.
      - ``"full"``: force 3-DOF even from a single sighting (under-
        determined but occasionally useful for regression tests).

    Residuals combine az and el errors with equal weight. The encoder
    az reported by the mount is in [-180, 180) — we wrap-diff the
    prediction against it to avoid 359° vs -1° issues. If the fit is
    ill-conditioned the solver still returns; the caller should check
    `residual_rms_deg` before trusting the result.
    """
    if len(sightings) < 1:
        raise ValueError("need at least 1 sighting to solve")
    if dof not in ("auto", "yaw", "full"):
        raise ValueError(f"unknown dof mode: {dof!r}")

    yaw_only = (dof == "yaw") or (dof == "auto" and len(sightings) == 1)

    def _resid(yaw: float, pitch: float, roll: float) -> np.ndarray:
        out = np.empty(2 * len(sightings), dtype=float)
        for i, s in enumerate(sightings):
            pred_az, pred_el, _ = _predict_mount_azel(
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
        x0 = np.array([yaw_seed_deg], dtype=float)
        result = least_squares(residuals, x0, method="lm")
        yaw = float(result.x[0])
        pitch, roll = pitch_seed_deg, roll_seed_deg
    else:
        def residuals(x: np.ndarray) -> np.ndarray:
            return _resid(float(x[0]), float(x[1]), float(x[2]))
        x0 = np.array([yaw_seed_deg, pitch_seed_deg, roll_seed_deg], dtype=float)
        result = least_squares(residuals, x0, method="lm")
        yaw, pitch, roll = [float(v) for v in result.x]

    per_landmark = []
    sq_sum = 0.0
    n = 0
    for s in sightings:
        pred_az, pred_el, _ = _predict_mount_azel(yaw, pitch, roll, site, s.landmark)
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


# ---------- REPL interaction -----------------------------------------


def _print(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _read_encoder(cli: AlpacaClient) -> tuple[float, float]:
    """Read raw mount encoder (el, az). Az wrapped to [-180, 180)."""
    loc_unused = EarthLocation.from_geodetic(0, 0, 0)
    alt, az, _ = measure_altaz_timed(cli, loc_unused)
    return alt, az


def _choose_targets(
    site: ObserverSite,
    *,
    interactive: bool = True,
) -> list[tuple[Landmark, float, float, float]]:
    """Decide which landmarks to sight. Prefer the two hardcoded
    defaults when both are above-horizon; otherwise fetch DOF and
    offer up to 10 visible candidates."""
    default_hits = filter_visible(list(DEFAULT_LANDMARKS), site, min_el_deg=0.3)
    if len(default_hits) >= 2:
        _print("[calibrate] using default landmarks: "
               + ", ".join(h[0].oas for h in default_hits[:2]))
        return default_hits[:2]

    _print("[calibrate] default landmarks below horizon; fetching FAA DOF…")
    try:
        candidates = fetch_nearby_landmarks(site)
    except Exception as exc:
        raise SystemExit(
            f"Couldn't fetch FAA DOF (offline? network error): {exc}\n"
            f"Either connect to the internet or pre-download the zip to\n"
            f"  {_repo_cache_hint()}"
        ) from exc
    hits = filter_visible(candidates, site, top_n=10)
    if not hits:
        raise SystemExit("no visible DOF landmarks within 20 km — move the site?")

    _print("[calibrate] visible landmarks (pick two):")
    for i, (lm, az, el, slant) in enumerate(hits, start=1):
        lit_flag = "lit" if lm.lit else "unlit"
        _print(f"  [{i:2d}] {lm.oas}  {lm.name[:35]:<35}  "
               f"az={az:6.2f}°  el={el:5.2f}°  slant={slant/1000:4.1f}km  "
               f"{lit_flag}")
    if not interactive:
        return hits[:2]
    picks: list[int] = []
    while len(picks) < 2:
        try:
            raw = input("select index (1-based): ").strip()
        except EOFError:
            raise SystemExit("aborted at target selection")
        if not raw.isdigit():
            _print("  enter a number")
            continue
        idx = int(raw)
        if not (1 <= idx <= len(hits)):
            _print(f"  out of range (1..{len(hits)})")
            continue
        if idx in picks:
            _print("  already selected")
            continue
        picks.append(idx)
    return [hits[i - 1] for i in picks]


def _repo_cache_hint() -> str:
    from scripts.trajectory.faa_dof import default_cache_path
    return str(default_cache_path())


def _nudge_loop(
    cli: AlpacaClient,
    target_az_deg: float,
    target_el_deg: float,
    *,
    dry_run: bool,
    no_move: bool,
) -> tuple[float, float] | None:
    """Run the interactive REPL; return (encoder_az, encoder_el) on
    'ok', None on 'skip'. Raises SystemExit on 'quit'."""
    loc = EarthLocation.from_geodetic(0, 0, 0)
    cur_el, cur_az = target_el_deg, target_az_deg
    if not no_move and not dry_run:
        try:
            cur_el, cur_az = _read_encoder(cli)
        except Exception as exc:
            _print(f"  [warn] couldn't read encoder: {exc}")

    while True:
        try:
            raw = input("cmd> ").strip()
        except EOFError:
            raise SystemExit("aborted")
        if not raw:
            continue
        if raw in ("ok", "y", "accept"):
            if no_move or dry_run:
                _print(f"  [recorded synthetic encoder={target_az_deg:+.3f}, "
                       f"{target_el_deg:+.3f}]")
                return target_az_deg, target_el_deg
            enc_el, enc_az = _read_encoder(cli)
            _print(f"  [recorded encoder az={enc_az:+.3f}° el={enc_el:+.3f}°]")
            return enc_az, enc_el
        if raw in ("skip", "s"):
            return None
        if raw in ("quit", "q", "abort"):
            raise SystemExit("aborted by user")
        if raw == "show":
            if no_move or dry_run:
                _print(f"  synthetic target = az {target_az_deg:+.3f}° "
                       f"el {target_el_deg:+.3f}°")
                continue
            try:
                enc_el, enc_az = _read_encoder(cli)
                _print(f"  encoder: az={enc_az:+.3f}° el={enc_el:+.3f}°")
            except Exception as exc:
                _print(f"  [warn] couldn't read encoder: {exc}")
            continue
        # Parse nudge: "h +0.5" or "v -0.2" (az / el deltas).
        parts = raw.split()
        if len(parts) != 2 or parts[0] not in ("h", "v"):
            _print("  commands: h ±deg, v ±deg, show, ok, skip, quit")
            continue
        try:
            delta = float(parts[1])
        except ValueError:
            _print("  need a number, e.g. 'h +0.5'")
            continue
        if parts[0] == "h":
            target_az_deg += delta
        else:
            target_el_deg += delta
        _print(f"  target az={target_az_deg:+.3f}° el={target_el_deg:+.3f}°")
        if no_move or dry_run:
            continue
        try:
            enc_el, enc_az, _stats = move_to_ff(
                cli,
                target_az_deg=target_az_deg, target_el_deg=target_el_deg,
                cur_az_deg=cur_az, cur_el_deg=cur_el, loc=loc,
                tag="[calibrate]", arrive_tolerance_deg=0.1,
            )
            cur_el, cur_az = enc_el, enc_az
            _print(f"  arrived: az={enc_az:+.3f}° el={enc_el:+.3f}°")
        except Exception as exc:
            _print(f"  [warn] move_to_ff failed: {exc}")


def _initial_slew(
    cli: AlpacaClient,
    site: ObserverSite,
    landmark: Landmark,
    prior_frame: MountFrame | None,
    *,
    dry_run: bool,
    no_move: bool,
) -> tuple[float, float]:
    """Compute the best initial encoder target for the landmark and
    (unless no-move) drive the mount there. Returns the encoder target
    we used."""
    if prior_frame is None:
        prior_frame = MountFrame.from_identity_enu(site)
    pred_az, pred_el, _ = prior_frame.ecef_to_mount_azel(landmark.ecef())
    # Wrap az to [-180, 180) — encoder convention matches measure_altaz_timed.
    pred_az_wrapped = _wrap_pm180(pred_az)
    if no_move or dry_run:
        _print(f"  [no-move] would slew to encoder az={pred_az_wrapped:+.2f}° "
               f"el={pred_el:+.2f}°")
        return pred_az_wrapped, pred_el
    try:
        cur_el, cur_az = _read_encoder(cli)
    except Exception:
        cur_el, cur_az = pred_el, pred_az_wrapped
    _print(f"  slewing to encoder az={pred_az_wrapped:+.2f}° el={pred_el:+.2f}° "
           f"from az={cur_az:+.2f}° el={cur_el:+.2f}°")
    loc = EarthLocation.from_geodetic(0, 0, 0)
    new_el, new_az, _ = move_to_ff(
        cli, target_az_deg=pred_az_wrapped, target_el_deg=pred_el,
        cur_az_deg=cur_az, cur_el_deg=cur_el, loc=loc,
        tag="[calibrate_rotation]", arrive_tolerance_deg=0.3,
    )
    _print(f"  arrived: az={new_az:+.3f}° el={new_el:+.3f}°")
    return new_az, new_el


# ---------- sightings I/O (for --no-move replay) ---------------------


def _sightings_to_json(sightings: list[Sighting]) -> str:
    out = []
    for s in sightings:
        d = asdict(s)
        d["landmark"] = asdict(s.landmark)
        out.append(d)
    return json.dumps(out, indent=2)


def _sightings_from_json(path: Path) -> list[Sighting]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[Sighting] = []
    for d in raw:
        lm_d = d["landmark"]
        lm = Landmark(**lm_d)
        s = Sighting(
            landmark=lm,
            encoder_az_deg=float(d["encoder_az_deg"]),
            encoder_el_deg=float(d["encoder_el_deg"]),
            true_az_deg=float(d["true_az_deg"]),
            true_el_deg=float(d["true_el_deg"]),
            slant_m=float(d["slant_m"]),
            t_unix=float(d["t_unix"]),
        )
        out.append(s)
    return out


# ---------- main -----------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--device", type=int, default=1)
    parser.add_argument("--out", type=Path, default=_CAL_PATH,
                        help="calibration output path (default device/mount_calibration.json)")
    parser.add_argument("--altitude-m", type=float, default=None,
                        help="Observer altitude in metres AMSL. Overrides --altitude-source.")
    parser.add_argument("--altitude-source", choices=("menu", "lookup", "prior", "prompt"),
                        default="menu",
                        help="Where to get the altitude from when --altitude-m is absent. "
                             "'menu' (default) shows an interactive chooser with a smart "
                             "default; 'lookup' hits Open-Meteo; 'prior' reuses the last "
                             "calibration's altitude; 'prompt' asks the user.")
    parser.add_argument("--yes-clear", action="store_true",
                        help="Non-interactive: clear prior calibration (backup to .bak) "
                             "before starting.")
    parser.add_argument("--keep-prior", action="store_true",
                        help="Non-interactive: keep prior calibration for seeding. "
                             "Conflicts with --yes-clear.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip mount motion and skip writing the JSON.")
    parser.add_argument("--no-move", action="store_true",
                        help="Skip mount motion; still reads encoder on 'ok' "
                             "unless combined with --sightings.")
    parser.add_argument("--sightings", type=Path, default=None,
                        help="Solve from a previously-saved sightings JSON "
                             "instead of running the REPL.")
    parser.add_argument("--save-sightings", type=Path, default=None,
                        help="Write captured sightings to JSON (for replay).")
    parser.add_argument("--force", action="store_true",
                        help="Write calibration even if residual RMS > 0.5°.")
    args = parser.parse_args(argv)

    if args.yes_clear and args.keep_prior:
        parser.error("--yes-clear and --keep-prior are mutually exclusive")
    if args.sightings is not None:
        return _main_replay(args)
    return _main_live(args)


# ---------- prior-calibration inspection -----------------------------


_KEEP_MAX_AGE_S = 6 * 3600
_KEEP_MAX_DISTANCE_M = 10.0


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
        if self.age_s is None or self.distance_from_current_m is None:
            return False
        return (
            self.age_s < _KEEP_MAX_AGE_S
            and self.distance_from_current_m < _KEEP_MAX_DISTANCE_M
        )


def _parse_calibrated_at(raw: str | None) -> datetime | None:
    """Parse the ``calibrated_at`` string emitted by both the old
    compass tool (``%Y-%m-%dT%H-%M-%S%z`` — dashes in the time AND the
    timezone offset) and any future ISO-8601 writer. Returns an aware
    datetime in UTC, or ``None`` if the input is missing / malformed."""
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
    # Last resort: try fromisoformat (handles Z and colon tz).
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _inspect_prior(
    path: Path, current_lat: float, current_lon: float,
) -> PriorInfo | None:
    """Parse the prior calibration JSON (if any) and return the age +
    distance metadata the clear-or-keep prompt uses. Returns ``None``
    when the file doesn't exist."""
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
    dt = _parse_calibrated_at(payload.get("calibrated_at") if isinstance(payload, dict) else None)
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


def _handle_clear_or_keep(
    args: argparse.Namespace, prior: PriorInfo | None,
) -> bool:
    """Return True if the caller should use the prior for seeding,
    False if it was (or never was) cleared.

    Side effect on "clear": atomic rename to ``<path>.bak`` so the
    user can undo.
    """
    if prior is None:
        return False  # nothing on disk; nothing to prompt about
    age_h = (prior.age_s / 3600.0) if prior.age_s is not None else None
    dist_m = prior.distance_from_current_m
    age_str = f"{age_h:.1f} h" if age_h is not None else "unknown age"
    dist_str = f"{dist_m:.1f} m" if dist_m is not None else "no observer on file"
    default_keep = prior.should_default_keep
    _print(f"[calibrate] prior calibration at {prior.path}:")
    _print(f"             age {age_str}, {dist_str} from current GPS → "
           f"default: {'keep' if default_keep else 'clear'}")

    if args.yes_clear:
        decision_keep = False
    elif args.keep_prior:
        decision_keep = True
    else:
        prompt = "Clear prior calibration? " + ("[y/N]: " if default_keep else "[Y/n]: ")
        try:
            raw = input(prompt).strip().lower()
        except EOFError:
            raise SystemExit("aborted at clear-or-keep prompt")
        if raw == "":
            decision_keep = default_keep
        elif raw in ("y", "yes"):
            decision_keep = False
        elif raw in ("n", "no"):
            decision_keep = True
        else:
            _print("  unrecognised answer; keeping prior.")
            decision_keep = True

    if decision_keep:
        _print("[calibrate] keeping prior calibration for seeding.")
        return True
    # Back up + remove so downstream seeding treats the scope as uncalibrated.
    bak = prior.path.with_suffix(prior.path.suffix + ".bak")
    try:
        prior.path.replace(bak)
        _print(f"[calibrate] moved {prior.path} → {bak}")
    except OSError as exc:
        _print(f"[calibrate] [warn] could not back up prior calibration: {exc}")
    return False


# ---------- altitude resolution --------------------------------------


def _prompt_altitude() -> float:
    while True:
        try:
            raw = input("observer altitude (metres AMSL): ").strip()
        except EOFError:
            raise SystemExit("aborted at altitude prompt")
        try:
            return float(raw)
        except ValueError:
            _print("  need a number (e.g. 2, 30, 100)")


def _resolve_altitude(
    args: argparse.Namespace,
    lat_deg: float, lon_deg: float,
    prior: PriorInfo | None, prior_kept: bool,
) -> float:
    """Decide observer altitude (metres AMSL).

    Priority: --altitude-m > --altitude-source (non-interactive) > menu.
    The menu shows only options that are actually available (prior
    entry only appears when a recent, local prior was kept).
    """
    if args.altitude_m is not None:
        return float(args.altitude_m)

    prior_available = (
        prior_kept
        and prior is not None
        and prior.observer_alt_m is not None
        and prior.distance_from_current_m is not None
        and prior.distance_from_current_m < _KEEP_MAX_DISTANCE_M
    )

    source = args.altitude_source
    if source == "prior":
        if not prior_available:
            raise SystemExit(
                "--altitude-source prior requested but no nearby prior "
                "calibration has a recorded altitude"
            )
        _print(f"[calibrate] altitude from prior calibration: "
               f"{prior.observer_alt_m:.2f} m AMSL")
        return float(prior.observer_alt_m)

    if source == "lookup":
        elev = lookup_elevation(lat_deg, lon_deg)
        _print(f"[calibrate] altitude from Open-Meteo: {elev:.2f} m AMSL")
        return elev

    if source == "prompt":
        return _prompt_altitude()

    # Interactive menu.
    return _altitude_menu(lat_deg, lon_deg, prior, prior_available)


def _altitude_menu(
    lat_deg: float, lon_deg: float,
    prior: PriorInfo | None, prior_available: bool,
) -> float:
    """Interactive altitude source chooser. Default is 'prior' if
    available (most accurate for re-runs), else 'lookup' if network
    is present, else 'manual'."""
    options: list[tuple[str, str]] = [("lookup", "elevation lookup (Open-Meteo)")]
    if prior_available:
        options.append(("prior", f"use prior calibration ({prior.observer_alt_m:.2f} m)"))
    options.append(("manual", "enter manually"))
    default_idx = 1 + (options.index(("prior", options[1][1])) if prior_available else 0)
    while True:
        _print("Observer altitude — pick a source:")
        for i, (_key, desc) in enumerate(options, start=1):
            marker = "  ← default" if i == default_idx else ""
            _print(f"  [{i}] {desc}{marker}")
        try:
            raw = input(f"choice [{default_idx}]: ").strip()
        except EOFError:
            raise SystemExit("aborted at altitude menu")
        if raw == "":
            idx = default_idx
        elif raw.isdigit() and 1 <= int(raw) <= len(options):
            idx = int(raw)
        else:
            _print("  out of range; try again")
            continue
        key = options[idx - 1][0]
        if key == "lookup":
            try:
                elev = lookup_elevation(lat_deg, lon_deg)
            except RuntimeError as exc:
                _print(f"  [lookup failed] {exc}")
                continue  # re-show menu
            _print(f"  → {elev:.2f} m AMSL")
            return elev
        if key == "prior":
            assert prior is not None and prior.observer_alt_m is not None
            _print(f"  → {prior.observer_alt_m:.2f} m AMSL")
            return float(prior.observer_alt_m)
        # manual
        return _prompt_altitude()


def _load_prior_frame(
    out_path: Path, site: ObserverSite,
) -> MountFrame | None:
    if not out_path.exists():
        return None
    try:
        return MountFrame.from_calibration_json(out_path, site=site)
    except Exception:
        return None


def _main_live(args: argparse.Namespace) -> int:
    cli = AlpacaClient(args.host, args.port, args.device)

    # Step 1: fetch GPS so both the staleness check and the altitude
    # menu can use the current observer coordinates.
    lat_deg, lon_deg = fetch_telescope_lonlat(cli)
    _print(f"[calibrate] telescope GPS: lat={lat_deg:+.6f}° lon={lon_deg:+.6f}°")

    # Step 2: inspect any prior calibration and ask whether to keep it.
    prior = _inspect_prior(args.out, lat_deg, lon_deg)
    prior_kept = _handle_clear_or_keep(args, prior)

    # Step 3: resolve altitude. GPS altitude isn't exposed by the scope,
    # so the options are: flag override, elevation lookup, reuse prior,
    # or prompt. Menu picks a sensible default based on what's available.
    alt_m = _resolve_altitude(args, lat_deg, lon_deg, prior, prior_kept)
    site = build_site(lat_deg=lat_deg, lon_deg=lon_deg, alt_m=alt_m)
    _print(f"[calibrate] observer @ lat={site.lat_deg:+.6f}° "
           f"lon={site.lon_deg:+.6f}° alt={site.alt_m:.1f} m")

    if not args.dry_run and not args.no_move:
        try:
            ensure_scenery_mode(cli)
            set_tracking(cli, False)
        except Exception as exc:
            _print(f"  [warn] scenery/tracking setup failed: {exc}")

    chosen = _choose_targets(site)
    prior_frame = _load_prior_frame(args.out, site) if prior_kept else None
    if prior_frame is not None:
        _print(f"[calibrate] seeding from existing calibration at {args.out}")

    # Working rotation used to predict the *next* landmark's encoder
    # pose. Starts from any prior calibration on disk; refined after
    # every successful sighting (yaw-only after #1, full 3-DOF once we
    # have ≥2). Drives `_initial_slew` so landmark #2 lands close to
    # the correct encoder position even if the prior was identity.
    working_frame = prior_frame

    sightings: list[Sighting] = []
    for i, (lm, true_az, true_el, slant) in enumerate(chosen, start=1):
        _print(f"\n[calibrate] landmark {i}/{len(chosen)}: "
               f"{lm.oas} {lm.name}")
        _print(f"  true (az, el) = ({true_az:.2f}°, {true_el:.2f}°)  "
               f"slant = {slant/1000:.2f} km")
        _print(f"  lighting: {'LIT (L-864/L-810/etc.)' if lm.lit else 'UNLIT — daylight only'}")
        target_az, target_el = _initial_slew(
            cli, site, lm, working_frame,
            dry_run=args.dry_run, no_move=args.no_move,
        )
        _print("  nudge the mount until the beacon is centered on the imager.")
        _print("  commands: 'h +0.2' (az), 'v -0.1' (el), 'show', 'ok', 'skip', 'quit'")
        rec = _nudge_loop(
            cli, target_az, target_el,
            dry_run=args.dry_run, no_move=args.no_move,
        )
        if rec is None:
            _print("  skipped.")
            continue
        enc_az, enc_el = rec
        sightings.append(Sighting(
            landmark=lm, encoder_az_deg=float(enc_az),
            encoder_el_deg=float(enc_el),
            true_az_deg=float(true_az), true_el_deg=float(true_el),
            slant_m=float(slant), t_unix=time.time(),
        ))

        # Progressive fit: yaw-only after the first sighting, full
        # 3-DOF once we have ≥2. Print residuals so the user can judge
        # whether the sighting landed on the beacon or on a nearby
        # bright object (outliers show up as >1° el residual).
        interim = solve_rotation(sightings, site)
        _print(f"  [progressive fit n={len(sightings)}, "
               f"dof={'yaw' if len(sightings) == 1 else '3'}] "
               f"yaw={interim.yaw_deg:+.3f}° "
               f"pitch={interim.pitch_deg:+.3f}° "
               f"roll={interim.roll_deg:+.3f}°  "
               f"residual RMS={interim.residual_rms_deg:.3f}°")
        for lm_rec in interim.per_landmark:
            _print(f"    {lm_rec['oas']}: "
                   f"d_az={lm_rec['residual_az_deg']:+.3f}° "
                   f"d_el={lm_rec['residual_el_deg']:+.3f}°")
        # Refresh the frame used for the next landmark's predictive slew.
        working_frame = MountFrame.from_euler_deg(
            yaw_deg=interim.yaw_deg,
            pitch_deg=interim.pitch_deg,
            roll_deg=interim.roll_deg,
            site=site,
        )

    if len(sightings) < 2:
        _print("\n[calibrate] need ≥2 sightings to solve; aborting without writing.")
        return 1

    if args.save_sightings is not None:
        args.save_sightings.write_text(
            _sightings_to_json(sightings), encoding="utf-8",
        )
        _print(f"[calibrate] sightings saved to {args.save_sightings}")

    sol = solve_rotation(sightings, site)
    _report_and_write(sol, site, args)
    return 0


def _main_replay(args: argparse.Namespace) -> int:
    """Solve from a saved sightings JSON — no mount, no network."""
    sightings = _sightings_from_json(args.sightings)
    if not sightings:
        _print("no sightings in file")
        return 1
    alt_m = args.altitude_m if args.altitude_m is not None else _prompt_altitude()
    # When replaying without a telescope, fall back to build_site() with
    # env vars; the caller can override via OBSERVER_LAT_DEG et al.
    from scripts.trajectory.observer import build_site
    site = build_site(alt_m=alt_m)
    _print(f"[replay] observer @ lat={site.lat_deg:+.6f}° "
           f"lon={site.lon_deg:+.6f}° alt={site.alt_m:.1f} m "
           f"(from env vars / defaults)")
    sol = solve_rotation(sightings, site)
    _report_and_write(sol, site, args)
    return 0


def _report_and_write(
    sol: RotationSolution, site: ObserverSite, args: argparse.Namespace,
) -> None:
    _print("\n[calibrate] 3-DOF rotation fit:")
    _print(f"  yaw   = {sol.yaw_deg:+8.3f}°")
    _print(f"  pitch = {sol.pitch_deg:+8.3f}°")
    _print(f"  roll  = {sol.roll_deg:+8.3f}°")
    _print(f"  residual RMS = {sol.residual_rms_deg:.3f}°")
    for lm_rec in sol.per_landmark:
        _print(f"    {lm_rec['oas']}: d_az={lm_rec['residual_az_deg']:+.3f}° "
               f"d_el={lm_rec['residual_el_deg']:+.3f}°")
    if sol.residual_rms_deg > 0.5 and not args.force:
        _print("\n[calibrate] residual RMS > 0.5° — refusing to write "
               "(pass --force to override).")
        return
    if args.dry_run:
        _print("\n[calibrate] --dry-run: skipping JSON write.")
        return
    write_calibration(args.out, sol, site, sol.per_landmark)
    _print(f"\n[calibrate] wrote {args.out}")


if __name__ == "__main__":
    raise SystemExit(main())
