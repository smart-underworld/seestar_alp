"""Tests for nighttime calibration (plate-solve workflow).

The session uses a background thread for the solver call. To keep tests
deterministic without timing dependencies, the FakePlateSolver returns
canned ``SolveResult`` values keyed by image path; the session's solve
worker is a daemon thread, so we wait briefly with a short polling loop
before asserting on status.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from device.nighttime_calibration import (
    MIN_SIGHTINGS_FOR_APPLY,
    NighttimeCalibrationManager,
    NighttimeCalibrationSession,
    radec_to_topocentric_azel,
)
from device.plate_solver import (
    FakePlateSolver,
    PlateSolverFailed,
    PlateSolverNotAvailable,
    SeestarPlateSolver,
    SolveResult,
    UnavailablePlateSolver,
    _parse_solve_field_stdout,
    get_default_plate_solver,
)
from device.rotation_calibration import solve_rotation_from_pairs
from scripts.trajectory.observer import build_site


DOCKWEILER = dict(lat_deg=33.9615051, lon_deg=-118.4581361, alt_m=2.0)


def _site():
    return build_site(**DOCKWEILER)


# ---------- PlateSolver layer ---------------------------------------


def test_unavailable_plate_solver_raises():
    s = UnavailablePlateSolver()
    assert not s.is_available()
    with pytest.raises(PlateSolverNotAvailable):
        s.solve(Path("/tmp/whatever"))


def test_fake_plate_solver_canned_results(tmp_path):
    canned = SolveResult(
        ra_deg=80.0,
        dec_deg=-10.0,
        fov_x_deg=1.27,
        fov_y_deg=0.71,
        position_angle_deg=12.0,
        stars_used=42,
    )
    img = tmp_path / "frame.jpg"
    img.write_text("dummy")
    fake = FakePlateSolver({str(img): canned})
    result = fake.solve(img)
    assert result == canned
    assert fake.calls == [img]


def test_fake_plate_solver_failure_raises(tmp_path):
    img = tmp_path / "frame.jpg"
    img.write_text("dummy")
    fake = FakePlateSolver({str(img): None})
    with pytest.raises(PlateSolverFailed):
        fake.solve(img)


def test_solve_field_stdout_parse_valid_centre_and_size():
    """Smoke-test the regex against a representative astrometry.net
    stdout fragment so a future solver-version bump shows up here
    instead of as a silent garbage solve."""
    sample = """
Reading input file 1 of 1: "frame.jpg"...
Field 1: solved with index index-4205-09.fits.
Field 1 solved: matched (10 match(es)) of 50 stars
Field 1: solved with index index-4205-09.fits.
Field center: (RA,Dec) = (80.123, -10.456) deg.
Field size: 1.27 x 0.71 degrees
Field rotation angle: up is 12.5 degrees E of N
"""
    parsed = _parse_solve_field_stdout(sample)
    assert parsed.ra_deg == pytest.approx(80.123)
    assert parsed.dec_deg == pytest.approx(-10.456)
    assert parsed.fov_x_deg == pytest.approx(1.27)
    assert parsed.fov_y_deg == pytest.approx(0.71)
    assert parsed.position_angle_deg == pytest.approx(12.5)
    assert parsed.stars_used == 10


def test_solve_field_stdout_parse_arcminute_units():
    """Solver may emit field size in arcminutes for narrow FOV; parser
    must convert."""
    sample = """
Field center: (RA,Dec) = (10.0, 20.0) deg.
Field size: 76.2 x 42.6 arcminutes
"""
    parsed = _parse_solve_field_stdout(sample)
    # 76.2 arcmin / 60 = 1.27°
    assert parsed.fov_x_deg == pytest.approx(1.27, abs=1e-3)
    assert parsed.fov_y_deg == pytest.approx(0.71, abs=1e-3)


def test_solve_field_stdout_parse_missing_centre_raises():
    with pytest.raises(PlateSolverFailed):
        _parse_solve_field_stdout("Field 1 unsolved.")


def test_get_default_plate_solver_returns_unavailable_without_solve_field(monkeypatch):
    import device.plate_solver as ps

    monkeypatch.setattr(ps.shutil, "which", lambda *a, **kw: None)
    s = ps.get_default_plate_solver()
    assert isinstance(s, UnavailablePlateSolver)


def test_get_default_plate_solver_prefers_seestar_when_runner_provided(monkeypatch):
    """Even when ``solve-field`` is on PATH, if the caller passes a
    telescope id and an action runner the factory returns the
    firmware-onboard backend so calibration sessions don't need
    astrometry.net installed."""
    import device.plate_solver as ps

    monkeypatch.setattr(ps.shutil, "which", lambda *a, **kw: "/fake/solve-field")
    s = ps.get_default_plate_solver(telescope_id=1, action_runner=lambda *a, **kw: None)
    assert isinstance(s, SeestarPlateSolver)
    assert s.kind == "seestar"


# ---------- SeestarPlateSolver ----------------------------------------


def test_seestar_plate_solver_parses_firmware_response():
    """Firmware reports RA in **hours** and Dec in **degrees**; the
    solver wraps everything in an Alpaca ``Value`` envelope. We must
    convert RA to degrees so the rotation solver downstream gets
    consistent units with the ``solve-field`` backend."""
    captured = {}

    def fake_runner(action, dev_num, params):
        captured["action"] = action
        captured["dev_num"] = dev_num
        captured["params"] = params
        return {
            "Value": {
                "ra_dec": [12.0, 30.0],  # 12h = 180°, 30°
                "fov": [1.27, 0.71],
                "angle": -177.79,
                "star_number": 1267,
                "duration_ms": 13223,
            },
            "ErrorNumber": 0,
            "ErrorMessage": "",
        }

    solver = SeestarPlateSolver(fake_runner, telescope_id=7, timeout_s=10.0)
    assert solver.is_available()
    result = solver.solve()  # no image_path
    assert captured == {
        "action": "start_solve_sync",
        "dev_num": 7,
        "params": {"timeout_s": 10.0},
    }
    assert result.ra_deg == pytest.approx(180.0)  # 12h × 15
    assert result.dec_deg == pytest.approx(30.0)
    assert result.fov_x_deg == pytest.approx(1.27)
    assert result.fov_y_deg == pytest.approx(0.71)
    assert result.position_angle_deg == pytest.approx(-177.79)
    assert result.stars_used == 1267


def test_seestar_plate_solver_handles_alpaca_error_envelope():
    """Non-zero ``ErrorNumber`` (e.g. firmware ``fail`` event or
    ``request_plate_solve_sync`` timeout surfaced via
    DevDriverException) should raise ``PlateSolverFailed`` with the
    error text propagated."""

    def fake_runner(action, dev_num, params):
        return {
            "ErrorNumber": 0x500,
            "ErrorMessage": "plate solve failed: code 251",
        }

    solver = SeestarPlateSolver(fake_runner, telescope_id=1)
    with pytest.raises(PlateSolverFailed, match="device error"):
        solver.solve()


def test_seestar_plate_solver_handles_unreachable_device():
    """``do_action_device`` returns ``None`` when the Alpaca driver
    refuses the request (e.g. scope offline). The solver must surface
    that as a clear failure rather than crashing on attribute access."""

    def fake_runner(action, dev_num, params):
        return None

    solver = SeestarPlateSolver(fake_runner, telescope_id=1)
    with pytest.raises(PlateSolverFailed, match="no response"):
        solver.solve()


def test_seestar_plate_solver_rejects_malformed_payload():
    def fake_runner(action, dev_num, params):
        return {"Value": {"unrelated": True}}

    solver = SeestarPlateSolver(fake_runner, telescope_id=1)
    with pytest.raises(PlateSolverFailed, match="missing ra_dec"):
        solver.solve()


def test_seestar_plate_solver_propagates_runner_exception():
    """If the action runner itself raises (network blip, JSON parse
    error), the solver should wrap it as ``PlateSolverFailed`` so the
    nighttime session records a failure for that sighting rather than
    aborting the whole run."""

    def fake_runner(action, dev_num, params):
        raise ConnectionError("boom")

    solver = SeestarPlateSolver(fake_runner, telescope_id=1)
    with pytest.raises(PlateSolverFailed, match="boom"):
        solver.solve()


def test_session_capture_sighting_works_without_image_path(tmp_path):
    """The Seestar onboard solver doesn't take an image path. The
    session must accept an omitted ``image_path`` and still record
    the sighting using whatever the solver returns."""
    import device.nighttime_calibration as nc

    # Skip astropy by short-circuiting the topocentric conversion.
    nc_radec = nc.radec_to_topocentric_azel
    try:
        nc.radec_to_topocentric_azel = lambda ra, dec, t, site: (ra, dec)
        canned = SolveResult(
            ra_deg=180.0,
            dec_deg=30.0,
            fov_x_deg=1.27,
            fov_y_deg=0.71,
            position_angle_deg=0.0,
        )
        # ``""`` is the FakePlateSolver sentinel for no image path.
        fake = FakePlateSolver({"": canned})
        session = _make_session(tmp_path, fake)
        session.capture_sighting(
            encoder_az_deg=180.0, encoder_el_deg=40.0
        )  # no image_path
        assert _wait_for(lambda: session.status().pending is None, timeout_s=5.0)
        st = session.status()
        assert st.n_accepted == 1
        assert st.sightings[0]["image_path"] == ""
    finally:
        nc.radec_to_topocentric_azel = nc_radec


def test_session_capture_requires_encoder_position(tmp_path):
    """Forgetting to pass ``encoder_az_deg`` / ``encoder_el_deg`` must
    raise a clear ValueError, not yield a confusing altitude-floor
    error from a silent ``0.0`` default."""
    session = _make_session(tmp_path, FakePlateSolver())
    with pytest.raises(ValueError, match="required"):
        session.capture_sighting(image_path=tmp_path / "img.jpg")
    with pytest.raises(ValueError, match="required"):
        session.capture_sighting(image_path=tmp_path / "img.jpg", encoder_az_deg=180.0)
    with pytest.raises(ValueError, match="required"):
        session.capture_sighting(image_path=tmp_path / "img.jpg", encoder_el_deg=40.0)


def test_solve_field_solver_requires_image_path():
    """``solve-field`` backend must reject a missing path with a clear
    error rather than running the binary on an empty argument."""
    from device.plate_solver import SolveFieldPlateSolver

    sf = SolveFieldPlateSolver(binary_path="/usr/bin/solve-field")
    with pytest.raises(PlateSolverFailed, match="requires an on-disk image"):
        sf.solve(None)


def test_get_default_plate_solver_no_args_keeps_legacy_behaviour(monkeypatch):
    """Calling ``get_default_plate_solver()`` with no args (the
    legacy unified-calibration call site) should still fall back to
    ``solve-field`` when present, preserving compatibility."""
    import device.plate_solver as ps

    monkeypatch.setattr(ps.shutil, "which", lambda *a, **kw: "/fake/solve-field")
    s = get_default_plate_solver()
    assert s.kind == "solve-field"


# ---------- solve_rotation_from_pairs ---------------------------------


def test_solve_rotation_from_pairs_recovers_known_rotation():
    """Generate synthetic sightings under a known rotation and verify
    the solver recovers the same yaw/pitch/roll."""
    # Truth rotation; sightings are synthesised by applying it to
    # randomly-distributed sky positions, then the solver should
    # invert it.
    from device.rotation_calibration import _predict_mount_azel_from_topo

    truth_yaw, truth_pitch, truth_roll = 12.5, -1.2, 0.7
    true_pairs = []
    test_directions = [
        (45.0, 30.0),
        (135.0, 50.0),
        (225.0, 60.0),
        (315.0, 25.0),
    ]
    for true_az, true_el in test_directions:
        enc_az, enc_el = _predict_mount_azel_from_topo(
            truth_yaw, truth_pitch, truth_roll, true_az, true_el
        )
        true_pairs.append((enc_az, enc_el, true_az, true_el))
    sol = solve_rotation_from_pairs(true_pairs)
    assert sol.yaw_deg == pytest.approx(truth_yaw, abs=0.001)
    assert sol.pitch_deg == pytest.approx(truth_pitch, abs=0.001)
    assert sol.roll_deg == pytest.approx(truth_roll, abs=0.001)
    assert sol.residual_rms_deg < 1e-3
    assert len(sol.per_landmark) == 4
    # Per-record dicts use the platesolve schema.
    assert sol.per_landmark[0]["kind"] == "platesolve"


def test_solve_rotation_from_pairs_yaw_only_one_sighting():
    """With one sighting the solver should fit yaw only (auto mode)."""
    from device.rotation_calibration import _predict_mount_azel_from_topo

    enc_az, enc_el = _predict_mount_azel_from_topo(8.0, 0.0, 0.0, 100.0, 30.0)
    sol = solve_rotation_from_pairs([(enc_az, enc_el, 100.0, 30.0)])
    assert sol.yaw_deg == pytest.approx(8.0, abs=0.001)
    assert sol.pitch_deg == 0.0
    assert sol.roll_deg == 0.0


# ---------- NighttimeCalibrationSession --------------------------------


def _wait_for(predicate, timeout_s: float = 5.0, poll_s: float = 0.05):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def _make_session(tmp_path, plate_solver):
    return NighttimeCalibrationSession(
        telescope_id=99,
        site=_site(),
        out_path=tmp_path / "mount_calibration.json",
        plate_solver=plate_solver,
    )


def test_session_capture_below_floor_refuses(tmp_path):
    session = _make_session(tmp_path, FakePlateSolver())
    with pytest.raises(ValueError, match="below.*altitude"):
        session.capture_sighting(
            image_path=tmp_path / "img.jpg",
            encoder_az_deg=180.0,
            encoder_el_deg=5.0,
        )


def test_session_capture_above_ceiling_refuses(tmp_path):
    session = _make_session(tmp_path, FakePlateSolver())
    with pytest.raises(ValueError, match="above"):
        session.capture_sighting(
            image_path=tmp_path / "img.jpg",
            encoder_az_deg=180.0,
            encoder_el_deg=85.0,
        )


def test_session_solver_failure_records_in_status(tmp_path, monkeypatch):
    img = tmp_path / "img.jpg"
    img.write_text("dummy")
    fake = FakePlateSolver({str(img): None})  # None → PlateSolverFailed
    session = _make_session(tmp_path, fake)
    session.capture_sighting(img, encoder_az_deg=180.0, encoder_el_deg=40.0)
    assert _wait_for(lambda: session.status().last_failed is not None)
    st = session.status()
    assert st.last_failed["status"] == "fail"
    assert "fake failure" in (st.last_failed["error"] or "")
    assert st.n_accepted == 0


def test_session_solver_returns_bad_fov_records_failure(tmp_path):
    img = tmp_path / "img.jpg"
    img.write_text("dummy")
    bad = SolveResult(
        ra_deg=90.0,
        dec_deg=20.0,
        fov_x_deg=10.0,  # outside [0.5, 3.0]
        fov_y_deg=10.0,
        position_angle_deg=0.0,
    )
    fake = FakePlateSolver({str(img): bad})
    session = _make_session(tmp_path, fake)
    session.capture_sighting(img, encoder_az_deg=180.0, encoder_el_deg=40.0)
    assert _wait_for(lambda: session.status().last_failed is not None)
    st = session.status()
    assert "FOV" in (st.last_failed["error"] or "")
    assert st.n_accepted == 0


def test_session_three_sightings_fit_succeeds(tmp_path, monkeypatch):
    """Build 3 captures with canned plate solves whose true az/el are
    known to invert under a chosen rotation. The session should accept
    all three and produce a fit. We monkey-patch radec_to_topocentric_azel
    so we don't depend on astropy + the real wall clock."""
    import device.nighttime_calibration as nc
    from device.rotation_calibration import _predict_mount_azel_from_topo

    truth_yaw, truth_pitch, truth_roll = 5.0, 1.0, -0.5
    test_dirs = [(60.0, 30.0), (180.0, 45.0), (300.0, 35.0)]

    # Map (ra, dec) → fake sky direction. Use ra/dec as direct (true_az, true_el)
    # for simplicity — we don't care that they're not realistic celestial
    # coordinates for the purposes of the rotation solver.
    def fake_radec_to_topo(ra, dec, t_unix, site):
        return ra, dec

    monkeypatch.setattr(nc, "radec_to_topocentric_azel", fake_radec_to_topo)

    canned = {}
    captures = []
    for i, (true_az, true_el) in enumerate(test_dirs):
        enc_az, enc_el = _predict_mount_azel_from_topo(
            truth_yaw, truth_pitch, truth_roll, true_az, true_el
        )
        img = tmp_path / f"img{i}.jpg"
        img.write_text("dummy")
        canned[str(img)] = SolveResult(
            ra_deg=true_az,
            dec_deg=true_el,
            fov_x_deg=1.27,
            fov_y_deg=0.71,
            position_angle_deg=0.0,
        )
        captures.append((img, enc_az, enc_el))

    fake = FakePlateSolver(canned)
    session = _make_session(tmp_path, fake)

    for img, enc_az, enc_el in captures:
        session.capture_sighting(img, enc_az, enc_el)
        assert _wait_for(lambda: session.status().pending is None, timeout_s=5.0)
    st = session.status()
    assert st.n_accepted == 3
    assert st.fit is not None
    assert st.fit["yaw_deg"] == pytest.approx(truth_yaw, abs=0.05)
    assert st.fit["pitch_deg"] == pytest.approx(truth_pitch, abs=0.05)
    assert st.fit["roll_deg"] == pytest.approx(truth_roll, abs=0.05)
    assert st.fit["residual_rms_deg"] < 0.1


def test_session_apply_writes_atomic_json(tmp_path, monkeypatch):
    import device.nighttime_calibration as nc

    monkeypatch.setattr(
        nc, "radec_to_topocentric_azel", lambda ra, dec, t, site: (ra, dec)
    )
    # Three minimal sightings with deterministic results.
    canned = {}
    captures = []
    for i, (az, el) in enumerate([(80.0, 35.0), (160.0, 40.0), (250.0, 55.0)]):
        img = tmp_path / f"img{i}.jpg"
        img.write_text("dummy")
        canned[str(img)] = SolveResult(
            ra_deg=az,
            dec_deg=el,
            fov_x_deg=1.27,
            fov_y_deg=0.71,
            position_angle_deg=0.0,
        )
        captures.append((img, az, el))

    fake = FakePlateSolver(canned)
    session = _make_session(tmp_path, fake)
    out = tmp_path / "mount_calibration.json"
    session.out_path = out

    for img, az, el in captures:
        session.capture_sighting(img, az, el)
        assert _wait_for(lambda: session.status().pending is None, timeout_s=5.0)

    session.apply()
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["calibration_method"] == "rotation_platesolve"
    assert payload["n_sightings"] == 3
    assert "yaw_offset_deg" in payload
    assert "observer" in payload
    assert payload["observer"]["lat_deg"] == pytest.approx(DOCKWEILER["lat_deg"])
    assert len(payload["sightings"]) == 3
    # Records carry kind=platesolve in the fit per-record list.
    assert payload["fit_per_record"][0]["kind"] == "platesolve"


def test_session_apply_refuses_below_minimum(tmp_path, monkeypatch):
    import device.nighttime_calibration as nc

    monkeypatch.setattr(
        nc, "radec_to_topocentric_azel", lambda ra, dec, t, site: (ra, dec)
    )
    img = tmp_path / "img.jpg"
    img.write_text("dummy")
    fake = FakePlateSolver(
        {
            str(img): SolveResult(
                ra_deg=100.0,
                dec_deg=30.0,
                fov_x_deg=1.27,
                fov_y_deg=0.71,
                position_angle_deg=0.0,
            )
        }
    )
    session = _make_session(tmp_path, fake)
    session.capture_sighting(img, encoder_az_deg=100.0, encoder_el_deg=30.0)
    assert _wait_for(lambda: session.status().pending is None, timeout_s=5.0)
    # Only 1 sighting; apply should refuse.
    with pytest.raises(ValueError, match=f"need .{MIN_SIGHTINGS_FOR_APPLY}"):
        session.apply()


def test_session_skip_pending_clears_failure(tmp_path):
    img = tmp_path / "img.jpg"
    img.write_text("dummy")
    fake = FakePlateSolver({str(img): None})
    session = _make_session(tmp_path, fake)
    session.capture_sighting(img, encoder_az_deg=180.0, encoder_el_deg=40.0)
    assert _wait_for(lambda: session.status().last_failed is not None)
    session.skip_pending()
    st = session.status()
    assert st.pending is None


def test_session_remove_sighting_refits(tmp_path, monkeypatch):
    import device.nighttime_calibration as nc

    monkeypatch.setattr(
        nc, "radec_to_topocentric_azel", lambda ra, dec, t, site: (ra, dec)
    )
    canned = {}
    captures = []
    for i, (az, el) in enumerate([(60.0, 35.0), (180.0, 45.0), (300.0, 35.0)]):
        img = tmp_path / f"img{i}.jpg"
        img.write_text("dummy")
        canned[str(img)] = SolveResult(
            ra_deg=az,
            dec_deg=el,
            fov_x_deg=1.27,
            fov_y_deg=0.71,
            position_angle_deg=0.0,
        )
        captures.append((img, az, el))
    fake = FakePlateSolver(canned)
    session = _make_session(tmp_path, fake)
    for img, az, el in captures:
        session.capture_sighting(img, az, el)
        assert _wait_for(lambda: session.status().pending is None, timeout_s=5.0)
    assert session.status().n_accepted == 3
    session.remove_sighting(1)
    st = session.status()
    assert st.n_accepted == 2


# ---------- NighttimeCalibrationManager ------------------------------


def test_manager_singleton():
    from device.nighttime_calibration import get_nighttime_manager

    a = get_nighttime_manager()
    b = get_nighttime_manager()
    assert a is b


def test_manager_refuses_when_live_tracker_running(tmp_path, monkeypatch):
    import device.live_tracker as lt

    class _FakeAlive:
        def is_alive(self):
            return True

    class _FakeMgr:
        def get(self, tid):
            return _FakeAlive()

    monkeypatch.setattr(lt, "get_manager", lambda: _FakeMgr())
    mgr = NighttimeCalibrationManager()
    session = NighttimeCalibrationSession(
        telescope_id=66,
        site=_site(),
        out_path=tmp_path / "out.json",
        plate_solver=FakePlateSolver(),
    )
    with pytest.raises(RuntimeError, match="live-tracking"):
        mgr.start(session)


def test_radec_to_topocentric_azel_roundtrip():
    """Sanity test the astropy-backed conversion against a known
    target. We pick a star at zenith from the equator at the right
    sidereal time so we can compute the expected AltAz analytically.

    The exact value depends on astropy's IERS table; we just check the
    function returns a finite (az, el) tuple in the expected ranges.
    """
    site = _site()
    # Use current time; we just need finite output, not an exact match.
    az, el = radec_to_topocentric_azel(0.0, 0.0, time.time(), site)
    assert -360.0 <= az <= 720.0
    assert -90.0 <= el <= 90.0


# ---------- auto-calibration ----------------------------------------


def test_pick_auto_calibration_targets_filters_altitude_band(monkeypatch):
    """Synthesise a catalog of stars at known (az, el) and verify the
    picker keeps only the 60–80° band and orders them by greedy
    farthest-point sampling."""
    from datetime import datetime, timezone

    import device.nighttime_calibration as nc
    from scripts.trajectory.celestial_targets import CelestialTarget

    fake_targets = [
        CelestialTarget(name="LowStar", kind="star", ra_hours=0, dec_deg=0, vmag=2.0),
        CelestialTarget(name="HighStar", kind="star", ra_hours=0, dec_deg=0, vmag=2.0),
        CelestialTarget(name="ZenithStar", kind="star", ra_hours=0, dec_deg=0, vmag=2.0),
        CelestialTarget(name="EastStar", kind="star", ra_hours=0, dec_deg=0, vmag=2.0),
        CelestialTarget(name="WestStar", kind="star", ra_hours=0, dec_deg=0, vmag=2.0),
    ]
    az_el_by_name = {
        "LowStar": (90.0, 30.0),  # below 60°, dropped
        "HighStar": (10.0, 70.0),  # in band, highest el
        "ZenithStar": (45.0, 85.0),  # above 80°, dropped
        "EastStar": (90.0, 65.0),  # in band
        "WestStar": (270.0, 65.0),  # in band, far from HighStar/EastStar
    }

    def fake_filter(targets, site, when_utc, **kwargs):
        out = []
        for t in targets:
            az, el = az_el_by_name[t.name]
            min_el = kwargs.get("min_el_deg", 20.0)
            if el >= min_el:
                out.append((t, az, el))
        return out

    monkeypatch.setattr(nc, "datetime", datetime)  # ensure import path stable
    import scripts.trajectory.celestial_targets as ct

    monkeypatch.setattr(ct, "filter_visible", fake_filter)
    monkeypatch.setattr(ct, "all_targets", lambda when, site: list(fake_targets))

    candidates = nc.pick_auto_calibration_targets(
        _site(),
        when_utc=datetime(2026, 4, 29, 6, 0, tzinfo=timezone.utc),
        pool_size=5,
    )
    names = [c.label for c in candidates]
    # Above-80° and below-60° entries dropped.
    assert "ZenithStar" not in names
    assert "LowStar" not in names
    # First entry is the highest-elevation in-band candidate.
    assert candidates[0].label == "HighStar"
    # Greedy sampling spreads across azimuth — second pick is the
    # farthest from the first (HighStar at az=10°), which is WestStar.
    assert candidates[1].label == "WestStar"
    # All survivors are in the 60–80° band.
    for c in candidates:
        assert 60.0 <= c.el_deg <= 80.0


def test_pick_auto_calibration_targets_returns_empty_when_obscured(monkeypatch):
    """Empty visible list → empty result, not a crash. The REST handler
    relies on this to surface a clear error instead of starting a
    doomed run."""
    import device.nighttime_calibration as nc
    import scripts.trajectory.celestial_targets as ct

    monkeypatch.setattr(ct, "filter_visible", lambda *a, **k: [])
    monkeypatch.setattr(ct, "all_targets", lambda when, site: [])
    candidates = nc.pick_auto_calibration_targets(_site())
    assert candidates == []


def test_auto_runner_drives_session_to_three_successes(tmp_path, monkeypatch):
    """End-to-end auto loop: 3 candidates, fake plate-solver returns
    canned results, fake slew/encoder always succeed. Runner should
    finish in ``done`` phase with all three sightings accepted."""
    import device.nighttime_calibration as nc
    from device.nighttime_calibration import (
        AutoCandidate,
        NighttimeAutoRunner,
    )

    monkeypatch.setattr(nc, "radec_to_topocentric_azel", lambda ra, dec, t, s: (ra, dec))
    candidates = [
        AutoCandidate(label="A", az_deg=10.0, el_deg=70.0),
        AutoCandidate(label="B", az_deg=180.0, el_deg=72.0),
        AutoCandidate(label="C", az_deg=300.0, el_deg=68.0),
    ]
    canned = {
        "": SolveResult(
            ra_deg=10.0, dec_deg=70.0, fov_x_deg=1.27, fov_y_deg=0.71,
            position_angle_deg=0.0,
        )
    }
    fake_solver = FakePlateSolver(canned)
    session = _make_session(tmp_path, fake_solver)
    encoder_pairs = iter([(10.0, 70.0), (180.0, 72.0), (300.0, 68.0)])
    runner = NighttimeAutoRunner(
        session=session,
        candidates=candidates,
        slew_func=lambda az, el: True,
        encoder_func=lambda: next(encoder_pairs),
        n_success_target=3,
        settle_after_slew_s=0.0,
        poll_interval_s=0.01,
    )
    runner.start()
    assert _wait_for(lambda: runner.status().phase == "done", timeout_s=5.0)
    st = runner.status()
    assert st.n_success == 3
    assert st.n_fail == 0
    assert all(c["status"] == "ok" for c in st.candidates)
    assert session.status().n_accepted == 3


def test_auto_runner_records_slew_refusal(tmp_path):
    """Sun-safety / horizon refusals (slew_func returns False) should
    be recorded as ``skipped``, not crash the loop, and the runner
    should continue to the next candidate."""
    from device.nighttime_calibration import AutoCandidate, NighttimeAutoRunner

    candidates = [
        AutoCandidate(label="Refused", az_deg=10.0, el_deg=70.0),
        AutoCandidate(label="Good", az_deg=180.0, el_deg=72.0),
    ]
    canned = {
        "": SolveResult(
            ra_deg=180.0, dec_deg=72.0, fov_x_deg=1.27, fov_y_deg=0.71,
            position_angle_deg=0.0,
        )
    }
    session = _make_session(tmp_path, FakePlateSolver(canned))

    slew_calls = []

    def slew(az, el):
        slew_calls.append((az, el))
        return az < 100.0  # first refused, second OK
        # NOTE: the first candidate's slew returns False → skipped

    # Override radec→azel for the second candidate's solve.
    import device.nighttime_calibration as nc

    nc.radec_to_topocentric_azel = lambda ra, dec, t, s: (ra, dec)
    runner = NighttimeAutoRunner(
        session=session,
        candidates=candidates,
        slew_func=lambda az, el: az > 100.0,
        encoder_func=lambda: (180.0, 72.0),
        n_success_target=1,
        settle_after_slew_s=0.0,
        poll_interval_s=0.01,
    )
    runner.start()
    assert _wait_for(lambda: runner.status().phase == "done", timeout_s=5.0)
    st = runner.status()
    assert st.candidates[0]["status"] == "skipped"
    assert st.candidates[1]["status"] == "ok"
    assert st.n_success == 1


def test_auto_runner_stops_on_cancel(tmp_path, monkeypatch):
    """``stop()`` should make the loop bail without poisoning the
    session — already-accepted sightings remain, no new ones are
    added once the stop event fires."""
    import threading

    import device.nighttime_calibration as nc
    from device.nighttime_calibration import AutoCandidate, NighttimeAutoRunner

    monkeypatch.setattr(nc, "radec_to_topocentric_azel", lambda ra, dec, t, s: (ra, dec))
    candidates = [AutoCandidate(label=f"T{i}", az_deg=i * 60.0, el_deg=70.0) for i in range(5)]
    canned = {
        "": SolveResult(
            ra_deg=10.0, dec_deg=70.0, fov_x_deg=1.27, fov_y_deg=0.71,
            position_angle_deg=0.0,
        )
    }
    session = _make_session(tmp_path, FakePlateSolver(canned))
    cancel_evt = threading.Event()

    def slow_slew(az, el):
        # First slew completes immediately; subsequent ones block until
        # the test signals cancel via stop().
        if az > 0.0 and not cancel_evt.is_set():
            cancel_evt.wait(timeout=2.0)
        return True

    runner = NighttimeAutoRunner(
        session=session,
        candidates=candidates,
        slew_func=slow_slew,
        encoder_func=lambda: (10.0, 70.0),
        n_success_target=99,
        settle_after_slew_s=0.0,
        poll_interval_s=0.01,
    )
    runner.start()
    # Wait for at least one success, then cancel.
    assert _wait_for(lambda: runner.status().n_success >= 1, timeout_s=5.0)
    runner.stop()
    cancel_evt.set()
    assert _wait_for(lambda: runner.status().phase == "cancelled", timeout_s=5.0)
    # Cancelled run preserved at least the first success.
    assert runner.status().n_success >= 1


def test_auto_manager_refuses_concurrent_runs(tmp_path, monkeypatch):
    """The process-singleton manager rejects a second start while one
    runner is alive on the same telescope — same mutex policy as the
    nighttime session manager."""
    import device.nighttime_calibration as nc
    from device.nighttime_calibration import (
        AutoCandidate,
        NighttimeAutoManager,
        NighttimeAutoRunner,
    )

    monkeypatch.setattr(nc, "radec_to_topocentric_azel", lambda ra, dec, t, s: (ra, dec))
    session = _make_session(tmp_path, FakePlateSolver())
    block = threading.Event()

    def hold_slew(az, el):
        block.wait(timeout=2.0)
        return True

    runner = NighttimeAutoRunner(
        session=session,
        candidates=[AutoCandidate(label="X", az_deg=0.0, el_deg=70.0)],
        slew_func=hold_slew,
        encoder_func=lambda: (0.0, 70.0),
        n_success_target=1,
        settle_after_slew_s=0.0,
        poll_interval_s=0.01,
    )
    mgr = NighttimeAutoManager()
    mgr.start(99, runner)
    try:
        with pytest.raises(RuntimeError, match="already"):
            mgr.start(99, runner)
    finally:
        block.set()
        runner.stop()
