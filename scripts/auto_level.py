#!/usr/bin/env python3
"""Quick CLI: drive the connected Seestar through 12 azimuths, fit the tilt,
print leveling guidance.

Prereq: `uv run python root_app.py` is running and the scope is connected.
This script sends commands through the running app's Alpaca action endpoint.

Usage:
    .venv/bin/python scripts/auto_level.py [--samples 12] [--alt 10]
                                           [--host 127.0.0.1] [--port 5555]
                                           [--device 1]
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
import time


_here = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.realpath(os.path.join(_here, "..")))

from astropy import units as u  # noqa: E402
from astropy.coordinates import EarthLocation  # noqa: E402

from datetime import datetime, timezone  # noqa: E402

from device.auto_level import (  # noqa: E402
    AutoLevelSample,
    apply_sign_flip,
    build_guidance,
    fit_auto_level,
    load_run,
    planned_azimuths,
    positions_to_rows,
    save_run,
)
from device.config import Config  # noqa: E402
from device.alpaca_client import AlpacaClient  # noqa: E402
from device.plant_limits import AzimuthLimits, CumulativeAzTracker  # noqa: E402
from device import velocity_controller as vc  # noqa: E402
from device.velocity_controller import (  # noqa: E402
    PositionLogger,
    ensure_scenery_mode,
    set_tracking,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _run_id() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def read_sensors(
    cli: AlpacaClient,
) -> tuple[float, float, float, float | None, float | None]:
    """Return (x, y, z, angle, heading) from balance + compass sensors.

    - x, y, z: balance-sensor IMU vector (g-units; z≈1 at rest)
    - angle: balance_sensor.angle — tilt deviation from level in degrees
    - heading: compass_sensor.direction — magnetic compass heading in degrees
    """
    resp = cli.method_sync(
        "get_device_state",
        {"keys": ["balance_sensor", "compass_sensor"]},
    )
    result = resp["result"]
    b = result["balance_sensor"]["data"]
    angle = b.get("angle")
    heading: float | None = None
    if "compass_sensor" in result:
        c = result["compass_sensor"]["data"]
        d = c.get("direction")
        if d is not None:
            heading = float(d)
    return (
        float(b["x"]),
        float(b["y"]),
        float(b["z"]),
        float(angle) if angle is not None else None,
        heading,
    )


class _EMA:
    """Single-channel exponential moving average with a time-constant.

    Uses the continuous-time form α = 1 − exp(−Δt / τ), so the filter
    behavior is independent of the poll rate. Call update(value, dt) with
    elapsed seconds since the last update.
    """

    def __init__(self, tau_s: float):
        self.tau = max(tau_s, 1e-6)
        self.value: float | None = None

    def update(self, new_value: float, dt_s: float) -> float:
        if new_value is None:
            return self.value if self.value is not None else float("nan")
        if self.value is None:
            self.value = new_value
            return self.value
        dt = max(dt_s, 0.0)
        alpha = 1.0 - math.exp(-dt / self.tau)
        self.value = alpha * new_value + (1.0 - alpha) * self.value
        return self.value


def live_monitor(
    cli: AlpacaClient,
    interval: float,
    tolerance_deg: float,
    x_offset: float,
    y_offset: float,
    tau_s: float = 1.0,
) -> None:
    """Interactive live-update loop showing current tilt. Ctrl+C to exit.

    EMA smoothing is applied to the raw IMU inputs (x, y, z, angle, heading)
    with the given time constant (default 1 s). Derived values (fit_tilt,
    trend) are recomputed from the smoothed inputs each tick — no separate
    smoothing stage on derived quantities.

    Shows two tilt readings side-by-side:
      fit_tilt  — our fit-corrected tilt in degrees, computed from smoothed
                  (x − x_offset, y − y_offset, z). Reads 0° when physically
                  level.
      seestar   — the scope's own reported balance_sensor.angle (smoothed).
                  Only reads 0° after you run the app's Level Calibration.

    Trend arrow and LEVEL-threshold follow fit_tilt (computed from smoothed
    inputs, so it's implicitly smooth too).
    """
    ema_x = _EMA(tau_s)
    ema_y = _EMA(tau_s)
    ema_z = _EMA(tau_s)
    ema_angle = _EMA(tau_s)
    ema_heading = _EMA(tau_s)

    # Rolling trend window (seconds). Stores (t, fit_tilt) pairs.
    trend_window_s = max(2.0, 3.0 * tau_s)
    trend_samples: list[tuple[float, float]] = []

    last_t = time.monotonic()
    try:
        while True:
            try:
                x, y, z, angle, heading = read_sensors(cli)
            except Exception as e:
                sys.stdout.write(f"\r[read error: {e}]\033[K")
                sys.stdout.flush()
                time.sleep(interval)
                continue

            now = time.monotonic()
            dt = now - last_t
            last_t = now

            # Smooth the raw IMU channels only.
            sm_x = ema_x.update(x, dt)
            sm_y = ema_y.update(y, dt)
            sm_z = ema_z.update(z, dt) if z is not None else None
            sm_angle = ema_angle.update(angle, dt) if angle is not None else None
            sm_heading = ema_heading.update(heading, dt) if heading is not None else None

            # Derive fit_tilt from the smoothed inputs — NOT separately filtered.
            tx = sm_x - x_offset
            ty = sm_y - y_offset
            z_eff = abs(sm_z) if sm_z else 1.0
            fit_tilt = math.degrees(math.atan2(math.hypot(tx, ty), z_eff))

            # Trend: compare current fit_tilt to the value ~trend_window_s ago.
            trend_samples.append((now, fit_tilt))
            trend_samples = [(t, v) for (t, v) in trend_samples if now - t <= trend_window_s]
            trend = ""
            if len(trend_samples) >= 2:
                oldest_v = trend_samples[0][1]
                delta = fit_tilt - oldest_v
                if abs(delta) < 0.005:
                    trend = "→ flat      "
                elif delta < 0:
                    trend = f"↓ {abs(delta):.3f}° better"
                else:
                    trend = f"↑ {delta:.3f}° worse "

            status = "LEVEL ✓" if fit_tilt < tolerance_deg else "adjust "
            fit_s = f"{fit_tilt:.3f}°"
            see_s = f"{sm_angle:.3f}°" if sm_angle is not None else "n/a"
            heading_s = f"{sm_heading:5.1f}°" if sm_heading is not None else "  n/a"
            z_s = f"{sm_z:+.4f}" if sm_z is not None else "n/a"
            line = (
                f"\r[{status}] fit_tilt={fit_s}  seestar={see_s}  "
                f"heading={heading_s}  x={sm_x:+.4f} y={sm_y:+.4f} z={z_s}  {trend}"
            )
            sys.stdout.write(line + "\033[K")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        sys.stdout.write("\n\n")
        sys.stdout.flush()
        print("Exited live monitor. Now open the Seestar app to calibrate the zero reference.")


def main() -> int:
    p = argparse.ArgumentParser(description="Auto-level a Seestar by multi-azimuth tilt fit.")
    p.add_argument("--samples", type=int, default=12,
                   help="Number of distinct azimuth positions to visit.")
    p.add_argument("--reads-per-position", type=int, default=5,
                   help="Sensor reads to average at each azimuth (reduces noise).")
    p.add_argument("--read-interval", type=float, default=0.1,
                   help="Delay between reads at a single position (seconds).")
    p.add_argument("--alt", type=float, default=None,
                   help="Altitude (deg) to hold during rotation. Default: current altitude, clamped to [5, 30].")
    p.add_argument("--settle", type=float, default=1.5,
                   help="Seconds to wait (after arrival) before starting to sample.")
    p.add_argument("--arrive-tolerance", type=float, default=0.5,
                   help="Start the settle timer once mount is within this many degrees of target.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--device", type=int, default=1)
    p.add_argument("--tolerance-deg", type=float, default=0.1)
    p.add_argument("--no-live", action="store_true",
                   help="Skip the live tilt monitor at the end.")
    p.add_argument("--live-interval", type=float, default=0.5,
                   help="Poll interval (seconds) for the live tilt monitor.")
    p.add_argument("--live-tau", type=float, default=1.0,
                   help="EMA time constant (seconds) for smoothing live readouts.")
    p.add_argument("--log-file", default=None,
                   help="Path to write the run log (JSON). Default: auto_level_logs/{run_id}.json")
    p.add_argument("--no-log", action="store_true",
                   help="Disable writing the run log.")
    p.add_argument("--position-log-file", default=None,
                   help="Path to write the position JSONL trace. Default: "
                        "auto_level_logs/{run_id}.positions.jsonl")
    p.add_argument("--no-position-log", action="store_true",
                   help="Disable the background position logger.")
    p.add_argument("--position-log-interval", type=float, default=0.5,
                   help="Poll interval (seconds) for the background position logger.")
    p.add_argument("--no-az-limits", action="store_true",
                   help="Skip plant_limits cable-wrap integration. By default the "
                        "sweep loads device/plant_limits.json and uses the "
                        "cumulative-aware azimuth planner.")
    p.add_argument("--no-unwind", action="store_true",
                   help="Skip the pre-sweep unwind_azimuth() hook that drives "
                        "cumulative az back toward 0 when cable headroom is low.")
    p.add_argument("--unwind-threshold-deg", type=float, default=180.0,
                   help="Trigger pre-sweep unwind when |cum_az_deg| exceeds this. "
                        "Default 180° (unwind kicks in at half the cable budget).")
    p.add_argument("--replay", default=None,
                   help="Path to a previously-saved run log. Skips hardware; reruns math only.")
    p.add_argument("--reanchor", action="store_true",
                   help="Force the sign-anchor prompt even if a sign is already stored in config.")
    args = p.parse_args()

    # Replay path — no hardware setup needed.
    if args.replay:
        return run_replay(args)

    # Load scope location from config (used by astropy altaz<->radec transform).
    Config.load_toml()
    if not Config.init_lat or not Config.init_long:
        print("ERROR: seestar_initialization.lat / long not set in device/config.toml.",
              file=sys.stderr)
        print("Set them to your site coordinates and retry.", file=sys.stderr)
        return 2
    loc = EarthLocation(lat=Config.init_lat * u.deg, lon=Config.init_long * u.deg, height=0 * u.m)

    cli = AlpacaClient(args.host, args.port, args.device)

    # Determine the log path (unless disabled).
    log_path = None
    if not args.no_log:
        log_path = args.log_file or os.path.join(
            _here, "..", "auto_level_logs", f"{_run_id()}.json"
        )
        log_path = os.path.abspath(log_path)
        print(f"Logging run to: {log_path}")

    # Start the background position logger (JSONL trace) unless disabled.
    position_logger: PositionLogger | None = None
    if not args.no_position_log:
        position_log_path = args.position_log_file or os.path.join(
            _here, "..", "auto_level_logs", f"{_run_id()}.positions.jsonl"
        )
        position_log_path = os.path.abspath(position_log_path)
        print(f"Logging positions (JSONL) to: {position_log_path}")
        position_logger = PositionLogger(
            cli, loc, position_log_path,
            poll_interval_s=args.position_log_interval,
        )
        position_logger.start()

    tracker_holder: list[CumulativeAzTracker | None] = [None]
    try:
        return _main_body(args, cli, loc, log_path, position_logger, tracker_holder)
    finally:
        if position_logger is not None:
            position_logger.set_phase("shutdown")
            position_logger.stop()
        tracker = tracker_holder[0]
        if tracker is not None:
            try:
                tracker.save()
                print(f"Saved az_tracker state (cum_az={tracker.cum_az_deg:+.3f}°).")
            except Exception as e:
                print(f"(warning: failed to save az_tracker: {e})", file=sys.stderr)


def _main_body(args, cli, loc, log_path, position_logger, tracker_holder):
    # Put the scope into scenery (terrestrial) view mode so scope_goto moves
    # the mount without triggering the AutoGoto plate-solve routine.
    print("Entering scenery view mode...")
    if position_logger is not None:
        position_logger.set_phase("scenery_mode")
    ensure_scenery_mode(cli)
    # Disable tracking for the sweep — see set_tracking() docstring.
    print("Disabling tracking for the sweep duration.")
    set_tracking(cli, False)

    # Load cable-wrap limits (optional). When present, the 2-axis mover
    # plans in cumulative az space so sweeps don't walk into the ±450°
    # hard stops. The tracker (loaded after the initial goto) keeps
    # cumulative state across sessions via device/plant_limits_state.json.
    az_limits = None if args.no_az_limits else AzimuthLimits.load()
    if az_limits is not None:
        print(f"AzimuthLimits loaded: usable "
              f"[{az_limits.usable_ccw_cum_deg:+.1f}°, "
              f"{az_limits.usable_cw_cum_deg:+.1f}°]")
    elif not args.no_az_limits:
        print("(no plant_limits.json found — sweep will not be cable-wrap aware)")

    # Decide the altitude we'll hold during rotation. Use raw encoder
    # (scope_get_horiz_coord) — scope_get_equ_coord + astropy goes stale
    # without plate-solve alignment and would return a fantasy altitude.
    start_alt_deg, start_az_deg = vc.measure_altaz(cli, loc)
    if args.alt is None:
        target_alt = max(5.0, min(start_alt_deg, 30.0))
        print(f"Current scope altitude {start_alt_deg:.1f}°; "
              f"holding at {target_alt:.1f}° during rotation.")
    else:
        target_alt = args.alt
        print(f"Current scope altitude {start_alt_deg:.1f}°; "
              f"holding at {target_alt:.1f}° during rotation.")

    reads = args.reads_per_position
    azimuths = planned_azimuths(args.samples, start_deg=-180.0)
    print(f"Collecting {args.samples} positions × {reads} reads each "
          f"(settle {args.settle}s after each arrival; controller=move_to_ff)")

    # Log metadata
    run_meta = {
        "run_id": _run_id(),
        "started_at": _now_iso(),
        "config": {
            "samples": args.samples,
            "alt_deg": target_alt,
            "reads_per_position": reads,
            "read_interval_s": args.read_interval,
            "settle_s": args.settle,
            "controller": "2d_ff_fb",
            "v_max_degs": vc.PLAN_MAX_RATE_DEGS,
            "a_max_degs2": 4.0,
            "j_max_degs3": 12.0,
            "profile": "scurve",
            "arrive_tolerance_deg": args.arrive_tolerance,
            "az_limits_loaded": az_limits is not None,
            "lat": Config.init_lat,
            "long": Config.init_long,
        },
    }
    log_positions: list[dict] = []

    # Anchor the cumulative-az tracker from the current wrapped encoder
    # reading BEFORE any motion. `load_or_fresh` uses the saved wrapped_az
    # vs current-wrapped-az comparison to detect power-cycle/home resets;
    # anchoring after a goto would make every run look like a power cycle.
    az_tracker: CumulativeAzTracker | None = None
    if az_limits is not None:
        az_tracker = CumulativeAzTracker.load_or_fresh(
            current_wrapped_az_deg=start_az_deg,
        )
        az_tracker.update(start_az_deg)
        tracker_holder[0] = az_tracker
        print(f"Start position: measured_alt={start_alt_deg:+.3f}°  "
              f"measured_az={start_az_deg:+.3f}°  "
              f"cum_az={az_tracker.cum_az_deg:+.3f}°")
    else:
        print(f"Start position: measured_alt={start_alt_deg:+.3f}°  "
              f"measured_az={start_az_deg:+.3f}°")

    # Pre-sweep unwind: if cable headroom is low, drive cumulative az back
    # toward 0 before starting the sweep. No-op when cum_az is within
    # `unwind_threshold_deg` of center.
    cur_alt_deg, cur_az_deg = start_alt_deg, start_az_deg
    if (
        not args.no_unwind
        and az_limits is not None
        and az_tracker is not None
        and abs(az_tracker.cum_az_deg) > args.unwind_threshold_deg
    ):
        print(f"Cable headroom low (cum_az={az_tracker.cum_az_deg:+.1f}°); "
              f"unwinding before sweep...", flush=True)
        vc.unwind_azimuth(
            cli, loc, az_tracker, az_limits,
            threshold_deg=args.unwind_threshold_deg,
            position_logger=position_logger,
        )
        cur_alt_deg, cur_az_deg = vc.measure_altaz(cli, loc)
        print(f"Unwind done: measured_az={cur_az_deg:+.3f}°  "
              f"cum_az={az_tracker.cum_az_deg:+.3f}°", flush=True)

    # Initial positioning: use the 2-axis FF+FB mover to drive to
    # (azimuths[0], target_alt). This is the same controller used per-step,
    # so behavior is uniform. Uses raw encoder throughout — no dependency
    # on plate-solve alignment / RA-Dec freshness.
    print(f"Initial goto: az={azimuths[0]:+.1f}° alt={target_alt:.1f}° "
          f"via move_to_ff (from cur_az={cur_az_deg:+.2f}° "
          f"cur_alt={cur_alt_deg:+.2f}°)")
    if position_logger is not None:
        position_logger.set_target(azimuths[0], target_alt)
        position_logger.set_phase("initial_goto", step=0)
        position_logger.mark_event("initial_goto_issue",
                                   target_az=azimuths[0], target_alt=target_alt)
    init_alt_deg, init_az_deg, init_stats = vc.move_to_ff(
        cli,
        target_az_deg=azimuths[0], target_el_deg=target_alt,
        cur_az_deg=cur_az_deg, cur_el_deg=cur_alt_deg,
        loc=loc, tag="[init]",
        position_logger=position_logger,
        az_limits=az_limits, az_tracker=az_tracker,
        el_min_deg=5.0, el_max_deg=85.0,
        arrive_tolerance_deg=args.arrive_tolerance,
    )
    cur_alt_deg, cur_az_deg = init_alt_deg, init_az_deg
    init_residual = vc.wrap_pm180(azimuths[0] - cur_az_deg)
    print(f"Initial goto done: measured_az={cur_az_deg:+.3f}°  "
          f"measured_alt={cur_alt_deg:+.3f}°  "
          f"residual_az={init_residual:+.3f}°  "
          f"converged={init_stats.get('converged')}", flush=True)
    if position_logger is not None:
        position_logger.set_phase("initial_settling", step=0)
        position_logger.mark_event(
            "initial_goto_arrived",
            residual_az_deg=init_residual,
            converged=init_stats.get("converged"),
        )
    time.sleep(args.settle)

    samples: list[AutoLevelSample] = []
    t_run_start = time.monotonic()
    for i, az in enumerate(azimuths, start=1):
        tag = f"[{i}/{args.samples}] az={az:+7.2f}°"
        t_step_start = time.monotonic()
        print(f"{tag} START  (cur_az={cur_az_deg:+.3f}°, cur_alt={cur_alt_deg:+.3f}°, "
              f"delta_az={vc.wrap_pm180(az - cur_az_deg):+.3f}°, "
              f"delta_alt={target_alt - cur_alt_deg:+.3f}°, "
              f"elapsed={t_step_start - t_run_start:.1f}s)",
              flush=True)
        if position_logger is not None:
            position_logger.set_target(az, target_alt)
            position_logger.set_phase("step_start", step=i)
            position_logger.mark_event("step_start",
                                       target_az=az, target_alt=target_alt,
                                       cur_az=cur_az_deg, cur_alt=cur_alt_deg)
        measured_alt_deg, measured_az, move_stats = vc.move_to_ff(
            cli,
            target_az_deg=az, target_el_deg=target_alt,
            cur_az_deg=cur_az_deg, cur_el_deg=cur_alt_deg,
            loc=loc, tag=tag,
            position_logger=position_logger,
            az_limits=az_limits, az_tracker=az_tracker,
            el_min_deg=5.0, el_max_deg=85.0,
            arrive_tolerance_deg=args.arrive_tolerance,
        )
        cur_az_deg = measured_az
        cur_alt_deg = measured_alt_deg
        # move_to_ff stats include both az- and el-specific residuals plus a
        # compat `final_residual_deg` aliased to the az residual. Print the
        # interesting numeric scalars inline.
        summary = "  ".join(
            f"{k}={v}" for k, v in move_stats.items()
            if k != "final_residual_deg" and v is not None and v != 0
            and not isinstance(v, bool)
        )
        print(f"{tag} MOVE DONE  step_time={time.monotonic() - t_step_start:.1f}s  "
              f"{summary}  "
              f"residual={move_stats['final_residual_deg']:+.3f}°",
              flush=True)
        if position_logger is not None:
            position_logger.set_phase("settling", step=i)
            position_logger.mark_event("move_done", **{
                k: v for k, v in move_stats.items() if k != "final_residual_deg"
            }, residual_deg=move_stats["final_residual_deg"])
        print(f"{tag} SETTLING  {args.settle}s before sampling...", flush=True)
        time.sleep(args.settle)

        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        angles: list[float] = []
        headings: list[float] = []
        raw_reads: list[dict] = []
        sample_start_t = time.monotonic()
        if position_logger is not None:
            position_logger.set_phase("sampling", step=i)
        print(f"{tag} SAMPLING  {reads} reads @ {args.read_interval}s interval:",
              end="", flush=True)
        for r in range(reads):
            if r > 0:
                time.sleep(args.read_interval)
            x, y, z, a, h = read_sensors(cli)
            t_offset = time.monotonic() - sample_start_t
            raw_reads.append({
                "t_offset_s": round(t_offset, 4),
                "x": x, "y": y, "z": z,
                "angle": a, "heading": h,
            })
            xs.append(x)
            ys.append(y)
            zs.append(z)
            if a is not None:
                angles.append(a)
            if h is not None:
                headings.append(h)
            print(f" {r+1}", end="", flush=True)
        print()

        def _stats(label: str, values: list[float], fmt: str = "+.5f") -> None:
            if not values:
                return
            m = statistics.mean(values)
            if len(values) >= 2:
                sd = statistics.stdev(values)
                print(f"       {label}: mean={m:{fmt}}  stdev={sd:.5f}  (n={len(values)})")
            else:
                print(f"       {label}: mean={m:{fmt}}  (n=1, stdev requires ≥2)")

        _stats("x      ", xs)
        _stats("y      ", ys)
        _stats("z      ", zs)
        _stats("angle  ", angles)
        _stats("heading", headings)

        avg_x = statistics.mean(xs)
        avg_y = statistics.mean(ys)
        avg_z = statistics.mean(zs) if zs else None
        avg_angle = statistics.mean(angles) if angles else None
        avg_heading = statistics.mean(headings) if headings else None

        # Per-position summary: balance offset (mean angle = tilt from level) and heading.
        offset_s = f"{avg_angle:.3f}°" if avg_angle is not None else "n/a"
        heading_s = f"{avg_heading:.1f}°" if avg_heading is not None else "n/a"
        print(f"       summary: balance_offset={offset_s}  heading={heading_s}")

        samples.append(AutoLevelSample(
            azimuth_deg=measured_az, sensor_x=avg_x, sensor_y=avg_y,
            sensor_z=avg_z, angle=avg_angle,
        ))
        log_positions.append({
            "index": i - 1,
            "azimuth_deg": measured_az,
            "commanded_azimuth_deg": az,
            "target_alt_deg": target_alt,
            "measured_alt_deg": measured_alt_deg,
            "residual_deg": vc.wrap_pm180(measured_az - az),
            # Move stats (field set varies by control mode).
            **{f"move_{k}": v for k, v in move_stats.items()},
            "reads": raw_reads,
        })
        if log_path:
            try:
                save_run(log_path, run_meta, log_positions)
            except Exception as e:
                print(f"  (warning: failed to write log: {e})", file=sys.stderr)

    fit = fit_auto_level(samples)

    # Apply stored sign if configured; otherwise fit stays mount-frame only.
    stored_flip = _read_sign_flip()
    if stored_flip is not None and not args.reanchor:
        fit = apply_sign_flip(fit, stored_flip)

    _print_fit_block(fit)

    # Sign-anchor step: prompt the user if we haven't anchored yet, or if
    # --reanchor was passed, AND the measured tilt is meaningful (≥ 0.3°).
    need_anchor = (stored_flip is None) or args.reanchor
    if need_anchor and fit.tilt_deg >= 0.3:
        flip = _sign_anchor_prompt(cli, loc, fit, target_alt)
        if flip is not None:
            _write_sign_flip(flip)
            fit = apply_sign_flip(fit, flip)
            print()
            print("Re-applying sign to fit:")
            _print_fit_block(fit)

    guidance = build_guidance(fit, tolerance_deg=args.tolerance_deg)
    print()
    print(f">>> {guidance.message}")
    print()

    if args.no_live:
        return 0

    print()
    print("=== Live tilt monitor (Ctrl+C to exit) ===")
    print("Adjust the tripod slowly. The scope stays put; sensor axes are now fixed")
    print(f"in body frame. Polling every {args.live_interval:.1f}s.")
    print()
    live_monitor(
        cli,
        interval=args.live_interval,
        tolerance_deg=args.tolerance_deg,
        x_offset=fit.x_offset,
        y_offset=fit.y_offset,
        tau_s=args.live_tau,
    )
    return 0


def _print_fit_block(fit) -> None:
    print()
    print("=== Auto-Level Fit ===")
    print(f"  samples:          {fit.n_samples}")
    print(f"  tilt magnitude:   {fit.amplitude:.4f} sensor units  ({fit.tilt_deg:.2f}°)")
    print(f"  mount-az of tilt: {fit.tilt_mount_az_deg:.1f}°")
    if fit.uphill_world_az_deg is not None:
        from device.auto_level import azimuth_to_compass
        print(f"  uphill (world):   {fit.uphill_world_az_deg:.1f}°  "
              f"({azimuth_to_compass(fit.uphill_world_az_deg)})")
    else:
        print("  uphill (world):   <not yet anchored — slew-and-look step pending>")
    print(f"  sensor offsets:   x0={fit.x_offset:+.5f}  y0={fit.y_offset:+.5f}")
    print(f"  mean z:           {fit.mean_z:.5f}")
    print(f"  fit rms residual: {fit.rms_residual:.6f}")


def _read_sign_flip() -> bool | None:
    """Return cached sign-flip from config.toml, or None if unset."""
    val = Config.get_toml("seestar_initialization", "balance_sign_flip", None)
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _write_sign_flip(flip: bool) -> None:
    """Persist the sign-flip to config.toml under [seestar_initialization]."""
    try:
        Config.set_toml("seestar_initialization", "balance_sign_flip", flip)
        Config.save_toml()
        print(f"Saved balance_sign_flip={flip} to device/config.toml.")
    except Exception as e:
        print(f"(warning: failed to persist balance_sign_flip: {e})", file=sys.stderr)


def _sign_anchor_prompt(cli, loc, fit, target_alt: float) -> bool | None:
    """Slew scope to tilt_mount_az_deg and ask user if that side is high/low.

    Returns the sign-flip to apply (True = mount-az points to LOW side,
    so uphill is the opposite; False = mount-az already points uphill),
    or None if the user skipped.
    """
    print()
    print("=== Sign anchor ===")
    print("I'll slew the scope to the azimuth where the sensor sees maximum tilt")
    print(f"projection (mount-az {fit.tilt_mount_az_deg:.1f}°).")
    print("Once it arrives, physically look at your tripod: is the side the scope")
    print("is facing the HIGH side of the tripod, or the LOW side?")
    print()

    try:
        input("Press Enter to slew, or Ctrl+C to skip...")
    except (KeyboardInterrupt, EOFError):
        print("\n(skipped)")
        return None

    try:
        cur_alt, cur_az = vc.measure_altaz(cli, loc)
        vc.move_to_ff(
            cli,
            target_az_deg=fit.tilt_mount_az_deg, target_el_deg=target_alt,
            cur_az_deg=cur_az, cur_el_deg=cur_alt,
            loc=loc, tag="[anchor]",
            el_min_deg=5.0, el_max_deg=85.0,
            arrive_tolerance_deg=0.5,
        )
    except Exception as e:
        print(f"(anchor slew failed: {e}; skipping)")
        return None

    print()
    while True:
        try:
            ans = input("Is that side HIGH (h), LOW (l), or skip (s)? ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return None
        if ans in ("h", "high"):
            # Scope is facing the HIGH side, so tilt_mount_az IS uphill. No flip.
            return False
        if ans in ("l", "low"):
            # Scope is facing the LOW side, so uphill is 180° away. Flip.
            return True
        if ans in ("s", "skip", ""):
            return None
        print("Please answer h, l, or s.")


def run_replay(args) -> int:
    """Skip hardware; load a saved run log and rerun the math."""
    path = args.replay
    if not os.path.exists(path):
        print(f"ERROR: replay file not found: {path}", file=sys.stderr)
        return 2

    Config.load_toml()
    meta, positions, samples = load_run(path)
    print(f"Replaying run {meta.get('run_id')} (from {path})")
    cfg = meta.get("config", {})
    print(f"  started_at: {meta.get('started_at')}")
    print(f"  finished_at: {meta.get('finished_at')}")
    print(f"  config: samples={cfg.get('samples')}, alt={cfg.get('alt_deg')}°, "
          f"reads_per_position={cfg.get('reads_per_position')}")
    print()

    # Per-position table
    rows = positions_to_rows(positions)
    print("Per-position samples:")
    print(f"  {'az':>6}  {'n':>2}  {'x_mean':>10}  {'x_std':>9}  "
          f"{'y_mean':>10}  {'y_std':>9}  {'z_mean':>9}  {'angle':>7}  {'heading':>7}")
    for row in rows:
        def fmt(v, w, prec):
            return "n/a".rjust(w) if v is None else f"{v:>{w}.{prec}f}"
        print(f"  {row['az']:>6.1f}  {row['n']:>2}  "
              f"{fmt(row['x_mean'], 10, 5)}  {fmt(row['x_std'], 9, 5)}  "
              f"{fmt(row['y_mean'], 10, 5)}  {fmt(row['y_std'], 9, 5)}  "
              f"{fmt(row['z_mean'], 9, 5)}  "
              f"{fmt(row['angle_mean'], 7, 3)}  {fmt(row['heading_mean'], 7, 1)}")

    if len(samples) < 4:
        print(f"\nNeed at least 4 positions to fit; only {len(samples)} in log.",
              file=sys.stderr)
        return 2

    fit = fit_auto_level(samples)
    stored_flip = _read_sign_flip()
    if stored_flip is not None:
        fit = apply_sign_flip(fit, stored_flip)

    _print_fit_block(fit)
    guidance = build_guidance(fit, tolerance_deg=args.tolerance_deg)
    print()
    print(f">>> {guidance.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
