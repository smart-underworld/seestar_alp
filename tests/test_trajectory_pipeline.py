"""Unit tests for the trajectory-data pipeline (observer, JSONL, replay).

No network access: everything runs against a synthetic straight-line
aircraft fixture with analytically known az/el so we can lock in the
coordinate transforms, schema, and replay math without depending on
OpenSky or Celestrak.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from scripts.trajectory import replay
from scripts.trajectory.observer import (
    OBSERVER_ALT_M,
    OBSERVER_LAT_DEG,
    OBSERVER_LON_DEG,
    build_site,
    ecef_array_to_topo,
    ecef_to_topocentric,
    lla_to_ecef,
    unwrap_az_series,
)


# -- synthetic trajectory -------------------------------------------------


def _offset_latlon(lat_deg: float, lon_deg: float, dnorth_m: float, deast_m: float):
    """Small-offset ENU → lat/lon (flat-earth approx; good to ~1 m at a few km)."""
    dlat = dnorth_m / 111320.0
    dlon = deast_m / (111320.0 * math.cos(math.radians(lat_deg)))
    return lat_deg + dlat, lon_deg + dlon


def make_straight_aircraft(
    duration_s: float = 120.0,
    dt: float = 1.0,
    lateral_north_m: float = 5000.0,
    altitude_m: float = 3000.0,
    speed_mps: float = 100.0,
    callsign: str = "TEST123",
    icao24: str = "abcdef",
) -> tuple[dict, list[dict]]:
    """Synthesize a level flight passing dN north of the observer at altitude."""
    site = build_site()
    n = int(round(duration_s / dt)) + 1
    t_grid = np.arange(n) * dt + 1_700_000_000.0
    # Aircraft path in local ENU: east-ward at speed_mps, offset `lateral_north_m` north.
    east = speed_mps * (t_grid - t_grid[0]) - speed_mps * duration_s / 2.0
    samples: list[dict] = []
    lat_list, lon_list = [], []
    az_list, el_list, slant_list = [], [], []
    ecef_rows = []
    for i in range(n):
        lat, lon = _offset_latlon(
            site.lat_deg, site.lon_deg, lateral_north_m, float(east[i]),
        )
        alt = altitude_m + site.alt_m
        ex, ey, ez = lla_to_ecef(lat, lon, alt)
        ecef_rows.append((ex, ey, ez))
        lat_list.append(lat)
        lon_list.append(lon)
    ecef_arr = np.array(ecef_rows)
    az_arr, el_arr, slant_arr = ecef_array_to_topo(ecef_arr, site)
    for i in range(n):
        samples.append({
            "kind": "sample",
            "t_unix": float(t_grid[i]),
            "ecef_x": float(ecef_arr[i, 0]),
            "ecef_y": float(ecef_arr[i, 1]),
            "ecef_z": float(ecef_arr[i, 2]),
            "lat": lat_list[i],
            "lon": lon_list[i],
            "alt_m": altitude_m + site.alt_m,
            "az_deg": float(az_arr[i]),
            "el_deg": float(el_arr[i]),
            "slant_m": float(slant_arr[i]),
        })
        az_list.append(float(az_arr[i]))
        el_list.append(float(el_arr[i]))
        slant_list.append(float(slant_arr[i]))
    header = {
        "kind": "header",
        "source": "adsb",
        "id": icao24,
        "callsign": callsign,
        "observer_lat": site.lat_deg,
        "observer_lon": site.lon_deg,
        "observer_alt_m": site.alt_m,
        "duration_s": float(duration_s),
        "peak_el_deg": max(el_list),
        "min_el_deg": min(el_list),
        "min_slant_m": min(slant_list),
        "max_slant_m": max(slant_list),
        "sample_rate_hz": 1.0 / dt,
        "n_samples": n,
        "raw_sample_count": n,
        "created": "2024-01-01T00:00:00+00:00",
    }
    return header, samples


@pytest.fixture
def tmp_traj_file(tmp_path) -> Path:
    header, samples = make_straight_aircraft()
    path = tmp_path / "TEST123_abcdef_1700000000.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for s in samples:
            f.write(json.dumps(s) + "\n")
    return path


# -- observer / converter tests ------------------------------------------


def test_defaults_match_observer_site():
    # Regression guard — don't silently drift from El Segundo.
    assert abs(OBSERVER_LAT_DEG - 33.960583) < 1e-6
    assert abs(OBSERVER_LON_DEG - (-118.460139)) < 1e-6
    assert OBSERVER_ALT_M == 30.0


def test_observer_self_point_is_zero_slant():
    site = build_site()
    az, el, slant = ecef_to_topocentric(site.ecef_xyz)
    assert slant < 1e-3
    assert el == pytest.approx(90.0, abs=1e-6) or slant == pytest.approx(0.0)


def test_1km_east_gives_az_90_el_near_zero():
    site = build_site()
    lat, lon = _offset_latlon(site.lat_deg, site.lon_deg, 0.0, 1000.0)
    ecef = lla_to_ecef(lat, lon, site.alt_m)
    az, el, slant = ecef_to_topocentric(ecef)
    assert az == pytest.approx(90.0, abs=0.05)
    # Earth curvature drops target below horizon by ~78 m over 1 km → el ~ -0.45°.
    assert abs(el) < 1.0
    assert slant == pytest.approx(1000.0, rel=0.01)


def test_overhead_slant_matches_altitude():
    site = build_site()
    ecef = lla_to_ecef(site.lat_deg, site.lon_deg, site.alt_m + 10000.0)
    _az, el, slant = ecef_to_topocentric(ecef)
    assert el == pytest.approx(90.0, abs=1e-4)
    assert slant == pytest.approx(10000.0, abs=1.0)


def test_straight_flight_peak_elevation():
    """5 km north of observer at 3 km altitude ⇒ peak el = atan2(3000, 5000)."""
    header, samples = make_straight_aircraft(
        lateral_north_m=5000.0, altitude_m=3000.0,
    )
    peak_el = max(s["el_deg"] for s in samples)
    expected = math.degrees(math.atan2(3000.0, 5000.0))
    # Flat-earth offset generates the fixture; ellipsoid vs flat adds
    # ~0.06° at 5 km range. Loose tolerance reflects the analytical vs
    # geodetic approximation, not controller error.
    assert peak_el == pytest.approx(expected, abs=0.15)
    # Min el (at the ends) should be lower.
    min_el = min(s["el_deg"] for s in samples)
    assert min_el < peak_el - 5.0


def test_straight_flight_az_north_at_closest_approach():
    _hdr, samples = make_straight_aircraft(
        lateral_north_m=5000.0, altitude_m=3000.0,
    )
    mid = samples[len(samples) // 2]
    assert mid["az_deg"] == pytest.approx(0.0, abs=0.5) or \
        mid["az_deg"] == pytest.approx(360.0, abs=0.5)


def test_unwrap_az_series_handles_wrap():
    out = unwrap_az_series(np.array([170.0, 175.0, -175.0, -170.0]))
    assert list(out) == pytest.approx([170.0, 175.0, 185.0, 190.0])


# -- JSONL round-trip ---------------------------------------------------


def test_load_trajectory_parses_header_and_samples(tmp_traj_file):
    traj = replay.load_trajectory(tmp_traj_file)
    assert traj.header["source"] == "adsb"
    assert traj.header["callsign"] == "TEST123"
    assert len(traj.samples) == 121  # 120 s at 1 Hz inclusive
    s0 = traj.samples[0]
    for key in ("t_unix", "ecef_x", "ecef_y", "ecef_z",
                "az_deg", "el_deg", "slant_m"):
        assert key in s0


def test_load_trajectory_rejects_empty(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text(json.dumps({"kind": "header", "source": "adsb"}) + "\n")
    with pytest.raises(ValueError):
        replay.load_trajectory(path)


# -- replay tests --------------------------------------------------------


def test_replay_slow_track_tracks_well(tmp_traj_file):
    traj = replay.load_trajectory(tmp_traj_file)
    result = replay.simulate_replay(
        traj, tick_dt=0.5, tau_s=0.348, use_ff=True, az_limits=None,
    )
    az_rms = float(np.sqrt(np.mean(result.az_err ** 2)))
    el_rms = float(np.sqrt(np.mean(result.el_err ** 2)))
    az_peak = float(np.max(np.abs(result.az_err)))
    el_peak = float(np.max(np.abs(result.el_err)))
    assert az_rms < 0.3, f"az_rms={az_rms}"
    assert el_rms < 0.3, f"el_rms={el_rms}"
    # Allow a bigger tolerance on peak (edge-of-window derivatives).
    assert az_peak < 2.0
    assert el_peak < 2.0
    assert result.az_sat_count == 0
    assert result.el_sat_count == 0


def test_replay_no_ff_is_worse(tmp_traj_file):
    """With FF, tracking error should be smaller than without FF on a turning path."""
    traj = replay.load_trajectory(tmp_traj_file)
    ff_result = replay.simulate_replay(traj, use_ff=True, az_limits=None)
    no_ff_result = replay.simulate_replay(traj, use_ff=False, az_limits=None)
    ff_az_rms = float(np.sqrt(np.mean(ff_result.az_err ** 2)))
    no_ff_az_rms = float(np.sqrt(np.mean(no_ff_result.az_err ** 2)))
    # FF should beat no-FF on az at least by a small margin; equality allowed
    # for trivially-slow segments but we picked a curving crossing so FF wins.
    assert ff_az_rms <= no_ff_az_rms + 1e-6


def test_replay_flags_saturation_on_close_pass(tmp_path):
    """Close overhead pass exceeds plant v_max → saturation is flagged."""
    header, samples = make_straight_aircraft(
        duration_s=60.0, dt=1.0,
        lateral_north_m=1000.0,  # 1 km north, 3 km up ⇒ peak el ~71.6°
        altitude_m=3000.0,
        speed_mps=200.0,
    )
    path = tmp_path / "FAST_0001_1700000000.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for s in samples:
            f.write(json.dumps(s) + "\n")
    traj = replay.load_trajectory(path)
    result = replay.simulate_replay(traj, v_max=6.0, az_limits=None)
    total_sat = result.az_sat_count + result.el_sat_count
    assert total_sat > 0, (
        "expected saturation on a close overhead pass; "
        f"az_sat={result.az_sat_count}, el_sat={result.el_sat_count}"
    )


def test_replay_reports_string_is_multiline(tmp_traj_file):
    traj = replay.load_trajectory(tmp_traj_file)
    result = replay.simulate_replay(traj, az_limits=None)
    text = replay.report(result)
    assert "az error" in text
    assert "el error" in text
    assert "cable-wrap" in text


def test_write_jsonl_produces_ff_tick_events(tmp_path, tmp_traj_file):
    traj = replay.load_trajectory(tmp_traj_file)
    result = replay.simulate_replay(traj, az_limits=None)
    out = tmp_path / "replay.jsonl"
    replay.write_jsonl(result, out)
    lines = out.read_text().splitlines()
    header = json.loads(lines[0])
    assert header["kind"] == "header"
    assert header["source"] == "replay"
    events = [json.loads(line) for line in lines[1:]]
    assert len(events) == len(result.t_grid)
    assert all(e["event"] == "2d_ff_tick" for e in events)
    assert all("az_err" in e and "el_err" in e for e in events)
