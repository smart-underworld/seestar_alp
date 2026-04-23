"""Rank satellite trajectories by mechanical tracking feasibility.

Walks `data/trajectories/satellites/*.jsonl`, builds a JsonlECEFProvider
+ identity MountFrame for each, runs the StreamingFFController pre-check
and the offline replay simulator, and prints a ranked table.

Scoring (higher = better):
- Feasibility (must be True): cable-wrap OK, el within usable band,
  zero FF saturation.
- `replay.simulate_replay` RMS + peak tracking error below thresholds.
- Prefers passes with peak elevation near 60° (mid-sky — less extreme
  angular rates near zenith, and easier to keep inside el_max).
- Prefers longer passes (more useful flight time for test data).

Tiangong / CSS passes are pinned to the top of the recommendation regardless
of score (user requirement).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from device.plant_limits import AzimuthLimits
from device.reference_provider import JsonlECEFProvider
from device.streaming_controller import pre_check
from device.target_frame import MountFrame
from scripts.trajectory import replay


DEFAULT_DIR = Path("data/trajectories/satellites")


@dataclass
class TargetReport:
    path: Path
    name: str
    duration_s: float
    peak_el_deg: float
    peak_v_az_degs: float
    peak_v_el_degs: float
    peak_a_az_degs2: float
    peak_a_el_degs2: float
    cable_violations: int
    el_violations: int
    v_sat_ticks: int
    az_err_rms: float
    az_err_peak: float
    el_err_rms: float
    el_err_peak: float
    feasible: bool
    score: float
    tle_pinned: bool
    notes: list[str]

    def summary(self) -> str:
        tag = "★" if self.tle_pinned else ("✓" if self.feasible else "✗")
        return (
            f"{tag} {self.name:<30} "
            f"dur={self.duration_s:>5.0f}s "
            f"peak_el={self.peak_el_deg:>5.1f}° "
            f"peak_v_az={self.peak_v_az_degs:>4.2f}°/s "
            f"peak_v_el={self.peak_v_el_degs:>4.2f}°/s "
            f"az_err_rms={self.az_err_rms:>4.2f}° "
            f"el_err_rms={self.el_err_rms:>4.2f}° "
            f"score={self.score:>5.2f}"
        )


def _evaluate(path: Path, mount_frame: MountFrame) -> TargetReport:
    provider = JsonlECEFProvider(path, mount_frame)
    az_limits = AzimuthLimits.load()
    pre = pre_check(
        provider, az_limits=az_limits, el_max_deg=85.0, el_min_deg=-85.0,
    )
    traj = replay.load_trajectory(path)
    sim = replay.simulate_replay(
        traj, az_limits=az_limits, mount_frame=mount_frame,
    )
    header = provider.header
    peak_el_deg = float(header.get("peak_el_deg", pre.max_el_deg))
    name = header.get("name") or header.get("callsign") or header.get("id") or path.stem
    duration_s = float(header.get("duration_s", 0.0))

    az_rms = float(np.sqrt(np.mean(sim.az_err ** 2)))
    az_peak = float(np.max(np.abs(sim.az_err)))
    el_rms = float(np.sqrt(np.mean(sim.el_err ** 2)))
    el_peak = float(np.max(np.abs(sim.el_err)))

    # Score: feasible weight (largest), then track-error penalty, then
    # mid-sky bonus (peak_el closest to 60°), then duration bonus.
    if pre.feasible and sim.az_sat_count == 0 and sim.el_sat_count == 0:
        score = 100.0
    else:
        score = 0.0
    score -= 20.0 * az_rms
    score -= 20.0 * el_rms
    score -= abs(peak_el_deg - 60.0) * 0.2
    score += min(duration_s / 60.0, 10.0) * 1.0

    # Pin Tiangong / CSS passes to the top.
    tle_pinned = "TIANHE" in name.upper() or "CSS" in name.upper() or "TIANGONG" in name.upper()
    if tle_pinned:
        score += 1000.0

    notes = list(pre.notes)
    if sim.az_sat_count or sim.el_sat_count:
        notes.append(
            f"replay saturation: az={sim.az_sat_count} el={sim.el_sat_count}"
        )

    return TargetReport(
        path=path, name=str(name), duration_s=duration_s,
        peak_el_deg=peak_el_deg,
        peak_v_az_degs=pre.peak_v_az_degs,
        peak_v_el_degs=pre.peak_v_el_degs,
        peak_a_az_degs2=pre.peak_a_az_degs2,
        peak_a_el_degs2=pre.peak_a_el_degs2,
        cable_violations=pre.cable_wrap_violations,
        el_violations=pre.el_limit_violations,
        v_sat_ticks=pre.v_saturation_ticks,
        az_err_rms=az_rms, az_err_peak=az_peak,
        el_err_rms=el_rms, el_err_peak=el_peak,
        feasible=pre.feasible and sim.az_sat_count == 0 and sim.el_sat_count == 0,
        score=score,
        tle_pinned=tle_pinned,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir", type=Path, default=DEFAULT_DIR,
        help="Directory containing *.jsonl satellite passes",
    )
    parser.add_argument("--top", type=int, default=5,
                        help="Number of top targets to highlight")
    parser.add_argument("--json", type=Path, default=None,
                        help="Optional path to write structured ranking JSON")
    args = parser.parse_args(argv)

    jsonl_paths = sorted(args.dir.glob("*.jsonl"))
    if not jsonl_paths:
        print(f"no JSONL files found in {args.dir}")
        return 2
    mount_frame = MountFrame.from_identity_enu()

    reports: list[TargetReport] = []
    for p in jsonl_paths:
        try:
            reports.append(_evaluate(p, mount_frame))
        except Exception as exc:
            print(f"[skip] {p.name}: {exc}")
    if not reports:
        print("no targets could be evaluated")
        return 2

    reports.sort(key=lambda r: -r.score)

    print(f"\n{'─'*120}")
    print(f"Ranked targets ({len(reports)} total, top {args.top} shown):")
    print(f"{'─'*120}")
    for r in reports[: args.top]:
        print(r.summary())
        for note in r.notes:
            print(f"    ⚠ {note}")
        print(f"    file: {r.path.name}")

    print(f"\n{'─'*120}")
    print("All feasible targets:")
    print(f"{'─'*120}")
    for r in reports:
        marker = "★" if r.tle_pinned else ("✓" if r.feasible else "✗")
        print(f"  {marker} {r.name:<30} score={r.score:>7.2f}  file={r.path.name}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        with args.json.open("w", encoding="utf-8") as f:
            json.dump([{
                "path": str(r.path), "name": r.name,
                "duration_s": r.duration_s, "peak_el_deg": r.peak_el_deg,
                "peak_v_az_degs": r.peak_v_az_degs,
                "peak_v_el_degs": r.peak_v_el_degs,
                "az_err_rms": r.az_err_rms, "el_err_rms": r.el_err_rms,
                "cable_violations": r.cable_violations,
                "el_violations": r.el_violations,
                "v_saturation_ticks": r.v_sat_ticks,
                "feasible": r.feasible, "tle_pinned": r.tle_pinned,
                "score": r.score, "notes": r.notes,
            } for r in reports], f, indent=2)
        print(f"\n→ wrote ranking to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
