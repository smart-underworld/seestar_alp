"""Find bright satellite passes over the observer and export ECEF tracks.

Pulls TLEs from Celestrak (visual + stations groups), filters passes where
culmination altitude falls in [20°, 80°] and duration is at least 240 s,
samples each qualifying pass at 2 Hz, and writes a JSONL per pass.

ECEF is derived via skyfield's ITRS frame (`sat.at(t).frame_xyz(itrs).m`),
which is earth-fixed. Do NOT use `.position.km` — that is GCRS/ECI and
rotates relative to the earth by ~465 m/s at the equator.

Example:

    python -m scripts.trajectory.fetch_satellites --hours 24 --top-n 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from skyfield.api import Loader, wgs84
from skyfield.framelib import itrs

from scripts.trajectory.observer import (
    build_site,
    ecef_array_to_topo,
)


CELESTRAK_GROUPS = {
    "visual": "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle",
    "stations": "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
}

# Pass filter parameters (can be overridden on CLI).
MIN_CULM_EL_DEG = 20.0
MAX_CULM_EL_DEG = 80.0
MIN_PASS_DURATION_S = 240.0
MIN_EL_DEG_FOR_PASS = 10.0  # rise/set threshold for find_events


@dataclass
class Pass:
    satellite_name: str
    norad_id: str
    tle_line1: str
    tle_line2: str
    t_rise_unix: float
    t_culm_unix: float
    t_set_unix: float
    culm_el_deg: float


def _loader() -> Loader:
    cache_dir = Path(
        os.environ.get("SKYFIELD_CACHE", Path.home() / ".skyfield-data")
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    return Loader(str(cache_dir))


def load_tles(load: Loader) -> list:
    sats: list = []
    seen_norad: set[str] = set()
    for group, url in CELESTRAK_GROUPS.items():
        try:
            group_sats = load.tle_file(url, reload=False)
        except Exception as exc:  # skyfield may raise HTTP / parse errors
            print(f"[fetch_satellites] failed to load {group}: {exc}",
                  file=sys.stderr)
            continue
        for sat in group_sats:
            norad = str(sat.model.satnum)
            if norad in seen_norad:
                continue
            seen_norad.add(norad)
            sats.append(sat)
        print(f"[fetch_satellites] loaded {len(group_sats)} sats from {group}",
              file=sys.stderr)
    return sats


def find_passes(
    sat, observer, ts, t0, t1,
) -> list[Pass]:
    """Group find_events output into (rise, culm, set) triplets."""
    try:
        times, flags = sat.find_events(
            observer, t0, t1, altitude_degrees=MIN_EL_DEG_FOR_PASS,
        )
    except Exception as exc:
        print(f"[fetch_satellites] find_events failed for {sat.name}: {exc}",
              file=sys.stderr)
        return []

    passes: list[Pass] = []
    i = 0
    while i + 2 < len(flags):
        if flags[i] == 0 and flags[i + 1] == 1 and flags[i + 2] == 2:
            t_rise = times[i]
            t_culm = times[i + 1]
            t_set = times[i + 2]
            # Peak elevation at culmination.
            alt, _az, _dist = (sat - observer).at(t_culm).altaz()
            passes.append(Pass(
                satellite_name=sat.name,
                norad_id=str(sat.model.satnum),
                tle_line1=sat.tle_line1 if hasattr(sat, "tle_line1") else "",
                tle_line2=sat.tle_line2 if hasattr(sat, "tle_line2") else "",
                t_rise_unix=t_rise.utc_datetime().timestamp(),
                t_culm_unix=t_culm.utc_datetime().timestamp(),
                t_set_unix=t_set.utc_datetime().timestamp(),
                culm_el_deg=float(alt.degrees),
            ))
            i += 3
        else:
            i += 1
    return passes


def _pick_tle_lines(sat) -> tuple[str, str]:
    # Skyfield stores TLE lines on the EarthSatellite object when loaded via
    # tle_file. Fall back to reconstruction from the SGP4 model if needed.
    l1 = getattr(sat, "_line1", None) or getattr(sat, "tle_line1", None)
    l2 = getattr(sat, "_line2", None) or getattr(sat, "tle_line2", None)
    if l1 and l2:
        return str(l1), str(l2)
    # Fallback — don't block export; just record empty TLE in header.
    return "", ""


def export_pass(
    p: Pass, sat, site, load, out_dir: Path, sample_hz: float,
) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    dt = 1.0 / sample_hz
    t_grid = np.arange(p.t_rise_unix, p.t_set_unix + dt, dt)
    ts_scale = load.timescale()
    ecef = np.empty((len(t_grid), 3))
    for i, t_unix in enumerate(t_grid):
        t = ts_scale.from_datetime(
            datetime.fromtimestamp(float(t_unix), tz=timezone.utc)
        )
        ecef[i] = sat.at(t).frame_xyz(itrs).m
    az, el, slant = ecef_array_to_topo(ecef, site)

    safe_name = "".join(
        c if c.isalnum() else "_" for c in p.satellite_name.strip()
    ).strip("_") or f"norad{p.norad_id}"
    t0 = int(t_grid[0])
    path = out_dir / f"{safe_name}_{p.norad_id}_{t0}.jsonl"

    l1, l2 = _pick_tle_lines(sat)
    header = {
        "kind": "header",
        "source": "tle",
        "id": p.norad_id,
        "name": p.satellite_name,
        "observer_lat": site.lat_deg,
        "observer_lon": site.lon_deg,
        "observer_alt_m": site.alt_m,
        "duration_s": float(t_grid[-1] - t_grid[0]),
        "peak_el_deg": float(np.max(el)),
        "culm_el_deg": p.culm_el_deg,
        "min_slant_m": float(np.min(slant)),
        "max_slant_m": float(np.max(slant)),
        "sample_rate_hz": sample_hz,
        "n_samples": int(len(t_grid)),
        "tle": [l1, l2] if l1 else [],
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for i in range(len(t_grid)):
            rec = {
                "kind": "sample",
                "t_unix": float(t_grid[i]),
                "ecef_x": float(ecef[i, 0]),
                "ecef_y": float(ecef[i, 1]),
                "ecef_z": float(ecef[i, 2]),
                "az_deg": float(az[i]),
                "el_deg": float(el[i]),
                "slant_m": float(slant[i]),
            }
            f.write(json.dumps(rec) + "\n")
    print(
        f"[fetch_satellites] wrote {path.name}  "
        f"peak_el={header['peak_el_deg']:.1f}°  "
        f"dur={header['duration_s']:.0f}s  "
        f"slant=[{header['min_slant_m']/1000:.0f},{header['max_slant_m']/1000:.0f}] km",
        file=sys.stderr,
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24.0,
                        help="look-ahead window starting now (UTC)")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("data/trajectories/satellites"),
    )
    parser.add_argument("--top-n", type=int, default=5,
                        help="max passes to export, ranked by culm elevation")
    parser.add_argument("--sample-hz", type=float, default=2.0)
    args = parser.parse_args(argv)

    site = build_site()
    load = _loader()
    ts = load.timescale()

    sats = load_tles(load)
    if not sats:
        print("[fetch_satellites] no satellites loaded, aborting", file=sys.stderr)
        return 2

    observer = wgs84.latlon(
        latitude_degrees=site.lat_deg,
        longitude_degrees=site.lon_deg,
        elevation_m=site.alt_m,
    )

    now = time.time()
    t0 = ts.from_datetime(datetime.fromtimestamp(now, tz=timezone.utc))
    t1 = ts.from_datetime(
        datetime.fromtimestamp(now + args.hours * 3600.0, tz=timezone.utc)
    )
    print(f"[fetch_satellites] scanning {len(sats)} sats over {args.hours} h",
          file=sys.stderr)

    candidates: list[tuple[Pass, object]] = []
    for sat in sats:
        for p in find_passes(sat, observer, ts, t0, t1):
            duration = p.t_set_unix - p.t_rise_unix
            if duration < MIN_PASS_DURATION_S:
                continue
            if not (MIN_CULM_EL_DEG <= p.culm_el_deg <= MAX_CULM_EL_DEG):
                continue
            candidates.append((p, sat))

    print(f"[fetch_satellites] {len(candidates)} candidate passes match filter",
          file=sys.stderr)

    # Rank by culmination elevation descending (more interesting test cases),
    # but bias toward variety: dedupe by satellite name so we don't dump 5 ISS
    # passes.
    candidates.sort(key=lambda pair: -pair[0].culm_el_deg)
    picked: list[tuple[Pass, object]] = []
    seen_names: set[str] = set()
    for p, sat in candidates:
        if p.satellite_name in seen_names:
            continue
        seen_names.add(p.satellite_name)
        picked.append((p, sat))
        if len(picked) >= args.top_n:
            break

    exported = 0
    for p, sat in picked:
        if export_pass(p, sat, site, load, args.out_dir, args.sample_hz):
            exported += 1
    print(f"[fetch_satellites] exported {exported} pass(es) to {args.out_dir}",
          file=sys.stderr)
    return 0 if exported > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
