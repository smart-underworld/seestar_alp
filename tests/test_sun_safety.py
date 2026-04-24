"""Tests for device.sun_safety pure helpers (Phase 1).

Monitor-thread / jog-angle behavior is covered in a follow-up file once
those are added. These tests deliberately pin lat/lon and time so the
ephem path is deterministic and runs the same anywhere.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from device.sun_safety import (
    DEFAULT_ALT_THRESHOLD_DEG,
    SafetyTrip,
    angular_separation,
    compute_sun_altaz,
    is_sun_safe,
)


# El Segundo, CA — matches the user's site (also config.toml defaults).
SITE_LAT = 33.96
SITE_LON = -118.46


# --- angular_separation ---------------------------------------------------


def test_separation_identical_is_zero():
    assert angular_separation(123.0, 45.0, 123.0, 45.0) == pytest.approx(0.0)


def test_separation_quarter_turn_in_az_at_horizon():
    assert angular_separation(0.0, 0.0, 90.0, 0.0) == pytest.approx(90.0)


def test_separation_antipodal_horizons():
    # (0,0) and (180,0) lie on opposite sides of the horizon ring.
    assert angular_separation(0.0, 0.0, 180.0, 0.0) == pytest.approx(180.0)


def test_separation_same_az_pure_elevation():
    assert angular_separation(45.0, 10.0, 45.0, 40.0) == pytest.approx(30.0)


def test_separation_zenith_to_horizon_is_90():
    # +el=90 is the zenith, irrespective of azimuth.
    assert angular_separation(0.0, 90.0, 273.0, 0.0) == pytest.approx(90.0)


def test_separation_handles_az_wraparound():
    # 350° and 10° are 20° apart on the unit circle.
    assert angular_separation(350.0, 0.0, 10.0, 0.0) == pytest.approx(20.0)


def test_separation_clamps_floating_point_overflow():
    # Should not raise on a near-identical pointing where naive cos can
    # exceed 1.0 by FP rounding.
    sep = angular_separation(12.345678, 67.890123, 12.345678, 67.890123)
    assert math.isfinite(sep)
    assert sep == pytest.approx(0.0, abs=1e-9)


# --- compute_sun_altaz ----------------------------------------------------


def test_sun_below_horizon_at_local_midnight():
    # 09:00 UTC at lon -118.46 ≈ 01:00 local Pacific Standard Time.
    when = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    _, alt = compute_sun_altaz(lat_deg=SITE_LAT, lon_deg=SITE_LON, when=when)
    assert alt < DEFAULT_ALT_THRESHOLD_DEG


def test_sun_above_horizon_at_local_noon():
    # 20:00 UTC at lon -118.46 ≈ 12:00 local Pacific Standard Time.
    when = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
    _, alt = compute_sun_altaz(lat_deg=SITE_LAT, lon_deg=SITE_LON, when=when)
    assert alt > 25.0  # winter sun in LA at noon ~ 33° — give margin


def test_sun_altitude_consistent_across_naive_and_aware():
    naive = datetime(2026, 6, 21, 20, 0)
    aware = naive.replace(tzinfo=timezone.utc)
    a = compute_sun_altaz(lat_deg=SITE_LAT, lon_deg=SITE_LON, when=naive)
    b = compute_sun_altaz(lat_deg=SITE_LAT, lon_deg=SITE_LON, when=aware)
    assert a[0] == pytest.approx(b[0], abs=1e-6)
    assert a[1] == pytest.approx(b[1], abs=1e-6)


# --- is_sun_safe ----------------------------------------------------------


def _midnight_utc():
    return datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def _noon_utc():
    return datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)


def test_is_safe_when_sun_below_threshold_for_any_pointing():
    # Even pointing straight at where the sun will be at noon must be
    # safe at midnight, because the sun is below -10°.
    safe, reason = is_sun_safe(
        180.0, 33.0,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_midnight_utc(),
    )
    assert safe is True
    assert reason == ""


def test_is_unsafe_when_pointing_at_sun_during_day():
    sun_az, sun_alt = compute_sun_altaz(
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    safe, reason = is_sun_safe(
        sun_az, sun_alt,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    assert safe is False
    assert "sun_avoidance" in reason
    assert "separation" in reason


def test_is_safe_when_pointing_well_away_from_sun_during_day():
    sun_az, sun_alt = compute_sun_altaz(
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    # Point opposite the sun — separation should be ~180°.
    opp_az = (sun_az + 180.0) % 360.0
    opp_alt = -sun_alt
    safe, _ = is_sun_safe(
        opp_az, opp_alt,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    assert safe is True


def test_unsafe_at_just_inside_cone_edge():
    sun_az, sun_alt = compute_sun_altaz(
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    # 29° away in pure elevation → exact 29° great-circle separation.
    safe, _ = is_sun_safe(
        sun_az, sun_alt + 29.0,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    assert safe is False


def test_safe_at_just_outside_cone_edge():
    sun_az, sun_alt = compute_sun_altaz(
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    # 31° away in pure elevation → exact 31° great-circle separation.
    safe, _ = is_sun_safe(
        sun_az, sun_alt + 31.0,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    assert safe is True


def test_custom_cone_angle_overrides_default():
    sun_az, sun_alt = compute_sun_altaz(
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    # 31° away (pure elevation) — outside default 30° cone, inside 60°.
    target_alt = sun_alt + 31.0
    safe_default, _ = is_sun_safe(
        sun_az, target_alt,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
    )
    safe_wider, _ = is_sun_safe(
        sun_az, target_alt,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=_noon_utc(),
        min_separation_deg=60.0,
    )
    assert safe_default is True
    assert safe_wider is False


def test_custom_alt_threshold_overrides_default():
    # Sun at -5° (above -10° default → cone enforced; above -3° →
    # disabled). Use a small cone so we can flip behavior.
    when = datetime(2026, 1, 1, 14, 5, tzinfo=timezone.utc)  # ~near civil dawn
    sun_az, sun_alt = compute_sun_altaz(
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=when,
    )
    # Pick a time close to civil dawn; verify behavior changes if we
    # raise the threshold above the actual sun altitude.
    target_az, target_alt = sun_az, sun_alt  # pointing right at sun
    safe_default, _ = is_sun_safe(
        target_az, target_alt,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=when,
    )
    safe_disabled, _ = is_sun_safe(
        target_az, target_alt,
        lat_deg=SITE_LAT, lon_deg=SITE_LON, when=when,
        alt_threshold_deg=sun_alt + 1.0,
    )
    # With default threshold (-10°): if sun_alt > -10°, unsafe (pointing at sun).
    # With threshold above current sun_alt: always safe.
    if sun_alt >= DEFAULT_ALT_THRESHOLD_DEG:
        assert safe_default is False
    assert safe_disabled is True


# --- SafetyTrip dataclass -------------------------------------------------


def test_safety_trip_is_immutable():
    trip = SafetyTrip(
        when_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        sun_az_deg=180.0, sun_alt_deg=33.0,
        mount_az_deg=181.0, mount_el_deg=34.0,
        separation_deg=1.4, cone_deg=30.0,
        jog_angle_deg=90, jog_speed=1440, jog_duration_s=3,
    )
    with pytest.raises(Exception):
        trip.cone_deg = 15.0  # frozen dataclass — must raise


def test_safety_trip_default_message():
    trip = SafetyTrip(
        when_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        sun_az_deg=0, sun_alt_deg=0, mount_az_deg=0, mount_el_deg=0,
        separation_deg=0, cone_deg=30.0,
        jog_angle_deg=0, jog_speed=1440, jog_duration_s=3,
    )
    assert "Sun safety triggered" in trip.message
