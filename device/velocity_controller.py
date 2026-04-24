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
PLAN_MAX_RATE_DEGS = 5.0      # Per-axis planner cap (°/s). 1°/s below the firmware
                              # clamp (~6°/s at speed=1440) so the feedback loop has
                              # headroom to add correction velocity without saturating.


# ---------------------------------------------------------------------------
# Velocity-controller tuning constants
# ---------------------------------------------------------------------------

VC_LOOP_DT_S = 0.5              # target control-loop period; real dt is HTTP-bound
VC_CMD_DUR_S = 5                # dur_sec TTL on every scope_speed_move.
                                # Sized from observed update-to-update p99
                                # (~2.0s across step_response, controller,
                                # chirp data) with ~2.5x headroom. Shorter
                                # than the 10s firmware cap so a controller
                                # crash commits to at most v_max*5 = 30° of
                                # uncommanded motion instead of 60°. Still
                                # above the 5s MIN_DUR_S floor.
VC_KP = 0.3                     # proportional gain (°/s of rate per ° of error)
VC_KD = 0.4                     # derivative gain (°/s per (°/s measured rate))
VC_MAX_RATE_DEGS = 6.0
VC_MIN_SPEED = 40               # approach floor. Phase 1 deadband probe shows
                                # motion at 100% of linear model (speed/237)
                                # for every tested speed 20..200; the true
                                # stiction floor is below 20. 40 keeps a safety
                                # margin without being excessively conservative.
VC_FINE_MIN_SPEED = 20          # fine-finish floor. Phase 1: speed=20 produces
                                # +0.085 °/s (matches expected +0.084 within 1%).
VC_FINE_THRESHOLD_FACTOR = 4.0  # use fine floor when |error| <= this × tol
VC_MAIN_CLOSE_ENOUGH_DEG = 2.0
VC_STUCK_MIN_S = 2.0
VC_STUCK_MOVE_FRAC = 0.2
VC_MAX_HALVINGS = 4
VC_DEFAULT_TIMEOUT_S = 120
VC_TAU_S = 0.348                # first-order τ for the plant model. Used by:
                                # (1) move_azimuth_to_ff / move_elevation_to_ff
                                #     / move_to_ff for velocity feedforward
                                #     v_cmd = v_ref + τ·a_ref + FB;
                                # (2) legacy move_azimuth_to_pd deadbeat
                                #     predictor.
                                # Phase 1 fit (fw-timestamped step_response data,
                                # 20 bursts, trimmed to motor_active window):
                                # tau=0.348s, k_dc=0.996, train pos-RMSE 0.70°.
                                # Previous default was 0.8s; the high-τ value
                                # came from un-trimmed per-burst fits.
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
    """Issue a single scope_speed_move. Caller owns sequencing / timing.

    Refuses while `SunSafetyMonitor` holds the emergency lockout — see
    `device.sun_safety`. The monitor's own jog bypasses this wrapper by
    calling `cli.method_sync("scope_speed_move", ...)` directly, so it
    stays the single privileged motion source during the lockout window.
    """
    # Lazy import so this module stays importable without the sun_safety
    # module in minimal environments (scripts, unit tests of other parts).
    from device.sun_safety import SunSafetyLocked, sun_safety_is_locked_out
    if sun_safety_is_locked_out():
        raise SunSafetyLocked(
            "sun-safety emergency lockout active — speed_move refused"
        )
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
    """Read raw motor-encoder alt/az + firmware timestamp.

    Source: `scope_get_horiz_coord` → `[alt_encoder, az_encoder]`. Both
    values are in the mount's internal encoder frame — NOT sky alt/az.
    They're invariant to tripod rotation, independent of compass, and
    update live whenever the respective motor moves.

    Previously this used `scope_get_equ_coord` + astropy conversion,
    which only tracks live when the scope has been plate-solve-aligned
    in the current power session — without alignment, ra/dec is stale.
    The raw encoder path is always correct, so we use it unconditionally.

    `loc` is kept in the signature for backward compat but unused.

    Returns `(alt, az, firmware_t)`. `az` is wrapped to `[-180, +180)`.
    On a malformed response, retry once before raising — single-sample
    glitches shouldn't tear down a multi-second trajectory.
    """
    del loc  # intentionally unused; raw encoder values are location-agnostic

    def _call_once():
        resp = cli.method_sync("scope_get_horiz_coord")
        if not isinstance(resp, dict) or "result" not in resp:
            return None, resp
        return resp, resp
    resp, raw = _call_once()
    if resp is None:
        time.sleep(0.1)
        resp, raw = _call_once()
    if resp is None:
        raise RuntimeError(
            f"scope_get_horiz_coord returned unexpected payload: {raw!r}"
        )
    result = resp["result"]
    # Firmware returns [alt, az] as a 2-element list.
    alt_deg = float(result[0])
    az_deg = float(result[1])
    ts_raw = resp.get("Timestamp")
    fw_t: Optional[float] = None
    if ts_raw is not None:
        try:
            fw_t = float(ts_raw)
        except (TypeError, ValueError):
            fw_t = None
    return alt_deg, wrap_pm180(az_deg), fw_t


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
        tick_start = time.monotonic()
        elapsed = tick_start - t0
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
        # Deadline-based pacing: loop_dt_s is a MINIMUM tick period, not a
        # fixed delay. When RPCs already take longer than loop_dt_s (the
        # common case: two ~500 ms Alpaca round-trips = ~1 s per tick), this
        # sleep is zero and we iterate as fast as the HTTP proxy allows.
        remaining = loop_dt_s - (time.monotonic() - tick_start)
        if remaining > 0:
            time.sleep(remaining)

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
# Pure feedforward controller (Phase 2.1)
# ---------------------------------------------------------------------------


def move_azimuth_to_ff(
    cli: MountClient,
    target_az_deg: float,
    cur_az_deg: float,
    loc: EarthLocation,
    target_alt_deg: float,
    tag: str = "",
    position_logger: Any = None,
    v_max: float = PLAN_MAX_RATE_DEGS,
    a_max: float = 4.0,
    j_max: float = 12.0,
    tick_dt: float = 0.5,
    settle_s: float = 1.5,
    cold_start_lag_s: float = 0.0,
    profile: str = "scurve",
    az_forbidden_deg: Optional[float] = None,
    az_limits: Optional[Any] = None,  # plant_limits.AzimuthLimits
    az_tracker: Optional[Any] = None,  # plant_limits.CumulativeAzTracker
    kp_pos: float = 0.5,
    v_corr_max: float = 2.0,
    arrive_tolerance_deg: float = 0.3,
    settle_max_s: float = 5.0,
    converged_ticks_required: int = 2,
    fallback_residual_deg: float = 2.0,
    fallback_goto_fn: Optional[FallbackGotoFn] = None,
) -> tuple[float, float, dict]:
    """Closed-loop FF+FB azimuth mover.

    At every tick: `v_cmd = v_ff(t) + kp_pos * position_error`, clamped
    to ±v_corr_max for the correction term and ±v_max for the total.

    The plant's trajectory-time is derived from the firmware `Timestamp`
    (not host monotonic) so the error is compared against the correct
    reference despite RPC latency jitter. After the trajectory ends the
    loop keeps running at ref_vel=0 + correction until |error| is within
    `arrive_tolerance_deg` for `converged_ticks_required` consecutive
    ticks or `settle_max_s` elapses.

    Plant model: first-order lag with tau = VC_TAU_S (~0.348 s), k_dc ≈ 1.
    Phase 1 showed warm dead time ≈ 0 s; cold-start is ~0.5 s. The
    closed-loop P feedback absorbs cold-start lag automatically
    (position error accumulates during dead time → v_corr saturates to
    v_corr_max → plant catches up once warm). `cold_start_lag_s` > 0
    adds a pre-trajectory hold, only useful when running pure-FF
    (kp_pos=0) for research.

    Args:
        v_max, a_max, j_max: trajectory planner limits.
        profile: "scurve" (default, smoother first-tick cmd) or "trapezoid".
        tick_dt: command-issue interval (s). ~0.5 s given RPC round-trip.
        settle_s: delay after the final `speed=0` stop before reading
            final position. Covers plant first-order decay + poll wiggle.
        kp_pos: position-error gain (1/s). v_corr = kp_pos · pos_err.
            Set 0 to disable feedback (legacy pure-FF).
        v_corr_max: max |v_corr| in deg/s. Keeps v_corr bounded during
            cold-start windup.
        arrive_tolerance_deg: post-trajectory convergence threshold.
        settle_max_s: max time after trajectory end to wait for convergence.
        converged_ticks_required: # consecutive ticks below tolerance
            required to exit early.
        fallback_residual_deg: if final |residual| exceeds this and
            fallback_goto_fn is provided, invoke iscope fallback.

    Returns (measured_alt, measured_az, stats).
    """
    # Import here to avoid circular imports (trajectory depends on vc).
    from device.trajectory import scurve_profile, trapezoidal_profile

    if profile not in ("trapezoid", "scurve"):
        raise ValueError(f"unknown profile {profile!r}; expected trapezoid or scurve")

    stats = {
        "controller": "ff_fb" if kp_pos > 0 else "ff",
        "profile": profile,
        "kp_pos": kp_pos,
        "v_corr_max": v_corr_max,
        "trajectory_duration_s": 0.0,
        "commands_issued": 0,
        "ticks": 0,
        "tick_dt_mean_s": 0.0,
        "tick_dt_max_s": 0.0,
        "final_residual_deg": None,
        "max_tracking_err_deg": 0.0,
        "mean_tracking_err_deg": 0.0,
        "max_position_error_deg": 0.0,
        "max_v_corr_degs": 0.0,
        "settle_time_s": 0.0,
        "converged": False,
        "fallback_goto_used": False,
        "wall_time_s": 0.0,
        "cold_start_lag_s": cold_start_lag_s,
        # Compat keys for StepResult harness (shared with PD/velocity mode)
        "iterations": 0,
        "sign_flips": 0,
        "rate_ceiling_halvings": 0,
        "loop_dt_mean_s": 0.0,
        "loop_dt_max_s": 0.0,
        "stuck_bail": False,
    }

    # Cable-wrap-aware planning: when `az_limits` + `az_tracker` are
    # given, pick a cumulative target that stays within the mount's
    # usable cable range, and plan in cumulative (unwrapped) space via
    # `wrap_target=False`. Otherwise fall back to the legacy wrapped
    # planner with `az_forbidden_deg`.
    use_cumulative = az_limits is not None and az_tracker is not None
    if use_cumulative:
        from device.plant_limits import pick_cum_target
        p0_plan = az_tracker.cum_az_deg
        p_target_plan = pick_cum_target(
            cum_cur_deg=p0_plan,
            wrapped_cur_deg=cur_az_deg,
            wrapped_target_deg=target_az_deg,
            limits=az_limits,
        )
    else:
        p0_plan = cur_az_deg
        p_target_plan = target_az_deg

    if profile == "scurve":
        traj = scurve_profile(
            p0=p0_plan, v0=0.0, p_target=p_target_plan,
            v_max=v_max, a_max=a_max, j_max=j_max, tick_dt=tick_dt,
            t_offset=cold_start_lag_s,
            az_forbidden_deg=az_forbidden_deg,
            wrap_target=not use_cumulative,
        )
    else:
        traj = trapezoidal_profile(
            p0=p0_plan, v0=0.0, p_target=p_target_plan,
            v_max=v_max, a_max=a_max, tick_dt=tick_dt,
            t_offset=cold_start_lag_s,
            az_forbidden_deg=az_forbidden_deg,
            wrap_target=not use_cumulative,
        )
    stats["trajectory_duration_s"] = traj.total_duration

    if traj.total_duration == 0.0:
        # Already at target; just measure and return.
        measured_alt, measured_az = measure_altaz(cli, loc)
        stats["final_residual_deg"] = wrap_pm180(target_az_deg - measured_az)
        return measured_alt, measured_az, stats

    if position_logger is not None:
        position_logger.set_phase("ff_move")
        position_logger.mark_event(
            "ff_start",
            target_az=target_az_deg, cur_az=cur_az_deg,
            traj_duration_s=traj.total_duration,
            v_max=v_max, a_max=a_max, j_max=j_max, tick_dt=tick_dt,
            cold_start_lag_s=cold_start_lag_s, profile=profile,
            kp_pos=kp_pos, v_corr_max=v_corr_max,
            az_forbidden_deg=az_forbidden_deg,
        )

    # Prime: baseline fw_t so `t_plant = fw_t - fw_t_start` maps firmware
    # clock into trajectory time. The first sample is taken here, and the
    # trajectory-time clock begins from this fw_t.
    _, _, fw_t_start = measure_altaz_timed(cli, loc)
    t_wall_start = time.monotonic()

    tick_dts: list[float] = []
    tracking_errs: list[float] = []
    position_errs_abs: list[float] = []
    prev_tick_t = t_wall_start
    tick_idx = 0
    converged_count = 0
    t_settle_enter = None  # wall time when loop entered post-trajectory phase

    while True:
        now = time.monotonic()
        t_rel = now - t_wall_start

        # Measure plant first so the correction uses fresh data.
        _, measured_az, fw_t_now = measure_altaz_timed(cli, loc)

        # Advance cumulative tracker (if any) with the fresh wrapped reading.
        if az_tracker is not None:
            az_tracker.update(measured_az)

        # Plant's trajectory-time (fw-clock based for RPC-jitter immunity).
        if fw_t_now is not None and fw_t_start is not None:
            t_plant = fw_t_now - fw_t_start
        else:
            t_plant = t_rel  # fallback if firmware lacks Timestamp
        t_plant_clamped = max(0.0, min(t_plant, traj.total_duration))

        # Single reference: use t_plant so ref.pos is compared against the
        # plant state at the same timestamp (error signal) AND ref.vel
        # is the trajectory rate at "now" as the plant sees it. Splitting
        # into two refs (one at t_rel for cmd, one at t_plant for error)
        # introduces a phase offset equal to RPC latency.
        # When planning in cumulative coords, ref.pos lives in the same
        # unwrapped frame as az_tracker.cum_az_deg and the trajectory can
        # span multiple wraps — diff them directly. Wrapped mode compares
        # against the wrapped measurement with wrap_pm180.
        ref = traj.sample(t_plant_clamped)
        if use_cumulative:
            position_error = ref.pos - az_tracker.cum_az_deg
        else:
            position_error = wrap_pm180(ref.pos - measured_az)

        # P-term feedback with clamp.
        v_corr = kp_pos * position_error
        if v_corr > v_corr_max:
            v_corr = v_corr_max
        elif v_corr < -v_corr_max:
            v_corr = -v_corr_max

        # Feedforward: invert the first-order plant lag so the commanded
        # velocity leads the reference by τ·a. For a plant with transfer
        # function 1/(τs+1), v_cmd = v_ref + τ·a_ref makes the output
        # track v_ref exactly. VC_TAU_S = 0.348s from Phase 1 sysid.
        v_ff = ref.vel + VC_TAU_S * ref.acc
        cmd_vel = v_ff + v_corr
        # Clamp at the PLANT's max rate (MAIN_RATE_DEGS), not the planner's
        # cruise speed (v_max). The τ·a_ref term can briefly push v_ff above
        # v_max during accel phases (≈ 0.348 × 4.0 = 1.4°/s); the 6°/s clamp
        # caps at the plant limit and preserves the 1°/s FB headroom.
        if cmd_vel > MAIN_RATE_DEGS:
            cmd_vel = MAIN_RATE_DEGS
        elif cmd_vel < -MAIN_RATE_DEGS:
            cmd_vel = -MAIN_RATE_DEGS

        # Convert to firmware (speed, angle).
        if abs(cmd_vel) < 1e-6:
            speed_cmd = 0
            angle_cmd = 0
        else:
            speed_cmd = _rate_to_speed(abs(cmd_vel))
            if speed_cmd < VC_FINE_MIN_SPEED:
                speed_cmd = 0
            angle_cmd = 0 if cmd_vel > 0 else 180

        speed_move(cli, speed_cmd, angle_cmd, VC_CMD_DUR_S)
        stats["commands_issued"] += 1

        tracking_errs.append(abs(position_error))
        position_errs_abs.append(abs(position_error))
        if abs(v_corr) > stats["max_v_corr_degs"]:
            stats["max_v_corr_degs"] = abs(v_corr)

        if position_logger is not None:
            position_logger.mark_event(
                "ff_tick",
                t_rel=t_rel, fw_t=fw_t_now, t_plant=t_plant,
                ref_pos=ref.pos, ref_vel=ref.vel, ref_acc=ref.acc,
                meas_az=measured_az,
                tracking_err_deg=abs(position_error),
                position_error_deg=position_error,
                v_ff_degs=v_ff,
                v_corr_degs=v_corr, cmd_vel_degs=cmd_vel,
                cmd_speed=speed_cmd, cmd_angle=angle_cmd,
            )

        tick_dts.append(now - prev_tick_t)
        prev_tick_t = now
        tick_idx += 1

        # Termination — two distinct phases.
        if t_plant < traj.total_duration:
            # Still following the trajectory; keep going.
            pass
        else:
            # Past the trajectory; ref_vel=0 from here on, feedback holds
            # the plant at p_target. Count consecutive converged ticks.
            if t_settle_enter is None:
                t_settle_enter = now
            if abs(position_error) <= arrive_tolerance_deg:
                converged_count += 1
            else:
                converged_count = 0
            if converged_count >= converged_ticks_required:
                stats["converged"] = True
                break
            if (now - t_settle_enter) >= settle_max_s:
                break

        # Deadline-based sleep to next tick.
        next_tick_t = t_wall_start + tick_idx * tick_dt
        sleep_dt = next_tick_t - time.monotonic()
        if sleep_dt > 0:
            time.sleep(sleep_dt)

    # Clean stop after the loop exits.
    speed_move(cli, 0, 0, 1)
    stats["commands_issued"] += 1
    wait_for_mount_idle(cli, timeout_s=3.0)
    if settle_s > 0:
        time.sleep(settle_s)

    measured_alt, measured_az = measure_altaz(cli, loc)
    stats["final_residual_deg"] = wrap_pm180(target_az_deg - measured_az)
    stats["ticks"] = tick_idx
    stats["iterations"] = tick_idx  # compat
    if tick_dts:
        reals = tick_dts[1:] if len(tick_dts) > 1 else tick_dts
        stats["tick_dt_mean_s"] = sum(reals) / len(reals)
        stats["tick_dt_max_s"] = max(reals)
        stats["loop_dt_mean_s"] = stats["tick_dt_mean_s"]  # compat
        stats["loop_dt_max_s"] = stats["tick_dt_max_s"]    # compat
    if tracking_errs:
        stats["max_tracking_err_deg"] = max(tracking_errs)
        stats["mean_tracking_err_deg"] = sum(tracking_errs) / len(tracking_errs)
    if position_errs_abs:
        stats["max_position_error_deg"] = max(position_errs_abs)
    if t_settle_enter is not None:
        stats["settle_time_s"] = prev_tick_t - t_settle_enter
    stats["wall_time_s"] = time.monotonic() - t_wall_start

    if position_logger is not None:
        position_logger.mark_event(
            "ff_done",
            final_residual_deg=stats["final_residual_deg"],
            max_tracking_err_deg=stats["max_tracking_err_deg"],
            max_position_error_deg=stats["max_position_error_deg"],
            max_v_corr_degs=stats["max_v_corr_degs"],
            converged=stats["converged"],
            settle_time_s=stats["settle_time_s"],
            ticks=tick_idx,
        )

    # Fallback on large residual.
    if (
        fallback_goto_fn is not None
        and stats["final_residual_deg"] is not None
        and abs(stats["final_residual_deg"]) > fallback_residual_deg
    ):
        print(f"{tag} FF: final residual "
              f"{stats['final_residual_deg']:+.3f}° exceeds "
              f"{fallback_residual_deg}° — falling back to iscope", flush=True)
        stats["fallback_goto_used"] = True
        if position_logger is not None:
            position_logger.set_phase("ff_fallback_goto")
            position_logger.mark_event("ff_fallback_issue")
        ok = bool(fallback_goto_fn(cli, target_az_deg, target_alt_deg, loc))
        if ok:
            print(f"{tag} FF: fallback iscope arrived", flush=True)
        measured_alt, measured_az = measure_altaz(cli, loc)
        stats["final_residual_deg"] = wrap_pm180(target_az_deg - measured_az)

    return measured_alt, measured_az, stats


def move_azimuth_to_with_correction(
    cli: MountClient,
    target_az_deg: float,
    cur_az_deg: float,
    loc: EarthLocation,
    target_alt_deg: float,
    tag: str = "",
    position_logger: Any = None,
    arrive_tolerance_deg: float = 0.3,
    v_max: float = PLAN_MAX_RATE_DEGS,
    a_max: float = 4.0,
    j_max: float = 12.0,
    tick_dt: float = 0.5,
    settle_s: float = 1.5,
    cold_start_lag_s: float = 0.0,
    profile: str = "scurve",
    az_forbidden_deg: Optional[float] = None,
    az_limits: Optional[Any] = None,
    az_tracker: Optional[Any] = None,
    kp_pos: float = 0.5,
    v_corr_max: float = 2.0,
    settle_max_s: float = 5.0,
    fallback_residual_deg: float = 2.0,
    fallback_goto_fn: Optional[FallbackGotoFn] = None,
) -> tuple[float, float, dict]:
    """Alias for `move_azimuth_to_ff` with closed-loop feedback enabled.

    Historically this function ran the FF trajectory open-loop then did a
    post-hoc nudge loop to close the residual. The closed-loop variant in
    `move_azimuth_to_ff` (kp_pos > 0) holds the plant at the reference
    during the move AND past the trajectory end, removing the need for a
    separate correction phase.

    Kept as a named entry point so callers passing `arrive_tolerance_deg`
    get the expected convergence semantics.
    """
    return move_azimuth_to_ff(
        cli, target_az_deg=target_az_deg, cur_az_deg=cur_az_deg, loc=loc,
        target_alt_deg=target_alt_deg, tag=tag, position_logger=position_logger,
        v_max=v_max, a_max=a_max, j_max=j_max,
        tick_dt=tick_dt, settle_s=settle_s,
        cold_start_lag_s=cold_start_lag_s, profile=profile,
        az_forbidden_deg=az_forbidden_deg,
        az_limits=az_limits, az_tracker=az_tracker,
        kp_pos=kp_pos, v_corr_max=v_corr_max,
        arrive_tolerance_deg=arrive_tolerance_deg,
        settle_max_s=settle_max_s,
        fallback_residual_deg=fallback_residual_deg,
        fallback_goto_fn=fallback_goto_fn,
    )


# ---------------------------------------------------------------------------
# Unwind helper (restore cable headroom before dynamic tracking)
# ---------------------------------------------------------------------------


def unwind_azimuth(
    cli: MountClient,
    loc: EarthLocation,
    az_tracker: Any,
    az_limits: Any,
    threshold_deg: float = 180.0,
    tag: str = "[unwind]",
    position_logger: Any = None,
    **move_kwargs: Any,
) -> tuple[float, float, dict]:
    """Move the mount back toward cumulative 0 (cable midpoint) if the
    current cumulative az exceeds ``threshold_deg`` in either direction.

    Why: dynamic tracking (e.g. chasing a plane) can burn cable budget
    fast. Start each such track from near the midpoint so both sides
    have ~full headroom. When already within `threshold_deg` of center,
    no motion is issued and an informational stats dict is returned.

    Uses `move_azimuth_to_with_correction` to do the actual motion so
    the closed-loop FF+FB controller handles convergence.
    """
    cum_cur = az_tracker.cum_az_deg
    if abs(cum_cur) <= threshold_deg:
        return (0.0, 0.0, {
            "controller": "unwind_noop",
            "cum_cur_deg": cum_cur,
            "threshold_deg": threshold_deg,
            "final_residual_deg": 0.0,
            "fallback_goto_used": False,
            "iterations": 0, "sign_flips": 0, "rate_ceiling_halvings": 0,
            "commands_issued": 0, "loop_dt_mean_s": 0.0, "loop_dt_max_s": 0.0,
            "stuck_bail": False, "wall_time_s": 0.0,
        })
    # Measure to anchor the tracker + get a wrapped-cur for picking the target.
    _, wrapped_cur, _ = measure_altaz_timed(cli, loc)
    az_tracker.update(wrapped_cur)
    # We want cumulative to end up at 0 (cable midpoint). The equivalent
    # wrapped target is:
    target_wrapped = wrap_pm180(wrapped_cur - az_tracker.cum_az_deg)
    print(f"{tag} unwind: cum={az_tracker.cum_az_deg:+.3f}° -> wrapped "
          f"target={target_wrapped:+.3f}° (drive back to cable center)",
          flush=True)
    return move_azimuth_to_with_correction(
        cli,
        target_az_deg=target_wrapped,
        cur_az_deg=wrapped_cur,
        loc=loc,
        target_alt_deg=0.0,  # unused when fallback_goto_fn is None
        tag=tag,
        position_logger=position_logger,
        az_limits=az_limits,
        az_tracker=az_tracker,
        fallback_goto_fn=None,  # do not iscope-fallback during unwind
        **move_kwargs,
    )


# ---------------------------------------------------------------------------
# Elevation closed-loop FF+FB controller (Phase 4.3)
# ---------------------------------------------------------------------------


def move_elevation_to_ff(
    cli: MountClient,
    target_el_deg: float,
    cur_el_deg: float,
    loc: EarthLocation,
    tag: str = "",
    position_logger: Any = None,
    v_max: float = PLAN_MAX_RATE_DEGS,
    a_max: float = 4.0,
    j_max: float = 12.0,
    tick_dt: float = 0.5,
    settle_s: float = 1.5,
    profile: str = "scurve",
    el_min_deg: Optional[float] = None,
    el_max_deg: Optional[float] = None,
    kp_pos: float = 0.5,
    v_corr_max: float = 2.0,
    arrive_tolerance_deg: float = 0.3,
    settle_max_s: float = 5.0,
    converged_ticks_required: int = 2,
) -> tuple[float, float, dict]:
    """Closed-loop FF+FB elevation mover.

    Same architecture as `move_azimuth_to_ff` but for the elevation axis:
    - Firmware angles: 90 (up / increasing el) and 270 (down).
    - Position from `scope_get_horiz_coord[0]` (el encoder).
    - No azimuth wrap (el is a bounded joint, not a rotary cable-wrap).
    - Simple `el_min_deg` / `el_max_deg` clamp on target instead of
      cumulative cable-wrap planning.

    Returns `(measured_alt, measured_az, stats)` — note both axes are
    read even though only el is controlled.
    """
    from device.trajectory import scurve_profile, trapezoidal_profile

    if profile not in ("trapezoid", "scurve"):
        raise ValueError(f"unknown profile {profile!r}")

    if el_min_deg is not None and target_el_deg < el_min_deg:
        target_el_deg = el_min_deg
    if el_max_deg is not None and target_el_deg > el_max_deg:
        target_el_deg = el_max_deg

    stats: dict[str, Any] = {
        "controller": "el_ff_fb" if kp_pos > 0 else "el_ff",
        "profile": profile,
        "kp_pos": kp_pos,
        "trajectory_duration_s": 0.0,
        "commands_issued": 0,
        "ticks": 0,
        "final_residual_deg": None,
        "max_position_error_deg": 0.0,
        "max_v_corr_degs": 0.0,
        "converged": False,
        "wall_time_s": 0.0,
        # Compat keys.
        "iterations": 0, "sign_flips": 0, "rate_ceiling_halvings": 0,
        "loop_dt_mean_s": 0.0, "loop_dt_max_s": 0.0,
        "stuck_bail": False, "fallback_goto_used": False,
    }

    # Elevation doesn't wrap — use raw delta (wrap_target=False).
    delta = target_el_deg - cur_el_deg
    if abs(delta) < 0.01:
        measured_alt, measured_az = measure_altaz(cli, loc)
        stats["final_residual_deg"] = target_el_deg - measured_alt
        return measured_alt, measured_az, stats

    if profile == "scurve":
        traj = scurve_profile(
            p0=cur_el_deg, v0=0.0, p_target=target_el_deg,
            v_max=v_max, a_max=a_max, j_max=j_max, tick_dt=tick_dt,
            wrap_target=False,
        )
    else:
        traj = trapezoidal_profile(
            p0=cur_el_deg, v0=0.0, p_target=target_el_deg,
            v_max=v_max, a_max=a_max, tick_dt=tick_dt,
            wrap_target=False,
        )
    stats["trajectory_duration_s"] = traj.total_duration

    if position_logger is not None:
        position_logger.set_phase("el_ff_move")
        position_logger.mark_event(
            "el_ff_start",
            target_el=target_el_deg, cur_el=cur_el_deg,
            traj_duration_s=traj.total_duration,
            v_max=v_max, a_max=a_max, profile=profile,
            kp_pos=kp_pos,
        )

    # Prime fw_t baseline.
    _, _, fw_t_start = measure_altaz_timed(cli, loc)
    t_wall_start = time.monotonic()

    tick_dts: list[float] = []
    position_errs_abs: list[float] = []
    prev_tick_t = t_wall_start
    tick_idx = 0
    converged_count = 0
    t_settle_enter = None

    while True:
        now = time.monotonic()
        t_rel = now - t_wall_start

        measured_alt, _, fw_t_now = measure_altaz_timed(cli, loc)

        if fw_t_now is not None and fw_t_start is not None:
            t_plant = fw_t_now - fw_t_start
        else:
            t_plant = t_rel
        t_plant_clamped = max(0.0, min(t_plant, traj.total_duration))

        ref = traj.sample(t_plant_clamped)
        position_error = ref.pos - measured_alt  # no wrap for el

        v_corr = kp_pos * position_error
        if v_corr > v_corr_max:
            v_corr = v_corr_max
        elif v_corr < -v_corr_max:
            v_corr = -v_corr_max

        # Feedforward plant-inversion: v_cmd = v_ref + τ·a_ref + FB. See the
        # matching block in move_azimuth_to_ff for the derivation.
        v_ff = ref.vel + VC_TAU_S * ref.acc
        cmd_vel = v_ff + v_corr
        if cmd_vel > MAIN_RATE_DEGS:
            cmd_vel = MAIN_RATE_DEGS
        elif cmd_vel < -MAIN_RATE_DEGS:
            cmd_vel = -MAIN_RATE_DEGS

        if abs(cmd_vel) < 1e-6:
            speed_cmd = 0
            angle_cmd = 0
        else:
            speed_cmd = _rate_to_speed(abs(cmd_vel))
            if speed_cmd < VC_FINE_MIN_SPEED:
                speed_cmd = 0
            angle_cmd = 90 if cmd_vel > 0 else 270

        speed_move(cli, speed_cmd, angle_cmd, VC_CMD_DUR_S)
        stats["commands_issued"] += 1

        position_errs_abs.append(abs(position_error))
        if abs(v_corr) > stats["max_v_corr_degs"]:
            stats["max_v_corr_degs"] = abs(v_corr)

        if position_logger is not None:
            position_logger.mark_event(
                "el_ff_tick",
                t_rel=t_rel, fw_t=fw_t_now, t_plant=t_plant,
                ref_pos=ref.pos, ref_vel=ref.vel, ref_acc=ref.acc,
                meas_el=measured_alt,
                position_error_deg=position_error,
                v_ff_degs=v_ff,
                v_corr_degs=v_corr, cmd_vel_degs=cmd_vel,
                cmd_speed=speed_cmd, cmd_angle=angle_cmd,
            )

        tick_dts.append(now - prev_tick_t)
        prev_tick_t = now
        tick_idx += 1

        if t_plant < traj.total_duration:
            pass
        else:
            if t_settle_enter is None:
                t_settle_enter = now
            if abs(position_error) <= arrive_tolerance_deg:
                converged_count += 1
            else:
                converged_count = 0
            if converged_count >= converged_ticks_required:
                stats["converged"] = True
                break
            if (now - t_settle_enter) >= settle_max_s:
                break

        next_tick_t = t_wall_start + tick_idx * tick_dt
        sleep_dt = next_tick_t - time.monotonic()
        if sleep_dt > 0:
            time.sleep(sleep_dt)

    speed_move(cli, 0, 0, 1)
    stats["commands_issued"] += 1
    wait_for_mount_idle(cli, timeout_s=3.0)
    if settle_s > 0:
        time.sleep(settle_s)

    measured_alt, measured_az = measure_altaz(cli, loc)
    stats["final_residual_deg"] = target_el_deg - measured_alt
    stats["ticks"] = tick_idx
    stats["iterations"] = tick_idx
    if tick_dts:
        reals = tick_dts[1:] if len(tick_dts) > 1 else tick_dts
        stats["tick_dt_mean_s"] = sum(reals) / len(reals)
        stats["tick_dt_max_s"] = max(reals)
        stats["loop_dt_mean_s"] = stats["tick_dt_mean_s"]
        stats["loop_dt_max_s"] = stats["tick_dt_max_s"]
    if position_errs_abs:
        stats["max_position_error_deg"] = max(position_errs_abs)
    if t_settle_enter is not None:
        stats["settle_time_s"] = prev_tick_t - t_settle_enter
    stats["wall_time_s"] = time.monotonic() - t_wall_start

    if position_logger is not None:
        position_logger.mark_event(
            "el_ff_done",
            final_residual_deg=stats["final_residual_deg"],
            converged=stats["converged"],
            ticks=tick_idx,
        )

    return measured_alt, measured_az, stats


# ---------------------------------------------------------------------------
# Combined 2-axis controller (Phase 4.4)
# ---------------------------------------------------------------------------


def move_to_ff(
    cli: MountClient,
    target_az_deg: float,
    target_el_deg: float,
    cur_az_deg: float,
    cur_el_deg: float,
    loc: EarthLocation,
    tag: str = "",
    position_logger: Any = None,
    v_max: float = PLAN_MAX_RATE_DEGS,
    a_max: float = 4.0,
    j_max: float = 12.0,
    tick_dt: float = 0.5,
    settle_s: float = 1.5,
    profile: str = "scurve",
    az_limits: Optional[Any] = None,
    az_tracker: Optional[Any] = None,
    el_min_deg: Optional[float] = None,
    el_max_deg: Optional[float] = None,
    kp_pos: float = 0.5,
    v_corr_max: float = 2.0,
    arrive_tolerance_deg: float = 0.3,
    settle_max_s: float = 5.0,
    converged_ticks_required: int = 2,
    force_cum_az_target: Optional[float] = None,
) -> tuple[float, float, dict]:
    """Closed-loop FF+FB 2-axis mover — az and el simultaneously.

    Plans independent S-curve (or trapezoid) trajectories for each axis,
    runs a single tick loop, and at every tick composes the two commanded
    velocities into one `scope_speed_move(speed, angle, dur)`:

        speed = |v_vec| · SPEED_PER_DEG_PER_SEC
        angle = atan2(v_el, v_az)   (firmware: 0=+az, 90=+el)

    `v_max` caps the magnitude `|v_vec|` (not per-axis), so diagonal
    moves use the full plant rate. If both axes demand full speed the
    vector is scaled down proportionally.

    Convergence: waits until BOTH axes are within `arrive_tolerance_deg`
    for `converged_ticks_required` consecutive ticks, or
    `settle_max_s` expires.
    """
    import math
    from device.trajectory import scurve_profile_2d, trapezoidal_profile_2d

    if profile not in ("trapezoid", "scurve"):
        raise ValueError(f"unknown profile {profile!r}")

    # Clamp el target to limits.
    if el_min_deg is not None and target_el_deg < el_min_deg:
        target_el_deg = el_min_deg
    if el_max_deg is not None and target_el_deg > el_max_deg:
        target_el_deg = el_max_deg

    # Resolve az target (cumulative-aware if limits present).
    # When force_cum_az_target is set, it bypasses pick_cum_target and is
    # used as the cumulative planning target directly — needed for
    # cable-recentering, where the caller wants to unwind to cum=0 even
    # when the short wrapped path would go the other way.
    use_cum = az_limits is not None and az_tracker is not None
    if use_cum:
        p0_az = az_tracker.cum_az_deg
        if force_cum_az_target is not None:
            if not az_limits.contains_cum(force_cum_az_target):
                raise ValueError(
                    f"force_cum_az_target={force_cum_az_target:+.3f}° outside "
                    f"usable cable-wrap range "
                    f"[{az_limits.usable_ccw_cum_deg:+.1f}, "
                    f"{az_limits.usable_cw_cum_deg:+.1f}]"
                )
            p_target_az = force_cum_az_target
        else:
            from device.plant_limits import pick_cum_target
            p_target_az = pick_cum_target(
                p0_az, cur_az_deg, target_az_deg, az_limits,
            )
    else:
        p0_az = cur_az_deg
        p_target_az = target_az_deg

    # 2-D coordinated plan: straight line in (az, el) with both axes
    # arriving simultaneously. Returns a pair of PlannedTrajectory with
    # matched total_duration, so the existing tick loop samples cleanly.
    if profile == "scurve":
        traj_az, traj_el = scurve_profile_2d(
            p0_az=p0_az, p0_el=cur_el_deg,
            p_target_az=p_target_az, p_target_el=target_el_deg,
            v_max=v_max, a_max=a_max, j_max=j_max, tick_dt=tick_dt,
            wrap_az=not use_cum,
        )
    else:
        traj_az, traj_el = trapezoidal_profile_2d(
            p0_az=p0_az, p0_el=cur_el_deg,
            p_target_az=p_target_az, p_target_el=target_el_deg,
            v_max=v_max, a_max=a_max, tick_dt=tick_dt,
            wrap_az=not use_cum,
        )

    # 2-D coordinated plan produces matched durations for both axes; the
    # per-axis duration fields are kept for back-compat with existing log
    # consumers. path_len_deg distinguishes pure-axis vs diagonal moves.
    _delta_az_plan = (traj_az.points[-1].pos - traj_az.points[0].pos
                      if traj_az.points else 0.0)
    _delta_el_plan = (traj_el.points[-1].pos - traj_el.points[0].pos
                      if traj_el.points else 0.0)
    _path_len_deg = math.sqrt(_delta_az_plan * _delta_az_plan
                              + _delta_el_plan * _delta_el_plan)

    stats: dict[str, Any] = {
        "controller": "2d_ff_fb",
        "profile": profile,
        "traj_az_duration_s": traj_az.total_duration,
        "traj_el_duration_s": traj_el.total_duration,
        "traj_path_len_deg": _path_len_deg,
        "commands_issued": 0,
        "ticks": 0,
        "final_residual_az_deg": None,
        "final_residual_el_deg": None,
        "max_pos_err_az_deg": 0.0,
        "max_pos_err_el_deg": 0.0,
        "converged": False,
        "wall_time_s": 0.0,
        # Compat keys.
        "final_residual_deg": None,
        "iterations": 0, "sign_flips": 0, "rate_ceiling_halvings": 0,
        "loop_dt_mean_s": 0.0, "loop_dt_max_s": 0.0,
        "stuck_bail": False, "fallback_goto_used": False,
    }

    max_traj_dur = max(traj_az.total_duration, traj_el.total_duration)
    if max_traj_dur == 0.0:
        measured_alt, measured_az = measure_altaz(cli, loc)
        stats["final_residual_az_deg"] = wrap_pm180(target_az_deg - measured_az)
        stats["final_residual_el_deg"] = target_el_deg - measured_alt
        stats["final_residual_deg"] = stats["final_residual_az_deg"]
        return measured_alt, measured_az, stats

    if position_logger is not None:
        position_logger.set_phase("2d_ff_move")
        position_logger.mark_event(
            "2d_ff_start",
            target_az=target_az_deg, target_el=target_el_deg,
            cur_az=cur_az_deg, cur_el=cur_el_deg,
            p_target_az_cum=p_target_az,
            traj_az_dur=traj_az.total_duration,
            traj_el_dur=traj_el.total_duration,
            path_len_deg=_path_len_deg,
            profile=profile, kp_pos=kp_pos,
        )

    _, _, fw_t_start = measure_altaz_timed(cli, loc)
    t_wall_start = time.monotonic()

    tick_dts: list[float] = []
    prev_tick_t = t_wall_start
    tick_idx = 0
    converged_count = 0
    t_settle_enter = None

    while True:
        now = time.monotonic()
        t_rel = now - t_wall_start

        measured_alt, measured_az, fw_t_now = measure_altaz_timed(cli, loc)
        if az_tracker is not None:
            az_tracker.update(measured_az)

        if fw_t_now is not None and fw_t_start is not None:
            t_plant = fw_t_now - fw_t_start
        else:
            t_plant = t_rel

        # Az reference + feedforward + feedback.
        # When planning in cumulative coords (use_cum), ref_az.pos lives in
        # the same unwrapped frame as az_tracker.cum_az_deg, and the
        # trajectory can span multiple wraps — diff them directly. Wrapped
        # mode compares against the wrapped measurement with wrap_pm180.
        t_az = max(0.0, min(t_plant, traj_az.total_duration))
        ref_az = traj_az.sample(t_az)
        if use_cum:
            err_az = ref_az.pos - az_tracker.cum_az_deg
        else:
            err_az = wrap_pm180(ref_az.pos - measured_az)
        v_corr_az = max(-v_corr_max, min(v_corr_max, kp_pos * err_az))
        v_ff_az = ref_az.vel + VC_TAU_S * ref_az.acc
        v_cmd_az = v_ff_az + v_corr_az

        # El reference + feedforward + feedback.
        t_el = max(0.0, min(t_plant, traj_el.total_duration))
        ref_el = traj_el.sample(t_el)
        err_el = ref_el.pos - measured_alt
        v_corr_el = max(-v_corr_max, min(v_corr_max, kp_pos * err_el))
        v_ff_el = ref_el.vel + VC_TAU_S * ref_el.acc
        v_cmd_el = v_ff_el + v_corr_el

        # Clamp each axis independently at v_max. The firmware clamps
        # per-axis at speed=1440 internally, so the total speed CAN exceed
        # 1440 for diagonal moves (e.g. speed=2036 at angle=45° gives each
        # axis its full 6°/s). We mirror that here by clamping per-axis
        # rather than the magnitude.
        v_cmd_az = max(-MAIN_RATE_DEGS, min(MAIN_RATE_DEGS, v_cmd_az))
        v_cmd_el = max(-MAIN_RATE_DEGS, min(MAIN_RATE_DEGS, v_cmd_el))
        v_mag = math.sqrt(v_cmd_az * v_cmd_az + v_cmd_el * v_cmd_el)

        if v_mag < 1e-6:
            speed_cmd = 0
            angle_cmd = 0
        else:
            speed_cmd = _rate_to_speed(v_mag)
            if speed_cmd < VC_FINE_MIN_SPEED:
                speed_cmd = 0
            angle_cmd = int(round(math.degrees(math.atan2(v_cmd_el, v_cmd_az)))) % 360

        speed_move(cli, speed_cmd, angle_cmd, VC_CMD_DUR_S)
        stats["commands_issued"] += 1

        if abs(err_az) > stats["max_pos_err_az_deg"]:
            stats["max_pos_err_az_deg"] = abs(err_az)
        if abs(err_el) > stats["max_pos_err_el_deg"]:
            stats["max_pos_err_el_deg"] = abs(err_el)

        if position_logger is not None:
            position_logger.mark_event(
                "2d_ff_tick",
                t_rel=t_rel, fw_t=fw_t_now, t_plant=t_plant,
                ref_az=ref_az.pos, ref_el=ref_el.pos,
                ref_vel_az=ref_az.vel, ref_vel_el=ref_el.vel,
                ref_acc_az=ref_az.acc, ref_acc_el=ref_el.acc,
                meas_az=measured_az, meas_el=measured_alt,
                err_az=err_az, err_el=err_el,
                v_ff_az=v_ff_az, v_ff_el=v_ff_el,
                v_cmd_az=v_cmd_az, v_cmd_el=v_cmd_el,
                v_mag=v_mag, cmd_speed=speed_cmd, cmd_angle=angle_cmd,
            )

        tick_dts.append(now - prev_tick_t)
        prev_tick_t = now
        tick_idx += 1

        # Convergence: both axes past trajectory AND within tolerance.
        both_past = (t_plant >= traj_az.total_duration
                     and t_plant >= traj_el.total_duration)
        if both_past:
            if t_settle_enter is None:
                t_settle_enter = now
            both_ok = (abs(err_az) <= arrive_tolerance_deg
                       and abs(err_el) <= arrive_tolerance_deg)
            if both_ok:
                converged_count += 1
            else:
                converged_count = 0
            if converged_count >= converged_ticks_required:
                stats["converged"] = True
                break
            if (now - t_settle_enter) >= settle_max_s:
                break

        next_tick_t = t_wall_start + tick_idx * tick_dt
        sleep_dt = next_tick_t - time.monotonic()
        if sleep_dt > 0:
            time.sleep(sleep_dt)

    speed_move(cli, 0, 0, 1)
    stats["commands_issued"] += 1
    wait_for_mount_idle(cli, timeout_s=3.0)
    if settle_s > 0:
        time.sleep(settle_s)

    measured_alt, measured_az = measure_altaz(cli, loc)
    stats["final_residual_az_deg"] = wrap_pm180(target_az_deg - measured_az)
    stats["final_residual_el_deg"] = target_el_deg - measured_alt
    stats["final_residual_deg"] = stats["final_residual_az_deg"]
    stats["ticks"] = tick_idx
    stats["iterations"] = tick_idx
    if tick_dts:
        reals = tick_dts[1:] if len(tick_dts) > 1 else tick_dts
        stats["tick_dt_mean_s"] = sum(reals) / len(reals)
        stats["tick_dt_max_s"] = max(reals)
        stats["loop_dt_mean_s"] = stats["tick_dt_mean_s"]
        stats["loop_dt_max_s"] = stats["tick_dt_max_s"]
    if t_settle_enter is not None:
        stats["settle_time_s"] = prev_tick_t - t_settle_enter
    stats["wall_time_s"] = time.monotonic() - t_wall_start

    if position_logger is not None:
        position_logger.mark_event(
            "2d_ff_done",
            final_residual_az=stats["final_residual_az_deg"],
            final_residual_el=stats["final_residual_el_deg"],
            converged=stats["converged"],
            ticks=tick_idx,
        )

    return measured_alt, measured_az, stats


# ---------------------------------------------------------------------------
# Goto-origin convenience (end-of-session homing + cable-wrap recenter)
# ---------------------------------------------------------------------------


def goto_origin(
    cli: MountClient,
    loc: EarthLocation,
    *,
    az_limits: Optional[Any] = None,
    position_logger: Any = None,
    tag: str = "[origin]",
    v_max: float = PLAN_MAX_RATE_DEGS,
    a_max: float = 4.0,
    j_max: float = 12.0,
    tick_dt: float = 0.5,
    settle_s: float = 1.5,
    profile: str = "scurve",
    kp_pos: float = 0.5,
    v_corr_max: float = 2.0,
    arrive_tolerance_deg: float = 0.3,
    settle_max_s: float = 5.0,
    converged_ticks_required: int = 2,
    # stop-hit (homing) params
    hard_stop_speed: int = 1440,
    hard_stop_stall_tol_deg: float = 5.0,
    hard_stop_check_dt_s: float = 1.5,
    hard_stop_max_time_s: float = 260.0,
    hard_stop_direction: Optional[str] = None,
) -> tuple[float, float, dict]:
    """Home the mount to (az=0, el=0) via a cable hard stop.

    This is the deterministic homing primitive: it always drives the az
    axis until the cable hits a mechanical stop, uses that known absolute
    cumulative position as the reference, and then commands a precise
    unwind to ``cum_az=0`` simultaneously with an el move to the horizon.
    Any existing ``CumulativeAzTracker`` state is ignored — the hard-stop
    strike is the authoritative reference.

    Direction picking: if ``hard_stop_direction`` is None (default), picks
    whichever stop is closer in **wrapped** az (the axes' quickest possible
    stall, if luck has us on the first turn toward that stop). Otherwise
    pass ``'ccw'`` or ``'cw'`` to force a direction.

    Note: wrapped az alone does not uniquely determine cumulative az (any
    wrapped value matches 2–3 cum positions within the ±450° range), so
    we still need to stall to pin the cum reference exactly. Picking the
    smart direction optimizes the lucky-case motion time; worst case is
    the same as always-one-direction.

    Requires ``AzimuthLimits`` (either passed or loadable from
    ``plant_limits.json``) — without cable geometry we can't compute the
    unwind target.

    Handles ``ensure_scenery_mode``, ``set_tracking(False)``, idle wait,
    stall detection (dithered burst commands), the coordinated 2-D
    unwind via ``move_to_ff``, and tracker ``save()`` at the end. Caller
    only needs ``cli`` and ``loc``.
    """
    import random
    from device.plant_limits import AzimuthLimits, CumulativeAzTracker

    if az_limits is None:
        az_limits = AzimuthLimits.load()
    if az_limits is None:
        raise ValueError(
            "goto_origin requires AzimuthLimits (pass az_limits=... or "
            "populate device/plant_limits.json) — cable-wrap geometry is "
            "needed to compute the unwind from the hard stop."
        )

    ensure_scenery_mode(cli)
    set_tracking(cli, False)
    wait_for_mount_idle(cli, timeout_s=5.0)

    alt_before, az_before, _ = measure_altaz_timed(cli, loc)

    # Pick direction. Distance-in-wrapped to each hard stop:
    d_ccw = abs(wrap_pm180(az_before - az_limits.ccw_hard_stop_wrapped_deg))
    d_cw = abs(wrap_pm180(az_before - az_limits.cw_hard_stop_wrapped_deg))
    if hard_stop_direction is None:
        chosen = "ccw" if d_ccw <= d_cw else "cw"
    elif hard_stop_direction in ("ccw", "cw"):
        chosen = hard_stop_direction
    else:
        raise ValueError(
            f"hard_stop_direction must be 'ccw', 'cw', or None; "
            f"got {hard_stop_direction!r}"
        )
    if chosen == "ccw":
        burst_angle = 180
        stop_cum_ref = az_limits.ccw_hard_stop_cum_deg
        stop_wrapped_ref = az_limits.ccw_hard_stop_wrapped_deg
    else:
        burst_angle = 0
        stop_cum_ref = az_limits.cw_hard_stop_cum_deg
        stop_wrapped_ref = az_limits.cw_hard_stop_wrapped_deg

    print(f"{tag} before: az={az_before:+.3f}  el={alt_before:+.3f}  "
          f"(d_ccw={d_ccw:.1f}°, d_cw={d_cw:.1f}° — picking {chosen.upper()})",
          flush=True)

    if position_logger is not None:
        position_logger.mark_event(
            "goto_origin_start",
            az_before=az_before, alt_before=alt_before,
            d_ccw_wrapped_deg=d_ccw, d_cw_wrapped_deg=d_cw,
            chosen_direction=chosen,
        )

    # Stage 1: drive into the chosen hard stop with dithered bursts so
    # the firmware doesn't dedup consecutive identical speed_moves.
    rng = random.Random(0x60710)
    def _dither_dur() -> int:
        return rng.choice([6, 7, 8, 9, 10])
    def _issue() -> None:
        speed_move(cli, hard_stop_speed, burst_angle, _dither_dur())

    t_stage1_start = time.monotonic()
    _issue()
    next_reissue_t = t_stage1_start + rng.uniform(4.5, 5.5)

    prev_wrapped = az_before
    stall_streak = 0
    motion_total = 0.0
    bursts_issued = 1
    # Need ~2 consecutive low-progress windows before declaring stall,
    # but skip the first few seconds (firmware cold-start ramp-up).
    stall_start_warmup_s = 2.5
    while True:
        elapsed = time.monotonic() - t_stage1_start
        if elapsed > hard_stop_max_time_s:
            speed_move(cli, 0, 0, 1)
            wait_for_mount_idle(cli, timeout_s=3.0)
            raise RuntimeError(
                f"goto_origin: stall not detected within "
                f"{hard_stop_max_time_s:.0f}s (moved {motion_total:.0f}° "
                f"total); cable is 900° max — check hardware or "
                f"plant_limits.json"
            )
        time.sleep(hard_stop_check_dt_s)
        if time.monotonic() >= next_reissue_t:
            _issue()
            bursts_issued += 1
            next_reissue_t = time.monotonic() + rng.uniform(4.5, 5.5)
        _, cur_wrapped, _ = measure_altaz_timed(cli, loc)
        delta = wrap_pm180(cur_wrapped - prev_wrapped)
        motion_total += abs(delta)
        prev_wrapped = cur_wrapped
        warming_up = (time.monotonic() - t_stage1_start) < stall_start_warmup_s
        if abs(delta) < hard_stop_stall_tol_deg and not warming_up:
            stall_streak += 1
            if stall_streak >= 2:
                break
        else:
            stall_streak = 0

    speed_move(cli, 0, 0, 1)
    wait_for_mount_idle(cli, timeout_s=3.0)

    _, az_at_stop, _ = measure_altaz_timed(cli, loc)
    drift_from_ref = wrap_pm180(az_at_stop - stop_wrapped_ref)
    t_stage1_elapsed = time.monotonic() - t_stage1_start

    print(f"{tag} stalled {chosen.upper()} at az={az_at_stop:+.3f}  "
          f"(expected ~{stop_wrapped_ref:+.3f}, drift {drift_from_ref:+.3f}°)  "
          f"motion={motion_total:.1f}°  bursts={bursts_issued}  "
          f"t={t_stage1_elapsed:.1f}s", flush=True)

    if position_logger is not None:
        position_logger.mark_event(
            "goto_origin_stalled",
            az_at_stop=az_at_stop, drift_from_ref_deg=drift_from_ref,
            motion_total_deg=motion_total, bursts_issued=bursts_issued,
            stage1_elapsed_s=t_stage1_elapsed,
        )

    # Stage 2: fresh tracker anchored at the hard stop, unwind to cum=0.
    tracker = CumulativeAzTracker()
    tracker.reset(cum_az_deg=stop_cum_ref, wrapped_az_deg=az_at_stop)
    alt_at_stop, _, _ = measure_altaz_timed(cli, loc)

    print(f"{tag} unwind: tracker cum={stop_cum_ref:+.1f} -> 0  "
          f"(delta {-stop_cum_ref:+.1f}°)", flush=True)

    meas_alt, meas_az, stats = move_to_ff(
        cli,
        target_az_deg=0.0, target_el_deg=0.0,
        cur_az_deg=az_at_stop, cur_el_deg=alt_at_stop,
        loc=loc,
        tag=tag, position_logger=position_logger,
        v_max=v_max, a_max=a_max, j_max=j_max,
        tick_dt=tick_dt, settle_s=settle_s, profile=profile,
        az_limits=az_limits, az_tracker=tracker,
        kp_pos=kp_pos, v_corr_max=v_corr_max,
        arrive_tolerance_deg=arrive_tolerance_deg,
        settle_max_s=settle_max_s,
        converged_ticks_required=converged_ticks_required,
        force_cum_az_target=0.0,
    )

    try:
        tracker.save()
    except OSError:
        pass

    stats["hard_stop_direction"] = chosen
    stats["hard_stop_az_at_stall"] = az_at_stop
    stats["hard_stop_drift_from_ref_deg"] = drift_from_ref
    stats["hard_stop_motion_total_deg"] = motion_total
    stats["hard_stop_elapsed_s"] = t_stage1_elapsed
    return meas_alt, meas_az, stats


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

    Position source: `scope_get_horiz_coord` → raw motor encoder
    `[alt, az]`. This is always live (unlike `scope_get_equ_coord`
    which goes stale without plate-solve alignment). Polling at 0.5 s
    is safe — probed at 0.3 s without cancelling scope_speed_move.
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
        resp = self.cli.method_sync("scope_get_horiz_coord")
        if not isinstance(resp, dict) or "result" not in resp:
            raise RuntimeError(f"scope_get_horiz_coord bad response: {resp!r}")
        result = resp["result"]
        alt = float(result[0])
        az = wrap_pm180(float(result[1]))
        ts_raw = resp.get("Timestamp")
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
            "alt_deg": alt,
            "az_deg": az,
            "commanded_az_deg": cmd_az,
            "commanded_alt_deg": cmd_alt,
        }
