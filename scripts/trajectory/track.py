"""Live tracking CLI — drive the Seestar S50 from a JSONL trajectory.

Boots an Alpaca client, hooks a `PositionLogger` for post-hoc analysis,
builds a `JsonlECEFProvider` with an identity `MountFrame`, pre-checks
cable-wrap + elevation feasibility, then runs `StreamingFFController.track`.

Safety:
- `--dry-run` runs the whole loop including logging but sends no motor
  commands. Use this before every live run.
- SIGINT stops cleanly within one tick.
- Each `scope_speed_move` carries a 1 s TTL so a killed script doesn't keep
  the motor running.
- `--skip-precheck` bypasses the cable-wrap / el-limit gate; off by default.

Example:

    uv run python -m scripts.trajectory.track \\
        data/trajectories/satellites/CSS__TIANHE_48274_1776878184.jsonl \\
        --dry-run

    uv run python -m scripts.trajectory.track \\
        data/trajectories/satellites/CSS__TIANHE_48274_1776878184.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from astropy.coordinates import EarthLocation

from device.alpaca_client import AlpacaClient
from device.plant_limits import AzimuthLimits, CumulativeAzTracker
from device.reference_provider import JsonlECEFProvider
from device.streaming_controller import pre_check, track
from device.target_frame import MountFrame
from device.velocity_controller import PositionLogger, measure_altaz_timed
from scripts.trajectory.observer import build_site


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_id() -> str:
    return time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())


def _default_log_dir() -> Path:
    return _REPO_ROOT / "auto_level_logs"


def _wait_for_start(
    start_unix: float, label: str, stop_signal: threading.Event,
) -> None:
    while True:
        remaining = start_unix - time.time()
        if remaining <= 0.0:
            return
        if stop_signal.is_set():
            return
        if remaining > 5.0:
            print(
                f"[track] waiting {remaining:.0f}s for {label} "
                f"(at {time.strftime('%H:%M:%S', time.localtime(start_unix))})",
                file=sys.stderr,
            )
            stop_signal.wait(timeout=min(30.0, remaining - 2.0))
        else:
            stop_signal.wait(timeout=0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--device", type=int, default=1)
    parser.add_argument("--tick-dt", type=float, default=0.5)
    parser.add_argument("--latency-s", type=float, default=0.4)
    parser.add_argument("--tau-s", type=float, default=0.348)
    parser.add_argument("--kp-pos", type=float, default=0.5)
    parser.add_argument("--v-corr-max", type=float, default=2.0)
    parser.add_argument("--v-max", type=float, default=6.0)
    parser.add_argument("--el-max-deg", type=float, default=85.0)
    parser.add_argument("--start-offset-s", type=float, default=0.0,
                        help="Start tracking this many seconds before the "
                             "trajectory head time (negative = late start)")
    parser.add_argument("--max-duration-s", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="Log commands but don't send them to the mount")
    parser.add_argument("--skip-precheck", action="store_true",
                        help="Bypass cable-wrap / el-limit gate")
    parser.add_argument(
        "--log-dir", type=Path, default=None,
        help="Directory for the run's JSONL log (default auto_level_logs/)",
    )
    parser.add_argument(
        "--no-position-log", action="store_true",
        help="Disable PositionLogger (faster, but no post-run overlay)",
    )
    parser.add_argument(
        "--no-calibration", action="store_true",
        help="Ignore device/mount_calibration.json, use identity frame",
    )
    args = parser.parse_args(argv)

    if not args.trajectory.exists():
        print(f"trajectory not found: {args.trajectory}", file=sys.stderr)
        return 2

    site = build_site()
    loc = EarthLocation.from_geodetic(
        lon=site.lon_deg, lat=site.lat_deg, height=site.alt_m,
    )
    _cal_path = _REPO_ROOT / "device" / "mount_calibration.json"
    if _cal_path.exists() and not getattr(args, "no_calibration", False):
        mount_frame = MountFrame.from_calibration_json(_cal_path, site)
        _cal = json.loads(_cal_path.read_text())
        print(
            f"[track] using mount calibration: yaw_offset="
            f"{_cal['yaw_offset_deg']:+.2f}°  "
            f"(residual {_cal.get('residual_rms_deg', 0.0):.2f}°, "
            f"{_cal.get('n_stations', '?')} stations)",
            file=sys.stderr,
        )
    else:
        mount_frame = MountFrame.from_identity_enu(site)
        print("[track] using identity mount frame (no calibration)",
              file=sys.stderr)

    try:
        provider = JsonlECEFProvider(args.trajectory, mount_frame)
    except Exception as exc:
        print(f"failed to load provider: {exc}", file=sys.stderr)
        return 2

    header = provider.header
    t_start_traj, t_end_traj = provider.valid_range()
    pass_name = header.get("name") or header.get("callsign") or header.get("id") or args.trajectory.stem
    print(
        f"[track] target: {pass_name}  "
        f"dur={t_end_traj - t_start_traj:.0f}s  "
        f"head={time.strftime('%H:%M:%S', time.localtime(t_start_traj))}",
        file=sys.stderr,
    )

    az_limits = AzimuthLimits.load()
    if az_limits is None:
        print("[track] WARNING: AzimuthLimits.load() returned None; "
              "cable-wrap enforcement disabled", file=sys.stderr)

    # ---- pre-check ---------------------------------------------------
    pre = pre_check(
        provider, az_limits=az_limits,
        el_max_deg=args.el_max_deg, el_min_deg=-args.el_max_deg,
        tick_dt=args.tick_dt, tau_s=args.tau_s, v_max=args.v_max,
    )
    print("[track] pre-check:", file=sys.stderr)
    print(
        f"    peak |v_az| = {pre.peak_v_az_degs:.2f} °/s, "
        f"peak |v_el| = {pre.peak_v_el_degs:.2f} °/s, "
        f"el range [{pre.min_el_deg:+.1f}, {pre.max_el_deg:+.1f}]°",
        file=sys.stderr,
    )
    for note in pre.notes:
        print(f"    ⚠ {note}", file=sys.stderr)
    if not pre.feasible and not args.skip_precheck:
        print("[track] pre-check FAILED — aborting. Use --skip-precheck to override.",
              file=sys.stderr)
        return 3
    if pre.v_saturation_ticks:
        print(f"    (FF command saturates on {pre.v_saturation_ticks} tick(s); "
              "mount will clip but continue)", file=sys.stderr)

    # ---- connect mount ----------------------------------------------
    cli = AlpacaClient(args.host, args.port, args.device)
    try:
        alt0, az0_wrapped, _fw_t = measure_altaz_timed(cli, loc)
    except Exception as exc:
        print(f"[track] mount connection failed: {exc}", file=sys.stderr)
        return 4
    print(
        f"[track] mount online — current encoder "
        f"az={az0_wrapped:+.3f}°, el={alt0:+.3f}°",
        file=sys.stderr,
    )

    # ---- position logger -------------------------------------------
    position_logger: PositionLogger | None = None
    log_path: Path | None = None
    if not args.no_position_log:
        log_dir = args.log_dir or _default_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{_run_id()}.track-{args.trajectory.stem}.jsonl"
        position_logger = PositionLogger(
            cli, loc, log_path, poll_interval_s=args.tick_dt,
        )
        position_logger.start()
        position_logger.set_phase("track_init")
        position_logger.mark_event(
            "track_start",
            trajectory=str(args.trajectory),
            pass_name=pass_name,
            dry_run=args.dry_run,
            tick_dt=args.tick_dt, latency_s=args.latency_s,
            tau_s=args.tau_s, kp_pos=args.kp_pos,
            v_corr_max=args.v_corr_max, v_max=args.v_max,
            pre_check=json.dumps({
                "feasible": pre.feasible,
                "peak_v_az_degs": pre.peak_v_az_degs,
                "peak_v_el_degs": pre.peak_v_el_degs,
                "min_el_deg": pre.min_el_deg,
                "max_el_deg": pre.max_el_deg,
                "cable_violations": pre.cable_wrap_violations,
                "el_violations": pre.el_limit_violations,
                "v_saturation_ticks": pre.v_saturation_ticks,
            }),
        )
        print(f"[track] logging to {log_path}", file=sys.stderr)

    # ---- az tracker -----------------------------------------------
    tracker = CumulativeAzTracker.load_or_fresh(current_wrapped_az_deg=az0_wrapped)
    print(f"[track] cum_az anchor = {tracker.cum_az_deg:+.3f}°", file=sys.stderr)

    # ---- wait for start + run -------------------------------------
    stop_signal = threading.Event()
    desired_start = t_start_traj - args.start_offset_s
    _wait_for_start(desired_start, pass_name, stop_signal)

    print("[track] engaging controller — Ctrl-C to abort cleanly",
          file=sys.stderr)
    try:
        result = track(
            cli, provider,
            tick_dt=args.tick_dt, latency_s=args.latency_s, tau_s=args.tau_s,
            kp_pos=args.kp_pos, v_corr_max=args.v_corr_max, v_max=args.v_max,
            az_limits=az_limits, az_tracker=tracker,
            position_logger=position_logger,
            stop_signal=stop_signal,
            max_duration_s=args.max_duration_s,
            el_max_deg=args.el_max_deg, el_min_deg=-args.el_max_deg,
            dry_run=args.dry_run,
        )
    finally:
        if position_logger is not None:
            try:
                position_logger.mark_event("track_end")
                position_logger.stop()
            except Exception:
                pass

    print("[track] result:", file=sys.stderr)
    print(
        f"    exit_reason={result.exit_reason}  ticks={result.ticks}  "
        f"elapsed={result.elapsed_s:.1f}s",
        file=sys.stderr,
    )
    print(
        f"    az_err RMS={result.az_err_rms:.3f}°  peak={result.az_err_peak:.3f}°  "
        f"(saturations: {result.sat_az_ticks})",
        file=sys.stderr,
    )
    print(
        f"    el_err RMS={result.el_err_rms:.3f}°  peak={result.el_err_peak:.3f}°  "
        f"(saturations: {result.sat_el_ticks})",
        file=sys.stderr,
    )
    for e in result.errors:
        print(f"    ! {e}", file=sys.stderr)
    if log_path:
        print(f"    log: {log_path}", file=sys.stderr)
    return 0 if result.ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
