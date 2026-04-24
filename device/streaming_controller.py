"""Phase 5 streaming FF+FB controller.

Replaces `move_to_ff`'s point-to-point planner with an indefinite tick loop
fed by a `ReferenceProvider`. At each tick:

    ref = provider.sample(t_now + latency_s)
    err_az = ref.az_cum_deg - cur_az_cum
    err_el = ref.el_deg - cur_el
    v_ff_az = ref.v_az_degs + tau · ref.a_az_degs2     # feedforward
    v_ff_el = ref.v_el_degs + tau · ref.a_el_degs2
    v_corr = clamp(kp_pos · err, ±v_corr_max)         # feedback
    v_cmd  = clamp(v_ff + v_corr, ±v_max)             # per-axis
    scope_speed_move(speed, angle, dur=tick_ttl)

Controller exits cleanly on: external stop_signal, cable-wrap alarm, stale
provider for N consecutive ticks, max_duration_s elapsed, Ctrl-C.

Reuses helpers and conventions directly from device.velocity_controller so
post-run analysis goes through the same PositionLogger pipeline and the same
front-end overlay.
"""

from __future__ import annotations

import math
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from astropy.coordinates import EarthLocation

from device.plant_limits import AzimuthLimits, CumulativeAzTracker
from device.reference_provider import ReferenceProvider
from device.sun_safety import SunSafetyLocked, is_sun_safe as _is_sun_safe
from device.velocity_controller import (
    MAIN_RATE_DEGS,
    SPEED_PER_DEG_PER_SEC,
    VC_TAU_S,
    MountClient,
    measure_altaz_timed,
    speed_move,
    wrap_pm180,
)


TICK_DT_S = 0.5
LATENCY_S = 0.4
KP_POS = 0.5
V_CORR_MAX_DEGS = 2.0
# Tighter TTL than move_to_ff (5 s) — on crash/abort the mount auto-stops
# within 1 s instead of coasting to the next command. For a streaming loop
# this keeps a dead controller from driving the mount into a limit.
TICK_CMD_DUR_S = 1
STALE_TOLERANCE_TICKS = 4  # consecutive stale samples that force exit
MAX_DURATION_S = 900.0      # 15 min hard cap
# Threshold below which the instantaneous track heading is considered
# ill-defined (geostationary-like target). ψ freezes at the last good value
# and along/cross offsets stop updating until |v| rises again.
V_MIN_HEADING_LOCK_DEGS = 0.05
# EWMA time constant for ψ (track heading). ~2 s gives a clean filter at
# 0.5 s tick rate without noticeable lag.
HEADING_EWMA_TAU_S = 2.0


@dataclass(frozen=True)
class OffsetSnapshot:
    """Immutable snapshot of user-driven offsets, produced by an external
    offset provider. Defaults leave the tracker behavior unchanged.

    - time_offset_s: added to the per-tick provider query time. Positive
      values look ahead along the trajectory; negative look behind.
    - az_bias_deg / el_bias_deg: additive bias in the mount frame, fixed
      regardless of target heading.
    - along_deg / cross_deg: additive bias rotated into the mount frame by
      the instantaneous track heading (ψ). "Along +" points in the
      direction of motion; "Cross +" is 90° CCW of Along+.
    """
    time_offset_s: float = 0.0
    az_bias_deg: float = 0.0
    el_bias_deg: float = 0.0
    along_deg: float = 0.0
    cross_deg: float = 0.0


_ZERO_OFFSETS = OffsetSnapshot()


@dataclass(frozen=True)
class TickInfo:
    """Summary of one tick, passed to an optional tick_callback so callers
    (e.g. a web session wrapper) can expose live status without re-deriving
    quantities the loop already computed."""
    tick: int
    t_wall: float
    heading_deg: float               # ψ (EWMA) in degrees, wrapped to [0, 360)
    heading_locked: bool             # True when ψ was frozen (|v|<v_min)
    d_az_deg: float                  # total az bias applied this tick
    d_el_deg: float                  # total el bias applied this tick
    eff_ref_az_cum_deg: float
    eff_ref_el_deg: float
    cur_cum_az_deg: float
    cur_el_deg: float
    err_az_deg: float
    err_el_deg: float
    ref_stale: bool


@dataclass
class TrackResult:
    ok: bool                         # True if exited cleanly on end-of-provider or stop signal
    exit_reason: str                 # "end_of_track", "stop_signal", "cable_wrap", "stale", "timeout", "mount_error"
    ticks: int
    elapsed_s: float
    az_err_rms: float
    az_err_peak: float
    el_err_rms: float
    el_err_peak: float
    sat_az_ticks: int
    sat_el_ticks: int
    final_cum_az_deg: float
    final_el_deg: float
    errors: list[str] = field(default_factory=list)


@dataclass
class PreCheckResult:
    feasible: bool
    peak_v_az_degs: float
    peak_v_el_degs: float
    peak_a_az_degs2: float
    peak_a_el_degs2: float
    min_cum_az_deg: float
    max_cum_az_deg: float
    min_el_deg: float
    max_el_deg: float
    cable_wrap_violations: int
    el_limit_violations: int
    v_saturation_ticks: int          # ticks where |v_ref + tau·a_ref| > v_max
    notes: list[str] = field(default_factory=list)


# ---------- pre-check -------------------------------------------------


def pre_check(
    provider: ReferenceProvider,
    az_limits: AzimuthLimits | None,
    el_max_deg: float = 85.0,
    el_min_deg: float = -85.0,
    tick_dt: float = TICK_DT_S,
    tau_s: float = VC_TAU_S,
    v_max: float = MAIN_RATE_DEGS,
    starting_cum_az_deg: float | None = None,
) -> PreCheckResult:
    """Walk the whole trajectory before commanding anything.

    - Verifies every sample's `az_cum_deg` fits inside `az_limits.contains_cum`.
    - Verifies every sample's `el_deg` fits inside [el_min_deg, el_max_deg].
    - Counts ticks where the FF command would saturate the plant.

    `starting_cum_az_deg` is an optional shift applied to the provider's
    cumulative azimuth: the provider's spline is anchored to the ECEF-derived
    az_cum which may start far from the mount's current cumulative az. When
    supplied, we check `provider_az_cum[i] - provider_az_cum[0] + start`
    against the cable budget. If not supplied, the provider's raw az_cum is
    compared directly (useful when the mount is already aligned).
    """
    t0, t1 = provider.valid_range()
    n = int(np.floor((t1 - t0) / tick_dt)) + 1
    az_cum = np.zeros(n)
    el = np.zeros(n)
    v_az = np.zeros(n)
    v_el = np.zeros(n)
    a_az = np.zeros(n)
    a_el = np.zeros(n)
    for i in range(n):
        s = provider.sample(float(t0 + i * tick_dt))
        az_cum[i] = s.az_cum_deg
        el[i] = s.el_deg
        v_az[i] = s.v_az_degs
        v_el[i] = s.v_el_degs
        a_az[i] = s.a_az_degs2
        a_el[i] = s.a_el_degs2

    if starting_cum_az_deg is not None:
        az_cum = az_cum - az_cum[0] + float(starting_cum_az_deg)

    cable_violations = 0
    if az_limits is not None:
        ok = np.vectorize(az_limits.contains_cum)(az_cum)
        cable_violations = int(np.count_nonzero(~ok))

    el_violations = int(np.count_nonzero((el > el_max_deg) | (el < el_min_deg)))

    v_ff_az = v_az + tau_s * a_az
    v_ff_el = v_el + tau_s * a_el
    sat = int(np.count_nonzero(
        (np.abs(v_ff_az) > v_max) | (np.abs(v_ff_el) > v_max)
    ))

    notes: list[str] = []
    if cable_violations:
        notes.append(f"{cable_violations} tick(s) outside cable-wrap range")
    if el_violations:
        notes.append(
            f"{el_violations} tick(s) outside elevation band "
            f"[{el_min_deg:+.1f}, {el_max_deg:+.1f}]"
        )
    if sat:
        notes.append(f"{sat} tick(s) where FF command saturates ±{v_max:.1f}°/s")

    return PreCheckResult(
        feasible=(cable_violations == 0 and el_violations == 0),
        peak_v_az_degs=float(np.max(np.abs(v_az))),
        peak_v_el_degs=float(np.max(np.abs(v_el))),
        peak_a_az_degs2=float(np.max(np.abs(a_az))),
        peak_a_el_degs2=float(np.max(np.abs(a_el))),
        min_cum_az_deg=float(np.min(az_cum)),
        max_cum_az_deg=float(np.max(az_cum)),
        min_el_deg=float(np.min(el)),
        max_el_deg=float(np.max(el)),
        cable_wrap_violations=cable_violations,
        el_limit_violations=el_violations,
        v_saturation_ticks=sat,
        notes=notes,
    )


# ---------- main loop --------------------------------------------------


def track(
    cli: MountClient,
    provider: ReferenceProvider,
    *,
    tick_dt: float = TICK_DT_S,
    latency_s: float = LATENCY_S,
    tau_s: float = VC_TAU_S,
    kp_pos: float = KP_POS,
    v_corr_max: float = V_CORR_MAX_DEGS,
    v_max: float = MAIN_RATE_DEGS,
    az_limits: AzimuthLimits | None = None,
    az_tracker: CumulativeAzTracker | None = None,
    position_logger: "Any" = None,  # noqa: F821 (PositionLogger, avoid import cycle)
    stop_signal: threading.Event | None = None,
    max_duration_s: float = MAX_DURATION_S,
    stale_tolerance_ticks: int = STALE_TOLERANCE_TICKS,
    el_max_deg: float = 85.0,
    el_min_deg: float = -85.0,
    dry_run: bool = False,
    offset_provider: Callable[[], OffsetSnapshot] | None = None,
    tick_callback: Callable[[TickInfo], None] | None = None,
) -> TrackResult:
    """Indefinite FF+FB tick loop tracking a ReferenceProvider.

    Behavior:
    - If `t_now < provider.valid_range()[0]` at entry, waits (sleeping in
      `tick_dt` slices, still honoring stop_signal) until the head time.
    - On each tick, samples `provider(t_now + latency_s)`, computes FF+FB
      command, clamps per-axis, issues `scope_speed_move(speed, angle,
      dur=TICK_CMD_DUR_S)`.
    - On exit (any reason) issues a single zero-speed command and flushes
      az_tracker state to disk if provided.

    `dry_run=True` runs the whole loop but never calls `speed_move` — the
    mount sits still while the log records everything. Use for rehearsal.
    """
    errors: list[str] = []
    if stop_signal is None:
        stop_signal = threading.Event()
    sigint_handler = _install_sigint_handler(stop_signal)

    t0_wall = time.monotonic()
    prov_t0, prov_t1 = provider.valid_range()

    # Measure initial position so cumulative-az tracker is anchored.
    try:
        alt0, az0_wrapped, _fw_t0 = measure_altaz_timed(cli, EarthLocation.from_geodetic(0, 0, 0))
    except Exception as exc:
        _uninstall_sigint_handler(sigint_handler)
        return TrackResult(
            ok=False, exit_reason="mount_error",
            ticks=0, elapsed_s=0.0,
            az_err_rms=0.0, az_err_peak=0.0,
            el_err_rms=0.0, el_err_peak=0.0,
            sat_az_ticks=0, sat_el_ticks=0,
            final_cum_az_deg=0.0, final_el_deg=0.0,
            errors=[f"initial measure_altaz_timed failed: {exc}"],
        )
    if az_tracker is None:
        az_tracker = CumulativeAzTracker()
    cur_cum_az = az_tracker.update(az0_wrapped)
    cur_el = alt0

    # Wait until the provider head, if we are early. Sample-time accounting:
    # t_sample = t_now + latency_s must be ≥ prov_t0 for a valid reading.
    while True:
        now = time.time()
        if stop_signal.is_set():
            _uninstall_sigint_handler(sigint_handler)
            return _build_result(
                "stop_signal", 0, time.monotonic() - t0_wall,
                [], [], 0, 0, cur_cum_az, cur_el, errors,
            )
        if now + latency_s >= prov_t0:
            break
        # Sleep until the next tick boundary or stop.
        slice_s = min(tick_dt, prov_t0 - (now + latency_s))
        if slice_s > 0:
            stop_signal.wait(timeout=slice_s)

    # Anchor the reference to the mount's current cumulative position. The
    # provider's az_cum and el come from ECEF + identity-or-calibrated
    # MountFrame — true topocentric values. The mount's encoder has an
    # arbitrary power-on origin that doesn't share ECEF's datum. For tonight's
    # identity-frame operation we don't know (or try to correct) the absolute
    # offset — we just bias the reference so the mount only has to MOVE by
    # the same deltas the trajectory moves. Tracking *shape* is correct;
    # absolute sky-pointing is not (and is not a success criterion).
    try:
        t_anchor = max(time.time() + latency_s, prov_t0)
        ref_anchor = provider.sample(t_anchor)
    except ValueError as exc:
        _uninstall_sigint_handler(sigint_handler)
        return TrackResult(
            ok=False, exit_reason="mount_error",
            ticks=0, elapsed_s=time.monotonic() - t0_wall,
            az_err_rms=0.0, az_err_peak=0.0,
            el_err_rms=0.0, el_err_peak=0.0,
            sat_az_ticks=0, sat_el_ticks=0,
            final_cum_az_deg=cur_cum_az, final_el_deg=cur_el,
            errors=[f"anchor sample failed: {exc}"],
        )
    az_offset = cur_cum_az - ref_anchor.az_cum_deg
    el_offset = cur_el - ref_anchor.el_deg

    if position_logger is not None:
        position_logger.set_phase("stream_track")
        try:
            position_logger.mark_event(
                "stream_anchor",
                anchor_t=t_anchor,
                mount_cum_az=cur_cum_az,
                mount_el=cur_el,
                ref_az_cum=ref_anchor.az_cum_deg,
                ref_el=ref_anchor.el_deg,
                az_offset=az_offset,
                el_offset=el_offset,
            )
        except Exception:
            pass

    az_errs: list[float] = []
    el_errs: list[float] = []
    sat_az = 0
    sat_el = 0
    ticks = 0
    stale_streak = 0
    exit_reason = "end_of_track"

    # Track heading EWMA state. heading_rad_ewma holds the filter output;
    # heading_locked becomes True on ticks where |v| is too small to give a
    # meaningful direction (ψ is frozen at its last good value).
    heading_rad_ewma: float = 0.0
    heading_initialised = False
    heading_locked = True
    # Alpha for a first-order EWMA over a signal sampled at tick_dt.
    ewma_alpha = 1.0 - math.exp(-tick_dt / max(HEADING_EWMA_TAU_S, 1e-6))

    last_offset_snapshot: OffsetSnapshot | None = None

    try:
        while True:
            tick_start = time.monotonic()
            elapsed = tick_start - t0_wall

            if stop_signal.is_set():
                exit_reason = "stop_signal"
                break
            if elapsed > max_duration_s:
                exit_reason = "timeout"
                errors.append(f"max_duration_s={max_duration_s} reached")
                break

            off = offset_provider() if offset_provider is not None else _ZERO_OFFSETS
            if (
                position_logger is not None
                and last_offset_snapshot is not None
                and off != last_offset_snapshot
            ):
                try:
                    position_logger.mark_event(
                        "offset_change",
                        time_offset_s=off.time_offset_s,
                        az_bias_deg=off.az_bias_deg,
                        el_bias_deg=off.el_bias_deg,
                        along_deg=off.along_deg,
                        cross_deg=off.cross_deg,
                    )
                except Exception:
                    pass
            last_offset_snapshot = off

            # 1. Measure.
            try:
                alt, az_wrapped, _fw_t = measure_altaz_timed(
                    cli, EarthLocation.from_geodetic(0, 0, 0),
                )
            except Exception as exc:
                errors.append(f"measure_altaz_timed failed: {exc}")
                exit_reason = "mount_error"
                break
            cur_cum_az = az_tracker.update(az_wrapped)
            cur_el = alt

            # 2. Sample provider at latency-compensated time (+ user time offset).
            t_query = time.time() + latency_s + off.time_offset_s
            if t_query > prov_t1 + provider.__dict__.get("extrapolation_s", 1.0):
                # Past extrapolation horizon — a graceful end-of-track.
                exit_reason = "end_of_track"
                break
            try:
                ref = provider.sample(t_query)
            except ValueError as exc:
                errors.append(f"provider.sample({t_query}) raised: {exc}")
                exit_reason = "mount_error"
                break

            if ref.stale:
                stale_streak += 1
                if stale_streak >= stale_tolerance_ticks:
                    exit_reason = "stale"
                    errors.append(
                        f"{stale_streak} consecutive stale samples; exiting"
                    )
                    break
            else:
                stale_streak = 0

            # Update heading EWMA from the reference velocity, unless
            # |v| is too small to trust the direction.
            v_mag_ref = math.hypot(ref.v_az_degs, ref.v_el_degs)
            if v_mag_ref >= V_MIN_HEADING_LOCK_DEGS:
                new_h = math.atan2(ref.v_el_degs, ref.v_az_degs)
                if not heading_initialised:
                    heading_rad_ewma = new_h
                    heading_initialised = True
                else:
                    # Branch-unwrap toward current EWMA so 359°→1° doesn't
                    # bias the filter.
                    delta = math.atan2(
                        math.sin(new_h - heading_rad_ewma),
                        math.cos(new_h - heading_rad_ewma),
                    )
                    heading_rad_ewma = heading_rad_ewma + ewma_alpha * delta
                heading_locked = False
            else:
                heading_locked = True  # keep previous ψ

            cos_h = math.cos(heading_rad_ewma) if heading_initialised else 1.0
            sin_h = math.sin(heading_rad_ewma) if heading_initialised else 0.0
            d_az_rel = off.along_deg * cos_h - off.cross_deg * sin_h
            d_el_rel = off.along_deg * sin_h + off.cross_deg * cos_h
            d_az = off.az_bias_deg + (0.0 if not heading_initialised else d_az_rel)
            d_el = off.el_bias_deg + (0.0 if not heading_initialised else d_el_rel)

            # 3. Controller math. Apply the start-of-track anchor offset +
            #    user bias so the mount tracks deltas regardless of its
            #    arbitrary encoder origin.
            eff_ref_az = ref.az_cum_deg + az_offset + d_az
            eff_ref_el = ref.el_deg + el_offset + d_el
            err_az = eff_ref_az - cur_cum_az
            err_el = eff_ref_el - cur_el
            v_corr_az = _clip_scalar(kp_pos * err_az, -v_corr_max, v_corr_max)
            v_corr_el = _clip_scalar(kp_pos * err_el, -v_corr_max, v_corr_max)
            v_ff_az = ref.v_az_degs + tau_s * ref.a_az_degs2
            v_ff_el = ref.v_el_degs + tau_s * ref.a_el_degs2
            raw_az = v_ff_az + v_corr_az
            raw_el = v_ff_el + v_corr_el
            if abs(raw_az) > v_max:
                sat_az += 1
            if abs(raw_el) > v_max:
                sat_el += 1
            v_cmd_az = _clip_scalar(raw_az, -v_max, v_max)
            v_cmd_el = _clip_scalar(raw_el, -v_max, v_max)

            # 4. Cable-wrap runtime check (compare current cum_az, not command).
            if az_limits is not None and not az_limits.contains_cum(cur_cum_az):
                exit_reason = "cable_wrap"
                errors.append(
                    f"cum_az={cur_cum_az:+.3f}° outside usable "
                    f"[{az_limits.usable_ccw_cum_deg:+.1f}, "
                    f"{az_limits.usable_cw_cum_deg:+.1f}]"
                )
                break

            # 4b. Sun-avoidance runtime net. Coarse check on the
            #     reference sample's (az_cum, el) treated as sky — valid
            #     after rotation calibration, approximate otherwise.
            #     SunSafetyMonitor is the authoritative backstop; this
            #     just catches trajectories whose provider output rolls
            #     into the cone mid-run so we abort before the mount
            #     commits to the slew.
            sun_safe, sun_reason = _is_sun_safe(
                ref.az_cum_deg % 360.0, float(ref.el_deg),
            )
            if not sun_safe:
                exit_reason = "sun_avoidance"
                errors.append(sun_reason)
                break

            # 5. Compose firmware command.
            v_mag = float(np.hypot(v_cmd_az, v_cmd_el))
            speed = int(round(v_mag * SPEED_PER_DEG_PER_SEC))
            if v_mag > 1e-6:
                angle = int(round(
                    (np.degrees(np.arctan2(v_cmd_el, v_cmd_az)) + 360.0) % 360.0
                ))
            else:
                angle = 0
                speed = 0

            # 6. Issue and log.
            if not dry_run and speed > 0:
                try:
                    speed_move(cli, speed, angle, TICK_CMD_DUR_S)
                except SunSafetyLocked as exc:
                    # Monitor is running the jog; step out so the
                    # session's LiveTrackManager.stop() can tear us down.
                    errors.append(str(exc))
                    exit_reason = "sun_avoidance"
                    break
                except Exception as exc:
                    errors.append(f"speed_move failed: {exc}")
                    exit_reason = "mount_error"
                    break
            if position_logger is not None:
                position_logger.mark_event(
                    "stream_tick",
                    ref_az_cum=eff_ref_az,
                    ref_el=eff_ref_el,
                    raw_ref_az_cum=ref.az_cum_deg,
                    raw_ref_el=ref.el_deg,
                    ref_v_az=ref.v_az_degs,
                    ref_v_el=ref.v_el_degs,
                    ref_a_az=ref.a_az_degs2,
                    ref_a_el=ref.a_el_degs2,
                    v_ff_az=v_ff_az, v_ff_el=v_ff_el,
                    v_corr_az=v_corr_az, v_corr_el=v_corr_el,
                    v_cmd_az=v_cmd_az, v_cmd_el=v_cmd_el,
                    cmd_speed=speed, cmd_angle=angle,
                    cur_cum_az=cur_cum_az, cur_el=cur_el,
                    err_az=err_az, err_el=err_el,
                    stale=ref.stale, extrapolated=ref.extrapolated,
                    dry_run=dry_run,
                )

            if tick_callback is not None:
                try:
                    heading_deg = (
                        (math.degrees(heading_rad_ewma) + 360.0) % 360.0
                        if heading_initialised
                        else 0.0
                    )
                    tick_callback(
                        TickInfo(
                            tick=ticks,
                            t_wall=time.time(),
                            heading_deg=heading_deg,
                            heading_locked=heading_locked or not heading_initialised,
                            d_az_deg=d_az,
                            d_el_deg=d_el,
                            eff_ref_az_cum_deg=eff_ref_az,
                            eff_ref_el_deg=eff_ref_el,
                            cur_cum_az_deg=cur_cum_az,
                            cur_el_deg=cur_el,
                            err_az_deg=err_az,
                            err_el_deg=err_el,
                            ref_stale=ref.stale,
                        )
                    )
                except Exception:
                    pass

            az_errs.append(err_az)
            el_errs.append(err_el)
            ticks += 1

            # 7. Deadline-pace to the next tick.
            sleep_for = tick_dt - (time.monotonic() - tick_start)
            if sleep_for > 0:
                stop_signal.wait(timeout=sleep_for)
    finally:
        # Zero the motor no matter why we exited. Swallow failures — we
        # prefer to report the original exit reason.
        if not dry_run:
            try:
                speed_move(cli, 0, 0, TICK_CMD_DUR_S)
            except Exception:
                pass
        if az_tracker is not None:
            try:
                az_tracker.save()
            except Exception:
                pass
        if position_logger is not None:
            try:
                position_logger.set_phase("idle")
            except Exception:
                pass
        _uninstall_sigint_handler(sigint_handler)

    return _build_result(
        exit_reason, ticks, time.monotonic() - t0_wall,
        az_errs, el_errs, sat_az, sat_el,
        cur_cum_az, cur_el, errors,
    )


# ---------- helpers ---------------------------------------------------


def _clip_scalar(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _build_result(
    exit_reason: str, ticks: int, elapsed_s: float,
    az_errs: list[float], el_errs: list[float],
    sat_az: int, sat_el: int,
    final_cum_az: float, final_el: float,
    errors: list[str],
) -> TrackResult:
    if az_errs:
        az_arr = np.asarray(az_errs, dtype=float)
        el_arr = np.asarray(el_errs, dtype=float)
        az_rms = float(np.sqrt(np.mean(az_arr ** 2)))
        el_rms = float(np.sqrt(np.mean(el_arr ** 2)))
        az_peak = float(np.max(np.abs(az_arr)))
        el_peak = float(np.max(np.abs(el_arr)))
    else:
        az_rms = el_rms = az_peak = el_peak = 0.0
    ok = exit_reason in ("end_of_track", "stop_signal")
    return TrackResult(
        ok=ok, exit_reason=exit_reason,
        ticks=ticks, elapsed_s=elapsed_s,
        az_err_rms=az_rms, az_err_peak=az_peak,
        el_err_rms=el_rms, el_err_peak=el_peak,
        sat_az_ticks=sat_az, sat_el_ticks=sat_el,
        final_cum_az_deg=final_cum_az, final_el_deg=final_el,
        errors=errors,
    )


def _install_sigint_handler(stop_signal: threading.Event):
    """Install a SIGINT handler that sets stop_signal. Returns prev handler."""
    try:
        prev = signal.getsignal(signal.SIGINT)
    except ValueError:
        return None  # not on main thread

    def _handler(signum, frame):
        stop_signal.set()

    try:
        signal.signal(signal.SIGINT, _handler)
    except ValueError:
        return None
    return prev


def _uninstall_sigint_handler(prev) -> None:
    if prev is None:
        return
    try:
        signal.signal(signal.SIGINT, prev)
    except ValueError:
        pass


# Silence unused-import warnings for helpers used in docstrings.
_ = (wrap_pm180,)
