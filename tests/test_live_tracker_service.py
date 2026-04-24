"""Tests for device.live_tracker_service — the fourth AppRunner.

Covers the lifecycle wiring without touching the network or a real
mount: start → monitor installed, reload → thresholds updated, stop →
monitor torn down.
"""

from __future__ import annotations

import pytest

from device.live_tracker_service import LiveTrackerMain
from device import sun_safety as ss


@pytest.fixture(autouse=True)
def _clear_monitor_singleton():
    prev = ss.get_sun_monitor()
    yield
    ss.set_sun_monitor(prev)


@pytest.fixture
def _stub_load_toml(monkeypatch):
    """Neutralise Config.load_toml so test-level monkeypatches on
    Config.sun_avoidance_* survive start/reload calls (otherwise the
    TOML reader overwrites them from disk)."""
    from device.config import Config
    monkeypatch.setattr(Config, "load_toml", lambda *a, **kw: None)


def test_start_installs_monitor_and_stop_tears_it_down(monkeypatch, _stub_load_toml):
    # Avoid spinning up the real monitor thread (it would try to reach
    # a non-running ALP server). Replace SunSafetyMonitor.start with a
    # no-op.
    monkeypatch.setattr(ss.SunSafetyMonitor, "start", lambda self: None)

    main = LiveTrackerMain()
    assert ss.get_sun_monitor() is None
    main.start()
    assert ss.get_sun_monitor() is not None
    assert isinstance(ss.get_sun_monitor(), ss.SunSafetyMonitor)
    main.stop()
    assert ss.get_sun_monitor() is None


def test_start_respects_sun_avoidance_disabled_flag(monkeypatch, _stub_load_toml):
    from device.config import Config

    monkeypatch.setattr(ss.SunSafetyMonitor, "start", lambda self: None)
    monkeypatch.setattr(Config, "sun_avoidance_enabled", False, raising=False)

    main = LiveTrackerMain()
    main.start()
    assert ss.get_sun_monitor() is None  # never installed


def test_reload_pushes_updated_thresholds_into_running_monitor(monkeypatch, _stub_load_toml):
    from device.config import Config

    monkeypatch.setattr(ss.SunSafetyMonitor, "start", lambda self: None)

    main = LiveTrackerMain()
    main.start()
    m = ss.get_sun_monitor()
    assert m.min_separation_deg == 30.0  # default

    # Swap the config knob and reload.
    monkeypatch.setattr(Config, "sun_avoidance_min_sep_deg", 45.0, raising=False)
    main.reload()
    assert m.min_separation_deg == 45.0


def test_reload_spins_monitor_up_when_reenabled(monkeypatch, _stub_load_toml):
    from device.config import Config

    monkeypatch.setattr(ss.SunSafetyMonitor, "start", lambda self: None)
    monkeypatch.setattr(Config, "sun_avoidance_enabled", False, raising=False)

    main = LiveTrackerMain()
    main.start()
    assert ss.get_sun_monitor() is None

    monkeypatch.setattr(Config, "sun_avoidance_enabled", True, raising=False)
    main.reload()
    assert ss.get_sun_monitor() is not None


def test_abort_active_sessions_stops_manager_per_seestar(monkeypatch):
    """The default abort_active callback iterates over Config.seestars
    and stops both live_track + calibration managers. Simulated with
    a fake Config and fake managers."""
    from device.config import Config
    from device.live_tracker_service import _abort_active_sessions

    monkeypatch.setattr(
        Config, "seestars",
        [{"device_num": 1}, {"device_num": 2}],
        raising=False,
    )

    stops: list[int] = []

    class _FakeMgr:
        def stop(self, tid):
            stops.append(tid)

    import device.live_tracker as lt
    import device.rotation_calibration as rc
    monkeypatch.setattr(lt, "get_manager", lambda: _FakeMgr())
    monkeypatch.setattr(rc, "get_calibration_manager", lambda: _FakeMgr())

    _abort_active_sessions()
    assert sorted(stops) == [1, 1, 2, 2]  # each mgr called once per scope
