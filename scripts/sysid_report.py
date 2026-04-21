#!/usr/bin/env python3
"""Load Phase 1 sysid data, fit candidate plant models, report comparison.

Reads all JSONL files under auto_level_logs/sysid/ matching one of:

    step_response_*.jsonl   -> burst data with cmd_times
    deadband_*.jsonl        -> slow-speed motion
    latency_*.jsonl         -> motion-onset latency histogram
    chirp_*.jsonl           -> held-out validation trajectory

Fits: ZeroOrder, FirstOrderLag, FirstOrderRateLimited, AsymmetricFirstOrder
against the step_response burst segments. Scores each model against both
the training segments and the chirp holdout. Prints a table.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

import numpy as np

_here = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.realpath(os.path.join(_here, "..")))

from device.plant_models import (  # noqa: E402
    AsymmetricFirstOrderModel,
    FirstOrderLagModel,
    FirstOrderRateLimitedModel,
    Segment,
    ZeroOrderModel,
    cmd_speed_to_degs,
    samples_to_segment,
    score_segments,
)
from device.velocity_controller import SPEED_PER_DEG_PER_SEC, unwrap_az_series  # noqa: E402


def _sysid_dir() -> Path:
    return Path(_here).parent / "auto_level_logs" / "sysid"


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def load_step_response_segments(path: Path) -> list[Segment]:
    """Parse a step_response JSONL into a list of Segments, one per burst."""
    recs = _load_jsonl(path)
    segments: list[Segment] = []
    current_burst = None
    current_samples: list[tuple[float, float, float]] = []
    cmd_times_by_burst: list = []

    for r in recs:
        if r.get("kind") == "burst":
            # finalize prior
            if current_burst is not None and current_samples:
                segments.append(samples_to_segment(
                    current_samples,
                    speed=current_burst["speed"],
                    angle=current_burst["angle"],
                    cmd_times=current_burst["cmd_times"],
                ))
            current_burst = r
            current_samples = []
        elif r.get("kind") == "sample":
            current_samples.append((r["t"], r["az"], r.get("motor_active", 1.0)))
    if current_burst is not None and current_samples:
        segments.append(samples_to_segment(
            current_samples,
            speed=current_burst["speed"],
            angle=current_burst["angle"],
            cmd_times=current_burst["cmd_times"],
        ))
    return segments


def load_chirp_segment(path: Path) -> Segment:
    """Parse chirp JSONL into a single Segment covering the full duration."""
    recs = _load_jsonl(path)
    ts, azs, cmds, ma = [], [], [], []
    for r in recs:
        if r.get("kind") == "tick":
            ts.append(r["t"])
            azs.append(r["az"])
            # Use the recorded cmd signed velocity; not its integer speed.
            cmds.append(r.get("v_cmd_degs", cmd_speed_to_degs(r["speed"], r["angle"])))
            ma.append(1.0 if r["speed"] > 0 else 0.0)
    unwr = unwrap_az_series(azs)
    return Segment(
        ts=np.asarray(ts), azs_unwrapped=np.asarray(unwr),
        cmd_degs=np.asarray(cmds), motor_active=np.asarray(ma),
        speed=-1, angle=-1,
    )


def load_deadband_summary(path: Path) -> list[dict]:
    recs = _load_jsonl(path)
    return [r for r in recs if r.get("kind") == "step"]


def load_latency_summary(path: Path) -> dict:
    recs = _load_jsonl(path)
    rpc = [r["rpc_latency_s"] for r in recs if r.get("kind") == "trial"]
    mot = [r["motion_latency_s"] for r in recs
           if r.get("kind") == "trial" and r.get("motion_latency_s") is not None]
    return {"rpc_latencies": rpc, "motion_latencies": mot}


def _pct(xs, q):
    if not xs:
        return 0.0
    s = sorted(xs)
    i = max(0, min(len(s) - 1, int(q * len(s))))
    return s[i]


def find_latest(pattern: str) -> list[Path]:
    d = _sysid_dir()
    matches = sorted(d.glob(pattern))
    return matches


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fit-only", action="store_true",
                   help="Only print fit summary; skip latency/deadband tables.")
    args = p.parse_args()

    print("=" * 78)
    print("Phase 1 sysid report")
    print("=" * 78)

    # --- Load step response (training segments) ---
    step_files = find_latest("step_response_*.jsonl")
    training_segments: list[Segment] = []
    for f in step_files:
        segs = load_step_response_segments(f)
        training_segments.extend(segs)
        print(f"  step_response file: {f.name}  ({len(segs)} bursts)")
    if not training_segments:
        print("ERROR: no step_response data found under auto_level_logs/sysid/",
              file=sys.stderr)
        return 2
    print(f"  total training segments: {len(training_segments)}")
    print()

    # --- Trim segments to the active-burst window only.  Post-burst
    # decel/tracking-reengagement corrupts fits. We keep samples where the
    # motor is commanded active (or within 1s after last cmd expires).
    def trim(seg: Segment) -> Segment:
        # last cmd end = max(t_c + d) in cmd_times; we reconstruct via motor_active
        if np.any(seg.motor_active > 0):
            last_active_idx = int(np.max(np.where(seg.motor_active > 0)))
            stop = min(len(seg.ts), last_active_idx + 2)  # +1 post-sample
        else:
            stop = len(seg.ts)
        return Segment(
            ts=seg.ts[:stop],
            azs_unwrapped=seg.azs_unwrapped[:stop],
            cmd_degs=seg.cmd_degs[:stop],
            motor_active=seg.motor_active[:stop],
            speed=seg.speed, angle=seg.angle,
        )
    training_segments = [trim(s) for s in training_segments]

    # --- Fit each model ---
    models = {
        "zero_order":           ZeroOrderModel(),
        "first_order":          FirstOrderLagModel(),
        "first_order_ratelim":  FirstOrderRateLimitedModel(),
        "asym_first_order":     AsymmetricFirstOrderModel(),
    }
    fitted: dict[str, dict] = {}
    for name, m in models.items():
        try:
            m.fit(training_segments)
            score = score_segments(m, training_segments)
        except Exception as e:
            fitted[name] = {"error": repr(e)}
            continue
        fitted[name] = {"params": m.params_dict(), "train_score": score}

    # --- Chirp holdout ---
    chirp_files = find_latest("chirp_*.jsonl")
    chirp_score = {}
    if chirp_files:
        chirp_seg = load_chirp_segment(chirp_files[-1])
        print(f"  chirp holdout file: {chirp_files[-1].name}")
        for name, m in models.items():
            try:
                chirp_score[name] = score_segments(m, [chirp_seg])
            except Exception as e:
                chirp_score[name] = {"error": repr(e)}

    # --- Print model comparison ---
    print()
    print("Model comparison")
    print("-" * 78)
    header = f"  {'model':<22}  {'train_pos_rmse':>14}  {'train_rate_rmse':>14}  {'chirp_pos_rmse':>14}  {'params':<30}"
    print(header)
    for name in models.keys():
        f = fitted[name]
        if "error" in f:
            print(f"  {name:<22}  ERROR: {f['error']}")
            continue
        ts = f["train_score"]
        cs = chirp_score.get(name, {})
        chirp_txt = f"{cs['pos_rmse_deg']:>12.3f}°" if "pos_rmse_deg" in cs else "       —      "
        params_txt = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                               for k, v in f["params"].items() if k != "kind")
        print(
            f"  {name:<22}  "
            f"{ts['pos_rmse_deg']:>12.3f}°  "
            f"{ts['rate_rmse_degs']:>12.3f}°/s  "
            f"{chirp_txt:>14}  {params_txt}"
        )

    # --- Deadband / stiction table ---
    if not args.fit_only:
        print()
        db_files = find_latest("deadband_*.jsonl")
        if db_files:
            steps = load_deadband_summary(db_files[-1])
            print("Deadband (stiction) table (last run):")
            print(f"  {'angle':>5}  {'speed':>5}  {'mean_rate_degs':>14}  {'expected':>10}  {'ratio':>6}")
            for s in sorted(steps, key=lambda r: (r["angle"], r["speed"])):
                expected = (s["speed"] / SPEED_PER_DEG_PER_SEC) * (1 if s["angle"] == 0 else -1)
                ratio = s["mean_rate_degs"] / expected if abs(expected) > 1e-6 else 0.0
                print(f"  {s['angle']:>5}  {s['speed']:>5}  "
                      f"{s['mean_rate_degs']:>+12.3f}°/s  {expected:>+9.3f}  {ratio:>5.2f}")

        # --- Latency table ---
        print()
        lat_files = find_latest("latency_*.jsonl")
        if lat_files:
            lat = load_latency_summary(lat_files[-1])
            rpc, mot = lat["rpc_latencies"], lat["motion_latencies"]
            print("Latency (last run):")
            if rpc:
                print(f"  RPC ACK:  n={len(rpc)}  "
                      f"mean={1000*statistics.mean(rpc):.0f}ms  "
                      f"p50={1000*_pct(rpc, 0.5):.0f}ms  "
                      f"p90={1000*_pct(rpc, 0.9):.0f}ms  "
                      f"max={1000*max(rpc):.0f}ms")
            if mot:
                print(f"  motion-onset (post-ACK):  n={len(mot)}  "
                      f"mean={1000*statistics.mean(mot):.0f}ms  "
                      f"p50={1000*_pct(mot, 0.5):.0f}ms  "
                      f"p90={1000*_pct(mot, 0.9):.0f}ms  "
                      f"max={1000*max(mot):.0f}ms")

    print()
    print("(done)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
