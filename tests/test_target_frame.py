"""Tests for device.target_frame.MountFrame.

Synthetic-fixture driven: we construct ECEF points with analytically known
topocentric az/el and check that the MountFrame converts them correctly.
For rotated frames we verify that a uniform rotation between topo and mount
composes correctly.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from device.target_frame import MountFrame
from scripts.trajectory.observer import (
    lla_to_ecef,
)


def _offset_latlon(lat_deg: float, lon_deg: float, dnorth_m: float, deast_m: float):
    dlat = dnorth_m / 111320.0
    dlon = deast_m / (111320.0 * math.cos(math.radians(lat_deg)))
    return lat_deg + dlat, lon_deg + dlon


# --------------- identity-frame correctness --------------------------


def test_identity_observer_point_returns_zero_slant():
    mf = MountFrame.from_identity_enu()
    site = mf.site
    az, el, slant = mf.ecef_to_mount_azel(site.ecef_xyz)
    assert slant < 1e-3


def test_identity_due_east_km_gives_az_90():
    mf = MountFrame.from_identity_enu()
    site = mf.site
    lat, lon = _offset_latlon(site.lat_deg, site.lon_deg, 0.0, 1000.0)
    ecef = lla_to_ecef(lat, lon, site.alt_m)
    az, el, slant = mf.ecef_to_mount_azel(ecef)
    assert az == pytest.approx(90.0, abs=0.05)
    assert abs(el) < 1.0
    assert slant == pytest.approx(1000.0, rel=0.01)


def test_identity_overhead_el_90():
    mf = MountFrame.from_identity_enu()
    site = mf.site
    ecef = lla_to_ecef(site.lat_deg, site.lon_deg, site.alt_m + 5000.0)
    _az, el, slant = mf.ecef_to_mount_azel(ecef)
    assert el == pytest.approx(90.0, abs=1e-4)
    assert slant == pytest.approx(5000.0, abs=1.0)


# --------------- array form matches scalar form ---------------------


def test_array_form_matches_scalar_form():
    mf = MountFrame.from_identity_enu()
    site = mf.site
    pts = []
    for d_east in (-1000.0, 0.0, +1000.0, +3000.0):
        lat, lon = _offset_latlon(site.lat_deg, site.lon_deg, 500.0, d_east)
        pts.append(lla_to_ecef(lat, lon, site.alt_m + 2000.0))
    arr = np.array(pts)
    az_v, el_v, slant_v = mf.ecef_array_to_mount(arr)
    for i, p in enumerate(pts):
        az_s, el_s, slant_s = mf.ecef_to_mount_azel(p)
        assert az_v[i] == pytest.approx(az_s, abs=1e-6)
        assert el_v[i] == pytest.approx(el_s, abs=1e-6)
        assert slant_v[i] == pytest.approx(slant_s, abs=1e-6)


# --------------- Euler-rotation composition -------------------------


def test_pure_yaw_rotates_az():
    """A yaw=+30° rotation of the mount frame should rotate az by −30°.

    Interpretation: if the mount's 'az=0' is actually pointed 30° CCW from
    true north (yaw=+30° in ENU), then a target due north (topo az=0°) is
    seen by the mount at az=−30° ≡ 330°.
    """
    mf_id = MountFrame.from_identity_enu()
    mf_yaw = MountFrame.from_euler_deg(yaw_deg=30.0, pitch_deg=0.0, roll_deg=0.0)
    site = mf_id.site
    # Target 5 km due north, same altitude.
    lat, lon = _offset_latlon(site.lat_deg, site.lon_deg, 5000.0, 0.0)
    ecef = lla_to_ecef(lat, lon, site.alt_m)
    az_id, _el_id, _ = mf_id.ecef_to_mount_azel(ecef)
    az_y, _el_y, _ = mf_yaw.ecef_to_mount_azel(ecef)
    assert az_id == pytest.approx(0.0, abs=0.1) or az_id == pytest.approx(360.0, abs=0.1)
    # az_y should differ from az_id by approximately −30° (modulo 360).
    delta = ((az_y - az_id + 180.0) % 360.0) - 180.0
    assert delta == pytest.approx(-30.0, abs=0.2)


# --------------- trajectory derivatives ----------------------------


def test_trajectory_v_a_on_straight_flight():
    """A target flying east at 100 m/s 5 km north of observer, 3 km up.

    The topocentric rates are known from geometry and finite-diff smoothing
    on the generated samples should match within reasonable tolerance.
    """
    mf = MountFrame.from_identity_enu()
    site = mf.site
    duration_s = 120.0
    dt = 1.0
    n = int(duration_s / dt) + 1
    t = 1_700_000_000.0 + np.arange(n) * dt
    east = 100.0 * (t - t[0]) - 100.0 * duration_s / 2.0
    ecef_list = []
    for e in east:
        lat, lon = _offset_latlon(site.lat_deg, site.lon_deg, 5000.0, float(e))
        ecef_list.append(lla_to_ecef(lat, lon, site.alt_m + 3000.0))
    ecef_arr = np.array(ecef_list)
    traj = mf.ecef_traj_to_mount(ecef_arr, t)
    # At closest approach (midpoint): az-rate peaks at
    #   d(az)/dt = v_ground · north / (east² + north²)
    #            = 100 · 5000 / 5000²
    #            = 0.02 rad/s = 1.146 °/s
    # (altitude doesn't enter — az is a horizontal-plane angle).
    # Ignore edge ticks where np.gradient uses one-sided differences + the
    # smoothing kernel has reduced support.
    v_interior = traj["v_az_degs"][5:-5]
    peak_v_interior = float(np.max(np.abs(v_interior)))
    assert peak_v_interior == pytest.approx(1.146, abs=0.05)
    # az_cum should be monotonic (no ±180° jumps on this flight).
    dz = np.diff(traj["az_cum_deg"])
    assert np.all(dz >= 0) or np.all(dz <= 0)
    # Peak acceleration bounded (reasonable for this geometry).
    peak_a = float(np.max(np.abs(traj["a_az_degs2"][5:-5])))
    assert peak_a < 0.15


def test_trajectory_rejects_short_input():
    mf = MountFrame.from_identity_enu()
    with pytest.raises(ValueError):
        mf.ecef_traj_to_mount(np.zeros((3, 3)), np.zeros(3))


# --------------- SE(3) origin offset --------------------------------


def test_origin_offset_shifts_target_azel():
    """A 1 m ECEF translation of the mount origin must shift the computed
    azimuth of a nearby target by the expected amount.

    A target 1000 m due east of the nominal site, with the mount origin
    shifted 10 m *east* of the nominal site as well, should appear 990 m
    east of the mount origin — i.e. az still ~90°, but slant reduced by
    ~10 m.
    """
    mf0 = MountFrame.from_identity_enu()
    site = mf0.site
    # Build a 10 m east translation in ECEF. East unit vector in ECEF is
    # the first row of the ENU rotation (maps ECEF→ENU; its transpose maps
    # ENU→ECEF, so the east unit in ECEF is column 0 of enu_rotation.T =
    # row 0 of enu_rotation).
    east_ecef = site.enu_rotation[0]  # unit ECEF vector pointing east
    offset = 10.0 * east_ecef
    mf_shift = MountFrame.from_euler_deg(
        yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0,
        origin_offset_ecef_m=offset,
    )
    # Target ~1000 m due east of the *nominal* site.
    lat, lon = _offset_latlon(site.lat_deg, site.lon_deg, 0.0, 1000.0)
    ecef = lla_to_ecef(lat, lon, site.alt_m)
    _az0, _el0, slant0 = mf0.ecef_to_mount_azel(ecef)
    az1, el1, slant1 = mf_shift.ecef_to_mount_azel(ecef)
    # The 10 m east shift of the mount origin must reduce the apparent
    # slant by ~10 m (target is 10 m closer to the shifted origin).
    assert (slant0 - slant1) == pytest.approx(10.0, abs=0.1)
    assert az1 == pytest.approx(90.0, abs=0.05)
    assert abs(el1) < 1.0


def test_from_calibration_json_reads_translation(tmp_path):
    cal = {
        "yaw_offset_deg": 12.5,
        "origin_offset_ecef_m": [1.5, -0.7, 0.3],
    }
    p = tmp_path / "cal.json"
    p.write_text(__import__("json").dumps(cal))
    mf = MountFrame.from_calibration_json(p)
    assert np.allclose(mf.origin_offset_ecef_m, [1.5, -0.7, 0.3])


def test_from_calibration_json_honors_embedded_observer(tmp_path):
    """When the JSON carries an `observer` block and no explicit site
    is passed, the resulting MountFrame is anchored at the embedded
    lat/lon/alt — not the env-var default."""
    custom = {"lat_deg": 35.0, "lon_deg": -120.0, "alt_m": 500.0}
    cal = {
        "yaw_offset_deg": 0.0,
        "observer": custom,
    }
    p = tmp_path / "cal.json"
    p.write_text(__import__("json").dumps(cal))
    mf = MountFrame.from_calibration_json(p)
    assert mf.site.lat_deg == pytest.approx(35.0, abs=1e-9)
    assert mf.site.lon_deg == pytest.approx(-120.0, abs=1e-9)
    assert mf.site.alt_m == pytest.approx(500.0, abs=1e-9)


def test_from_calibration_json_explicit_site_wins_over_embedded(tmp_path):
    """Caller-supplied `site` overrides the embedded observer block."""
    from scripts.trajectory.observer import build_site
    cal = {
        "yaw_offset_deg": 0.0,
        "observer": {"lat_deg": 35.0, "lon_deg": -120.0, "alt_m": 500.0},
    }
    p = tmp_path / "cal.json"
    p.write_text(__import__("json").dumps(cal))
    site = build_site(lat_deg=40.0, lon_deg=-100.0, alt_m=1000.0)
    mf = MountFrame.from_calibration_json(p, site=site)
    assert mf.site.lat_deg == pytest.approx(40.0, abs=1e-9)


def test_default_origin_offset_is_zero_and_backward_compat():
    mf_id = MountFrame.from_identity_enu()
    mf_yaw = MountFrame.from_euler_deg(yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0)
    assert np.allclose(mf_id.origin_offset_ecef_m, 0.0)
    assert np.allclose(mf_yaw.origin_offset_ecef_m, 0.0)
    # Observer position should resolve to zero slant as before.
    az, el, slant = mf_id.ecef_to_mount_azel(mf_id.site.ecef_xyz)
    assert slant < 1e-3
