"""End-to-end test of StreamingFFController against a FakeMountClient.

Drives a short straight-line aircraft fixture through the real controller
and real plant simulation (`FirstOrderLagModel`), asserts tracking RMS
under the same bounds we expect on hardware.
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import numpy as np

from device.plant_limits import AzimuthLimits, CumulativeAzTracker
from device.reference_provider import JsonlECEFProvider
from device.streaming_controller import (
    OffsetSnapshot,
    TickInfo,
    pre_check,
    track,
)
from device.target_frame import MountFrame
from scripts.trajectory.observer import build_site, lla_to_ecef
from tests.fakes.fake_mount import FakeMountClient


def _offset_latlon(lat_deg, lon_deg, dnorth_m, deast_m):
    dlat = dnorth_m / 111320.0
    dlon = deast_m / (111320.0 * math.cos(math.radians(lat_deg)))
    return lat_deg + dlat, lon_deg + dlon


def _write_fixture(
    path: Path,
    t0_unix: float,
    duration_s: float = 5.0,
    dt: float = 0.5,
    lateral_north_m: float = 5000.0,
    altitude_m: float = 3000.0,
    speed_mps: float = 100.0,
) -> None:
    """Write a short straight-flight JSONL anchored at `t0_unix`."""
    site = build_site()
    n = int(round(duration_s / dt)) + 1
    t_grid = t0_unix + np.arange(n) * dt
    east = speed_mps * (t_grid - t_grid[0]) - speed_mps * duration_s / 2.0
    with path.open("w", encoding="utf-8") as f:
        header = {
            "kind": "header", "source": "adsb", "id": "test",
            "observer_lat": site.lat_deg, "observer_lon": site.lon_deg,
            "observer_alt_m": site.alt_m, "duration_s": duration_s,
            "sample_rate_hz": 1.0 / dt, "n_samples": n,
        }
        f.write(json.dumps(header) + "\n")
        for i in range(n):
            lat, lon = _offset_latlon(
                site.lat_deg, site.lon_deg, lateral_north_m, float(east[i]),
            )
            alt = altitude_m + site.alt_m
            ex, ey, ez = lla_to_ecef(lat, lon, alt)
            f.write(json.dumps({
                "kind": "sample", "t_unix": float(t_grid[i]),
                "ecef_x": ex, "ecef_y": ey, "ecef_z": ez,
                "lat": lat, "lon": lon, "alt_m": alt,
                "az_deg": 0.0, "el_deg": 0.0, "slant_m": 0.0,
            }) + "\n")


# --------- pre-check tests -------------------------------------------


def test_pre_check_feasible(tmp_path):
    path = tmp_path / "flight.jsonl"
    _write_fixture(path, t0_unix=time.time() + 1.0, duration_s=10.0, dt=1.0)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf)
    result = pre_check(provider, az_limits=AzimuthLimits.load(), el_max_deg=85.0)
    assert result.feasible
    assert result.cable_wrap_violations == 0
    assert result.el_limit_violations == 0
    assert result.peak_v_az_degs < 2.0  # slow pass; rates well below plant


def test_pre_check_rejects_el_over_limit(tmp_path):
    """Close overhead pass peaks too high for the mount's usable el band."""
    path = tmp_path / "overhead.jsonl"
    _write_fixture(
        path, t0_unix=time.time() + 1.0, duration_s=10.0, dt=1.0,
        lateral_north_m=300.0, altitude_m=3000.0,
    )
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf)
    result = pre_check(provider, az_limits=None, el_max_deg=80.0)
    assert not result.feasible
    assert result.el_limit_violations > 0


# --------- end-to-end track against FakeMountClient ------------------


def test_track_synthetic_flight_rms_bounded(tmp_path):
    """Full tracking loop: controller + real plant simulation. Run in real time.

    The fixture is 3 s of level flight (short so the test finishes quickly)
    starting 1 s in the future so the controller's pre-head wait is
    exercised but does not dominate the test.
    """
    path = tmp_path / "flight.jsonl"
    t0 = time.time() + 1.0
    _write_fixture(path, t0_unix=t0, duration_s=3.0, dt=0.5)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf, extrapolation_s=1.0)

    cli = FakeMountClient()
    # Park the fake mount at the pass start so the controller doesn't spend
    # its first few ticks slewing from some arbitrary parked position.
    first = provider.sample(t0)
    cli.set_position(az_deg=first.az_cum_deg, el_deg=first.el_deg)

    tracker = CumulativeAzTracker()
    stop = threading.Event()

    result = track(
        cli, provider,
        tick_dt=0.5, latency_s=0.4, tau_s=0.348,
        kp_pos=0.5, v_corr_max=2.0, v_max=6.0,
        az_limits=None, az_tracker=tracker,
        stop_signal=stop, max_duration_s=10.0,
    )

    assert result.exit_reason in ("end_of_track", "stop_signal"), \
        f"unexpected exit {result.exit_reason}: {result.errors}"
    assert result.ticks >= 4
    # Tracking error: startup transient + k_dc=0.996 bias. Same thresholds
    # the offline replay achieves on the same geometry.
    assert result.az_err_rms < 0.6, f"az_rms={result.az_err_rms}"
    assert result.el_err_rms < 0.6, f"el_rms={result.el_err_rms}"
    assert result.az_err_peak < 3.0
    assert result.el_err_peak < 3.0


def test_track_stop_signal_aborts(tmp_path):
    path = tmp_path / "flight.jsonl"
    t0 = time.time() + 0.3
    _write_fixture(path, t0_unix=t0, duration_s=10.0, dt=0.5)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf, extrapolation_s=1.0)
    cli = FakeMountClient()
    first = provider.sample(t0)
    cli.set_position(az_deg=first.az_cum_deg, el_deg=first.el_deg)

    stop = threading.Event()

    def _fire_stop_after(delay_s):
        time.sleep(delay_s)
        stop.set()

    t_stop = threading.Thread(target=_fire_stop_after, args=(1.2,), daemon=True)
    t_stop.start()
    t_start = time.monotonic()
    result = track(cli, provider, stop_signal=stop, max_duration_s=30.0)
    t_elapsed = time.monotonic() - t_start

    assert result.exit_reason == "stop_signal"
    # Must have exited promptly after signal (within 1 tick + slack).
    assert t_elapsed < 2.5


def test_track_exits_when_per_tick_sun_guard_trips(tmp_path, monkeypatch):
    """Controller bails with exit_reason='sun_avoidance' when the per-tick
    guard marks the reference sample unsafe (e.g. trajectory rolls into
    the sun cone). Monkeypatches the guard so this runs deterministically
    at any time of day."""
    path = tmp_path / "flight.jsonl"
    t0 = time.time() + 0.3
    _write_fixture(path, t0_unix=t0, duration_s=3.0, dt=0.5)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf, extrapolation_s=1.0)
    cli = FakeMountClient()
    first = provider.sample(t0)
    cli.set_position(az_deg=first.az_cum_deg, el_deg=first.el_deg)

    # Force the guard to always refuse.
    import device.streaming_controller as sc
    monkeypatch.setattr(
        sc, "_is_sun_safe",
        lambda az, el: (False, "sun_avoidance: forced by test"),
    )

    result = track(cli, provider, max_duration_s=10.0)
    assert result.exit_reason == "sun_avoidance"
    assert any("sun_avoidance" in e for e in result.errors)


def test_track_exits_sun_avoidance_when_speed_move_locked_out(tmp_path):
    """If the lockout-aware speed_move raises SunSafetyLocked mid-track,
    the controller exits with exit_reason='sun_avoidance' instead of
    retrying."""
    from device.sun_safety import (
        SunSafetyMonitor,
        get_sun_monitor,
        set_sun_monitor,
    )

    path = tmp_path / "flight.jsonl"
    t0 = time.time() + 0.3
    _write_fixture(path, t0_unix=t0, duration_s=3.0, dt=0.5)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf, extrapolation_s=1.0)
    cli = FakeMountClient()
    first = provider.sample(t0)
    cli.set_position(az_deg=first.az_cum_deg, el_deg=first.el_deg)

    class _FakeJog:
        def __call__(self, *_a, **_kw):
            pass

    prev = get_sun_monitor()
    m = SunSafetyMonitor(
        altaz_reader=lambda: None, jog_command=_FakeJog(),
        lat_deg=0.0, lon_deg=0.0,
    )
    m._emergency_lockout.set()  # pretend monitor is mid-jog
    set_sun_monitor(m)
    try:
        result = track(cli, provider, max_duration_s=10.0)
    finally:
        set_sun_monitor(prev)

    assert result.exit_reason == "sun_avoidance"


def test_dry_run_does_not_command_mount(tmp_path):
    path = tmp_path / "flight.jsonl"
    t0 = time.time() + 0.3
    _write_fixture(path, t0_unix=t0, duration_s=2.0, dt=0.5)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf, extrapolation_s=1.0)
    cli = FakeMountClient()
    first = provider.sample(t0)
    cli.set_position(az_deg=first.az_cum_deg, el_deg=first.el_deg)

    result = track(cli, provider, dry_run=True, max_duration_s=10.0)
    assert result.exit_reason == "end_of_track"
    # In dry-run mode the only "commands" issued are the final zero-stop
    # (also skipped), so commands_received should be 0.
    assert cli.state.commands_received == 0


# --------- offset_provider + tick_callback hooks -------------------------


def _run_dry_with_offsets(
    tmp_path: Path,
    offsets: OffsetSnapshot,
    duration_s: float = 3.0,
) -> list[TickInfo]:
    """Run a short dry-run track with a fixed offset snapshot and return
    the TickInfo records captured by the callback."""
    path = tmp_path / "flight.jsonl"
    t0 = time.time() + 0.3
    _write_fixture(path, t0_unix=t0, duration_s=duration_s, dt=0.5)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf, extrapolation_s=1.0)
    cli = FakeMountClient()
    first = provider.sample(t0)
    cli.set_position(az_deg=first.az_cum_deg, el_deg=first.el_deg)

    captured: list[TickInfo] = []
    track(
        cli, provider,
        dry_run=True, max_duration_s=10.0,
        offset_provider=lambda: offsets,
        tick_callback=captured.append,
    )
    return captured


def test_tick_callback_receives_info_without_offsets(tmp_path):
    ticks = _run_dry_with_offsets(tmp_path, OffsetSnapshot(), duration_s=2.0)
    assert len(ticks) >= 2
    assert all(isinstance(t, TickInfo) for t in ticks)
    # With zero offsets the total bias must be exactly zero.
    assert all(abs(t.d_az_deg) < 1e-9 and abs(t.d_el_deg) < 1e-9 for t in ticks)


def test_az_el_bias_applied_as_absolute_shift(tmp_path):
    bias = OffsetSnapshot(az_bias_deg=0.3, el_bias_deg=-0.2)
    ticks = _run_dry_with_offsets(tmp_path, bias, duration_s=2.0)
    assert ticks, "expected at least one tick"
    for t in ticks:
        assert abs(t.d_az_deg - 0.3) < 1e-9
        assert abs(t.d_el_deg - (-0.2)) < 1e-9


def test_along_cross_bias_rotates_with_heading(tmp_path):
    """A target moving purely east-ward has ψ ≈ 0; along should map to
    d_az, cross should map to d_el (since the along/cross basis has
    Along+ aligned with heading and Cross+ 90° CCW of it)."""
    bias = OffsetSnapshot(along_deg=0.4, cross_deg=0.1)
    ticks = _run_dry_with_offsets(tmp_path, bias, duration_s=2.0)
    # Ignore the first tick or two while ψ EWMA warms up.
    tail = ticks[-3:]
    assert tail, "no tail ticks"
    for t in tail:
        assert not t.heading_locked
        assert abs(t.d_az_deg - 0.4) < 0.02
        assert abs(t.d_el_deg - 0.1) < 0.02


def test_heading_locks_at_low_velocity():
    """A stationary-reference provider should freeze ψ and report
    heading_locked=True."""
    import types

    from device.reference_provider import ReferenceSample
    t0 = time.time() + 0.2
    t1 = t0 + 3.0

    def sample(t):
        return ReferenceSample(
            t_unix=float(t), az_cum_deg=10.0, el_deg=45.0,
            v_az_degs=0.0, v_el_degs=0.0,
            a_az_degs2=0.0, a_el_degs2=0.0,
            stale=False, extrapolated=False,
        )

    provider = types.SimpleNamespace(
        sample=sample,
        valid_range=lambda: (t0, t1),
    )

    cli = FakeMountClient()
    cli.set_position(az_deg=10.0, el_deg=45.0)

    captured: list[TickInfo] = []
    track(
        cli, provider,
        dry_run=True, max_duration_s=5.0,
        offset_provider=lambda: OffsetSnapshot(along_deg=0.3),
        tick_callback=captured.append,
    )
    assert captured, "no ticks captured"
    # heading is locked when |v| < V_MIN_HEADING_LOCK_DEGS (=0.05°/s).
    assert all(t.heading_locked for t in captured)
    # And along/cross contribution must be suppressed (0.0) while locked.
    for t in captured:
        assert abs(t.d_az_deg) < 1e-9
        assert abs(t.d_el_deg) < 1e-9


def test_time_offset_shifts_query_time(tmp_path):
    """Passing a positive time_offset_s reaches the end-of-track
    faster; a large offset past the extrapolation horizon exits as
    end_of_track near-immediately."""
    path = tmp_path / "flight.jsonl"
    t0 = time.time() + 0.3
    _write_fixture(path, t0_unix=t0, duration_s=5.0, dt=0.5)
    mf = MountFrame.from_identity_enu()
    provider = JsonlECEFProvider(path, mf, extrapolation_s=1.0)
    cli = FakeMountClient()
    first = provider.sample(t0)
    cli.set_position(az_deg=first.az_cum_deg, el_deg=first.el_deg)

    # Offset well past the tail + extrapolation budget → immediate end.
    result = track(
        cli, provider,
        dry_run=True, max_duration_s=10.0,
        offset_provider=lambda: OffsetSnapshot(time_offset_s=30.0),
    )
    assert result.exit_reason == "end_of_track"
    assert result.ticks == 0
