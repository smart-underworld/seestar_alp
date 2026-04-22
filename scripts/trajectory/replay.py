"""Offline lab harness: replay a trajectory JSONL through the plant model.

Reads the JSONL produced by fetch_aircraft / fetch_satellites, resamples the
topocentric (az, el) stream onto the controller tick grid, synthesizes
feedforward commands with the Phase 4.5 formula
`v_cmd = v_ref + τ · a_ref`, feeds those commands through
`device.plant_models.FirstOrderLagModel.simulate(...)` per axis, and reports
tracking error.

This does NOT touch the real mount, the TCP simulator, or
`device.trajectory` (which is a point-to-point planner, not a streaming
reference). It is a sanity check for the ECEF→az/el→FF pipeline that will
eventually drive the Phase 5 `StreamingFFController`.

Example:

    python -m scripts.trajectory.replay \
        data/trajectories/aircraft/UAL123_a1b2c3_1700000000.jsonl --plot
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from device.plant_limits import AzimuthLimits
from device.plant_models import FirstOrderLagModel

from scripts.trajectory.observer import unwrap_az_series


# Defaults matching Phase 4.5 velocity_controller constants.
TAU_S = 0.348
K_DC = 0.996
V_MAX_DEGS = 6.0
TICK_DT_S = 0.5
KP_POS = 0.5
V_CORR_MAX_DEGS = 2.0


@dataclass
class TrajectoryFile:
    header: dict
    samples: list[dict]


def load_trajectory(path: Path) -> TrajectoryFile:
    header: dict | None = None
    samples: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("kind") == "header":
                header = rec
            elif rec.get("kind") == "sample":
                samples.append(rec)
    if header is None:
        raise ValueError(f"{path}: no header record")
    if len(samples) < 4:
        raise ValueError(f"{path}: too few samples ({len(samples)})")
    return TrajectoryFile(header=header, samples=samples)


def resample_to_ticks(
    traj: TrajectoryFile, tick_dt: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (t_grid, az_cum_deg, el_deg) on a uniform tick grid.

    az is unwrapped into a cumulative (non-wrapping) series before
    interpolation so a crossing through ±180° doesn't produce a spurious
    360° step in the reference.
    """
    t_raw = np.array([s["t_unix"] for s in traj.samples])
    az_raw = np.array([s["az_deg"] for s in traj.samples])
    el_raw = np.array([s["el_deg"] for s in traj.samples])
    az_cum_raw = unwrap_az_series(az_raw)

    t0 = float(t_raw[0])
    t1 = float(t_raw[-1])
    # Snap to an integer number of ticks.
    n = int(np.floor((t1 - t0) / tick_dt)) + 1
    t_grid = t0 + np.arange(n) * tick_dt
    az_cum = np.interp(t_grid, t_raw, az_cum_raw)
    el = np.interp(t_grid, t_raw, el_raw)
    return t_grid, az_cum, el


def _smoothed_rates(
    position: np.ndarray, tick_dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Central differences + short moving-average smoothing → (v, a)."""
    v = np.gradient(position, tick_dt)
    a = np.gradient(v, tick_dt)
    # 3-sample moving average → ~1.5 tick (0.75 s) smoothing for the
    # acceleration term. Short enough to preserve real dynamics, long
    # enough to suppress gradient double-derivative noise.
    if len(a) >= 3:
        kernel = np.ones(3) / 3.0
        a = np.convolve(a, kernel, mode="same")
    return v, a


@dataclass
class ReplayResult:
    t_grid: np.ndarray
    az_ref: np.ndarray
    el_ref: np.ndarray
    az_sim: np.ndarray
    el_sim: np.ndarray
    v_cmd_az: np.ndarray
    v_cmd_el: np.ndarray
    v_ref_az: np.ndarray
    v_ref_el: np.ndarray
    az_err: np.ndarray
    el_err: np.ndarray
    az_sat_count: int
    el_sat_count: int
    cable_wrap_violations: int
    header: dict


def simulate_replay(
    traj: TrajectoryFile,
    tick_dt: float = TICK_DT_S,
    tau_s: float = TAU_S,
    k_dc: float = K_DC,
    v_max: float = V_MAX_DEGS,
    kp_pos: float = KP_POS,
    v_corr_max: float = V_CORR_MAX_DEGS,
    use_ff: bool = True,
    az_limits: AzimuthLimits | None = None,
) -> ReplayResult:
    """Simulate FF+FB tracking on a first-order plant.

    Matches device.velocity_controller.move_to_ff semantics: each tick,
    `v_cmd = v_ff + v_corr` where v_corr = clamp(kp_pos · pos_err, ±v_corr_max)
    and v_ff = v_ref + τ · a_ref (or just v_ref when use_ff=False). The
    total command is clamped to ±v_max before being sent to the plant.
    """
    t_grid, az_ref, el_ref = resample_to_ticks(traj, tick_dt)
    v_ref_az, a_ref_az = _smoothed_rates(az_ref, tick_dt)
    v_ref_el, a_ref_el = _smoothed_rates(el_ref, tick_dt)

    if use_ff:
        v_ff_az = v_ref_az + tau_s * a_ref_az
        v_ff_el = v_ref_el + tau_s * a_ref_el
    else:
        v_ff_az = v_ref_az.copy()
        v_ff_el = v_ref_el.copy()

    model = FirstOrderLagModel()
    model.tau = tau_s
    model.k_dc = k_dc

    n = len(t_grid)
    v_cmd_az = np.zeros(n)
    v_cmd_el = np.zeros(n)
    az_sim = np.zeros(n)
    el_sim = np.zeros(n)
    v_sim_az = 0.0
    v_sim_el = 0.0
    az_sim[0] = az_ref[0]
    el_sim[0] = el_ref[0]
    sat_az = 0
    sat_el = 0

    for i in range(n):
        # Feedback on position error at this tick.
        err_az = az_ref[i] - az_sim[i]
        err_el = el_ref[i] - el_sim[i]
        v_corr_az = np.clip(kp_pos * err_az, -v_corr_max, v_corr_max)
        v_corr_el = np.clip(kp_pos * err_el, -v_corr_max, v_corr_max)
        raw_az = v_ff_az[i] + v_corr_az
        raw_el = v_ff_el[i] + v_corr_el
        cmd_az = float(np.clip(raw_az, -v_max, v_max))
        cmd_el = float(np.clip(raw_el, -v_max, v_max))
        if abs(raw_az) > v_max:
            sat_az += 1
        if abs(raw_el) > v_max:
            sat_el += 1
        v_cmd_az[i] = cmd_az
        v_cmd_el[i] = cmd_el
        if i == n - 1:
            # No more ticks after this; sim endpoint is already stored.
            break
        # Step plant by one tick.
        v_sim_az_next = model.predict_rate(v_sim_az, cmd_az, tick_dt)
        v_sim_el_next = model.predict_rate(v_sim_el, cmd_el, tick_dt)
        # Trapezoidal position update over the tick.
        az_sim[i + 1] = az_sim[i] + 0.5 * (v_sim_az + v_sim_az_next) * tick_dt
        el_sim[i + 1] = el_sim[i] + 0.5 * (v_sim_el + v_sim_el_next) * tick_dt
        v_sim_az = v_sim_az_next
        v_sim_el = v_sim_el_next

    az_err = az_ref - az_sim
    el_err = el_ref - el_sim

    cable_violations = 0
    if az_limits is not None:
        ok = np.vectorize(az_limits.contains_cum)(az_sim)
        cable_violations = int(np.count_nonzero(~ok))

    return ReplayResult(
        t_grid=t_grid, az_ref=az_ref, el_ref=el_ref,
        az_sim=az_sim, el_sim=el_sim,
        v_cmd_az=v_cmd_az, v_cmd_el=v_cmd_el,
        v_ref_az=v_ref_az, v_ref_el=v_ref_el,
        az_err=az_err, el_err=el_err,
        az_sat_count=sat_az, el_sat_count=sat_el,
        cable_wrap_violations=cable_violations,
        header=traj.header,
    )


def report(result: ReplayResult) -> str:
    az_rms = float(np.sqrt(np.mean(result.az_err ** 2)))
    el_rms = float(np.sqrt(np.mean(result.el_err ** 2)))
    az_peak = float(np.max(np.abs(result.az_err)))
    el_peak = float(np.max(np.abs(result.el_err)))
    header = result.header
    src = header.get("source", "?")
    ident = header.get("id", "?")
    label = header.get("callsign") or header.get("name") or ident
    lines = [
        f"{src}:{ident} ({label})",
        f"  duration       {header.get('duration_s', 0):.0f} s",
        f"  samples        {len(result.t_grid)} ticks @ {result.t_grid[1] - result.t_grid[0]:.3f}s",
        f"  peak el        {header.get('peak_el_deg', float('nan')):.1f}°",
        f"  az error       RMS {az_rms:.3f}°   peak {az_peak:.3f}°",
        f"  el error       RMS {el_rms:.3f}°   peak {el_peak:.3f}°",
        f"  az saturation  {result.az_sat_count}/{len(result.t_grid)} ticks",
        f"  el saturation  {result.el_sat_count}/{len(result.t_grid)} ticks",
    ]
    if result.cable_wrap_violations:
        lines.append(
            f"  cable-wrap     {result.cable_wrap_violations} violations "
            f"(az_sim out of usable cum range)"
        )
    else:
        lines.append("  cable-wrap     OK")
    return "\n".join(lines)


def write_jsonl(result: ReplayResult, path: Path) -> None:
    """Emit per-tick records compatible with the velocity_controller log UI.

    Payload keys mirror the `2d_ff_tick` event shape so `/api/.../log` can
    render it with zero changes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "kind": "header",
        "source": "replay",
        "id": result.header.get("id"),
        "poll_interval_s": float(result.t_grid[1] - result.t_grid[0]),
        "original_source": result.header.get("source"),
    }
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for i in range(len(result.t_grid)):
            rec = {
                "kind": "event",
                "event": "2d_ff_tick",
                "t": float(result.t_grid[i]),
                "az_ref": float(result.az_ref[i]),
                "el_ref": float(result.el_ref[i]),
                "az_sim": float(result.az_sim[i]),
                "el_sim": float(result.el_sim[i]),
                "az_err": float(result.az_err[i]),
                "el_err": float(result.el_err[i]),
                "v_cmd_az": float(result.v_cmd_az[i]),
                "v_cmd_el": float(result.v_cmd_el[i]),
                "v_ref_az": float(result.v_ref_az[i]),
                "v_ref_el": float(result.v_ref_el[i]),
            }
            f.write(json.dumps(rec) + "\n")


def _plot(result: ReplayResult, path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[replay] matplotlib not available, skipping --plot",
              file=sys.stderr)
        return
    t = result.t_grid - result.t_grid[0]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(t, result.az_ref, label="ref")
    axes[0].plot(t, result.az_sim, label="sim", linestyle="--")
    axes[0].set_ylabel("az (deg, cumulative)")
    axes[0].legend(loc="upper right")
    axes[1].plot(t, result.el_ref, label="ref")
    axes[1].plot(t, result.el_sim, label="sim", linestyle="--")
    axes[1].set_ylabel("el (deg)")
    axes[1].legend(loc="upper right")
    axes[2].plot(t, result.az_err, label="az err")
    axes[2].plot(t, result.el_err, label="el err")
    axes[2].set_ylabel("error (deg)")
    axes[2].set_xlabel("t (s)")
    axes[2].legend(loc="upper right")
    axes[2].grid(True, alpha=0.3)
    fig.suptitle(
        f"{result.header.get('source')}:{result.header.get('id')} replay"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[replay] plot → {path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("--tick-dt", type=float, default=TICK_DT_S)
    parser.add_argument("--tau", type=float, default=TAU_S)
    parser.add_argument("--k-dc", type=float, default=K_DC)
    parser.add_argument("--v-max", type=float, default=V_MAX_DEGS)
    parser.add_argument("--no-ff", action="store_true",
                        help="disable feedforward (v_cmd = v_ref)")
    parser.add_argument("--no-cable-check", action="store_true",
                        help="skip loading AzimuthLimits from device/plant_limits.json")
    parser.add_argument("--plot", type=Path, default=None,
                        help="write PNG comparison plot (requires matplotlib)")
    parser.add_argument("--jsonl-out", type=Path, default=None,
                        help="write per-tick 2d_ff_tick JSONL (usable in the "
                             "velocity_controller log UI)")
    args = parser.parse_args(argv)

    traj = load_trajectory(args.trajectory)
    az_limits = None if args.no_cable_check else AzimuthLimits.load()
    result = simulate_replay(
        traj,
        tick_dt=args.tick_dt, tau_s=args.tau, k_dc=args.k_dc, v_max=args.v_max,
        use_ff=not args.no_ff,
        az_limits=az_limits,
    )
    print(report(result))
    if args.plot is not None:
        _plot(result, args.plot)
    if args.jsonl_out is not None:
        write_jsonl(result, args.jsonl_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
