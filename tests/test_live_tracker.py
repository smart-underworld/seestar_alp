"""Tests for device.live_tracker — AtomicOffsets, TargetCatalog, session
lifecycle. Session-thread tests use the PositionLogger real implementation
and a FakeMountClient, but they don't drive a real Alpaca HTTP endpoint —
instead they rely on the session's dry-run + test-only cli override.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

from device.live_tracker import (
    ALONG_BOUND_DEG,
    AZ_BIAS_BOUND_DEG,
    AtomicOffsets,
    CachedTarget,
    EL_BIAS_BOUND_DEG,
    TIME_OFFSET_BOUND_S,
    LiveTrackManager,
    LiveTrackSession,
    TargetCatalog,
    load_session_mount_frame,
)
from device.reference_provider import JsonlECEFProvider, ReferenceSample
from device.streaming_controller import OffsetSnapshot
from device.target_frame import MountFrame
from scripts.trajectory.observer import build_site, lla_to_ecef


# --------- AtomicOffsets --------------------------------------------------


def test_atomic_offsets_defaults_are_zero():
    off = AtomicOffsets()
    snap = off.get()
    assert snap == OffsetSnapshot()


def test_atomic_offsets_clamps_to_bounds():
    off = AtomicOffsets()
    snap = off.set(
        az_bias_deg=100.0, el_bias_deg=-100.0,
        along_deg=100.0, cross_deg=-100.0,
        time_offset_s=100.0,
    )
    assert snap.az_bias_deg == AZ_BIAS_BOUND_DEG
    assert snap.el_bias_deg == -EL_BIAS_BOUND_DEG
    assert snap.along_deg == ALONG_BOUND_DEG
    assert snap.cross_deg == -ALONG_BOUND_DEG  # symmetric bound
    assert snap.time_offset_s == TIME_OFFSET_BOUND_S


def test_atomic_offsets_rejects_nan():
    """NaN values must raise before being stored — otherwise they
    propagate through the streaming controller and poison the mount
    command (NaN in az_bias → NaN in eff_ref_az → NaN velocity)."""
    import math

    import pytest
    off = AtomicOffsets()
    for field in ("az_bias_deg", "el_bias_deg", "along_deg", "cross_deg",
                  "time_offset_s"):
        with pytest.raises(ValueError):
            off.set(**{field: float("nan")})
    # Unchanged after failed set.
    assert off.get() == OffsetSnapshot()
    # +inf / -inf still clamp cleanly — not regressed by the NaN check.
    snap = off.set(az_bias_deg=float("inf"))
    assert math.isfinite(snap.az_bias_deg)
    assert snap.az_bias_deg == AZ_BIAS_BOUND_DEG


def test_atomic_offsets_partial_updates_preserve_other_fields():
    off = AtomicOffsets()
    off.set(az_bias_deg=0.2, el_bias_deg=-0.1, along_deg=0.05, cross_deg=0.02)
    snap = off.set(time_offset_s=0.5)
    assert snap.time_offset_s == 0.5
    assert snap.az_bias_deg == 0.2
    assert snap.el_bias_deg == -0.1
    assert snap.along_deg == 0.05
    assert snap.cross_deg == 0.02


def test_atomic_offsets_reset_scopes():
    off = AtomicOffsets()
    off.set(az_bias_deg=1.0, el_bias_deg=1.0, along_deg=1.0, cross_deg=1.0, time_offset_s=2.0)
    after_azel = off.reset_azel()
    assert after_azel.az_bias_deg == 0.0 and after_azel.el_bias_deg == 0.0
    assert after_azel.along_deg == 1.0 and after_azel.cross_deg == 1.0
    assert after_azel.time_offset_s == 2.0
    after_ac = off.reset_alongcross()
    assert after_ac.along_deg == 0.0 and after_ac.cross_deg == 0.0
    assert after_ac.time_offset_s == 2.0
    after_all = off.reset_all()
    assert after_all == OffsetSnapshot()


def test_atomic_offsets_thread_safety_smoke():
    """Many threads writing should not produce inconsistent snapshots."""
    off = AtomicOffsets()
    def writer():
        for _ in range(200):
            off.set(az_bias_deg=0.1, el_bias_deg=-0.1)
    threads = [threading.Thread(target=writer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = off.get()
    assert snap.az_bias_deg == 0.1 and snap.el_bias_deg == -0.1


# --------- TargetCatalog --------------------------------------------------


def _offset_latlon(lat_deg, lon_deg, dnorth_m, deast_m):
    import math
    dlat = dnorth_m / 111320.0
    dlon = deast_m / (111320.0 * math.cos(math.radians(lat_deg)))
    return lat_deg + dlat, lon_deg + dlon


def _write_fixture(path: Path, t0_unix: float, duration_s: float = 5.0, dt: float = 0.5) -> None:
    site = build_site()
    n = int(round(duration_s / dt)) + 1
    t_grid = t0_unix + np.arange(n) * dt
    east = 100.0 * (t_grid - t_grid[0]) - 100.0 * duration_s / 2.0
    header = {
        "kind": "header", "source": "test", "id": path.stem,
        "callsign": "FIXTURE", "duration_s": duration_s,
        "n_samples": n, "peak_el_deg": 5.0, "min_slant_m": 5000.0,
        "sample_rate_hz": 1.0 / dt,
    }
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for i in range(n):
            lat, lon = _offset_latlon(site.lat_deg, site.lon_deg, 5000.0, float(east[i]))
            ex, ey, ez = lla_to_ecef(lat, lon, site.alt_m + 3000.0)
            f.write(json.dumps({
                "kind": "sample", "t_unix": float(t_grid[i]),
                "ecef_x": ex, "ecef_y": ey, "ecef_z": ez,
                "lat": lat, "lon": lon, "alt_m": site.alt_m + 3000.0,
                "az_deg": 0.0, "el_deg": 0.0, "slant_m": 0.0,
            }) + "\n")


def test_target_catalog_lists_cached(tmp_path):
    root = tmp_path / "trajectories"
    (root / "aircraft").mkdir(parents=True)
    (root / "satellites").mkdir(parents=True)
    _write_fixture(root / "aircraft" / "a.jsonl", t0_unix=time.time() + 1.0)
    _write_fixture(root / "satellites" / "b.jsonl", t0_unix=time.time() + 1.0)
    catalog = TargetCatalog(root, live_enabled=False)
    cached = catalog.list_cached()
    assert len(cached) == 2
    kinds = {t.kind for t in cached}
    assert kinds == {"aircraft", "satellite"}
    assert all(isinstance(t, CachedTarget) for t in cached)
    assert all(t.n_samples > 0 for t in cached)


def test_target_catalog_make_provider_for_file(tmp_path):
    root = tmp_path / "trajectories"
    (root / "aircraft").mkdir(parents=True)
    p = root / "aircraft" / "a.jsonl"
    _write_fixture(p, t0_unix=time.time() + 1.0)
    catalog = TargetCatalog(root, live_enabled=False)
    provider = catalog.make_provider(
        "file", p.stem, MountFrame.from_identity_enu(),
    )
    assert isinstance(provider, JsonlECEFProvider)
    t0, t1 = provider.valid_range()
    assert t1 > t0


def test_target_catalog_missing_id_raises(tmp_path):
    import pytest
    catalog = TargetCatalog(tmp_path, live_enabled=False)  # no trajectories subdir
    with pytest.raises(KeyError):
        catalog.make_provider("file", "nope", MountFrame.from_identity_enu())


def test_target_catalog_live_missing_id_raises(tmp_path):
    import pytest
    catalog = TargetCatalog(tmp_path, live_enabled=False)
    with pytest.raises(KeyError):
        catalog.make_provider("live", "anything", MountFrame.from_identity_enu())


def test_target_catalog_defers_adsb_poller_until_list_live(tmp_path):
    """Spec: starting a TargetCatalog must not spin up the adsb.fi
    poller thread. Only `list_live()` should wake it up so the live
    tracker stays quiescent when not in use."""
    catalog = TargetCatalog(tmp_path, live_enabled=True)
    # Just after construction: no thread should exist.
    assert catalog._live_thread is None
    try:
        # Touching list_live() spins the poller up. Can't wait for real
        # network traffic, but we can verify the thread is alive within
        # a beat of the call returning.
        catalog.list_live()
        alive = False
        for _ in range(20):
            if catalog._live_thread is not None and catalog._live_thread.is_alive():
                alive = True
                break
            time.sleep(0.05)
        assert alive, "adsb.fi poller did not start after list_live()"
    finally:
        catalog.close()
        if catalog._live_thread is not None:
            catalog._live_thread.join(timeout=2.0)


def test_target_catalog_live_disabled_never_starts_poller(tmp_path):
    catalog = TargetCatalog(tmp_path, live_enabled=False)
    catalog.list_live()
    assert catalog._live_thread is None


# --------- load_session_mount_frame --------------------------------------


def test_load_session_mount_frame_returns_mountframe():
    mf = load_session_mount_frame()
    assert isinstance(mf, MountFrame)


# --------- LiveTrackSession + Manager (lifecycle) ------------------------


class _StationaryProvider:
    """Minimal ReferenceProvider used to verify session lifecycle without
    driving the real FF loop long enough to matter."""

    def __init__(self, t0: float, duration_s: float = 3.0):
        self._t0 = t0
        self._t1 = t0 + duration_s

    def sample(self, t):
        return ReferenceSample(
            t_unix=float(t), az_cum_deg=0.0, el_deg=45.0,
            v_az_degs=0.0, v_el_degs=0.0,
            a_az_degs2=0.0, a_el_degs2=0.0,
            stale=False, extrapolated=False,
        )

    def valid_range(self):
        return (self._t0, self._t1)


def test_live_track_manager_start_stop_roundtrip(tmp_path, monkeypatch):
    """End-to-end session lifecycle with a fake mount and a stationary
    provider. Verifies start → status.active → stop → status.exit_reason."""
    # Patch AlpacaClient inside the live_tracker module so the session
    # thread doesn't try to hit a real HTTP endpoint.
    import device.live_tracker as lt

    class _FakeCli:
        def method_sync(self, method, params=None):
            if method == "scope_get_horiz_coord":
                return {
                    "result": [45.0, 0.0],
                    "Timestamp": f"{time.time():.6f}",
                }
            return {"result": None}

    monkeypatch.setattr(lt, "AlpacaClient", lambda *a, **kw: _FakeCli())

    offsets = AtomicOffsets()
    provider = _StationaryProvider(t0=time.time() + 0.2)
    session = LiveTrackSession(
        telescope_id=99,
        target_kind="file",
        target_id="fixture",
        target_display_name="Fixture",
        provider=provider,
        offsets=offsets,
        dry_run=True,
        log_dir=tmp_path / "logs",
    )
    mgr = LiveTrackManager()
    mgr.start(session)
    try:
        # Let at least one tick fire.
        time.sleep(1.0)
        st = mgr.status(99)
        assert st is not None
        assert st.active
    finally:
        mgr.stop(99)

    # Post-stop: thread should have joined and exit_reason populated.
    final = mgr.status(99)
    assert final is not None
    assert not final.active
    assert final.exit_reason in {"stop_signal", "end_of_track", "timeout"}


def test_live_track_manager_set_offsets_when_running(tmp_path, monkeypatch):
    import device.live_tracker as lt

    class _FakeCli:
        def method_sync(self, method, params=None):
            if method == "scope_get_horiz_coord":
                return {"result": [45.0, 0.0], "Timestamp": f"{time.time():.6f}"}
            return {"result": None}

    monkeypatch.setattr(lt, "AlpacaClient", lambda *a, **kw: _FakeCli())

    session = LiveTrackSession(
        telescope_id=100,
        target_kind="file",
        target_id="fixture",
        target_display_name="Fixture",
        provider=_StationaryProvider(t0=time.time() + 0.2),
        offsets=AtomicOffsets(),
        dry_run=True,
        log_dir=tmp_path / "logs",
    )
    mgr = LiveTrackManager()
    mgr.start(session)
    try:
        snap = mgr.set_offsets(100, az_bias_deg=0.3)
        assert snap is not None
        assert snap.az_bias_deg == 0.3
        snap2 = mgr.reset_offsets(100, scope="azel")
        assert snap2.az_bias_deg == 0.0
    finally:
        mgr.stop(100)


# --------- LiveADSBProvider -----------------------------------------------


def test_live_adsb_provider_builds_from_buffer():
    import math

    from device.live_tracker import LiveADSBProvider, _LiveBuffer

    site = build_site()
    buf = _LiveBuffer(icao24="deadbe", callsign="TEST1")
    t0 = time.time() - 10.0
    n = 8
    for i in range(n):
        east_m = 100.0 * i
        lat = site.lat_deg + (5000.0 / 111320.0)
        lon = site.lon_deg + (east_m / (111320.0 * math.cos(math.radians(site.lat_deg))))
        ecef = tuple(float(x) for x in lla_to_ecef(lat, lon, site.alt_m + 3000.0))
        buf.append(t0 + float(i), ecef)

    provider = LiveADSBProvider(buf, MountFrame.from_identity_enu(site), rebuild_s=0.0)
    t_start, t_end = provider.valid_range()
    assert t_end > t_start
    mid = 0.5 * (t_start + t_end)
    sample = provider.sample(mid)
    assert isinstance(sample, ReferenceSample)
    assert not sample.stale


def test_live_adsb_provider_stale_without_samples():
    import device.live_tracker as lt
    buf = lt._LiveBuffer(icao24="none", callsign="")
    provider = lt.LiveADSBProvider(buf, MountFrame.from_identity_enu())
    s = provider.sample(time.time())
    assert s.stale


def test_auto_slew_refuses_when_target_inside_sun_cone(monkeypatch):
    """Spec: LiveTrackSession._auto_slew must consult sun_safety.is_sun_safe
    against the provider's first (az, el) and refuse the pre-slew
    (exit_reason='sun_avoidance') rather than commanding the mount into
    the cone."""
    import device.live_tracker as lt
    from device import sun_safety as ss

    # Force is_sun_safe to always refuse. The session's cur_az/el
    # reading comes from the fake client.
    real_is_sun_safe = ss.is_sun_safe
    monkeypatch.setattr(
        ss, "is_sun_safe",
        lambda *a, **kw: (False, "sun_avoidance: forced by test"),
    )
    try:
        class _FakeCli:
            def method_sync(self, method, params=None):
                if method == "scope_get_horiz_coord":
                    return {
                        "result": [45.0, 0.0],
                        "Timestamp": f"{time.time():.6f}",
                    }
                return {"result": None}

        monkeypatch.setattr(lt, "AlpacaClient", lambda *a, **kw: _FakeCli())

        session = LiveTrackSession(
            telescope_id=77,
            target_kind="file", target_id="fix", target_display_name="Fix",
            provider=_StationaryProvider(t0=time.time() + 0.2),
            offsets=AtomicOffsets(),
            dry_run=True,
        )
        cli = _FakeCli()
        loc = None  # loc is unused by measure_altaz_timed under the fake
        session._auto_slew(cli, loc)
    finally:
        monkeypatch.setattr(ss, "is_sun_safe", real_is_sun_safe)

    assert session._exit_reason == "sun_avoidance"
    assert session._phase == "refused"
    assert any("sun_avoidance" in e for e in session._errors)


def test_stop_requested_during_preslew_records_exit_reason():
    """Direct unit of the pre-slew stop helper: flipping the stop event
    makes the helper return True and stamp the session with
    exit_reason='stop_signal', phase='stopped'."""
    session = LiveTrackSession(
        telescope_id=200,
        target_kind="file", target_id="fix", target_display_name="Fix",
        provider=_StationaryProvider(t0=time.time() + 1.0),
        offsets=AtomicOffsets(),
        dry_run=True,
    )
    assert session._stop_requested_during_preslew() is False
    session._stop_evt.set()
    assert session._stop_requested_during_preslew() is True
    assert session._exit_reason == "stop_signal"
    assert session._phase == "stopped"


def test_live_track_manager_double_start_refuses(tmp_path, monkeypatch):
    import pytest
    import device.live_tracker as lt

    class _FakeCli:
        def method_sync(self, method, params=None):
            if method == "scope_get_horiz_coord":
                return {"result": [45.0, 0.0], "Timestamp": f"{time.time():.6f}"}
            return {"result": None}

    monkeypatch.setattr(lt, "AlpacaClient", lambda *a, **kw: _FakeCli())

    def make_session():
        return LiveTrackSession(
            telescope_id=101,
            target_kind="file", target_id="fix", target_display_name="Fix",
            provider=_StationaryProvider(t0=time.time() + 0.2),
            offsets=AtomicOffsets(),
            dry_run=True,
            log_dir=tmp_path / "logs",
        )

    mgr = LiveTrackManager()
    s1 = make_session()
    mgr.start(s1)
    try:
        with pytest.raises(RuntimeError):
            mgr.start(make_session())
    finally:
        mgr.stop(101)


def test_live_track_manager_start_atomic_under_lock():
    """Regression for a TOCTOU race: session.start() must run while the
    manager lock is held. Otherwise two concurrent mgr.start() calls
    for the same telescope id can both pass the is_alive() check (the
    first session is registered but its thread hasn't been spawned yet,
    so is_alive() returns False) and spawn duplicate tracking threads
    that both drive the mount."""
    mgr = LiveTrackManager()
    captured: dict[str, bool] = {}

    class _FakeSession:
        telescope_id = 300

        def __init__(self) -> None:
            self._alive = False

        def start(self) -> None:
            # Observe the manager lock from inside session.start(). If
            # mgr.start() dropped the lock before calling us, a racing
            # caller could observe is_alive()=False and overwrite the
            # registry — exactly the bug this test guards against.
            captured["lock_held_during_session_start"] = mgr._lock.locked()
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def stop(self, timeout: float = 5.0) -> None:
            pass

        def status(self):
            return None

    mgr.start(_FakeSession())
    assert captured["lock_held_during_session_start"] is True
