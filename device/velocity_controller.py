"""Closed-loop velocity controller for the Seestar azimuth axis.

Wraps the firmware's time-bounded velocity command (`scope_speed_move`) in
a PD+feedforward control loop that re-issues the command each tick so the
mount tracks a desired azimuth target. The dur_sec on every issued command
is the firmware cap (10 s), acting as a safety TTL — if the loop stops
ticking for any reason the motor auto-terminates within 10 s.

Design notes
------------
- Firmware cap `dur_sec ≤ 10` and silently ignored above 10; firmware also
  clamps speed at ~1440 (see `_SPEED_PER_DEG_PER_SEC` calibration).
- Polling `scope_get_equ_coord` at ≥ 0.3 s is safe (does not cancel an
  active move).
- The mount re-engages sidereal tracking when the motor goes idle; callers
  should disable tracking (`set_tracking(False)`) for the duration of a
  sweep, otherwise the firmware can drive the mount at up to max slew
  speed toward stale goto targets after each stop.
- Stiction floor: speed < ~80 does not produce reliable motion. The
  controller uses two floors, `_VC_MIN_SPEED` and `_VC_FINE_MIN_SPEED`.
- The feedforward predictor uses a first-order plant model
  `rate(t) = r_ss · (1 − exp(−t/τ))` with τ defaulting to 0.8 s (fit
  from step-response data; see scripts/auto_level_tuning.md).

See `scripts/tune_vc.py` for the step-response characterization harness
that produced the calibration constants in this module.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time


# ---------------------------------------------------------------------------
# Firmware / calibration constants (empirically measured on a Seestar S50)
# ---------------------------------------------------------------------------

SPEED_PER_DEG_PER_SEC = 237   # rate °/s ≈ speed / 237 (verified ±1% speed 80..1440)
MIN_DUR_S = 5                 # firmware floor; dur_sec < 5 not used by convention
DUR_SEC_CAP = 10              # firmware ignores dur_sec > 10
MAIN_SPEED = 1440             # firmware-clamped max speed
MAIN_RATE_DEGS = 6.0          # ~6.09 °/s at speed=1440 (10 s burst avg)


# ---------------------------------------------------------------------------
# Velocity-controller tuning constants
# ---------------------------------------------------------------------------

VC_LOOP_DT_S = 0.5              # target control-loop period; real dt is HTTP-bound
VC_CMD_DUR_S = 10               # dur_sec on every scope_speed_move (firmware cap)
VC_KP = 0.3                     # proportional gain (°/s of rate per ° of error)
VC_KD = 0.4                     # derivative gain (°/s per (°/s measured rate))
VC_MAX_RATE_DEGS = 6.0
VC_MIN_SPEED = 100              # approach floor; < 80 is stiction-dominated
VC_FINE_MIN_SPEED = 80          # fine-finish floor (still in reliable-motion band)
VC_FINE_THRESHOLD_FACTOR = 4.0  # use fine floor when |error| <= this × tol
VC_MAIN_CLOSE_ENOUGH_DEG = 2.0
VC_STUCK_MIN_S = 2.0
VC_STUCK_MOVE_FRAC = 0.2
VC_MAX_HALVINGS = 4
VC_DEFAULT_TIMEOUT_S = 120
VC_TAU_S = 0.8                  # first-order τ for the feedforward predictor
VC_USE_PREDICTOR = True


@runtime_checkable
class MountClient(Protocol):
    """Any object exposing the Alpaca-style method_sync RPC."""

    def method_sync(self, method: str, params: Any = None) -> Any: ...


FallbackGotoFn = Callable[[MountClient, float, float, EarthLocation], bool]
"""Signature: (cli, target_az_deg, target_alt_deg, loc) -> True on arrival."""


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def wrap_pm180(deg: float) -> float:
    """Wrap an angle in degrees into the half-open interval [-180, +180).

    -180 is inclusive, +180 wraps back to -180 — same convention as Python's
    modulo on [0, 360).
    """
    return ((deg + 180.0) % 360.0) - 180.0


def unwrap_az_series(wrapped_samples: list[float]) -> list[float]:
    """Given an azimuth sample series wrapped to [-180, +180), return an
    unwrapped cumulative series suitable for fitting.

    Each per-step delta is interpreted modulo 360 via wrap_pm180: if two
    adjacent wrapped samples differ by more than 180, the true motion is
    assumed to be the shorter path (< 180). This is safe as long as the
    true per-sample delta is bounded below ±180 — at the S50's 6°/s
    firmware cap and sample intervals up to 30 s the implicit bound is
    ~180° per 30 s, which the caller must respect.

    The first element is returned as-is; subsequent elements accumulate
    wrap_pm180(sample[i] - sample[i-1]).
    """
    if not wrapped_samples:
        return []
    out = [wrapped_samples[0]]
    for i in range(1, len(wrapped_samples)):
        d = wrap_pm180(wrapped_samples[i] - wrapped_samples[i - 1])
        out.append(out[-1] + d)
    return out


def _rate_to_speed(rate_degs: float) -> int:
    """Convert a desired signed rate °/s to an unsigned firmware speed unit."""
    return int(round(abs(rate_degs) * SPEED_PER_DEG_PER_SEC))


def speed_move(cli: MountClient, speed: int, angle: int, dur_sec: int) -> None:
    """Issue a single scope_speed_move. Caller owns sequencing / timing."""
    cli.method_sync(
        "scope_speed_move",
        {"speed": int(speed), "angle": int(angle), "dur_sec": int(dur_sec)},
    )


def wait_for_mount_idle(
    cli: MountClient, timeout_s: float, poll_s: float = 0.3,
) -> tuple[bool, float]:
    """Poll mount state until move_type == "none" or timeout.

    Returns (idle, elapsed_s). Polling via get_device_state does NOT cancel
    an active scope_speed_move (probed at 0.3 s cadence).
    """
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = cli.method_sync("get_device_state", {"keys": ["mount"]})
            mt = resp["result"]["mount"].get("move_type", "none")
            if mt == "none":
                return True, time.monotonic() - t0
        except Exception:
            pass
        time.sleep(poll_s)
    return False, time.monotonic() - t0


def measure_altaz(cli: MountClient, loc: EarthLocation) -> tuple[float, float]:
    """Query RA/Dec and convert to (alt°, az°) with az wrapped to [-180, +180).

    Caller must guarantee the mount is not currently running a
    scope_speed_move — otherwise the read cancels it. Safe immediately
    before/after a burst when the motor is idle.
    """
    alt, az, _ = measure_altaz_timed(cli, loc)
    return alt, az


def measure_altaz_timed(
    cli: MountClient, loc: EarthLocation,
) -> tuple[float, float, Optional[float]]:
    """Like `measure_altaz` but also returns the firmware timestamp at
    which the position was captured (seconds, monotonic firmware uptime).

    Returns `(alt, az, firmware_t)`; `firmware_t` is None if the response
    lacks a `Timestamp` field (e.g. a non-firmware mock). The firmware
    timestamp eliminates HTTP-latency jitter from dt computations and is
    the correct clock for motion-onset / plant-fitting dt.

    Format reference: device/seestar_device.py:500 — responses look like
        {"jsonrpc":"2.0","Timestamp":"9507.244805160","method":...,
         "result":{"ra":...,"dec":...},"code":0,"id":...}
    """
    resp = cli.method_sync("scope_get_equ_coord")
    result = resp["result"]
    ra_h = float(result["ra"])
    dec_deg = float(result["dec"])
    aa = SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg).transform_to(
        AltAz(obstime=Time.now(), location=loc)
    )
    ts_raw = resp.get("Timestamp") if isinstance(resp, dict) else None
    fw_t: Optional[float] = None
    if ts_raw is not None:
        try:
            fw_t = float(ts_raw)
        except (TypeError, ValueError):
            fw_t = None
    return float(aa.alt.deg), wrap_pm180(float(aa.az.deg)), fw_t


def set_tracking(cli: MountClient, enabled: bool) -> None:
    """Enable/disable firmware sidereal tracking.

    Disable for auto-level sweeps: on stop the firmware otherwise drives
    the mount at up to max slew speed toward stale targets. Observed
    ~5 °/s backward drift between sweep steps until this was disabled.
    """
    try:
        cli.method_sync("scope_set_track_state", enabled)
    except Exception:
        # non-fatal; caller can log if needed
        pass


# ---------------------------------------------------------------------------
# Main control function
# ---------------------------------------------------------------------------

def move_azimuth_to_velocity(
    cli: MountClient,
    target_az_deg: float,
    cur_az_deg: float,
    loc: EarthLocation,
    target_alt_deg: float,
    tag: str = "",
    arrive_tolerance_deg: float = 0.5,
    position_logger: Any = None,
    timeout_s: float = VC_DEFAULT_TIMEOUT_S,
    kp: float = VC_KP,
    kd: float = VC_KD,
    max_rate_degs: float = VC_MAX_RATE_DEGS,
    loop_dt_s: float = VC_LOOP_DT_S,
    min_speed: int = VC_MIN_SPEED,
    fine_min_speed: int = VC_FINE_MIN_SPEED,
    fine_threshold_factor: float = VC_FINE_THRESHOLD_FACTOR,
    max_halvings: int = VC_MAX_HALVINGS,
    stuck_min_s: float = VC_STUCK_MIN_S,
    stuck_move_frac: float = VC_STUCK_MOVE_FRAC,
    use_predictor: bool = VC_USE_PREDICTOR,
    tau_s: float = VC_TAU_S,
    fallback_goto_fn: Optional[FallbackGotoFn] = None,
) -> tuple[float, float, dict]:
    """Drive the azimuth axis to `target_az_deg` via scope_speed_move.

    At each tick (nominally every loop_dt_s):
      1. Measure position (RA/Dec → alt/az, wrap az).
      2. Compute error and derivative (measured_rate from Δpos/Δt).
      3. Either: one-step feedforward (predictor) OR pure PD.
      4. Clamp desired rate to rate_ceiling; convert to (speed, angle).
      5. Issue scope_speed_move(speed, angle, dur_sec=VC_CMD_DUR_S).

    Arrival: two consecutive ticks with |error| <= arrive_tolerance_deg and
    motor stopped.

    Stuck detection: if we've been commanding motion but position barely
    moved over a rolling window, halve the rate ceiling. Up to
    max_halvings halvings, then invoke fallback_goto_fn (if provided).

    Returns (measured_alt, measured_az, stats).
    """
    stats = {
        "commands_issued": 0,
        "rate_ceiling_halvings": 0,
        "stuck_bail": False,
        "fallback_goto_used": False,
        "elapsed_s": 0.0,
        "iterations": 0,
        "sign_flips": 0,
        "loop_dt_mean_s": 0.0,
        "loop_dt_max_s": 0.0,
        "final_residual_deg": None,
    }

    rate_ceiling = max_rate_degs
    last_speed = 0
    last_angle = 0
    last_az = cur_az_deg
    last_t: Optional[float] = None
    last_error_sign = 0
    loop_dts: list[float] = []
    stuck_since_t: Optional[float] = None
    stuck_since_az = cur_az_deg

    def _issue(speed: int, angle: int, event: str) -> None:
        nonlocal last_speed, last_angle
        speed_move(cli, speed, angle, VC_CMD_DUR_S)
        last_speed = speed
        last_angle = angle
        stats["commands_issued"] += 1
        if position_logger is not None:
            position_logger.mark_event(
                event, speed=speed, angle=angle, dur_sec=VC_CMD_DUR_S,
            )

    t0 = time.monotonic()
    fallback_reason: Optional[str] = None
    consecutive_within_tol = 0

    if position_logger is not None:
        position_logger.set_phase("vc_move")

    while True:
        elapsed = time.monotonic() - t0
        stats["elapsed_s"] = elapsed
        stats["iterations"] += 1
        if elapsed > timeout_s:
            fallback_reason = f"velocity loop timed out after {elapsed:.1f}s"
            break

        measured_alt, measured_az = measure_altaz(cli, loc)
        now = time.monotonic()
        error = wrap_pm180(target_az_deg - measured_az)

        if last_t is not None:
            dt = now - last_t
            loop_dts.append(dt)
            signed_move = wrap_pm180(measured_az - last_az)
            measured_rate = signed_move / dt if dt > 0 else 0.0
        else:
            dt = 0.0
            measured_rate = 0.0
        last_az = measured_az
        last_t = now

        cur_sign = 1 if error > 0 else (-1 if error < 0 else 0)
        if cur_sign != 0 and last_error_sign != 0 and cur_sign != last_error_sign:
            stats["sign_flips"] += 1
        if cur_sign != 0:
            last_error_sign = cur_sign

        if abs(error) <= arrive_tolerance_deg:
            consecutive_within_tol += 1
            if last_speed != 0:
                _issue(0, 0, "vc_stop")
            if consecutive_within_tol >= 2:
                stats["final_residual_deg"] = error
                if loop_dts:
                    stats["loop_dt_mean_s"] = sum(loop_dts) / len(loop_dts)
                    stats["loop_dt_max_s"] = max(loop_dts)
                return measured_alt, measured_az, stats
            time.sleep(loop_dt_s)
            continue
        else:
            consecutive_within_tol = 0

        # Stuck detection.
        if last_speed >= fine_min_speed:
            if stuck_since_t is None:
                stuck_since_t = time.monotonic()
                stuck_since_az = measured_az
            else:
                window = time.monotonic() - stuck_since_t
                window_moved = abs(wrap_pm180(measured_az - stuck_since_az))
                expected = (last_speed / SPEED_PER_DEG_PER_SEC) * window
                if window >= stuck_min_s and window_moved < max(
                    0.3, stuck_move_frac * expected,
                ):
                    if stats["rate_ceiling_halvings"] < max_halvings:
                        new_ceiling = max(
                            min_speed / SPEED_PER_DEG_PER_SEC,
                            rate_ceiling / 2,
                        )
                        print(
                            f"{tag} vc: stuck (moved {window_moved:.2f}° vs "
                            f"expected ~{expected:.1f}° over {window:.1f}s); "
                            f"halving rate ceiling {rate_ceiling:.2f} → "
                            f"{new_ceiling:.2f}°/s",
                            flush=True,
                        )
                        if position_logger is not None:
                            position_logger.mark_event(
                                "vc_stuck_halve",
                                old_ceiling=rate_ceiling,
                                new_ceiling=new_ceiling,
                                window_moved=window_moved,
                                window_s=round(window, 3),
                            )
                        rate_ceiling = new_ceiling
                        stats["rate_ceiling_halvings"] += 1
                        stuck_since_t = time.monotonic()
                        stuck_since_az = measured_az
                    else:
                        fallback_reason = (
                            f"velocity loop stuck at floor rate "
                            f"{rate_ceiling:.2f}°/s "
                            f"(moved {window_moved:.2f}° in {window:.1f}s)"
                        )
                        stats["stuck_bail"] = True
                        break
        else:
            stuck_since_t = None
            stuck_since_az = measured_az

        # Control law: predictor OR pure PD.
        if use_predictor and dt > 0 and last_t is not None:
            G = tau_s * (1.0 - math.exp(-dt / tau_s))
            denom = dt - G
            if denom > 1e-3:
                desired_rate = (error - measured_rate * G) / denom
            else:
                desired_rate = kp * error - kd * measured_rate
        else:
            desired_rate = kp * error - kd * measured_rate
        desired_rate = max(-rate_ceiling, min(rate_ceiling, desired_rate))
        new_angle = 0 if desired_rate >= 0 else 180

        floor_speed = (
            fine_min_speed
            if abs(error) <= fine_threshold_factor * arrive_tolerance_deg
            else min_speed
        )
        raw_speed = _rate_to_speed(desired_rate)
        new_speed = max(floor_speed, raw_speed) if raw_speed > 0 else 0

        print(
            f"{tag} vc iter={stats['iterations']} dt={dt:.2f}s: "
            f"error={error:+.3f}° measured_az={measured_az:+.3f}° "
            f"measured_rate={measured_rate:+.2f}°/s "
            f"cmd speed={new_speed} angle={new_angle} "
            f"(desired_rate={desired_rate:+.2f}°/s, "
            f"ceiling={rate_ceiling:.2f})",
            flush=True,
        )
        _issue(new_speed if new_speed > 0 else 0, new_angle, "vc_issue")
        time.sleep(loop_dt_s)

    if loop_dts:
        stats["loop_dt_mean_s"] = sum(loop_dts) / len(loop_dts)
        stats["loop_dt_max_s"] = max(loop_dts)

    if last_speed != 0:
        _issue(0, 0, "vc_stop")
        wait_for_mount_idle(cli, timeout_s=3.0)

    if fallback_reason is not None:
        print(f"{tag} FALLBACK: {fallback_reason}", flush=True)
        if fallback_goto_fn is not None:
            stats["fallback_goto_used"] = True
            if position_logger is not None:
                position_logger.set_phase("vc_fallback_goto")
                position_logger.mark_event("vc_fallback_issue", reason=fallback_reason)
            ok = bool(fallback_goto_fn(cli, target_az_deg, target_alt_deg, loc))
            if ok:
                print(f"{tag} fallback: iscope arrived", flush=True)
            else:
                print(f"{tag} WARNING: fallback goto did not arrive", flush=True)
            measured_alt, measured_az = measure_altaz(cli, loc)
            stats["final_residual_deg"] = wrap_pm180(target_az_deg - measured_az)
            return measured_alt, measured_az, stats
        else:
            # No fallback available — return whatever we got.
            stats["final_residual_deg"] = error
            return measured_alt, measured_az, stats

    measured_alt, measured_az = measure_altaz(cli, loc)
    stats["final_residual_deg"] = wrap_pm180(target_az_deg - measured_az)
    return measured_alt, measured_az, stats


# ---------------------------------------------------------------------------
# Astropy coordinate helpers (shared by iscope-goto fallback, the
# position logger, and any CLI that wants to convert between frames).
# ---------------------------------------------------------------------------

def radec_to_altaz(
    ra_h: float, dec_deg: float, loc: EarthLocation, t: Time,
) -> tuple[float, float]:
    c = SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg)
    altaz = c.transform_to(AltAz(obstime=t, location=loc))
    return float(altaz.alt.deg), float(altaz.az.deg)


def altaz_to_radec(
    alt_deg: float, az_deg: float, loc: EarthLocation, t: Time,
) -> tuple[float, float]:
    altaz = SkyCoord(
        alt=alt_deg * u.deg,
        az=az_deg * u.deg,
        frame=AltAz(obstime=t, location=loc),
    )
    icrs = altaz.icrs
    return float(icrs.ra.hour), float(icrs.dec.deg)


def angular_distance_deg(
    ra1_h: float, dec1_d: float, ra2_h: float, dec2_d: float,
) -> float:
    """Great-circle angular distance (degrees) between two RA/Dec points.

    RA in hours, Dec in degrees. Uses the spherical law of cosines, clamped
    to guard against floating-point drift pushing |cos| slightly past 1.
    """
    ra1 = math.radians(ra1_h * 15.0)
    ra2 = math.radians(ra2_h * 15.0)
    d1 = math.radians(dec1_d)
    d2 = math.radians(dec2_d)
    cos_d = (
        math.sin(d1) * math.sin(d2)
        + math.cos(d1) * math.cos(d2) * math.cos(ra1 - ra2)
    )
    cos_d = max(-1.0, min(1.0, cos_d))
    return math.degrees(math.acos(cos_d))


# ---------------------------------------------------------------------------
# Iscope (firmware goto) helpers — used for initial positioning and as the
# fallback path when the velocity loop times out or gets stuck.
# ---------------------------------------------------------------------------

def ensure_scenery_mode(cli: MountClient) -> None:
    """Enter scenery (terrestrial) view mode (no target)."""
    cli.method_sync("iscope_start_view", {"mode": "scenery"})
    time.sleep(1.5)


def issue_slew(
    cli: MountClient, az_deg: float, alt_deg: float, loc: EarthLocation,
) -> tuple[float, float]:
    """Send iscope_start_view (scenery + target). Returns the commanded RA/Dec
    so the caller can compute distance-to-target in Python.

    Uses dict-params so the app's verify-injection transform doesn't mangle
    the payload (list-params would be wrapped as [[list], 'verify']).
    """
    ra_h, dec_deg = altaz_to_radec(alt_deg, az_deg, loc, Time.now())
    cli.method_sync(
        "iscope_start_view",
        {
            "mode": "scenery",
            "target_ra_dec": [ra_h, dec_deg],
            "target_name": f"autolevel_az{az_deg:.0f}",
            "lp_filter": False,
        },
    )
    return ra_h, dec_deg


def wait_until_near_target(
    cli: MountClient,
    target_ra_h: float,
    target_dec_d: float,
    tolerance_deg: float = 0.5,
    timeout: float = 90.0,
    poll: float = 0.3,
    stall_threshold_s: float = 5.0,
    stall_delta_deg: float = 0.05,
    nudge_fn: Optional[Callable[[float], Optional[tuple[float, float]]]] = None,
    nudge_multiplier: float = 10.0,
) -> tuple[bool, Optional[float], bool]:
    """Poll actual RA/Dec via scope_get_equ_coord; compute distance in Python.

    Returns (ok, last_dist_deg, stalled).

    - `ok` is True if within `tolerance_deg` of target.
    - `stalled` is True if the scope's reported position hasn't changed by
      more than `stall_delta_deg` over the last `stall_threshold_s` seconds
      (but we also aren't close to target yet) — caller should re-issue slew.

    When `nudge_fn` is provided, it's called exactly once — the first time
    the reported distance falls below `nudge_multiplier * tolerance_deg` but
    is still above `tolerance_deg`. Firmware sometimes decelerates and stops
    just outside tolerance; a second slew command at short range nudges it
    the rest of the way. The callback may return a new (ra_h, dec_d) tuple
    (because the fresh altaz→radec conversion uses a later timestamp), in
    which case we switch our distance comparison to that new target.
    """
    deadline = time.time() + timeout
    last_dist: Optional[float] = None
    last_move_t = time.time()
    last_pos: Optional[tuple[float, float]] = None
    nudge_threshold = tolerance_deg * nudge_multiplier
    nudged = False
    tgt_ra, tgt_dec = target_ra_h, target_dec_d
    while time.time() < deadline:
        try:
            resp = cli.method_sync("scope_get_equ_coord")
            ra = float(resp["result"]["ra"])
            dec = float(resp["result"]["dec"])
        except Exception:
            time.sleep(poll)
            continue
        dist = angular_distance_deg(ra, dec, tgt_ra, tgt_dec)
        last_dist = dist
        if dist <= tolerance_deg:
            return True, dist, False

        if not nudged and dist <= nudge_threshold and nudge_fn is not None:
            nudged = True
            new_target = nudge_fn(dist)
            if new_target is not None:
                tgt_ra, tgt_dec = new_target
            # reset stall clock after the nudge — scope about to accelerate again
            last_move_t = time.time()
            last_pos = None

        if last_pos is not None:
            moved = angular_distance_deg(ra, dec, last_pos[0], last_pos[1])
            if moved >= stall_delta_deg:
                last_move_t = time.time()
        last_pos = (ra, dec)
        if time.time() - last_move_t > stall_threshold_s:
            return False, dist, True

        time.sleep(poll)
    return False, last_dist, False


_FALLBACK_GOTO_TOL_DEG = 3.0
_FALLBACK_GOTO_TIMEOUT_S = 60


def iscope_fallback_goto(
    cli: MountClient,
    target_az_deg: float,
    target_alt_deg: float,
    loc: EarthLocation,
) -> bool:
    """Standard iscope-goto fallback for the velocity loop.

    Matches `FallbackGotoFn` — pass it directly as `fallback_goto_fn=` to
    `move_azimuth_to_velocity`. Uses the default 3°/60 s tolerance.
    """
    tgt_ra, tgt_dec = issue_slew(cli, target_az_deg, target_alt_deg, loc)
    ok, _dist, _ = wait_until_near_target(
        cli,
        target_ra_h=tgt_ra,
        target_dec_d=tgt_dec,
        tolerance_deg=_FALLBACK_GOTO_TOL_DEG,
        timeout=_FALLBACK_GOTO_TIMEOUT_S,
        stall_threshold_s=5.0,
    )
    return bool(ok)


# ---------------------------------------------------------------------------
# Position logger — background thread that samples mount position to a
# JSONL file so tuning runs can be visualized on the /velocity_controller
# page. Annotated via set_target / set_phase / mark_event from the main
# thread.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class PositionLogger:
    """Background thread that samples mount position every `poll_interval_s`
    and appends each sample as a JSONL record.

    The main thread annotates state via `set_target(az, alt)` and
    `set_phase(name, step=...)`; those values are copied into each poll
    record. Also exposes `mark_event(name, **extra)` to write one-off
    event records interleaved with the polled samples.

    Alpaca exposes no subscription API for position, so this polls
    `scope_get_equ_coord` and converts to alt/az via astropy. Polling at
    0.5 s is safe — probed at 0.3 s without cancelling scope_speed_move.
    """

    def __init__(
        self,
        cli: MountClient,
        loc: EarthLocation,
        path: str | os.PathLike,
        poll_interval_s: float = 0.5,
    ):
        self.cli = cli
        self.loc = loc
        self.path = Path(path)
        self.poll_interval = poll_interval_s
        self._commanded_az: Optional[float] = None
        self._commanded_alt: Optional[float] = None
        self._phase: str = "init"
        self._step: Optional[int] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file = None
        self._write_lock = threading.Lock()

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", buffering=1)  # line-buffered
        self._write({
            "t": _now_iso(),
            "kind": "header",
            "poll_interval_s": self.poll_interval,
        })
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="PositionLogger", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._file is not None:
            self._write({"t": _now_iso(), "kind": "footer"})
            self._file.close()
            self._file = None

    def set_target(
        self, az_deg: Optional[float], alt_deg: Optional[float],
    ) -> None:
        with self._lock:
            self._commanded_az = az_deg
            self._commanded_alt = alt_deg

    def set_phase(self, phase: str, step: Optional[int] = None) -> None:
        with self._lock:
            self._phase = phase
            if step is not None:
                self._step = step

    def mark_event(self, event: str, **extra) -> None:
        if self._file is None:
            return
        with self._lock:
            snapshot = {
                "phase": self._phase,
                "step": self._step,
                "commanded_az_deg": self._commanded_az,
                "commanded_alt_deg": self._commanded_alt,
            }
        rec = {
            "t": _now_iso(), "kind": "event", "event": event,
            **snapshot, **extra,
        }
        self._write(rec)

    def _write(self, rec: dict) -> None:
        if self._file is None:
            return
        with self._write_lock:
            try:
                self._file.write(json.dumps(rec) + "\n")
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                rec = self._sample()
                self._write(rec)
            except Exception as e:
                self._write({
                    "t": _now_iso(),
                    "kind": "error",
                    "error": repr(e),
                })
            if self._stop_event.wait(self.poll_interval):
                break

    def _sample(self) -> dict:
        resp = self.cli.method_sync("scope_get_equ_coord")
        ra = float(resp["result"]["ra"])
        dec = float(resp["result"]["dec"])
        aa = SkyCoord(ra=ra * u.hourangle, dec=dec * u.deg).transform_to(
            AltAz(obstime=Time.now(), location=self.loc)
        )
        alt = float(aa.alt.deg)
        az = wrap_pm180(float(aa.az.deg))
        ts_raw = resp.get("Timestamp") if isinstance(resp, dict) else None
        fw_t: Optional[float] = None
        if ts_raw is not None:
            try:
                fw_t = float(ts_raw)
            except (TypeError, ValueError):
                fw_t = None
        with self._lock:
            phase = self._phase
            step = self._step
            cmd_az = self._commanded_az
            cmd_alt = self._commanded_alt
        return {
            "t": _now_iso(),
            "fw_t": fw_t,
            "kind": "sample",
            "phase": phase,
            "step": step,
            "ra_h": ra,
            "dec_deg": dec,
            "alt_deg": alt,
            "az_deg": az,
            "commanded_az_deg": cmd_az,
            "commanded_alt_deg": cmd_alt,
        }
