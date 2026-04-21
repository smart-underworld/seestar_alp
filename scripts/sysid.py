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
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", required=True,
                   choices=["step_response", "deadband", "latency", "chirp",
                            "speed_transition"])
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
