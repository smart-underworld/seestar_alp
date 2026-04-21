#!/usr/bin/env python3
"""Fast tuning harness for auto_level's velocity-mode controller.

Three modes:

  --mode setpoints   (default)
        Drive a short list of az setpoints via move_azimuth_to_velocity.
        Useful for measuring convergence behavior and oscillation
        against different PD tunings.

  --mode step_response
        Issue scope_speed_move(speed, angle, dur_sec) bursts from rest and
        sample position at a fixed interval. Fits a first-order response
        rate(t) = r_ss · (1 − exp(−t/τ)) for each commanded speed.

  --mode diagonal
        Issue short bursts at a list of angles (e.g. 0, 45, 90, …, 315)
        and measure the resulting (Δaz, Δalt) vector. Verifies whether
        firmware does proper vector decomposition of the commanded angle.
        Re-centers to a safe "home" position between bursts.

HTTP command latency (scope_get_equ_coord, scope_speed_move,
get_device_state) is recorded on every call and summarized at the end
of every run.

Usage examples:
    # Setpoint tuning run:
    uv run python scripts/tune_vc.py \\
        --setpoints=-170,+30,-60,+90,-30,+170 \\
        --kp 0.3 --kd 0.4 --tol 0.3 --alt 10.0

    # Step-response characterization at 4 speeds:
    uv run python scripts/tune_vc.py --mode step_response \\
        --step-speeds=100,300,700,1440 --step-dur 8.0 --step-sample-dt 0.5
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_here = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.realpath(os.path.join(_here, "..")))

from astropy import units as u  # noqa: E402
from astropy.coordinates import EarthLocation  # noqa: E402

from datetime import datetime  # noqa: E402

from device.alpaca_client import AlpacaClient  # noqa: E402
from device.config import Config  # noqa: E402
from device import velocity_controller as vc  # noqa: E402
from device.plant_limits import AzimuthLimits, CumulativeAzTracker  # noqa: E402
from device.velocity_controller import (  # noqa: E402
    PositionLogger,
    ensure_scenery_mode,
    iscope_fallback_goto,
    issue_slew,
    wait_until_near_target,
)


def _run_id() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


# Aliases so the rest of this file can keep its short local names.
_wrap_pm180 = vc.wrap_pm180
_measure_altaz = vc.measure_altaz
_speed_move = vc.speed_move
_wait_for_mount_idle = vc.wait_for_mount_idle
set_tracking = vc.set_tracking
_MIN_DUR_S = vc.MIN_DUR_S
_SPEED_PER_DEG_PER_SEC = vc.SPEED_PER_DEG_PER_SEC
move_azimuth_to_velocity = vc.move_azimuth_to_velocity
move_azimuth_to_ff = vc.move_azimuth_to_ff
move_azimuth_to_with_correction = vc.move_azimuth_to_with_correction


class InstrumentedAlpacaClient(AlpacaClient):
    """AlpacaClient subclass that records every method_sync round-trip
    latency, keyed by firmware method name."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.latencies: dict[str, list[float]] = {}

    def method_sync(self, method: str, params=None):
        t0 = time.monotonic()
        result = super().method_sync(method, params)
        dt = time.monotonic() - t0
        self.latencies.setdefault(method, []).append(dt)
        return result

    def summary(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for method, samples in self.latencies.items():
            if not samples:
                continue
            srt = sorted(samples)
            n = len(srt)
            out[method] = {
                "count": n,
                "mean_ms": 1000 * statistics.mean(srt),
                "p50_ms": 1000 * srt[n // 2],
                "p90_ms": 1000 * srt[max(0, int(0.9 * n) - 1)],
                "p99_ms": 1000 * srt[max(0, int(0.99 * n) - 1)],
                "max_ms": 1000 * srt[-1],
            }
        return out


def _print_latency_summary(cli: InstrumentedAlpacaClient) -> None:
    s = cli.summary()
    if not s:
        return
    print()
    print("HTTP command latency (ms, RPC round-trip through the Alpaca action endpoint)")
    print(f"  {'method':<24}  {'n':>5}  {'mean':>6}  {'p50':>6}  {'p90':>6}  {'p99':>6}  {'max':>6}")
    for method in sorted(s.keys()):
        st = s[method]
        print(
            f"  {method:<24}  {st['count']:>5}  "
            f"{st['mean_ms']:>5.0f}  {st['p50_ms']:>5.0f}  "
            f"{st['p90_ms']:>5.0f}  {st['p99_ms']:>5.0f}  "
            f"{st['max_ms']:>5.0f}"
        )


# ---------------------------------------------------------------------------
# Setpoint mode
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    target: float
    start_az: float
    end_az: float
    residual: float
    iterations: int
    commands_issued: int
    sign_flips: int
    rate_ceiling_halvings: int
    loop_dt_mean: float
    loop_dt_max: float
    wall_time_s: float
    stuck_bail: bool
    fallback_goto_used: bool


def _parse_floats(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def _parse_ints(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def run_setpoints(cli: InstrumentedAlpacaClient, args) -> int:
    loc = EarthLocation(
        lat=Config.init_lat * u.deg, lon=Config.init_long * u.deg, height=0 * u.m
    )
    setpoints = _parse_floats(args.setpoints)
    if not setpoints:
        print("ERROR: need at least one setpoint", file=sys.stderr)
        return 2

    print("=" * 78)
    print("Velocity-controller tuning — setpoint mode")
    print(f"  kp={args.kp}  kd={args.kd}  max_rate={args.max_rate}°/s  loop_dt={args.loop_dt}s")
    print(f"  min_speed={args.min_speed}  fine_min_speed={args.fine_min_speed}  "
          f"fine_thresh_factor={args.fine_thresh_factor}")
    print(f"  predictor={'on' if args.use_predictor else 'off'}  τ={args.tau}s")
    print(f"  tol={args.tol}°  alt={args.alt}°  timeout={args.timeout}s")
    print(f"  setpoints ({len(setpoints)}): {setpoints}")
    print("=" * 78)

    # Start background position logger so the /velocity_controller page
    # picks up this tuning run. Writes auto_level_logs/<run_id>.positions.jsonl.
    log_path = Path(_here).parent / "auto_level_logs" / f"{_run_id()}.positions.jsonl"
    logger = PositionLogger(cli, loc, log_path, poll_interval_s=0.5)
    logger.start()
    logger.set_phase("tune_vc_setpoints_init")
    logger.mark_event(
        "run_start",
        predictor="on" if args.use_predictor else "off",
        kp=args.kp, kd=args.kd, tau=args.tau, tol=args.tol, alt=args.alt,
        setpoints=setpoints,
    )
    print(f"PositionLogger → {log_path}")

    # Load cable-wrap limits (optional). If present, the FF controller
    # will plan in cumulative (unwrapped) space and refuse targets that
    # would exceed the measured usable range.
    az_limits: AzimuthLimits | None = None
    az_tracker: CumulativeAzTracker | None = None
    if getattr(args, "use_az_limits", True):
        az_limits = AzimuthLimits.load()
        if az_limits is not None:
            az_tracker = CumulativeAzTracker()
            print(f"AzimuthLimits loaded: usable "
                  f"[{az_limits.usable_ccw_cum_deg:+.1f}°, "
                  f"{az_limits.usable_cw_cum_deg:+.1f}°] "
                  f"(hard stops ±{az_limits.total_travel_deg/2:.1f}°)")
        else:
            print("No plant_limits.json found — skipping cable-wrap enforcement.")

    try:
        print("Entering scenery mode...")
        ensure_scenery_mode(cli)
        print("Disabling tracking...")
        set_tracking(cli, False)

        first = setpoints[0]
        print(f"Initial goto: az={first:+.1f}° alt={args.alt:.1f}° (coarse tol 3°)")
        logger.set_target(first, args.alt)
        init_ra, init_dec = issue_slew(cli, first, args.alt, loc)
        ok, init_dist, _ = wait_until_near_target(
            cli,
            target_ra_h=init_ra,
            target_dec_d=init_dec,
            tolerance_deg=3.0,
            timeout=60.0,
            stall_threshold_s=5.0,
        )
        if not ok:
            print(f"  (warning: initial goto did not reach 3° — dist={init_dist})")
        time.sleep(1.0)
        _, cur_az = _measure_altaz(cli, loc)
        if az_tracker is not None:
            az_tracker.update(cur_az)
            print(f"Initial arrived: measured_az={cur_az:+.3f}°  "
                  f"cum_az={az_tracker.cum_az_deg:+.3f}°")
        else:
            print(f"Initial arrived: measured_az={cur_az:+.3f}°")
        print()

        results: list[StepResult] = []
        t_run_start = time.monotonic()
        for i, target in enumerate(setpoints, start=1):
            tag = f"[{i}/{len(setpoints)}] az={target:+7.2f}°"
            logger.set_phase("tune_vc_setpoint", step=i)
            logger.set_target(target, args.alt)
            logger.mark_event("setpoint_start", step=i, target_az=target, cur_az=cur_az)
            delta = _wrap_pm180(target - cur_az)
            t_step = time.monotonic()
            print(f"{tag} START  (cur={cur_az:+.3f}°, delta={delta:+.3f}°)", flush=True)
            try:
                if args.control in ("feedforward", "ff_pure"):
                    # ff_pure forces kp_pos=0 (pure open-loop FF);
                    # feedforward uses the configured kp_pos (closed-loop).
                    kp_pos_use = 0.0 if args.control == "ff_pure" else args.kp_pos
                    _, meas_az, stats = move_azimuth_to_ff(
                        cli,
                        target_az_deg=target,
                        cur_az_deg=cur_az,
                        loc=loc,
                        target_alt_deg=args.alt,
                        tag=tag,
                        position_logger=logger,
                        v_max=args.max_rate,
                        a_max=args.a_max,
                        j_max=args.j_max,
                        tick_dt=args.loop_dt,
                        settle_s=args.settle if args.settle > 0 else 1.5,
                        cold_start_lag_s=args.cold_start_lag,
                        profile=args.profile,
                        az_forbidden_deg=args.az_forbidden,
                        az_limits=az_limits,
                        az_tracker=az_tracker,
                        kp_pos=kp_pos_use,
                        v_corr_max=args.v_corr_max,
                        arrive_tolerance_deg=args.tol,
                        settle_max_s=args.settle_max_s,
                        fallback_residual_deg=args.ff_fallback_residual,
                        fallback_goto_fn=iscope_fallback_goto,
                    )
                else:
                    _, meas_az, stats = move_azimuth_to_velocity(
                        cli,
                        target_az_deg=target,
                        cur_az_deg=cur_az,
                        loc=loc,
                        target_alt_deg=args.alt,
                        tag=tag,
                        arrive_tolerance_deg=args.tol,
                        position_logger=logger,
                        timeout_s=args.timeout,
                        kp=args.kp,
                        kd=args.kd,
                        max_rate_degs=args.max_rate,
                        loop_dt_s=args.loop_dt,
                        min_speed=args.min_speed,
                        fine_min_speed=args.fine_min_speed,
                        fine_threshold_factor=args.fine_thresh_factor,
                        max_halvings=args.max_halvings,
                        use_predictor=args.use_predictor,
                        tau_s=args.tau,
                        fallback_goto_fn=iscope_fallback_goto,
                    )
            except Exception as e:
                print(f"{tag} ERROR: {e}", file=sys.stderr)
                logger.mark_event("setpoint_error", step=i, error=repr(e))
                return 1
            wall = time.monotonic() - t_step
            results.append(StepResult(
                target=target, start_az=cur_az, end_az=meas_az,
                residual=stats["final_residual_deg"],
                iterations=stats["iterations"],
                commands_issued=stats["commands_issued"],
                sign_flips=stats["sign_flips"],
                rate_ceiling_halvings=stats["rate_ceiling_halvings"],
                loop_dt_mean=stats["loop_dt_mean_s"],
                loop_dt_max=stats["loop_dt_max_s"],
                wall_time_s=wall,
                stuck_bail=stats["stuck_bail"],
                fallback_goto_used=stats["fallback_goto_used"],
            ))
            cur_az = meas_az
            logger.mark_event(
                "setpoint_done", step=i, target_az=target, meas_az=meas_az,
                residual=stats["final_residual_deg"],
                iterations=stats["iterations"],
                wall_s=wall,
                fallback_goto_used=stats["fallback_goto_used"],
            )
            print(
                f"{tag} DONE  wall={wall:.1f}s  iter={stats['iterations']}  "
                f"cmds={stats['commands_issued']}  flips={stats['sign_flips']}  "
                f"halvings={stats['rate_ceiling_halvings']}  "
                f"dt_mean={stats['loop_dt_mean_s']:.2f}s  "
                f"residual={stats['final_residual_deg']:+.3f}°"
                + ("  [FALLBACK]" if stats["fallback_goto_used"] else "")
                + ("  [STUCK_BAIL]" if stats["stuck_bail"] else ""),
                flush=True,
            )
            if args.settle > 0:
                time.sleep(args.settle)
            print()

        total_wall = time.monotonic() - t_run_start
        logger.set_phase("tune_vc_setpoints_done")
        logger.mark_event("run_end", total_wall_s=total_wall, steps=len(results))
    finally:
        logger.stop()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    header = (f"  {'step':>4}  {'target':>8}  {'residual':>9}  {'iter':>4}  "
              f"{'cmds':>4}  {'flips':>5}  {'halv':>4}  "
              f"{'dt_mean':>7}  {'wall':>6}")
    print(header)
    for i, r in enumerate(results, start=1):
        flags = ""
        if r.fallback_goto_used: flags += " FB"
        if r.stuck_bail: flags += " SB"
        print(
            f"  {i:>4}  {r.target:>+8.2f}  {r.residual:>+9.3f}  "
            f"{r.iterations:>4}  {r.commands_issued:>4}  "
            f"{r.sign_flips:>5}  {r.rate_ceiling_halvings:>4}  "
            f"{r.loop_dt_mean:>6.2f}s  {r.wall_time_s:>5.1f}s{flags}"
        )
    print()
    abs_res = [abs(r.residual) for r in results]
    iters = [r.iterations for r in results]
    flips = [r.sign_flips for r in results]
    print(
        f"  total_wall={total_wall:.1f}s  steps={len(results)}  "
        f"|residual| mean={statistics.mean(abs_res):.3f}° max={max(abs_res):.3f}°  "
        f"iter mean={statistics.mean(iters):.1f} max={max(iters)}  "
        f"flips mean={statistics.mean(flips):.1f} max={max(flips)}"
    )
    return 0


# ---------------------------------------------------------------------------
# Step-response mode
# ---------------------------------------------------------------------------


def _collect_step_response(
    cli: InstrumentedAlpacaClient,
    loc: EarthLocation,
    speed: int,
    angle: int,
    dur_sec: int,
    sample_dt: float,
) -> tuple[list[tuple[float, float]], dict]:
    """Command scope_speed_move(speed, angle, dur_sec) from rest and sample
    position at `sample_dt` intervals for dur_sec + 2 s (to capture decel).

    Returns:
        samples: list of (t_relative_s, delta_az_deg) starting at (0, 0)
        meta: dict with start_az, end_az, etc.
    """
    _, az0 = _measure_altaz(cli, loc)
    t_start = time.monotonic()
    _speed_move(cli, speed, angle, dur_sec)
    samples: list[tuple[float, float]] = [(0.0, 0.0)]

    total_window = dur_sec + 2.0
    next_sample_t = t_start + sample_dt
    while time.monotonic() - t_start < total_window:
        now = time.monotonic()
        if now < next_sample_t:
            time.sleep(max(0.0, next_sample_t - now))
        _, az = _measure_altaz(cli, loc)
        t_rel = time.monotonic() - t_start
        d_az = _wrap_pm180(az - az0)
        samples.append((t_rel, d_az))
        next_sample_t += sample_dt

    # Ensure motor is idle before returning.
    _wait_for_mount_idle(cli, timeout_s=3.0)
    _, az_end = _measure_altaz(cli, loc)
    return samples, {
        "start_az": az0,
        "end_az": az_end,
        "total_motion_deg": abs(_wrap_pm180(az_end - az0)),
        "dur_sec": dur_sec,
        "speed": speed,
        "angle": angle,
    }


def _fit_first_order(samples: list[tuple[float, float]], dur_sec: float):
    """Fit rate(t) = r_ss · (1 − exp(−t / τ)) via position integral model:

        pos(t) = r_ss · [t − τ · (1 − exp(−t / τ))]

    Fit on the samples *during* the commanded burst (0 ≤ t ≤ dur_sec) only,
    which is where the first-order assumption holds (no decel yet). Signed
    direction is encoded in r_ss.

    Returns (r_ss, tau, rmse_deg) or (None, None, None) if fit fails.
    """
    import numpy as np
    from scipy.optimize import curve_fit

    ts = np.array([s[0] for s in samples])
    azs = np.array([s[1] for s in samples])
    mask = ts <= dur_sec + 0.2  # small margin
    ts_fit = ts[mask]
    azs_fit = azs[mask]
    if len(ts_fit) < 4:
        return None, None, None

    def pos_model(t, r_ss, tau):
        tau = max(tau, 1e-3)
        return r_ss * (t - tau * (1.0 - np.exp(-t / tau)))

    # Good initial guess: r_ss from end-of-burst slope; tau ~ 0.3 s.
    r0 = (azs_fit[-1] - azs_fit[-2]) / max(ts_fit[-1] - ts_fit[-2], 1e-3)
    if not math.isfinite(r0) or abs(r0) < 1e-3:
        r0 = azs_fit[-1] / max(ts_fit[-1], 1e-3)
    try:
        popt, _ = curve_fit(
            pos_model, ts_fit, azs_fit, p0=[r0, 0.3],
            maxfev=5000,
        )
    except Exception:
        return None, None, None
    r_ss, tau = float(popt[0]), float(popt[1])
    pred = pos_model(ts_fit, r_ss, tau)
    rmse = float(np.sqrt(np.mean((pred - azs_fit) ** 2)))
    return r_ss, tau, rmse


def run_step_response(cli: InstrumentedAlpacaClient, args) -> int:
    loc = EarthLocation(
        lat=Config.init_lat * u.deg, lon=Config.init_long * u.deg, height=0 * u.m
    )

    speeds = _parse_ints(args.step_speeds)
    if not speeds:
        print("ERROR: need at least one step speed", file=sys.stderr)
        return 2
    dur = int(args.step_dur)
    if dur < _MIN_DUR_S:
        print(f"ERROR: step-dur must be >= {_MIN_DUR_S} (firmware floor)", file=sys.stderr)
        return 2

    print("=" * 78)
    print("Velocity-controller tuning — step-response characterization")
    print(f"  speeds: {speeds}")
    print(f"  burst_dur={dur}s  sample_dt={args.step_sample_dt}s")
    print(f"  alt={args.alt}°  alternate direction per burst: {args.step_alternate}")
    print("=" * 78)

    print("Entering scenery mode; disabling tracking...")
    ensure_scenery_mode(cli)
    set_tracking(cli, False)

    # Initial goto somewhere safe (away from ±180°). Use args.step_start_az.
    start_az = args.step_start_az
    print(f"Initial goto: az={start_az:+.1f}° alt={args.alt:.1f}°")
    init_ra, init_dec = issue_slew(cli, start_az, args.alt, loc)
    ok, init_dist, _ = wait_until_near_target(
        cli, target_ra_h=init_ra, target_dec_d=init_dec,
        tolerance_deg=3.0, timeout=60.0, stall_threshold_s=5.0,
    )
    if not ok:
        print(f"  (warning: initial goto did not reach 3° — dist={init_dist})")
    # Wait for the firmware to report move_type == "none" AND re-disable
    # tracking (firmware re-engages it on goto completion).
    idle_ok, idle_elapsed = _wait_for_mount_idle(cli, timeout_s=15.0)
    print(f"Post-goto: mount idle reached after {idle_elapsed:.2f}s "
          f"(ok={idle_ok}); re-disabling tracking.")
    set_tracking(cli, False)
    time.sleep(1.0)

    # Collect.
    results = []
    jsonl_path = None
    if args.step_log:
        jsonl_path = Path(args.step_log)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_path.write_text("")  # truncate

    for i, speed in enumerate(speeds, start=1):
        angle = 0 if (not args.step_alternate or i % 2 == 1) else 180
        # Re-center after each burst if we've wandered too far from start_az.
        _, cur_az = _measure_altaz(cli, loc)
        if abs(_wrap_pm180(cur_az - start_az)) > 40.0:
            print(f"[{i}/{len(speeds)}] re-centering to {start_az:+.1f}° before next burst...")
            init_ra, init_dec = issue_slew(cli, start_az, args.alt, loc)
            wait_until_near_target(
                cli, target_ra_h=init_ra, target_dec_d=init_dec,
                tolerance_deg=3.0, timeout=60.0, stall_threshold_s=5.0,
            )
            _wait_for_mount_idle(cli, timeout_s=15.0)
            set_tracking(cli, False)
            time.sleep(1.0)

        # Ensure the mount is truly idle and tracking is off right before
        # the characterization burst, else firmware quirks corrupt the
        # measurement.
        _wait_for_mount_idle(cli, timeout_s=5.0)
        set_tracking(cli, False)

        print(f"[{i}/{len(speeds)}] step-response: speed={speed} angle={angle} dur={dur}s")
        samples, meta = _collect_step_response(
            cli, loc, speed=speed, angle=angle, dur_sec=dur,
            sample_dt=args.step_sample_dt,
        )
        r_ss, tau, rmse = _fit_first_order(samples, dur)

        # Expected steady-state rate per the linear calibration speed/237.
        r_ss_expected = speed / _SPEED_PER_DEG_PER_SEC * (1 if angle == 0 else -1)
        total_motion = meta["total_motion_deg"]

        row = {
            "speed": speed,
            "angle": angle,
            "dur_sec": dur,
            "total_motion_deg": total_motion,
            "r_ss_expected_degs": r_ss_expected,
            "r_ss_fitted_degs": r_ss,
            "tau_s": tau,
            "fit_rmse_deg": rmse,
            "sample_count": len(samples),
            "samples": samples,
        }
        results.append(row)

        if tau is not None:
            print(
                f"   → total_motion={total_motion:.2f}°  "
                f"fitted r_ss={r_ss:+.3f}°/s (expected {r_ss_expected:+.3f}°/s)  "
                f"τ={tau:.3f}s  fit_rmse={rmse:.3f}°"
            )
        else:
            print(f"   → total_motion={total_motion:.2f}°  (fit failed)")
        if jsonl_path is not None:
            with jsonl_path.open("a") as f:
                f.write(json.dumps({k: v for k, v in row.items() if k != "samples"}) + "\n")
                for (t, d) in samples:
                    f.write(json.dumps({
                        "speed": speed, "angle": angle, "t": t, "delta_az_deg": d,
                    }) + "\n")
        time.sleep(1.0)
        print()

    # Summary.
    print("=" * 78)
    print("STEP-RESPONSE SUMMARY")
    print("=" * 78)
    print(f"  {'speed':>6}  {'angle':>5}  {'r_ss_exp':>10}  {'r_ss_fit':>10}  {'τ (s)':>7}  {'rmse':>6}")
    for r in results:
        tau_s = f"{r['tau_s']:>7.3f}" if r['tau_s'] is not None else "    -  "
        rss_f = f"{r['r_ss_fitted_degs']:>+9.3f}" if r['r_ss_fitted_degs'] is not None else "     -   "
        rmse = f"{r['fit_rmse_deg']:>5.3f}" if r['fit_rmse_deg'] is not None else "   -  "
        print(
            f"  {r['speed']:>6}  {r['angle']:>5}  "
            f"{r['r_ss_expected_degs']:>+9.3f}  {rss_f}  "
            f"{tau_s}  {rmse}"
        )
    taus = [r['tau_s'] for r in results if r['tau_s'] is not None]
    if taus:
        print()
        print(
            f"  τ stats across {len(taus)} fits:  "
            f"mean={statistics.mean(taus):.3f}s  "
            f"median={statistics.median(taus):.3f}s  "
            f"min={min(taus):.3f}s  max={max(taus):.3f}s"
        )
    if jsonl_path is not None:
        print(f"  raw samples saved to: {jsonl_path}")
    return 0


# ---------------------------------------------------------------------------
# Diagonal-angle calibration mode
# ---------------------------------------------------------------------------


def _recenter(cli, loc, home_alt: float, home_az: float) -> tuple[float, float]:
    """Slew to (home_alt, home_az), wait idle, disable tracking, return
    measured (alt, az)."""
    ra, dec = issue_slew(cli, home_az, home_alt, loc)
    wait_until_near_target(
        cli, target_ra_h=ra, target_dec_d=dec,
        tolerance_deg=3.0, timeout=60.0, stall_threshold_s=5.0,
    )
    _wait_for_mount_idle(cli, timeout_s=15.0)
    set_tracking(cli, False)
    time.sleep(1.0)
    return _measure_altaz(cli, loc)


def run_diagonal(cli: InstrumentedAlpacaClient, args) -> int:
    loc = EarthLocation(
        lat=Config.init_lat * u.deg, lon=Config.init_long * u.deg, height=0 * u.m
    )
    angles = _parse_floats(args.diag_angles)
    if not angles:
        print("ERROR: need at least one angle", file=sys.stderr)
        return 2
    speed = int(args.diag_speed)
    dur = int(args.diag_dur)
    home_alt = args.diag_home_alt
    home_az = args.diag_home_az

    print("=" * 78)
    print("Velocity-controller tuning — diagonal-angle calibration")
    print(f"  speed={speed}  dur_sec={dur}  home=(alt={home_alt:.1f}°, az={home_az:.1f}°)")
    print(f"  angles ({len(angles)}): {angles}")
    print("=" * 78)

    print("Entering scenery mode; disabling tracking...")
    ensure_scenery_mode(cli)
    set_tracking(cli, False)

    nominal_rate = speed / _SPEED_PER_DEG_PER_SEC  # °/s (unsigned magnitude)
    nominal_motion = nominal_rate * dur             # degrees magnitude for full burst

    results = []
    for i, angle in enumerate(angles, start=1):
        print(f"[{i}/{len(angles)}] recentering to (alt={home_alt:.1f}, az={home_az:.1f})...")
        alt0, az0 = _recenter(cli, loc, home_alt, home_az)
        print(f"  pre-burst: alt={alt0:+.3f}° az={az0:+.3f}°")

        print(f"[{i}/{len(angles)}] burst: angle={angle:.1f} speed={speed} dur={dur}s")
        _speed_move(cli, speed, int(angle), dur)
        _wait_for_mount_idle(cli, timeout_s=dur + 5.0)
        time.sleep(0.5)  # decel settle

        alt1, az1 = _measure_altaz(cli, loc)
        d_alt = alt1 - alt0
        d_az = _wrap_pm180(az1 - az0)
        mag_obs = math.hypot(d_az, d_alt)
        # Observed "effective" direction in mount frame.
        # Convention test: if angle=0 drives +az and angle=90 drives +alt,
        # then expected Δaz = |v|·cos(angle), Δalt = |v|·sin(angle).
        ang_rad = math.radians(angle)
        exp_d_az = nominal_motion * math.cos(ang_rad)
        exp_d_alt = nominal_motion * math.sin(ang_rad)
        dir_obs = math.degrees(math.atan2(d_alt, d_az))
        # Normalize for easy compare.
        ratio_mag = mag_obs / nominal_motion if nominal_motion > 0 else 0.0

        print(f"  Δaz={d_az:+.3f}°  Δalt={d_alt:+.3f}°  |v|={mag_obs:.3f}°")
        print(f"  expected (vector): Δaz={exp_d_az:+.3f}°  Δalt={exp_d_alt:+.3f}°  "
              f"|v|_nominal={nominal_motion:.3f}°")
        print(f"  obs_dir={dir_obs:+.1f}° (cmd angle={angle:+.1f}°)  "
              f"|v|_ratio={ratio_mag:.2f}")

        results.append({
            "cmd_angle": angle,
            "d_az": d_az, "d_alt": d_alt,
            "exp_d_az": exp_d_az, "exp_d_alt": exp_d_alt,
            "mag_obs": mag_obs, "mag_exp": nominal_motion,
            "dir_obs": dir_obs, "dir_err": _wrap_pm180(dir_obs - angle),
            "ratio_mag": ratio_mag,
        })
        time.sleep(0.5)
        print()

    # Summary.
    print("=" * 78)
    print("DIAGONAL SUMMARY")
    print("=" * 78)
    print(f"  {'cmd_ang':>7}  {'Δaz':>8}  {'Δalt':>8}  "
          f"{'exp_Δaz':>8}  {'exp_Δalt':>8}  "
          f"{'obs_dir':>8}  {'dir_err':>8}  {'|v|_ratio':>9}")
    for r in results:
        print(
            f"  {r['cmd_angle']:>+7.1f}  "
            f"{r['d_az']:>+8.3f}  {r['d_alt']:>+8.3f}  "
            f"{r['exp_d_az']:>+8.3f}  {r['exp_d_alt']:>+8.3f}  "
            f"{r['dir_obs']:>+8.1f}  {r['dir_err']:>+8.1f}  {r['ratio_mag']:>9.3f}"
        )
    print()
    dir_errs = [abs(r['dir_err']) for r in results]
    ratios = [r['ratio_mag'] for r in results]
    print(
        f"  dir_err |mean|={statistics.mean(dir_errs):.2f}°  "
        f"max={max(dir_errs):.2f}°  "
        f"|v|_ratio mean={statistics.mean(ratios):.3f}  "
        f"(1.0 = firmware does proper vector decomposition)"
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["setpoints", "step_response", "diagonal"],
                   default="setpoints")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--device", type=int, default=1)
    p.add_argument("--alt", type=float, default=10.0)

    # Setpoint mode args.
    p.add_argument("--tol", type=float, default=0.3)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--settle", type=float, default=0.5)
    p.add_argument("--setpoints", default="-170,+30,-60,+90,-30,+170")
    p.add_argument("--kp", type=float, default=0.3)
    p.add_argument("--kd", type=float, default=0.4)
    p.add_argument("--max-rate", type=float, default=5.0,
                   help="Max velocity (°/s) for the FF planner. Default 5.0 "
                        "leaves 1°/s headroom below the firmware cap (~6°/s).")
    p.add_argument("--loop-dt", type=float, default=0.5)
    p.add_argument("--min-speed", type=int, default=100)
    p.add_argument("--fine-min-speed", type=int, default=80)
    p.add_argument("--fine-thresh-factor", type=float, default=4.0)
    p.add_argument("--max-halvings", type=int, default=4)
    p.add_argument("--use-predictor", dest="use_predictor",
                   action="store_true", default=True,
                   help="Use the one-step feedforward predictor (default on).")
    p.add_argument("--no-predictor", dest="use_predictor",
                   action="store_false",
                   help="Disable predictor; fall back to pure PD control.")
    p.add_argument("--tau", type=float, default=0.8,
                   help="Acceleration time constant τ (s) for the predictor.")
    p.add_argument("--control",
                   choices=["velocity", "feedforward", "ff_pure"],
                   default="velocity",
                   help="Controller: 'velocity' (PD+predictor, default); "
                        "'feedforward' (open-loop trajectory + post-move "
                        "slow-nudge correction loop); 'ff_pure' (trajectory "
                        "only, no correction — for evaluating raw FF).")
    p.add_argument("--a-max", type=float, default=10.0,
                   help="FF: max accel (°/s²) for trajectory planner.")
    p.add_argument("--j-max", type=float, default=40.0,
                   help="FF: max jerk (°/s³) for the S-curve profile.")
    p.add_argument("--profile", choices=["trapezoid", "scurve"],
                   default="scurve",
                   help="FF: trajectory profile. S-curve (default) ramps "
                        "accel at j_max for smoother commanded-rate changes.")
    p.add_argument("--cold-start-lag", type=float, default=0.0,
                   help="FF: cold-start dead-time compensation (s). Only "
                        "useful with --control ff_pure; closed-loop FF+FB "
                        "absorbs cold-start via feedback.")
    p.add_argument("--az-forbidden", type=float, default=None,
                   help="Single forbidden azimuth (°). Kept for compatibility; "
                        "prefer the cumulative bounds loaded from plant_limits.json.")
    p.add_argument("--no-az-limits", dest="use_az_limits",
                   action="store_false", default=True,
                   help="Ignore plant_limits.json even if present (disables "
                        "cumulative cable-wrap bounds enforcement).")
    p.add_argument("--ff-fallback-residual", type=float, default=2.0,
                   help="FF: invoke iscope fallback if final |residual| > this.")
    p.add_argument("--kp-pos", type=float, default=0.5,
                   help="FF+FB: P-gain on position error (1/s). "
                        "v_corr = kp_pos · pos_err. Set 0 for pure-FF.")
    p.add_argument("--v-corr-max", type=float, default=2.0,
                   help="FF+FB: clamp on |v_corr| (deg/s). Prevents "
                        "windup during cold-start dead time.")
    p.add_argument("--settle-max-s", type=float, default=5.0,
                   help="FF+FB: max post-trajectory time to wait for "
                        "convergence before exiting the loop.")

    # Step-response mode args.
    p.add_argument("--step-speeds", default="100,300,700,1440",
                   help="Comma-separated speeds for step-response bursts.")
    p.add_argument("--step-dur", type=float, default=8,
                   help="Duration in seconds of each burst (≥ _MIN_DUR_S=5).")
    p.add_argument("--step-sample-dt", type=float, default=0.5,
                   help="Position-sample interval during each burst.")
    p.add_argument("--step-start-az", type=float, default=0.0,
                   help="Starting azimuth for the characterization (kept "
                        "away from ±180° boundary).")
    p.add_argument("--step-alternate", action="store_true", default=True,
                   help="Alternate +az / −az direction between bursts to "
                        "keep the mount near start_az.")
    p.add_argument("--step-log", default=None,
                   help="Path to a JSONL file to write raw samples to.")

    # Diagonal mode args.
    p.add_argument("--diag-angles", default="0,45,90,135,180,225,270,315",
                   help="Comma-separated angles (°) to test for vector decomposition.")
    p.add_argument("--diag-speed", type=int, default=500,
                   help="Speed for each diagonal burst.")
    p.add_argument("--diag-dur", type=int, default=5,
                   help="Burst duration (≥ _MIN_DUR_S=5).")
    p.add_argument("--diag-home-alt", type=float, default=5.0,
                   help="Home altitude for recentering.")
    p.add_argument("--diag-home-az", type=float, default=0.0,
                   help="Home azimuth for recentering.")
    args = p.parse_args()

    Config.load_toml()
    if not Config.init_lat or not Config.init_long:
        print("ERROR: lat/long not set in device/config.toml", file=sys.stderr)
        return 2

    cli = InstrumentedAlpacaClient(args.host, args.port, args.device)

    if args.mode == "setpoints":
        rc = run_setpoints(cli, args)
    elif args.mode == "step_response":
        rc = run_step_response(cli, args)
    elif args.mode == "diagonal":
        rc = run_diagonal(cli, args)
    else:
        print(f"ERROR: unknown mode {args.mode}", file=sys.stderr)
        rc = 2

    _print_latency_summary(cli)
    return rc


if __name__ == "__main__":
    sys.exit(main())
