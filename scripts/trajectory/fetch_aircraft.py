"""Poll OpenSky Network (anonymous REST) for aircraft near the observer.

Writes one JSONL per qualifying aircraft track to an output directory.
Filters by slant range ≤ 20 km, altitude 1–40 kft, peak elevation ≤ 80°.
Tracks are resampled onto a 1 Hz grid via linear interpolation so
downstream replay can step at a uniform tick rate.

Anonymous OpenSky tolerates ~10 s cadence per IP; don't poll faster.
See https://opensky-network.org/apidoc/rest.html

Example:

    python -m scripts.trajectory.fetch_aircraft --duration-min 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

from scripts.trajectory.observer import (
    ObserverSite,
    build_site,
    ecef_array_to_topo,
    lla_to_ecef,
)


_OPENSKY_URL = "https://opensky-network.org/api/states/all"

_BBOX = {  # ~20 km around (33.96°N, -118.46°W)
    "lamin": 33.78, "lamax": 34.14,
    "lomin": -118.68, "lomax": -118.27,
}

# State-vector field indices per OpenSky API docs.
_FIELDS = [
    "icao24", "callsign", "origin_country", "time_position", "last_contact",
    "longitude", "latitude", "baro_altitude", "on_ground", "velocity",
    "true_track", "vertical_rate", "sensors", "geo_altitude", "squawk",
    "spi", "position_source",
]
_IDX = {name: i for i, name in enumerate(_FIELDS)}


# Filter thresholds.
MIN_ALT_M = 304.8      # 1 000 ft
MAX_ALT_M = 12192.0    # 40 000 ft
MAX_SLANT_M = 20000.0  # 20 km peak-slant requirement (target must come inside this at least once)
MAX_PEAK_EL_DEG = 80.0
MIN_TRACK_SAMPLES = 30
MIN_TRACK_DURATION_S = 60.0


@dataclass
class RawSample:
    t_unix: float
    lat: float
    lon: float
    alt_m: float
    velocity_mps: float | None
    heading_deg: float | None
    vertical_rate_mps: float | None


@dataclass
class AircraftTrack:
    icao24: str
    callsign: str
    samples: list[RawSample] = field(default_factory=list)


def poll_once(session: requests.Session, timeout: float = 20.0) -> list[list] | None:
    """Single /states/all query. Returns raw state-vector list or None on error."""
    try:
        r = session.get(_OPENSKY_URL, params=_BBOX, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"[fetch_aircraft] poll failed: {exc}", file=sys.stderr)
        return None
    try:
        data = r.json()
    except ValueError as exc:
        print(f"[fetch_aircraft] bad JSON: {exc}", file=sys.stderr)
        return None
    return data.get("states") or []


def extract_sample(sv: list) -> tuple[str, str, RawSample] | None:
    """Pull the useful fields out of one state-vector row, or None if unusable."""
    icao24 = sv[_IDX["icao24"]]
    if not icao24:
        return None
    if sv[_IDX["on_ground"]]:
        return None
    lat = sv[_IDX["latitude"]]
    lon = sv[_IDX["longitude"]]
    t = sv[_IDX["time_position"]]
    if lat is None or lon is None or t is None:
        return None
    # Prefer geo_altitude (GNSS, ~WGS84) over baro_altitude (pressure alt).
    alt = sv[_IDX["geo_altitude"]]
    if alt is None:
        alt = sv[_IDX["baro_altitude"]]
    if alt is None:
        return None
    callsign = (sv[_IDX["callsign"]] or "").strip()
    return icao24, callsign, RawSample(
        t_unix=float(t), lat=float(lat), lon=float(lon), alt_m=float(alt),
        velocity_mps=_opt_float(sv[_IDX["velocity"]]),
        heading_deg=_opt_float(sv[_IDX["true_track"]]),
        vertical_rate_mps=_opt_float(sv[_IDX["vertical_rate"]]),
    )


def _opt_float(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def collect(
    duration_min: float, poll_s: float = 10.0, session: requests.Session | None = None,
) -> dict[str, AircraftTrack]:
    if session is None:
        session = requests.Session()
    tracks: dict[str, AircraftTrack] = {}
    end_at = time.time() + duration_min * 60.0
    polls = 0
    while time.time() < end_at:
        poll_start = time.time()
        states = poll_once(session)
        polls += 1
        if states is not None:
            for sv in states:
                parsed = extract_sample(sv)
                if parsed is None:
                    continue
                icao24, callsign, sample = parsed
                track = tracks.get(icao24)
                if track is None:
                    track = AircraftTrack(icao24=icao24, callsign=callsign)
                    tracks[icao24] = track
                elif callsign and not track.callsign:
                    track.callsign = callsign
                # Dedupe by time_position.
                if track.samples and track.samples[-1].t_unix == sample.t_unix:
                    continue
                track.samples.append(sample)
        print(f"[fetch_aircraft] poll {polls}: {len(tracks)} aircraft seen, "
              f"{sum(len(t.samples) for t in tracks.values())} samples",
              file=sys.stderr)
        # Sleep to respect rate limits.
        elapsed = time.time() - poll_start
        sleep_for = max(0.0, poll_s - elapsed)
        remaining = end_at - time.time()
        if remaining <= 0:
            break
        time.sleep(min(sleep_for, remaining))
    # Keep samples sorted per track.
    for tr in tracks.values():
        tr.samples.sort(key=lambda s: s.t_unix)
    return tracks


def _track_ecef(samples: list[RawSample]) -> np.ndarray:
    out = np.empty((len(samples), 3))
    for i, s in enumerate(samples):
        out[i] = lla_to_ecef(s.lat, s.lon, s.alt_m)
    return out


def _resample_1hz(
    samples: list[RawSample],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (t_grid, lat, lon, alt_m, interpolated_mask) at 1 Hz."""
    ts = np.array([s.t_unix for s in samples])
    lats = np.array([s.lat for s in samples])
    lons = np.array([s.lon for s in samples])
    alts = np.array([s.alt_m for s in samples])
    t0 = float(np.floor(ts[0]))
    t1 = float(np.ceil(ts[-1]))
    t_grid = np.arange(t0, t1 + 1.0, 1.0)
    lat_g = np.interp(t_grid, ts, lats)
    lon_g = np.interp(t_grid, ts, lons)
    alt_g = np.interp(t_grid, ts, alts)
    # Flag any tick more than 1 s from the nearest raw sample as interpolated.
    nearest_gap = np.min(np.abs(t_grid[:, None] - ts[None, :]), axis=1)
    interp_mask = nearest_gap > 1.0
    return t_grid, lat_g, lon_g, alt_g, interp_mask


def qualify_and_export(
    track: AircraftTrack, site: ObserverSite, out_dir: Path,
) -> Path | None:
    if len(track.samples) < MIN_TRACK_SAMPLES:
        return _reject(track, "too few samples")
    span = track.samples[-1].t_unix - track.samples[0].t_unix
    if span < MIN_TRACK_DURATION_S:
        return _reject(track, f"span {span:.1f}s < {MIN_TRACK_DURATION_S}s")
    # Altitude filter (reject whole track if any sample is out of the band).
    alts = [s.alt_m for s in track.samples]
    if min(alts) < MIN_ALT_M or max(alts) > MAX_ALT_M:
        return _reject(
            track, f"altitude out of band [{min(alts):.0f}, {max(alts):.0f}] m")
    # Range / elevation filter: use raw samples for quick check.
    ecef_raw = _track_ecef(track.samples)
    _, el_raw, slant_raw = ecef_array_to_topo(ecef_raw, site)
    if float(np.min(slant_raw)) > MAX_SLANT_M:
        return _reject(track, f"min slant {np.min(slant_raw):.0f} m > {MAX_SLANT_M:.0f} m")
    if float(np.max(el_raw)) > MAX_PEAK_EL_DEG:
        return _reject(track, f"peak el {np.max(el_raw):.1f}° > {MAX_PEAK_EL_DEG}°")

    # Resample onto 1 Hz grid and recompute topocentric.
    t_grid, lat_g, lon_g, alt_g, interp_mask = _resample_1hz(track.samples)
    ecef_rs = np.empty((len(t_grid), 3))
    for i in range(len(t_grid)):
        ecef_rs[i] = lla_to_ecef(float(lat_g[i]), float(lon_g[i]), float(alt_g[i]))
    az_rs, el_rs, slant_rs = ecef_array_to_topo(ecef_rs, site)

    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = int(t_grid[0])
    safe_name = track.callsign.replace(" ", "").replace("/", "_") or track.icao24
    path = out_dir / f"{safe_name}_{track.icao24}_{t0}.jsonl"

    header = {
        "kind": "header",
        "source": "adsb",
        "id": track.icao24,
        "callsign": track.callsign,
        "observer_lat": site.lat_deg,
        "observer_lon": site.lon_deg,
        "observer_alt_m": site.alt_m,
        "duration_s": float(t_grid[-1] - t_grid[0]),
        "peak_el_deg": float(np.max(el_rs)),
        "min_el_deg": float(np.min(el_rs)),
        "min_slant_m": float(np.min(slant_rs)),
        "max_slant_m": float(np.max(slant_rs)),
        "sample_rate_hz": 1.0,
        "n_samples": int(len(t_grid)),
        "raw_sample_count": int(len(track.samples)),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for i in range(len(t_grid)):
            rec = {
                "kind": "sample",
                "t_unix": float(t_grid[i]),
                "ecef_x": float(ecef_rs[i, 0]),
                "ecef_y": float(ecef_rs[i, 1]),
                "ecef_z": float(ecef_rs[i, 2]),
                "lat": float(lat_g[i]),
                "lon": float(lon_g[i]),
                "alt_m": float(alt_g[i]),
                "az_deg": float(az_rs[i]),
                "el_deg": float(el_rs[i]),
                "slant_m": float(slant_rs[i]),
            }
            if interp_mask[i]:
                rec["interpolated"] = True
            f.write(json.dumps(rec) + "\n")
    print(
        f"[fetch_aircraft] wrote {path.name}  "
        f"peak_el={header['peak_el_deg']:.1f}°  "
        f"slant=[{header['min_slant_m']/1000:.1f},{header['max_slant_m']/1000:.1f}] km  "
        f"dur={header['duration_s']:.0f}s  raw={header['raw_sample_count']}",
        file=sys.stderr,
    )
    return path


def _reject(track: AircraftTrack, reason: str) -> None:
    print(
        f"[fetch_aircraft] reject {track.callsign or track.icao24}: {reason}",
        file=sys.stderr,
    )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-min", type=float, default=30.0)
    parser.add_argument("--poll-s", type=float, default=10.0)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("data/trajectories/aircraft"),
    )
    parser.add_argument("--top-n", type=int, default=5,
                        help="keep the N longest qualifying tracks")
    args = parser.parse_args(argv)

    site = build_site()
    print(
        f"[fetch_aircraft] observer {site.lat_deg:+.6f}, {site.lon_deg:+.6f}, "
        f"{site.alt_m:.0f} m — polling for {args.duration_min:.0f} min",
        file=sys.stderr,
    )
    tracks = collect(args.duration_min, poll_s=args.poll_s)
    print(f"[fetch_aircraft] collected {len(tracks)} candidate tracks",
          file=sys.stderr)

    # Sort by sample count descending; write until we have top_n exports.
    ordered = sorted(tracks.values(), key=lambda t: -len(t.samples))
    exported = 0
    for tr in ordered:
        path = qualify_and_export(tr, site, args.out_dir)
        if path is not None:
            exported += 1
            if exported >= args.top_n:
                break
    print(f"[fetch_aircraft] exported {exported} track(s) to {args.out_dir}",
          file=sys.stderr)
    return 0 if exported > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
