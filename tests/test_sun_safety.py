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
    SunSafetyMonitor,
    angular_separation,
    compute_jog_angle,
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


# --- compute_jog_angle ----------------------------------------------------


def _apply_jog(mount_az, mount_el, angle_deg, jog_speed=1440, jog_duration_s=3.0):
    """Forward-simulate exactly what the monitor does: motion in (daz, del)."""
    rate = jog_speed / 237.0
    step = rate * jog_duration_s
    rad = math.radians(angle_deg)
    new_az = (mount_az + step * math.cos(rad)) % 360.0
    new_el = max(-90.0, min(90.0, mount_el + step * math.sin(rad)))
    return new_az, new_el


def _sep_after_jog(mount_az, mount_el, sun_az, sun_alt, angle):
    new_az, new_el = _apply_jog(mount_az, mount_el, angle)
    return angular_separation(new_az, new_el, sun_az, sun_alt)


def test_jog_increases_separation_sun_east_mount_west():
    sun_az, sun_alt = 90.0, 30.0
    mount_az, mount_el = 100.0, 30.0  # 10° east of mount; inside 30° cone
    sep_before = angular_separation(mount_az, mount_el, sun_az, sun_alt)
    angle = compute_jog_angle(mount_az, mount_el, sun_az, sun_alt)
    sep_after = _sep_after_jog(mount_az, mount_el, sun_az, sun_alt, angle)
    assert sep_after > sep_before, f"angle={angle} sep before={sep_before} after={sep_after}"


def test_jog_increases_separation_sun_west_mount_east():
    sun_az, sun_alt = 270.0, 30.0
    mount_az, mount_el = 260.0, 30.0
    sep_before = angular_separation(mount_az, mount_el, sun_az, sun_alt)
    angle = compute_jog_angle(mount_az, mount_el, sun_az, sun_alt)
    sep_after = _sep_after_jog(mount_az, mount_el, sun_az, sun_alt, angle)
    assert sep_after > sep_before


def test_jog_increases_separation_sun_above_mount():
    # Sun at 40° alt, mount at 30° alt — optical axis pointing low at same az.
    sun_az, sun_alt = 180.0, 40.0
    mount_az, mount_el = 180.0, 30.0
    sep_before = angular_separation(mount_az, mount_el, sun_az, sun_alt)
    angle = compute_jog_angle(mount_az, mount_el, sun_az, sun_alt)
    sep_after = _sep_after_jog(mount_az, mount_el, sun_az, sun_alt, angle)
    assert sep_after > sep_before
    # Should be moving downward (angle near 270° = -el).
    assert 200 < angle < 340


def test_jog_increases_separation_sun_below_mount():
    sun_az, sun_alt = 180.0, 20.0
    mount_az, mount_el = 180.0, 30.0
    sep_before = angular_separation(mount_az, mount_el, sun_az, sun_alt)
    angle = compute_jog_angle(mount_az, mount_el, sun_az, sun_alt)
    sep_after = _sep_after_jog(mount_az, mount_el, sun_az, sun_alt, angle)
    assert sep_after > sep_before
    # Should be moving up (near 90°).
    assert 20 < angle < 160


def test_jog_direction_is_opposite_from_sun_in_az_el_space():
    # 45° diagonal from sun in (daz, del) space → jog should be ~225°
    # (i.e. 45° + 180°).
    sun_az, sun_alt = 100.0, 40.0
    mount_az, mount_el = 110.0, 50.0   # +10° in az, +10° in el from sun
    angle = compute_jog_angle(mount_az, mount_el, sun_az, sun_alt)
    # direction-to-sun has atan2(-10, -10) = -135° → -135 + 360 = 225°.
    # away-from-sun direction: atan2(10, 10) = 45° ≈ the answer.
    assert abs(angle - 45) < 2


def test_jog_never_decreases_separation_over_random_inputs():
    """Property check: the function must not pick a direction that
    brings the mount closer to the sun."""
    rng = __import__("random").Random(1234)
    failures = []
    for _ in range(200):
        sun_az = rng.uniform(0, 360)
        sun_alt = rng.uniform(-5, 75)
        # Mount somewhere in the 30° cone around the sun.
        daz = rng.uniform(-20, 20)
        del_ = rng.uniform(-20, 20)
        mount_az = (sun_az + daz) % 360.0
        mount_el = max(-85.0, min(85.0, sun_alt + del_))
        if math.hypot(daz, del_) < 0.1:
            continue  # degenerate: mount coincides with sun
        sep_before = angular_separation(mount_az, mount_el, sun_az, sun_alt)
        angle = compute_jog_angle(mount_az, mount_el, sun_az, sun_alt)
        sep_after = _sep_after_jog(mount_az, mount_el, sun_az, sun_alt, angle)
        if sep_after < sep_before - 1e-3:
            failures.append(
                f"sun=({sun_az:.1f},{sun_alt:.1f}) mount=({mount_az:.1f},{mount_el:.1f})"
                f" angle={angle} sep {sep_before:.2f}→{sep_after:.2f}"
            )
    assert not failures, "jog decreased separation:\n" + "\n".join(failures[:5])


# --- SunSafetyMonitor: lockout + jog behavior ----------------------------


class _FakeJog:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []
        self.was_locked_during_call: list[bool] = []
        self._monitor: SunSafetyMonitor | None = None

    def bind(self, m: SunSafetyMonitor) -> None:
        self._monitor = m

    def __call__(self, speed: int, angle: int, dur: int) -> None:
        self.calls.append((speed, angle, dur))
        if self._monitor is not None:
            self.was_locked_during_call.append(self._monitor.is_locked_out())


def test_monitor_trips_and_calls_abort_then_jog_then_releases():
    # Mount pointing RIGHT at a fixed sun position; monitor should trip.
    sun_pos = (180.0, 30.0)

    # Patch compute_sun_altaz via the module so tick() sees a known sun.
    from device import sun_safety as ss
    real = ss.compute_sun_altaz
    ss.compute_sun_altaz = lambda **kw: sun_pos
    try:
        aborts: list[int] = []
        jog = _FakeJog()
        m = SunSafetyMonitor(
            altaz_reader=lambda: (181.0, 31.0),   # 1.4° from sun
            jog_command=jog,
            abort_active=lambda: aborts.append(1),
            lat_deg=33.96, lon_deg=-118.46,
            jog_duration_s=0,   # make the post-jog sleep fast
        )
        jog.bind(m)
        # Drive one tick in-line; don't bother with the thread loop.
        m._tick()
    finally:
        ss.compute_sun_altaz = real

    assert len(aborts) == 1, "abort_active should be called exactly once"
    assert len(jog.calls) == 1, "jog_command should be called exactly once"
    speed, angle, dur = jog.calls[0]
    assert speed == 1440
    assert dur == 0
    assert 0 <= angle < 360
    # Lockout should have been set during the jog call.
    assert jog.was_locked_during_call == [True]
    # After _trigger_emergency returns, lockout should be cleared.
    assert m.is_locked_out() is False
    trip = m.last_trip()
    assert trip is not None
    assert trip.cone_deg == 30.0
    assert trip.separation_deg < 30.0
    assert trip.jog_angle_deg == angle


def test_monitor_skips_when_sun_below_threshold():
    from device import sun_safety as ss
    real = ss.compute_sun_altaz
    ss.compute_sun_altaz = lambda **kw: (180.0, -15.0)  # below -10° default
    try:
        jog = _FakeJog()
        m = SunSafetyMonitor(
            altaz_reader=lambda: (180.0, -15.0),  # pointing RIGHT at sun
            jog_command=jog,
            lat_deg=33.96, lon_deg=-118.46,
            jog_duration_s=0,
        )
        m._tick()
    finally:
        ss.compute_sun_altaz = real
    assert jog.calls == []
    assert m.last_trip() is None


def test_monitor_does_not_trip_when_altaz_reader_returns_none():
    # Simulates "mount not plate-solved; RA/Dec unreliable".
    from device import sun_safety as ss
    real = ss.compute_sun_altaz
    ss.compute_sun_altaz = lambda **kw: (180.0, 30.0)
    try:
        jog = _FakeJog()
        m = SunSafetyMonitor(
            altaz_reader=lambda: None,
            jog_command=jog,
            lat_deg=33.96, lon_deg=-118.46,
            jog_duration_s=0,
        )
        m._tick()
    finally:
        ss.compute_sun_altaz = real
    assert jog.calls == []
    assert m.last_trip() is None


def test_monitor_skip_when_disabled():
    from device import sun_safety as ss
    real = ss.compute_sun_altaz
    ss.compute_sun_altaz = lambda **kw: (180.0, 30.0)
    try:
        jog = _FakeJog()
        m = SunSafetyMonitor(
            altaz_reader=lambda: (180.0, 30.0),
            jog_command=jog,
            lat_deg=33.96, lon_deg=-118.46,
            jog_duration_s=0,
            enabled=False,
        )
        m._tick()
    finally:
        ss.compute_sun_altaz = real
    assert jog.calls == []


def test_monitor_dismiss_hides_last_trip():
    from device import sun_safety as ss
    real = ss.compute_sun_altaz
    ss.compute_sun_altaz = lambda **kw: (180.0, 30.0)
    try:
        m = SunSafetyMonitor(
            altaz_reader=lambda: (181.0, 31.0),
            jog_command=_FakeJog(),
            lat_deg=33.96, lon_deg=-118.46,
            jog_duration_s=0,
        )
        m._tick()
    finally:
        ss.compute_sun_altaz = real
    assert m.last_trip() is not None
    m.dismiss_last_trip()
    assert m.last_trip() is None


def test_reload_updates_thresholds_without_restart():
    m = SunSafetyMonitor(
        altaz_reader=lambda: None,
        jog_command=_FakeJog(),
        lat_deg=33.96, lon_deg=-118.46,
    )
    assert m.min_separation_deg == 30.0
    assert m.enabled is True
    m.reload(min_separation_deg=15.0, enabled=False)
    assert m.min_separation_deg == 15.0
    assert m.enabled is False


# --- module-level singleton helpers --------------------------------------


def test_sun_safety_is_locked_out_without_monitor():
    from device.sun_safety import (
        get_sun_monitor,
        set_sun_monitor,
        sun_safety_is_locked_out,
    )
    prev = get_sun_monitor()
    set_sun_monitor(None)
    try:
        assert sun_safety_is_locked_out() is False
    finally:
        set_sun_monitor(prev)


def test_set_and_get_sun_monitor_roundtrip():
    from device.sun_safety import get_sun_monitor, set_sun_monitor
    prev = get_sun_monitor()
    m = SunSafetyMonitor(
        altaz_reader=lambda: None,
        jog_command=_FakeJog(),
        lat_deg=0.0, lon_deg=0.0,
    )
    set_sun_monitor(m)
    try:
        assert get_sun_monitor() is m
    finally:
        set_sun_monitor(prev)


# --- speed_move wrapper: honors emergency lockout ------------------------


class _DummyCli:
    """Minimal MountClient double — just records method_sync calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def method_sync(self, method: str, params=None):
        self.calls.append((method, dict(params or {})))
        return {"result": {}}


def test_speed_move_passes_through_when_not_locked():
    from device.sun_safety import get_sun_monitor, set_sun_monitor
    from device.velocity_controller import speed_move
    prev = get_sun_monitor()
    set_sun_monitor(None)
    try:
        cli = _DummyCli()
        speed_move(cli, speed=100, angle=45, dur_sec=1)
        assert cli.calls == [
            ("scope_speed_move", {"speed": 100, "angle": 45, "dur_sec": 1}),
        ]
    finally:
        set_sun_monitor(prev)


def test_speed_move_refuses_while_monitor_locked_out():
    from device.sun_safety import SunSafetyLocked, get_sun_monitor, set_sun_monitor
    from device.velocity_controller import speed_move
    prev = get_sun_monitor()
    m = SunSafetyMonitor(
        altaz_reader=lambda: None,
        jog_command=_FakeJog(),
        lat_deg=0.0, lon_deg=0.0,
    )
    # Simulate the monitor mid-jog.
    m._emergency_lockout.set()
    set_sun_monitor(m)
    try:
        cli = _DummyCli()
        with pytest.raises(SunSafetyLocked):
            speed_move(cli, speed=100, angle=45, dur_sec=1)
        assert cli.calls == []  # firmware never touched
    finally:
        set_sun_monitor(prev)
