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

import math
import time
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
    resp = cli.method_sync("scope_get_equ_coord")
    result = resp["result"]
    ra_h = float(result["ra"])
    dec_deg = float(result["dec"])
    aa = SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg).transform_to(
        AltAz(obstime=Time.now(), location=loc)
    )
    return float(aa.alt.deg), wrap_pm180(float(aa.az.deg))


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
