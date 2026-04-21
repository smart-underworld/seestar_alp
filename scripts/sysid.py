#!/usr/bin/env python3
"""System-identification harness for the Seestar velocity plant.

Modes (each writes JSONL under auto_level_logs/sysid/):

    --mode step_response
        Step from rest at a list of commanded speeds; optionally chain two
        back-to-back 10 s bursts at the same (speed, angle) to let the
        plant reach steady state at high commanded speeds where a single
        10 s burst is insufficient.

    --mode deadband
        Ramp commanded speed from 0 upward until motion first appears.
        Maps the stiction floor and confirms the minimum useful command.

    --mode latency
        Issue a single burst and measure three latencies per command:
        RPC ACK (t_response - t_send), first detectable motion
        (t_first_motion - t_response), and time-to-half-ss rate. Repeats
        N times to build a histogram.

    --mode chirp
        Play a linear-frequency-swept velocity profile
        v_cmd(t) = A * sin(2*pi*f(t)*t), issuing one scope_speed_move per
        control-loop tick. Held-out data for plant-model validation.

    --mode limits
        Slowly command motion in one direction (--direction cw|ccw|up|down)
        and detect stall. Reports the azimuth/altitude at which the mount
        stops responding — the physical hard limit in that direction.
        ASSUMES the mount is pre-positioned; does NOT iscope-goto. Run
        once per direction.

    --mode trajectory_track
        Build a trapezoidal velocity profile from the current az to
        (cur_az + --delta), run it via `move_azimuth_to_ff`, and compute
        the tracking RMSE (measured vs reference) across the trajectory.
        Cleanly separates "does the planner's trajectory match reality?"
        from "does the correction wrapper close residual?" Used to
        validate cold-start compensation.

Shared setup: enters scenery mode, disables tracking, does an iscope
goto to a safe start position. All azimuth-only for now; elevation is a
follow-up (hard altitude limits need extra guards).

Uses device.velocity_controller helpers (speed_move, wait_for_mount_idle,
measure_altaz, ensure_scenery_mode, issue_slew, wait_until_near_target,
set_tracking, wrap_pm180, unwrap_az_series) and device.alpaca_client
(AlpacaClient). No imports from scripts.auto_level or scripts.tune_vc —
this script is self-contained Phase-1 tooling.
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
from datetime import datetime
from pathlib import Path
from typing import Optional

_here = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.realpath(os.path.join(_here, "..")))

from astropy import units as u  # noqa: E402
from astropy.coordinates import EarthLocation  # noqa: E402

from device.alpaca_client import AlpacaClient  # noqa: E402
from device.config import Config  # noqa: E402
from device.velocity_controller import (  # noqa: E402
    MIN_DUR_S,
    SPEED_PER_DEG_PER_SEC,
    ensure_scenery_mode,
    issue_slew,
    measure_altaz,
    measure_altaz_timed,
    set_tracking,
    speed_move,
    wait_for_mount_idle,
    wait_until_near_target,
    wrap_pm180,
)


# ---------------------------------------------------------------------------
# Latency-instrumented client — records (t_send, t_ack) per method call.
# ---------------------------------------------------------------------------


@dataclass
class _CallRecord:
    method: str
    t_send: float                # host monotonic seconds at HTTP send
    t_ack: float                 # host monotonic seconds at HTTP response
    fw_t_ack: Optional[float]    # firmware timestamp on response, None if missing
    params: Optional[dict] = None


class TimedAlpacaClient(AlpacaClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[_CallRecord] = []

    def method_sync(self, method: str, params=None):
        t0 = time.monotonic()
        result = super().method_sync(method, params)
        t1 = time.monotonic()
        fw_t: Optional[float] = None
        if isinstance(result, dict):
            ts_raw = result.get("Timestamp")
            if ts_raw is not None:
                try:
                    fw_t = float(ts_raw)
                except (TypeError, ValueError):
                    fw_t = None
        self.calls.append(_CallRecord(
            method=method, t_send=t0, t_ack=t1, fw_t_ack=fw_t,
            params=params if isinstance(params, dict) else None,
        ))
        return result

    def last_call(self, method: str) -> Optional[_CallRecord]:
        for r in reversed(self.calls):
            if r.method == method:
                return r
        return None


# ---------------------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------------------


def _now_id() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _sysid_logs_dir() -> Path:
    return Path(_here).parent / "auto_level_logs" / "sysid"


def _open_jsonl(mode_name: str) -> Path:
    d = _sysid_logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{mode_name}_{_now_id()}.jsonl"


def _write_jsonl(path: Path, rec: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def _make_loc() -> EarthLocation:
    return EarthLocation(
        lat=Config.init_lat * u.deg, lon=Config.init_long * u.deg, height=0 * u.m,
    )


def _setup_mount(
    cli: TimedAlpacaClient, loc: EarthLocation, start_az: float, start_alt: float,
) -> None:
    print("Entering scenery mode; disabling tracking...")
    ensure_scenery_mode(cli)
    set_tracking(cli, False)
    print(f"Initial goto: az={start_az:+.1f}° alt={start_alt:.1f}°")
    ra, dec = issue_slew(cli, start_az, start_alt, loc)
    ok, dist, _ = wait_until_near_target(
        cli, target_ra_h=ra, target_dec_d=dec,
        tolerance_deg=3.0, timeout=60.0, stall_threshold_s=5.0,
    )
    if not ok:
        print(f"  (warning: initial goto did not reach 3° — dist={dist})")
    idle_ok, idle_elapsed = wait_for_mount_idle(cli, timeout_s=15.0)
    print(f"Post-goto mount idle={idle_ok} after {idle_elapsed:.2f}s; "
          f"re-disabling tracking.")
    set_tracking(cli, False)
    time.sleep(1.0)


def _recenter_if_far(
    cli: TimedAlpacaClient, loc: EarthLocation,
    start_az: float, start_alt: float, max_drift_deg: float = 40.0,
) -> None:
    _, cur_az = measure_altaz(cli, loc)
    if abs(wrap_pm180(cur_az - start_az)) > max_drift_deg:
        print(f"  (recentering to {start_az:+.1f}°)")
        ra, dec = issue_slew(cli, start_az, start_alt, loc)
        wait_until_near_target(
            cli, target_ra_h=ra, target_dec_d=dec,
            tolerance_deg=3.0, timeout=60.0, stall_threshold_s=5.0,
        )
        wait_for_mount_idle(cli, timeout_s=15.0)
        set_tracking(cli, False)
        time.sleep(1.0)


# ---------------------------------------------------------------------------
# mode: step_response  (with optional multi-burst chaining for high speed)
# ---------------------------------------------------------------------------


def _collect_bursts(
    cli: TimedAlpacaClient, loc: EarthLocation,
    speed: int, angle: int, dur_sec: int, n_chain: int, sample_dt: float,
) -> tuple[list[tuple[float, Optional[float], float, float]], dict]:
    """Issue n_chain back-to-back scope_speed_moves at the same (speed, angle)
    with no stop between. Sample position throughout.

    Returns:
        samples: list of (host_t_s, fw_t_s, wrapped_az_deg, motor_active_flag)
                 host_t is monotonic seconds from burst start (host clock).
                 fw_t is firmware uptime seconds (sub-microsecond); None if
                 the response lacked a Timestamp.
        meta: dict with start_az, end_az, cmd_times, etc.
    """
    _, az0, _ = measure_altaz_timed(cli, loc)
    t_zero = time.monotonic()
    cmd_times: list[tuple[float, int, int, int]] = []  # (t_rel, speed, angle, dur)

    for i in range(n_chain):
        t_rel = time.monotonic() - t_zero
        speed_move(cli, speed, angle, dur_sec)
        cmd_times.append((t_rel, speed, angle, dur_sec))
        if i < n_chain - 1:
            # Pre-issue the next command a little before the previous one
            # expires. Firmware supersedes the in-flight command so there's
            # no observable gap.
            time.sleep(max(0.5, dur_sec - 1.5))

    total_window = dur_sec * n_chain - 1.5 * (n_chain - 1) + 3.0
    samples: list[tuple[float, Optional[float], float, float]] = []
    next_sample_t = t_zero
    while time.monotonic() - t_zero < total_window:
        now = time.monotonic()
        if now < next_sample_t:
            time.sleep(max(0.0, next_sample_t - now))
        _, az, fw_t = measure_altaz_timed(cli, loc)
        t_rel = time.monotonic() - t_zero
        # motor_active flag: 1 while any cmd is still active
        motor_active = 0.0
        for (t_c, _s, _a, d) in cmd_times:
            if t_c <= t_rel <= t_c + d:
                motor_active = 1.0
                break
        samples.append((t_rel, fw_t, az, motor_active))
        next_sample_t += sample_dt

    wait_for_mount_idle(cli, timeout_s=3.0)
    _, az_end = measure_altaz(cli, loc)
    total_motion = sum(
        wrap_pm180(samples[i + 1][2] - samples[i][2])
        for i in range(len(samples) - 1)
    )
    return samples, {
        "start_az": az0,
        "end_az": az_end,
        "total_motion_deg": total_motion,
        "cmd_times": cmd_times,
        "speed": speed,
        "angle": angle,
        "dur_sec": dur_sec,
        "n_chain": n_chain,
    }


def run_step_response(cli: TimedAlpacaClient, args) -> int:
    loc = _make_loc()
    speeds = [int(x) for x in args.speeds.split(",") if x.strip()]
    dur = int(args.dur)
    chain = int(args.chain)
    if dur < MIN_DUR_S:
        print(f"ERROR: dur must be >= {MIN_DUR_S}", file=sys.stderr)
        return 2
    if chain < 1:
        print("ERROR: chain must be >= 1", file=sys.stderr)
        return 2

    print("=" * 78)
    print(f"sysid step_response — speeds={speeds} dur={dur}s chain={chain}")
    print("=" * 78)

    _setup_mount(cli, loc, args.start_az, args.alt)
    log_path = _open_jsonl("step_response")
    _write_jsonl(log_path, {
        "kind": "header", "mode": "step_response", "speeds": speeds,
        "dur_sec": dur, "chain": chain, "sample_dt": args.sample_dt,
        "alt": args.alt, "start_az": args.start_az,
        "n_speed_per_deg_per_sec": SPEED_PER_DEG_PER_SEC,
    })

    for i, speed in enumerate(speeds, start=1):
        angle = 0 if i % 2 == 1 else 180
        _recenter_if_far(cli, loc, args.start_az, args.alt)
        wait_for_mount_idle(cli, timeout_s=5.0)
        set_tracking(cli, False)
        print(f"[{i}/{len(speeds)}] speed={speed} angle={angle} "
              f"dur={dur}s chain={chain}")
        samples, meta = _collect_bursts(
            cli, loc, speed=speed, angle=angle, dur_sec=dur, n_chain=chain,
            sample_dt=args.sample_dt,
        )
        _write_jsonl(log_path, {"kind": "burst", **meta,
                                "sample_count": len(samples)})
        for (t, fw_t, az, ma) in samples:
            _write_jsonl(log_path, {
                "kind": "sample", "speed": speed, "angle": angle,
                "chain_index": i, "t": t, "fw_t": fw_t,
                "az": az, "motor_active": ma,
            })
        print(f"   → total_motion={meta['total_motion_deg']:+.2f}°")
        time.sleep(1.0)

    print(f"wrote: {log_path}")
    return 0


# ---------------------------------------------------------------------------
# mode: deadband  (ramp commanded speed until motion observed)
# ---------------------------------------------------------------------------


def run_deadband(cli: TimedAlpacaClient, args) -> int:
    loc = _make_loc()
    speeds = [int(x) for x in args.speeds.split(",") if x.strip()]
    dwell = float(args.dwell)
    rest = float(args.rest)
    dur = int(args.dur)
    if dur < MIN_DUR_S:
        print(f"ERROR: dur must be >= {MIN_DUR_S}", file=sys.stderr)
        return 2

    print("=" * 78)
    print(f"sysid deadband — ramp speeds={speeds} dwell={dwell}s")
    print("=" * 78)

    _setup_mount(cli, loc, args.start_az, args.alt)
    log_path = _open_jsonl("deadband")
    _write_jsonl(log_path, {
        "kind": "header", "mode": "deadband", "speeds": speeds,
        "dwell_s": dwell, "rest_s": rest, "dur_sec": dur,
        "n_speed_per_deg_per_sec": SPEED_PER_DEG_PER_SEC,
    })

    for direction_angle in (0, 180):
        for i, speed in enumerate(speeds, start=1):
            _recenter_if_far(cli, loc, args.start_az, args.alt)
            wait_for_mount_idle(cli, timeout_s=5.0)
            set_tracking(cli, False)
            _, az0 = measure_altaz(cli, loc)
            t0 = time.monotonic()
            speed_move(cli, speed, direction_angle, dur)
            # Sample at 0.5s throughout the dwell.
            dwell_samples: list[tuple[float, Optional[float], float]] = []
            next_t = t0 + 0.5
            while time.monotonic() - t0 < dwell:
                time.sleep(max(0.0, next_t - time.monotonic()))
                _, az, fw_t = measure_altaz_timed(cli, loc)
                dwell_samples.append((time.monotonic() - t0, fw_t, az))
                next_t += 0.5
            wait_for_mount_idle(cli, timeout_s=5.0)
            _, az_end = measure_altaz(cli, loc)
            total_with_end = wrap_pm180(az_end - az0)
            mean_rate = total_with_end / dwell if dwell > 0 else 0.0
            print(f"  angle={direction_angle} speed={speed}: "
                  f"Δaz={total_with_end:+.3f}° mean_rate={mean_rate:+.3f}°/s")
            _write_jsonl(log_path, {
                "kind": "step", "angle": direction_angle, "speed": speed,
                "dwell_s": dwell, "delta_az_deg": total_with_end,
                "mean_rate_degs": mean_rate,
                "sample_count": len(dwell_samples),
            })
            for (t, fw_t, az) in dwell_samples:
                _write_jsonl(log_path, {
                    "kind": "sample", "angle": direction_angle, "speed": speed,
                    "t": t, "fw_t": fw_t, "az": az,
                })
            time.sleep(rest)

    print(f"wrote: {log_path}")
    return 0


# ---------------------------------------------------------------------------
# mode: latency  (measure t_send, t_ack, t_first_motion)
# ---------------------------------------------------------------------------


def run_latency(cli: TimedAlpacaClient, args) -> int:
    loc = _make_loc()
    n = int(args.n)
    speed = int(args.speed)
    dur = int(args.dur)
    if dur < MIN_DUR_S:
        print(f"ERROR: dur must be >= {MIN_DUR_S}", file=sys.stderr)
        return 2

    print("=" * 78)
    print(f"sysid latency — n={n} speed={speed} dur={dur}s")
    print("=" * 78)

    _setup_mount(cli, loc, args.start_az, args.alt)
    log_path = _open_jsonl("latency")
    _write_jsonl(log_path, {
        "kind": "header", "mode": "latency", "n": n, "speed": speed,
        "dur_sec": dur, "poll_dt_s": args.poll_dt,
    })

    poll_dt = float(args.poll_dt)
    motion_thresh_degs = 0.05

    for i in range(n):
        _recenter_if_far(cli, loc, args.start_az, args.alt)
        wait_for_mount_idle(cli, timeout_s=5.0)
        set_tracking(cli, False)
        angle = 0 if i % 2 == 0 else 180

        _, az0, fw_t0 = measure_altaz_timed(cli, loc)
        t_send = time.monotonic()
        speed_move(cli, speed, angle, dur)
        t_ack = time.monotonic()
        rpc_latency = t_ack - t_send
        # Firmware-side ACK time, captured by TimedAlpacaClient.
        fw_t_ack = cli.calls[-1].fw_t_ack if cli.calls else None

        # Poll until we see motion or timeout. Record both host and
        # firmware timestamps; the firmware-time motion-onset latency is
        # the primary number (eliminates HTTP-latency jitter).
        t_first_motion_host: Optional[float] = None
        fw_t_first_motion: Optional[float] = None
        # samples: (host_t_post_ack, fw_t, d_az_deg)
        az_samples: list[tuple[float, Optional[float], float]] = []
        timeout_deadline = t_ack + 5.0
        while time.monotonic() < timeout_deadline:
            time.sleep(poll_dt)
            _, az, fw_t = measure_altaz_timed(cli, loc)
            t_sample = time.monotonic()
            d = wrap_pm180(az - az0)
            az_samples.append((t_sample - t_ack, fw_t, d))
            if t_first_motion_host is None and abs(d) > motion_thresh_degs:
                t_first_motion_host = t_sample
                fw_t_first_motion = fw_t
                break

        motion_latency_host = (
            t_first_motion_host - t_ack if t_first_motion_host else None
        )
        fw_motion_latency = (
            fw_t_first_motion - fw_t_ack
            if (fw_t_first_motion is not None and fw_t_ack is not None)
            else None
        )

        def _ms(x):
            return "timeout" if x is None else f"{1000*x:.0f}ms"

        print(f"  [{i+1}/{n}] rpc={_ms(rpc_latency)}  "
              f"host_motion={_ms(motion_latency_host)}  "
              f"fw_motion={_ms(fw_motion_latency)}")

        _write_jsonl(log_path, {
            "kind": "trial", "i": i, "angle": angle,
            "rpc_latency_s": rpc_latency,
            "motion_latency_s": motion_latency_host,
            "fw_motion_latency_s": fw_motion_latency,
            "fw_t_ack": fw_t_ack,
            "fw_t_first_motion": fw_t_first_motion,
            "motion_threshold_deg": motion_thresh_degs,
            "sample_count": len(az_samples),
        })

        # Wait for burst to finish and settle.
        wait_for_mount_idle(cli, timeout_s=dur + 3.0)
        time.sleep(0.5)

    # Aggregate.
    rpcs = [r.t_ack - r.t_send for r in cli.calls if r.method == "scope_speed_move"]
    print()
    if rpcs:
        srt = sorted(rpcs)
        print(f"RPC-latency n={len(srt)} mean={1000*statistics.mean(srt):.0f}ms "
              f"p50={1000*srt[len(srt)//2]:.0f}ms "
              f"p90={1000*srt[int(0.9*len(srt))-1]:.0f}ms "
              f"max={1000*srt[-1]:.0f}ms")
    print(f"wrote: {log_path}")
    return 0


# ---------------------------------------------------------------------------
# mode: chirp  (swept-frequency velocity profile)
# ---------------------------------------------------------------------------


def run_chirp(cli: TimedAlpacaClient, args) -> int:
    loc = _make_loc()
    f0 = float(args.f0)
    f1 = float(args.f1)
    amp_degs = float(args.amp_degs)     # amplitude in deg/s of commanded velocity
    duration = float(args.duration)
    tick_dt = float(args.tick_dt)
    min_speed_cmd = 80  # below this, stiction dominates; clip to zero

    print("=" * 78)
    print(f"sysid chirp — f0={f0}Hz f1={f1}Hz amp={amp_degs}°/s T={duration}s "
          f"tick={tick_dt}s")
    print("=" * 78)

    _setup_mount(cli, loc, args.start_az, args.alt)
    log_path = _open_jsonl("chirp")
    _write_jsonl(log_path, {
        "kind": "header", "mode": "chirp",
        "f0_hz": f0, "f1_hz": f1, "amp_degs": amp_degs,
        "duration_s": duration, "tick_dt_s": tick_dt,
        "min_speed_cmd": min_speed_cmd,
        "n_speed_per_deg_per_sec": SPEED_PER_DEG_PER_SEC,
    })

    # Instantaneous phase for linear chirp:
    #   f(t) = f0 + (f1 - f0) * (t / duration)
    #   phase(t) = 2*pi * integral_0^t f(s) ds
    #            = 2*pi * (f0 * t + 0.5 * (f1 - f0) / duration * t^2)

    _, az_start = measure_altaz(cli, loc)
    t0 = time.monotonic()
    while True:
        t_rel = time.monotonic() - t0
        if t_rel > duration:
            break
        phase = 2.0 * math.pi * (f0 * t_rel + 0.5 * (f1 - f0) / duration * t_rel * t_rel)
        v_cmd_degs = amp_degs * math.sin(phase)
        speed_cmd = int(round(abs(v_cmd_degs) * SPEED_PER_DEG_PER_SEC))
        if speed_cmd < min_speed_cmd:
            speed_cmd = 0
        angle_cmd = 0 if v_cmd_degs >= 0 else 180
        # Issue the command (dur_sec = 10; it supersedes each tick).
        if speed_cmd == 0:
            # explicit stop
            speed_move(cli, 0, 0, 1)
        else:
            speed_move(cli, speed_cmd, angle_cmd, 10)
        # Sample position for the log (same scope_get_equ_coord poll).
        _, az, fw_t = measure_altaz_timed(cli, loc)
        _write_jsonl(log_path, {
            "kind": "tick", "t": t_rel, "fw_t": fw_t,
            "v_cmd_degs": v_cmd_degs, "speed": speed_cmd, "angle": angle_cmd,
            "az": az,
        })
        # sleep to next tick
        next_tick = t0 + (math.floor(t_rel / tick_dt) + 1) * tick_dt
        time.sleep(max(0.0, next_tick - time.monotonic()))

    # Stop.
    speed_move(cli, 0, 0, 1)
    wait_for_mount_idle(cli, timeout_s=5.0)
    _, az_end = measure_altaz(cli, loc)
    print(f"chirp done; az_drift={wrap_pm180(az_end - az_start):+.3f}°")
    print(f"wrote: {log_path}")
    return 0


# ---------------------------------------------------------------------------
# mode: speed_transition  (warm motion-onset latency)
# ---------------------------------------------------------------------------


def _parse_transition_pairs(s: str) -> list[tuple[int, int]]:
    out = []
    for chunk in s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        a, b = chunk.split(":")
        out.append((int(a), int(b)))
    return out


def run_speed_transition(cli: TimedAlpacaClient, args) -> int:
    """For each (A, B) pair: ramp to A, hold to steady state, then command B
    and measure how long until the observed rate diverges from A.

    Rate threshold: we detect "rate has changed" when the windowed mean
    rate over the most-recent 0.3 s differs from A by > max(0.15 * |A-B|,
    0.3°/s). Less conservative than waiting for rate = B (which takes
    ~tau), but robust to sampling noise.
    """
    loc = _make_loc()
    pairs = _parse_transition_pairs(args.transition_pairs)
    if not pairs:
        print("ERROR: need at least one transition pair", file=sys.stderr)
        return 2

    print("=" * 78)
    print(f"sysid speed_transition — pairs={pairs}")
    print("=" * 78)

    _setup_mount(cli, loc, args.start_az, args.alt)
    log_path = _open_jsonl("speed_transition")
    _write_jsonl(log_path, {
        "kind": "header", "mode": "speed_transition", "pairs": pairs,
        "n_speed_per_deg_per_sec": SPEED_PER_DEG_PER_SEC,
    })

    poll_dt = float(args.poll_dt)      # e.g. 0.05 s with fast proxy
    hold_a_s = float(args.hold_a)      # default 8.0
    hold_b_s = float(args.hold_b)      # default 4.0

    for idx, (A, B) in enumerate(pairs):
        _recenter_if_far(cli, loc, args.start_az, args.alt)
        wait_for_mount_idle(cli, timeout_s=5.0)
        set_tracking(cli, False)
        angle = 0 if idx % 2 == 0 else 180
        rate_A_expected = A / SPEED_PER_DEG_PER_SEC

        print(f"\n[{idx+1}/{len(pairs)}] transition {A}→{B} angle={angle}")
        # Command A and sample until steady state.
        speed_move(cli, A, angle, 10)
        time.sleep(hold_a_s)  # wait ~8s, past tau ramp

        # Measure steady-state rate: two samples 0.3s apart
        _, az0, fw_t0 = measure_altaz_timed(cli, loc)
        time.sleep(0.3)
        _, az1, fw_t1 = measure_altaz_timed(cli, loc)
        if fw_t0 is None or fw_t1 is None:
            ss_dt = time.monotonic() - (time.monotonic() - 0.3)  # fallback
        else:
            ss_dt = fw_t1 - fw_t0
        ss_rate_A = wrap_pm180(az1 - az0) / max(ss_dt, 1e-3)
        print(f"  steady-state A rate: {ss_rate_A:+.3f}°/s (expected "
              f"{rate_A_expected if angle == 0 else -rate_A_expected:+.3f}°/s)")

        # Transition to B.
        _, az_pre, fw_t_pre = measure_altaz_timed(cli, loc)
        t_cmd_B = time.monotonic()
        speed_move(cli, B, angle, 10)
        t_ack_B = time.monotonic()
        fw_t_ack_B = cli.calls[-1].fw_t_ack
        rpc_latency_B = t_ack_B - t_cmd_B

        # Poll tightly for rate to diverge from A.
        # Threshold: midway between A-rate and B-rate, scaled.
        target_rate_expected = B / SPEED_PER_DEG_PER_SEC  # |rate|
        if angle == 180:
            target_rate_expected = -target_rate_expected
            ss_rate_A = ss_rate_A  # already signed
        # Divergence threshold: |observed - A| > max(0.3, 0.15 * |A-B|)
        thresh = max(0.3, 0.15 * abs(ss_rate_A - target_rate_expected))

        # Log ALL samples collected in the hold_b window; separately compute
        # rate-change using a sliding window of the last min_window_s of
        # samples.
        all_samples: list[tuple[float, Optional[float], float]] = []  # (host_t_rel, fw_t, az)
        min_window_s = 0.3   # min time spread for a rate estimate to be meaningful
        t_change_host: Optional[float] = None
        fw_t_change: Optional[float] = None

        timeout_deadline = t_ack_B + hold_b_s
        while time.monotonic() < timeout_deadline:
            time.sleep(poll_dt)
            _, az_i, fw_t_i = measure_altaz_timed(cli, loc)
            t_i = time.monotonic()
            all_samples.append((t_i - t_ack_B, fw_t_i, az_i))
            # For rate-change detection: find the oldest sample at least
            # min_window_s before the latest. DON'T break on first
            # detection -- we want the full trajectory to see whether the
            # plant decelerates through zero or transitions smoothly.
            if len(all_samples) >= 2 and t_change_host is None:
                latest = all_samples[-1]
                for j in range(len(all_samples) - 2, -1, -1):
                    older = all_samples[j]
                    if older[1] is not None and latest[1] is not None:
                        dt_win = latest[1] - older[1]
                    else:
                        dt_win = latest[0] - older[0]
                    if dt_win >= min_window_s:
                        signed = wrap_pm180(latest[2] - older[2])
                        win_rate = signed / dt_win
                        if abs(win_rate - ss_rate_A) > thresh:
                            t_change_host = t_i
                            fw_t_change = fw_t_i
                        break
        samples = all_samples

        # Let B continue to steady state for remaining hold time, then stop.
        speed_move(cli, 0, 0, 1)
        wait_for_mount_idle(cli, timeout_s=4.0)

        host_latency = (t_change_host - t_ack_B) if t_change_host else None
        fw_latency = (
            fw_t_change - fw_t_ack_B
            if (fw_t_change is not None and fw_t_ack_B is not None)
            else None
        )

        def _ms(x):
            return "timeout" if x is None else f"{1000*x:.0f}ms"

        print(f"  rate-change: host={_ms(host_latency)}  fw={_ms(fw_latency)}  "
              f"thresh={thresh:.2f}°/s")

        _write_jsonl(log_path, {
            "kind": "trial", "idx": idx, "A": A, "B": B, "angle": angle,
            "rate_A_measured_degs": ss_rate_A,
            "rate_B_expected_degs": target_rate_expected,
            "rpc_latency_s": rpc_latency_B,
            "host_rate_change_latency_s": host_latency,
            "fw_rate_change_latency_s": fw_latency,
            "fw_t_ack_B": fw_t_ack_B,
            "fw_t_rate_change": fw_t_change,
            "threshold_degs": thresh,
            "sample_count": len(samples),
        })
        for (t, fw_t, az) in samples:
            _write_jsonl(log_path, {
                "kind": "sample", "idx": idx, "A": A, "B": B,
                "t": t, "fw_t": fw_t, "az": az,
            })

        time.sleep(0.5)

    print(f"\nwrote: {log_path}")
    return 0


# ---------------------------------------------------------------------------
# mode: limits  (probe physical hard stops)
# ---------------------------------------------------------------------------


def run_limits(cli: TimedAlpacaClient, args) -> int:
    """Slow-command motion in one direction and detect stall.

    Safety rules:
    - Does NOT call `_setup_mount` — assumes the user has manually
      pre-positioned the mount (via `jog` or the web UI) away from the
      suspected limit. Performing an iscope goto here could silently
      land us against a limit before the probe starts.
    - Uses a low speed so a missed stall detection just results in a
      slow, gentle motion into the stop.
    - Gives up after `--max-dur` seconds regardless.
    """
    loc = _make_loc()
    direction = args.direction
    if direction not in ("cw", "ccw", "up", "down"):
        print(f"ERROR: unknown direction {direction!r}", file=sys.stderr)
        return 2
    speed = int(args.speed)
    max_dur_s = float(args.max_dur)
    sample_dt = float(args.sample_dt)
    stall_window_s = float(args.stall_window)
    stall_rate_threshold = float(args.stall_rate)
    min_motion_deg = float(args.min_motion)

    if direction == "cw":
        angle = 0
        axis_label = "az"
    elif direction == "ccw":
        angle = 180
        axis_label = "az"
    elif direction == "up":
        angle = 90
        axis_label = "alt"
    else:  # down
        angle = 270
        axis_label = "alt"

    print("=" * 78)
    print(f"sysid limits — direction={direction} speed={speed} "
          f"max_dur={max_dur_s}s")
    print("Make sure the mount is pre-positioned AWAY from the suspected limit.")
    print("=" * 78)

    ensure_scenery_mode(cli)
    # After a power-cycle the arm stays folded (mount.close=true) until
    # the firmware finishes unfolding from scenery-view mode. speed_move
    # is silently dropped while close=true, so poll until it clears.
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state = cli.method_sync("get_device_state").get("result", {})
        if not state.get("mount", {}).get("close", True):
            break
        time.sleep(0.5)
    set_tracking(cli, False)
    wait_for_mount_idle(cli, timeout_s=5.0)

    alt0, az0, fw_t0 = measure_altaz_timed(cli, loc)
    print(f"Starting at alt={alt0:+.3f}° az={az0:+.3f}°")

    log_path = _open_jsonl("limits")
    _write_jsonl(log_path, {
        "kind": "header", "mode": "limits", "direction": direction,
        "angle": angle, "speed": speed,
        "max_dur_s": max_dur_s, "sample_dt_s": sample_dt,
        "stall_window_s": stall_window_s,
        "stall_rate_degs": stall_rate_threshold,
        "min_motion_deg": min_motion_deg,
        "start_az": az0, "start_alt": alt0,
        "n_speed_per_deg_per_sec": SPEED_PER_DEG_PER_SEC,
    })

    # Kick off the motion. scope_speed_move caps dur_sec at 10s, so we
    # re-issue before that cap expires. Dither the re-issue interval and
    # dur_sec so consecutive commands aren't byte-identical — firmware
    # appears to silently drop duplicate speed_move requests, producing
    # spurious "stalls" mid-probe. Alternating the dur_sec by ±1-2s and
    # the re-issue cadence defeats the dedupe without changing mean rate.
    import random as _rand
    _rng = _rand.Random(0x5331d)  # deterministic for reproducible probes
    _FIRMWARE_CAP_S = 10
    def _dithered_dur() -> int:
        return _rng.choice([6, 7, 8, 9, _FIRMWARE_CAP_S])
    def _dithered_interval() -> float:
        return _rng.uniform(4.5, 5.5)
    t_start = time.monotonic()
    init_dur = min(int(max_dur_s), _dithered_dur())
    speed_move(cli, speed, angle, init_dur)
    next_reissue_t = t_start + _dithered_interval()

    samples: list[tuple[float, float | None, float, float]] = []  # t_rel, fw_t, az, alt
    stalled = False
    stall_at_az = None
    stall_at_alt = None
    next_sample_t = t_start + sample_dt
    window_len = max(2, int(round(stall_window_s / sample_dt)))

    # Track cumulative (unwrapped) azimuth motion so the stall-detect's
    # min_motion check works through multi-turn probes without resetting
    # whenever we cross the ±180° wrap boundary.
    cum_az_motion = 0.0
    prev_az = az0
    retries_used = 0
    max_retries = int(args.stall_retries)

    def _retry_motion() -> tuple[bool, float]:
        """Stop, pause, re-issue motion, sample briefly.

        Returns (motion_resumed, motion_deg). motion_resumed is True
        if the plant moved more than the stall rate threshold during
        the verify window.
        """
        speed_move(cli, 0, 0, 1)
        wait_for_mount_idle(cli, timeout_s=3.0)
        time.sleep(0.8)
        # Fresh command with a short (dithered) dur.
        speed_move(cli, speed, angle, _dithered_dur())
        # Watch for motion for ~2.5s (> cold-start 0.5s + a few rate samples).
        verify_dur_s = 2.5
        verify_start = time.monotonic()
        _, az_v0, _ = measure_altaz_timed(cli, loc)
        motion_deg = 0.0
        while time.monotonic() - verify_start < verify_dur_s:
            time.sleep(sample_dt)
            _, az_v, _ = measure_altaz_timed(cli, loc)
            motion_deg = abs(wrap_pm180(az_v - az_v0))
            if motion_deg > 0.5:
                return True, motion_deg
        return False, motion_deg

    while time.monotonic() - t_start < max_dur_s:
        wait = next_sample_t - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        # Re-issue the motion command before the firmware cap expires,
        # dithering dur_sec + cadence so consecutive frames aren't identical.
        if time.monotonic() >= next_reissue_t:
            remaining = max_dur_s - (time.monotonic() - t_start)
            dur = int(max(MIN_DUR_S, min(remaining, _dithered_dur())))
            speed_move(cli, speed, angle, dur)
            next_reissue_t = time.monotonic() + _dithered_interval()
        alt_i, az_i, fw_t_i = measure_altaz_timed(cli, loc)
        t_rel = time.monotonic() - t_start
        samples.append((t_rel, fw_t_i, az_i, alt_i))
        next_sample_t += sample_dt

        # Unwrapped cumulative motion (for az probes).
        if axis_label == "az":
            cum_az_motion += wrap_pm180(az_i - prev_az)
            prev_az = az_i

        # Stall test: look back `window_len` samples.
        if len(samples) >= window_len:
            recent = samples[-window_len:]
            dt_win = recent[-1][0] - recent[0][0]
            if axis_label == "az":
                d_win = wrap_pm180(recent[-1][2] - recent[0][2])
                total_motion = abs(cum_az_motion)
            else:
                d_win = recent[-1][3] - recent[0][3]
                total_motion = abs(samples[-1][3] - alt0)
            rate_win = abs(d_win / dt_win) if dt_win > 0 else 0.0
            if total_motion > min_motion_deg and rate_win < stall_rate_threshold:
                candidate_az = samples[-1][2]
                candidate_alt = samples[-1][3]
                print(f"  STALL-candidate at t={t_rel:.1f}s: "
                      f"alt={candidate_alt:+.3f}° az={candidate_az:+.3f}° "
                      f"cum_motion={cum_az_motion:+.1f}° "
                      f"(window rate {rate_win:.3f}°/s)")
                retries_used += 1
                if retries_used > max_retries:
                    stalled = True
                    stall_at_az = candidate_az
                    stall_at_alt = candidate_alt
                    print(f"  CONFIRMED limit after {max_retries} retries.")
                    break
                print(f"  retry {retries_used}/{max_retries}: stop, pause, "
                      "re-issue to verify…")
                resumed, motion = _retry_motion()
                if resumed:
                    print(f"  -> motion RESUMED ({motion:.2f}° in verify window) "
                          "— spurious stall, continuing probe.")
                    # Reset rate-window so we don't immediately re-trigger.
                    samples = samples[-1:]
                    # Force a fresh re-issue next loop iteration.
                    next_reissue_t = time.monotonic()
                    next_sample_t = time.monotonic() + sample_dt
                    continue
                print(f"  -> motion did NOT resume ({motion:.2f}°); "
                      f"still looks stalled (retry {retries_used}/{max_retries}).")

        # Status line.
        if axis_label == "az":
            print(f"  t={t_rel:>5.1f}s  alt={alt_i:+.3f}° az={az_i:+.3f}°  "
                  f"cum_motion={cum_az_motion:+.1f}°")
        else:
            print(f"  t={t_rel:>5.1f}s  alt={alt_i:+.3f}° az={az_i:+.3f}°  "
                  f"|motion|={abs(alt_i - alt0):.3f}°")

    # Stop.
    speed_move(cli, 0, 0, 1)
    wait_for_mount_idle(cli, timeout_s=4.0)
    time.sleep(0.3)
    alt_final, az_final, _ = measure_altaz_timed(cli, loc)
    print()
    print(f"Final position after stop: alt={alt_final:+.3f}° az={az_final:+.3f}°")

    for (t, fw_t, az, alt) in samples:
        _write_jsonl(log_path, {
            "kind": "sample", "t": t, "fw_t": fw_t, "az": az, "alt": alt,
        })
    _write_jsonl(log_path, {
        "kind": "result",
        "stalled": stalled,
        "stall_at_az": stall_at_az,
        "stall_at_alt": stall_at_alt,
        "final_az": az_final,
        "final_alt": alt_final,
        "cum_az_motion_deg": cum_az_motion,
        "total_motion_deg": (
            abs(cum_az_motion)
            if axis_label == "az"
            else abs(alt_final - alt0)
        ),
    })
    if stalled:
        print(f"Hard limit detected at {axis_label}={stall_at_az if axis_label == 'az' else stall_at_alt:+.3f}°")
    else:
        print("No stall detected in the probe window. Mount may have full travel "
              "in this direction, or start point was too far from the limit "
              "for the chosen speed/dur.")
    print(f"wrote: {log_path}")
    return 0


# ---------------------------------------------------------------------------
# mode: trajectory_track  (planner-isolation validation)
# ---------------------------------------------------------------------------


class _CollectingLogger:
    """Duck-typed stand-in for PositionLogger — captures `mark_event` calls
    into an in-memory list so trajectory_track can post-process the
    `ff_tick` stream emitted by `move_azimuth_to_ff`."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def set_phase(self, *_a, **_kw) -> None:
        pass

    def set_target(self, *_a, **_kw) -> None:
        pass

    def mark_event(self, name: str, **fields) -> None:
        self.events.append({"name": name, **fields})


def run_trajectory_track(cli: TimedAlpacaClient, args) -> int:
    from device.velocity_controller import move_azimuth_to_ff

    loc = _make_loc()
    delta = float(args.delta)
    v_max = float(args.v_max)
    a_max = float(args.a_max)
    j_max = float(args.j_max)
    profile = str(args.profile)
    cold_start_lag = float(args.cold_start_lag)
    tick_dt = float(args.tick_dt)

    print("=" * 78)
    print(f"sysid trajectory_track — delta={delta:+.1f}° profile={profile} "
          f"v_max={v_max} a_max={a_max} j_max={j_max} "
          f"cold_start_lag={cold_start_lag}s tick_dt={tick_dt}s")
    print("=" * 78)

    _setup_mount(cli, loc, args.start_az, args.alt)
    set_tracking(cli, False)
    _, cur_az = measure_altaz(cli, loc)
    target_az = cur_az + delta  # planner wraps internally via wrap_pm180
    print(f"start_az={cur_az:+.3f}°  target_az={target_az:+.3f}°")

    logger = _CollectingLogger()
    _, meas_az, stats = move_azimuth_to_ff(
        cli,
        target_az_deg=target_az,
        cur_az_deg=cur_az,
        loc=loc,
        target_alt_deg=args.alt,
        tag="[trajectory_track]",
        position_logger=logger,
        v_max=v_max,
        a_max=a_max,
        j_max=j_max,
        tick_dt=tick_dt,
        settle_s=1.5,
        cold_start_lag_s=cold_start_lag,
        profile=profile,
        fallback_residual_deg=1e9,
        fallback_goto_fn=None,
    )

    # Extract ff_tick events and compute tracking RMSE.
    ticks = [e for e in logger.events if e["name"] == "ff_tick"]
    errs = [float(t.get("tracking_err_deg", 0.0)) for t in ticks]
    if errs:
        rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
        mean = sum(errs) / len(errs)
        peak = max(errs)
    else:
        rmse = mean = peak = float("nan")

    final_residual = stats.get("final_residual_deg")
    print()
    print(f"ticks_captured={len(ticks)}  trajectory_duration={stats['trajectory_duration_s']:.2f}s")
    print(f"tracking: mean={mean:.3f}°  peak={peak:.3f}°  RMSE={rmse:.3f}°")
    if final_residual is not None:
        print(f"final_residual={final_residual:+.3f}°  (measured_az={meas_az:+.3f}°)")

    log_path = _open_jsonl("trajectory_track")
    _write_jsonl(log_path, {
        "kind": "header", "mode": "trajectory_track",
        "delta_deg": delta, "profile": profile,
        "v_max_degs": v_max, "a_max_degs2": a_max, "j_max_degs3": j_max,
        "cold_start_lag_s": cold_start_lag, "tick_dt_s": tick_dt,
        "start_az": cur_az, "target_az": target_az,
        "n_speed_per_deg_per_sec": SPEED_PER_DEG_PER_SEC,
    })
    _write_jsonl(log_path, {
        "kind": "summary",
        "ticks_captured": len(ticks),
        "tracking_mean_deg": mean,
        "tracking_peak_deg": peak,
        "tracking_rmse_deg": rmse,
        "final_residual_deg": final_residual,
        "trajectory_duration_s": stats["trajectory_duration_s"],
        "wall_time_s": stats["wall_time_s"],
    })
    for ev in logger.events:
        _write_jsonl(log_path, {"kind": "event", **ev})
    print(f"wrote: {log_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", required=True,
                   choices=["step_response", "deadband", "latency", "chirp",
                            "speed_transition", "trajectory_track", "limits"])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--device", type=int, default=1)
    p.add_argument("--alt", type=float, default=10.0)
    p.add_argument("--start-az", type=float, default=0.0,
                   help="Azimuth to recenter to before each burst.")

    # step_response
    p.add_argument("--speeds", default="80,100,200,300,500,700,900,1100,1300,1440",
                   help="Comma-separated commanded speeds.")
    p.add_argument("--dur", type=int, default=10,
                   help="Burst dur_sec (firmware cap 10).")
    p.add_argument("--chain", type=int, default=1,
                   help="Number of back-to-back bursts at the same speed "
                        "(chains via firmware cmd supersede).")
    p.add_argument("--sample-dt", type=float, default=0.5,
                   help="Position sampling interval (s).")

    # deadband
    p.add_argument("--dwell", type=float, default=5.0,
                   help="deadband: seconds per commanded speed.")
    p.add_argument("--rest", type=float, default=1.5,
                   help="deadband: seconds between speeds.")

    # latency
    p.add_argument("--n", type=int, default=10,
                   help="latency: trials.")
    p.add_argument("--speed", type=int, default=500,
                   help="latency: commanded speed per trial.")
    p.add_argument("--poll-dt", type=float, default=0.1,
                   help="latency: polling interval for motion detection.")

    # chirp
    p.add_argument("--f0", type=float, default=0.05)
    p.add_argument("--f1", type=float, default=0.5)
    p.add_argument("--amp-degs", type=float, default=2.0,
                   help="Commanded-velocity amplitude (deg/s). Must be "
                        "well below max rate (6 deg/s) to stay unsaturated.")
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--tick-dt", type=float, default=0.5)

    # speed_transition
    p.add_argument("--transition-pairs",
                   default="0:300,300:500,500:300,500:1000,1000:500,1000:0",
                   help="Comma-separated from:to firmware-speed pairs.")
    p.add_argument("--hold-a", type=float, default=8.0,
                   help="speed_transition: seconds to hold A before B.")
    p.add_argument("--hold-b", type=float, default=4.0,
                   help="speed_transition: seconds to watch for rate change "
                        "after commanding B.")

    # limits
    p.add_argument("--direction", choices=["cw", "ccw", "up", "down"],
                   default="cw",
                   help="limits: direction to probe (cw/ccw az, up/down el).")
    p.add_argument("--max-dur", type=float, default=30.0,
                   help="limits: max motion duration (s) before giving up.")
    p.add_argument("--stall-window", type=float, default=1.5,
                   help="limits: window (s) used to detect stall.")
    p.add_argument("--stall-rate", type=float, default=0.05,
                   help="limits: stall threshold |rate| (deg/s).")
    p.add_argument("--min-motion", type=float, default=0.5,
                   help="limits: ignore stalls before we've moved this "
                        "much from start (skips cold-start dead time).")
    p.add_argument("--stall-retries", type=int, default=2,
                   help="limits: on stall detection, stop+pause+re-issue "
                        "this many times to verify. Confirms only if no "
                        "retry produces motion.")

    # trajectory_track
    p.add_argument("--delta", type=float, default=60.0,
                   help="trajectory_track: signed azimuth delta (deg).")
    p.add_argument("--v-max", type=float, default=5.0,
                   help="trajectory_track: max velocity (deg/s) for the planner "
                        "(headroom below firmware cap ~6°/s).")
    p.add_argument("--a-max", type=float, default=10.0,
                   help="trajectory_track: max accel (deg/s²) for the planner.")
    p.add_argument("--j-max", type=float, default=40.0,
                   help="trajectory_track: max jerk (deg/s³) for S-curve planner.")
    p.add_argument("--profile", choices=["trapezoid", "scurve"],
                   default="trapezoid",
                   help="trajectory_track: trajectory profile (trapezoid|scurve).")
    p.add_argument("--cold-start-lag", type=float, default=0.5,
                   help="trajectory_track: cold-start dead-time compensation (s). "
                        "Set 0 to disable the lead-in hold.")

    return p


def main() -> int:
    args = _build_parser().parse_args()
    cli = TimedAlpacaClient(args.host, args.port, args.device)
    if args.mode == "step_response":
        return run_step_response(cli, args)
    elif args.mode == "deadband":
        return run_deadband(cli, args)
    elif args.mode == "latency":
        return run_latency(cli, args)
    elif args.mode == "chirp":
        return run_chirp(cli, args)
    elif args.mode == "speed_transition":
        return run_speed_transition(cli, args)
    elif args.mode == "trajectory_track":
        return run_trajectory_track(cli, args)
    elif args.mode == "limits":
        return run_limits(cli, args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
