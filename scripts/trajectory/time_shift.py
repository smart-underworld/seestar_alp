"""Time-shift a trajectory JSONL so it 'starts now' (or at a given unix time).

For hardware tracking tests we don't care that Tiangong is actually flying
over right now — we care that the mount can faithfully follow the shape
of an LEO trajectory. Shifting all `t_unix` values by a constant delta
preserves the (az, el) shape exactly (ECEF is earth-fixed), so the mount
sees the same angular-rate profile it would during the real pass.

Usage:

    python -m scripts.trajectory.time_shift INPUT.jsonl OUTPUT.jsonl
    python -m scripts.trajectory.time_shift INPUT.jsonl OUTPUT.jsonl \\
        --start-at-unix 1776500000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--start-at-unix", type=float, default=None,
        help="New t_unix for the first sample (defaults to now + 5s)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 2

    header = None
    samples: list[dict] = []
    with args.input.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("kind") == "header":
                header = rec
            elif rec.get("kind") == "sample":
                samples.append(rec)
    if header is None or not samples:
        print("input missing header or samples", file=sys.stderr)
        return 2

    t_old_start = float(samples[0]["t_unix"])
    target_start = args.start_at_unix if args.start_at_unix is not None else time.time() + 5.0
    shift = target_start - t_old_start

    header = dict(header)
    header["t_shift_s"] = shift
    header["original_t_start"] = t_old_start

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for s in samples:
            s = dict(s)
            s["t_unix"] = float(s["t_unix"]) + shift
            f.write(json.dumps(s) + "\n")

    dur = samples[-1]["t_unix"] - samples[0]["t_unix"]
    print(
        f"[time_shift] wrote {args.output}\n"
        f"  original start: {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(t_old_start))}\n"
        f"  shifted  start: {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(target_start))}\n"
        f"  shift: {shift:+.0f} s ({shift/3600:+.2f} h)\n"
        f"  duration: {dur:.0f} s",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
