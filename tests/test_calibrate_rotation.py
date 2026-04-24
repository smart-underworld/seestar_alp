"""Unit tests for scripts.trajectory.calibrate_rotation.

Synthetic-data tests only — no hardware, no network. The REPL + mount
control paths are out of scope; we exercise the solver against
known-rotation synthesized sightings.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from device.target_frame import MountFrame
from scripts.trajectory.calibrate_rotation import (
    PriorInfo,
    RotationSolution,
    Sighting,
    _altitude_menu,
    _handle_clear_or_keep,
    _inspect_prior,
    _parse_calibrated_at,
    _resolve_altitude,
    solve_rotation,
    terrestrial_refraction_deg,
    write_calibration,
)
from scripts.trajectory.faa_dof import (
    CULVER_CITY_06_001087,
    HYPERION_06_000301,
    Landmark,
)
from scripts.trajectory.observer import build_site, haversine_m, lookup_elevation


DOCKWEILER = dict(lat_deg=33.9615051, lon_deg=-118.4581361, alt_m=2.0)


def _synth_sighting(
    landmark: Landmark, site, yaw: float, pitch: float, roll: float,
) -> Sighting:
    """Forward-model: for a given rotation, produce what the encoder
    would read when the scope is exactly on the landmark (including
    the terrestrial-refraction lift applied by the solver)."""
    mf = MountFrame.from_euler_deg(
        yaw_deg=yaw, pitch_deg=pitch, roll_deg=roll, site=site,
    )
    az, el, slant = mf.ecef_to_mount_azel(landmark.ecef())
    # Match the solver: the scope sees the apparent (refracted) el.
    el_apparent = el + terrestrial_refraction_deg(slant)
    # Match the encoder convention: wrap az into [-180, 180).
    az_wrapped = ((az + 180.0) % 360.0) - 180.0
    mf_id = MountFrame.from_identity_enu(site)
    true_az, true_el, _ = mf_id.ecef_to_mount_azel(landmark.ecef())
    return Sighting(
        landmark=landmark,
        encoder_az_deg=az_wrapped,
        encoder_el_deg=el_apparent,
        true_az_deg=true_az,
        true_el_deg=true_el,
        slant_m=slant,
        t_unix=0.0,
    )


def test_solver_recovers_known_rotation_yaw_only():
    """Inject a 12° yaw offset; solver must recover it."""
    site = build_site(**DOCKWEILER)
    yaw_true, pitch_true, roll_true = 12.0, 0.0, 0.0
    sightings = [
        _synth_sighting(HYPERION_06_000301, site, yaw_true, pitch_true, roll_true),
        _synth_sighting(CULVER_CITY_06_001087, site, yaw_true, pitch_true, roll_true),
    ]
    sol = solve_rotation(sightings, site)
    assert sol.yaw_deg == pytest.approx(yaw_true, abs=0.01)
    assert sol.pitch_deg == pytest.approx(pitch_true, abs=0.01)
    assert sol.roll_deg == pytest.approx(roll_true, abs=0.01)
    assert sol.residual_rms_deg < 0.01


def test_solver_recovers_small_tilt():
    """Yaw + small pitch + small roll — realistic tripod tilt."""
    site = build_site(**DOCKWEILER)
    yaw_true, pitch_true, roll_true = -25.0, 0.8, -0.3
    sightings = [
        _synth_sighting(HYPERION_06_000301, site, yaw_true, pitch_true, roll_true),
        _synth_sighting(CULVER_CITY_06_001087, site, yaw_true, pitch_true, roll_true),
    ]
    sol = solve_rotation(sightings, site)
    # With only 2 sightings we can end up in a local min for the
    # under-constrained pitch/roll split, but the residuals must be
    # tiny and the composite rotation must match.
    assert sol.residual_rms_deg < 0.05
    # Reconstruct the rotation and verify it maps both landmarks back
    # to the synthesized encoder (az, el) within 0.05°.
    mf_sol = MountFrame.from_euler_deg(
        yaw_deg=sol.yaw_deg, pitch_deg=sol.pitch_deg, roll_deg=sol.roll_deg, site=site,
    )
    for s in sightings:
        az, el, _ = mf_sol.ecef_to_mount_azel(s.landmark.ecef())
        az_w = ((az + 180.0) % 360.0) - 180.0
        d_az = ((az_w - s.encoder_az_deg + 180.0) % 360.0) - 180.0
        assert abs(d_az) < 0.05
        assert abs(el - s.encoder_el_deg) < 0.05


def test_solver_rejects_zero_sightings():
    site = build_site(**DOCKWEILER)
    with pytest.raises(ValueError):
        solve_rotation([], site)


def test_solver_auto_mode_single_sighting_fits_yaw_only():
    """With 1 sighting, `dof='auto'` should fit yaw only, leaving
    pitch/roll at the seed values (default 0)."""
    site = build_site(**DOCKWEILER)
    # Synthesize at pure yaw so the single-sighting fit has a clean
    # answer; pitch/roll must come back at 0 since we lock them.
    one = [_synth_sighting(HYPERION_06_000301, site, 15.0, 0.0, 0.0)]
    sol = solve_rotation(one, site)
    assert sol.yaw_deg == pytest.approx(15.0, abs=0.02)
    assert sol.pitch_deg == 0.0
    assert sol.roll_deg == 0.0
    # Residual at the single point should be near zero.
    assert sol.residual_rms_deg < 0.01


def test_solver_dof_yaw_forces_yaw_only_even_with_two_sightings():
    site = build_site(**DOCKWEILER)
    yaw_true = -45.0
    two = [
        _synth_sighting(HYPERION_06_000301, site, yaw_true, 0.0, 0.0),
        _synth_sighting(CULVER_CITY_06_001087, site, yaw_true, 0.0, 0.0),
    ]
    sol = solve_rotation(two, site, dof="yaw")
    assert sol.yaw_deg == pytest.approx(yaw_true, abs=0.02)
    assert sol.pitch_deg == 0.0
    assert sol.roll_deg == 0.0


def test_terrestrial_refraction_matches_datasheet():
    """At k=0.13 the apparent el lift for Hyperion (5.5 km) is ~0.003°
    and for Culver City (9.2 km) is ~0.005°, per the user's datasheet."""
    hyperion = terrestrial_refraction_deg(5523.0)
    culver = terrestrial_refraction_deg(9180.0)
    assert hyperion == pytest.approx(0.003, abs=0.001)
    assert culver == pytest.approx(0.005, abs=0.001)
    # Monotone in distance.
    assert terrestrial_refraction_deg(20000.0) > culver
    # Degenerate: zero slant → zero correction.
    assert terrestrial_refraction_deg(0.0) == 0.0


def test_write_calibration_produces_readable_schema(tmp_path):
    """Round-trip: write → MountFrame.from_calibration_json reads back."""
    site = build_site(**DOCKWEILER)
    sol = RotationSolution(
        yaw_deg=-75.123, pitch_deg=0.2, roll_deg=-0.1,
        residual_rms_deg=0.08,
        per_landmark=[
            {
                "oas": "06-000301", "name": "Hyperion",
                "lat_deg": 33.918889, "lon_deg": -118.427223,
                "height_amsl_m": 103.3,
                "encoder_az_deg": 73.75, "encoder_el_deg": 1.03,
                "true_az_deg": 148.87, "true_el_deg": 1.03,
                "slant_m": 5523.0,
                "predicted_az_deg": 73.75, "predicted_el_deg": 1.03,
                "residual_az_deg": 0.0, "residual_el_deg": 0.0,
            },
        ],
    )
    out = tmp_path / "cal.json"
    write_calibration(out, sol, site, sol.per_landmark)
    # Required schema fields.
    payload = json.loads(out.read_text())
    assert payload["yaw_offset_deg"] == pytest.approx(-75.123)
    assert payload["pitch_offset_deg"] == pytest.approx(0.2)
    assert payload["roll_offset_deg"] == pytest.approx(-0.1)
    assert payload["origin_offset_ecef_m"] == [0.0, 0.0, 0.0]
    assert payload["calibration_method"] == "rotation_landmarks"
    assert payload["observer"]["lat_deg"] == pytest.approx(DOCKWEILER["lat_deg"])
    assert payload["observer"]["lon_deg"] == pytest.approx(DOCKWEILER["lon_deg"])
    assert payload["observer"]["alt_m"] == pytest.approx(DOCKWEILER["alt_m"])
    # Readable via MountFrame.from_calibration_json with embedded observer.
    mf = MountFrame.from_calibration_json(out)
    assert mf.site.lat_deg == pytest.approx(DOCKWEILER["lat_deg"], abs=1e-9)


def test_write_calibration_parents_created(tmp_path):
    """Nested path gets its parent dir created."""
    site = build_site(**DOCKWEILER)
    sol = RotationSolution(yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0,
                           residual_rms_deg=0.0, per_landmark=[])
    out = tmp_path / "nested" / "dir" / "cal.json"
    write_calibration(out, sol, site, [])
    assert out.exists()


# ---------- haversine + elevation lookup -----------------------------


def test_haversine_known_distance():
    """Two points 1° latitude apart on the same meridian ≈ 111.2 km.
    Used as an independent cross-check of the helper."""
    d = haversine_m(0.0, 0.0, 1.0, 0.0)
    assert d == pytest.approx(111_200.0, rel=0.002)


def test_haversine_same_point_is_zero():
    assert haversine_m(33.96, -118.46, 33.96, -118.46) == 0.0


def test_lookup_elevation_happy(monkeypatch):
    """Open-Meteo returns {"elevation": [2.0]} — we return 2.0."""
    class _FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"elevation": [2.3]}

    called = {}
    def fake_get(url, params=None, timeout=None):
        called["url"] = url
        called["params"] = params
        return _FakeResp()
    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    assert lookup_elevation(33.96, -118.46) == pytest.approx(2.3)
    assert "api.open-meteo.com" in called["url"]
    assert called["params"]["latitude"].startswith("33.")
    assert called["params"]["longitude"].startswith("-118.")


def test_lookup_elevation_raises_on_http_error(monkeypatch):
    import requests
    def bad_get(url, params=None, timeout=None):
        raise requests.ConnectionError("no network")
    monkeypatch.setattr(requests, "get", bad_get)
    with pytest.raises(RuntimeError, match="elevation lookup failed"):
        lookup_elevation(33.96, -118.46)


def test_lookup_elevation_raises_on_malformed_payload(monkeypatch):
    class _FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"elevation": "not a list"}
    import requests
    monkeypatch.setattr(
        requests, "get",
        lambda url, params=None, timeout=None: _FakeResp(),
    )
    with pytest.raises(RuntimeError, match="malformed"):
        lookup_elevation(0.0, 0.0)


# ---------- _parse_calibrated_at -------------------------------------


def test_parse_calibrated_at_legacy_dash_format():
    """The shipped calibrate_compass output uses dashes everywhere
    including the timezone offset; fromisoformat can't read that."""
    dt = _parse_calibrated_at("2026-04-21T23-28-52-0700")
    assert dt is not None
    # UTC-7 → UTC: 23:28:52 -07:00 == 06:28:52 UTC next day
    assert dt.tzinfo is timezone.utc
    assert dt.year == 2026 and dt.month == 4 and dt.day == 22
    assert dt.hour == 6 and dt.minute == 28 and dt.second == 52


def test_parse_calibrated_at_iso_colon_format():
    dt = _parse_calibrated_at("2026-04-22T06:28:52+00:00")
    assert dt is not None
    assert dt.hour == 6 and dt.minute == 28


def test_parse_calibrated_at_none_on_missing_or_bad():
    assert _parse_calibrated_at(None) is None
    assert _parse_calibrated_at("") is None
    assert _parse_calibrated_at("not a timestamp") is None


# ---------- _inspect_prior + _handle_clear_or_keep -------------------


def _write_prior(
    path, *, lat, lon, alt, ts_iso,
) -> None:
    path.write_text(json.dumps({
        "yaw_offset_deg": -79.0, "residual_rms_deg": 0.2,
        "calibrated_at": ts_iso,
        "observer": {"lat_deg": lat, "lon_deg": lon, "alt_m": alt},
    }))


def _now_dash(offset_hours: float = 0.0) -> str:
    """Build a dash-style timestamp offset by `offset_hours` from now."""
    dt = datetime.now(timezone.utc) - timedelta(hours=offset_hours)
    return dt.strftime("%Y-%m-%dT%H-%M-%S%z")


def test_inspect_prior_missing_file(tmp_path):
    assert _inspect_prior(tmp_path / "nope.json", 0.0, 0.0) is None


def test_inspect_prior_recent_local_defaults_keep(tmp_path):
    p = tmp_path / "cal.json"
    _write_prior(p, lat=33.96, lon=-118.46, alt=2.0,
                 ts_iso=_now_dash(offset_hours=1.0))
    info = _inspect_prior(p, current_lat=33.96, current_lon=-118.46)
    assert info is not None
    assert info.age_s is not None and info.age_s < 6 * 3600
    assert info.distance_from_current_m is not None
    assert info.distance_from_current_m < 10.0
    assert info.should_default_keep is True


def test_inspect_prior_stale_defaults_clear(tmp_path):
    p = tmp_path / "cal.json"
    _write_prior(p, lat=33.96, lon=-118.46, alt=2.0,
                 ts_iso=_now_dash(offset_hours=10.0))
    info = _inspect_prior(p, current_lat=33.96, current_lon=-118.46)
    assert info.should_default_keep is False


def test_inspect_prior_moved_defaults_clear(tmp_path):
    p = tmp_path / "cal.json"
    _write_prior(p, lat=33.96, lon=-118.46, alt=2.0,
                 ts_iso=_now_dash(offset_hours=0.0))
    # Current GPS 50 m north of prior — well beyond the 10 m threshold.
    info = _inspect_prior(p, current_lat=33.96 + 50 / 111_320.0,
                          current_lon=-118.46)
    assert info.should_default_keep is False


def test_inspect_prior_without_observer_block_cannot_default_keep(tmp_path):
    """Legacy compass output has no `observer` block; fail safe →
    default clear."""
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({
        "yaw_offset_deg": -79.0, "residual_rms_deg": 0.2,
        "calibrated_at": _now_dash(offset_hours=0.1),
    }))
    info = _inspect_prior(p, 33.96, -118.46)
    assert info is not None
    assert info.observer_lat_deg is None
    assert info.should_default_keep is False


def _fake_args(**overrides):
    return argparse.Namespace(
        yes_clear=overrides.get("yes_clear", False),
        keep_prior=overrides.get("keep_prior", False),
        altitude_m=overrides.get("altitude_m", None),
        altitude_source=overrides.get("altitude_source", "menu"),
    )


def test_handle_clear_or_keep_default_keep(monkeypatch, tmp_path):
    """Recent+local prior, user hits Enter → keep, file stays."""
    p = tmp_path / "cal.json"
    _write_prior(p, lat=33.96, lon=-118.46, alt=2.0,
                 ts_iso=_now_dash(offset_hours=0.5))
    prior = _inspect_prior(p, 33.96, -118.46)
    monkeypatch.setattr("builtins.input", lambda _p: "")  # Enter
    kept = _handle_clear_or_keep(_fake_args(), prior)
    assert kept is True
    assert p.exists()
    assert not (p.with_suffix(p.suffix + ".bak")).exists()


def test_handle_clear_or_keep_default_clear(monkeypatch, tmp_path):
    """Stale prior, user hits Enter → clear, backed up to .bak."""
    p = tmp_path / "cal.json"
    _write_prior(p, lat=33.96, lon=-118.46, alt=2.0,
                 ts_iso=_now_dash(offset_hours=20.0))
    prior = _inspect_prior(p, 33.96, -118.46)
    monkeypatch.setattr("builtins.input", lambda _p: "")
    kept = _handle_clear_or_keep(_fake_args(), prior)
    assert kept is False
    assert not p.exists()
    assert (p.with_suffix(p.suffix + ".bak")).exists()


def test_handle_clear_or_keep_yes_flag_forces_clear(tmp_path):
    """`--yes-clear` bypasses the prompt even for a fresh prior."""
    p = tmp_path / "cal.json"
    _write_prior(p, lat=33.96, lon=-118.46, alt=2.0,
                 ts_iso=_now_dash(offset_hours=0.1))
    prior = _inspect_prior(p, 33.96, -118.46)
    kept = _handle_clear_or_keep(_fake_args(yes_clear=True), prior)
    assert kept is False
    assert not p.exists()


def test_handle_clear_or_keep_keep_flag_forces_keep(tmp_path):
    """`--keep-prior` bypasses the prompt even for a stale prior."""
    p = tmp_path / "cal.json"
    _write_prior(p, lat=33.96, lon=-118.46, alt=2.0,
                 ts_iso=_now_dash(offset_hours=30.0))
    prior = _inspect_prior(p, 33.96, -118.46)
    kept = _handle_clear_or_keep(_fake_args(keep_prior=True), prior)
    assert kept is True
    assert p.exists()


def test_handle_clear_or_keep_no_prior_returns_false(tmp_path):
    assert _handle_clear_or_keep(_fake_args(), None) is False


# ---------- _resolve_altitude + menu ---------------------------------


def _prior(lat=33.96, lon=-118.46, alt=5.0, dist=1.0):
    return PriorInfo(
        path=__import__("pathlib").Path("/nonexistent"),
        observer_lat_deg=lat, observer_lon_deg=lon, observer_alt_m=alt,
        calibrated_at=datetime.now(timezone.utc),
        age_s=3600.0, distance_from_current_m=dist,
    )


def test_resolve_altitude_flag_wins(monkeypatch):
    """`--altitude-m 30` skips every source."""
    # input() must NOT be called; if it is, raise so the test fails.
    monkeypatch.setattr(
        "builtins.input",
        lambda _p: (_ for _ in ()).throw(AssertionError("should not prompt")),
    )
    val = _resolve_altitude(_fake_args(altitude_m=30.0), 33.96, -118.46, None, False)
    assert val == 30.0


def test_resolve_altitude_source_prior_requires_prior(monkeypatch):
    with pytest.raises(SystemExit, match="prior"):
        _resolve_altitude(_fake_args(altitude_source="prior"),
                          33.96, -118.46, None, False)


def test_resolve_altitude_source_prior_uses_it(monkeypatch):
    prior = _prior(alt=7.5, dist=1.0)
    val = _resolve_altitude(
        _fake_args(altitude_source="prior"),
        33.96, -118.46, prior, prior_kept=True,
    )
    assert val == pytest.approx(7.5)


def test_resolve_altitude_source_lookup(monkeypatch):
    """--altitude-source lookup calls Open-Meteo directly, no menu."""
    with mock.patch(
        "scripts.trajectory.calibrate_rotation.lookup_elevation",
        return_value=4.2,
    ) as m:
        val = _resolve_altitude(
            _fake_args(altitude_source="lookup"), 33.96, -118.46, None, False,
        )
    assert val == pytest.approx(4.2)
    m.assert_called_once_with(33.96, -118.46)


def test_resolve_altitude_source_prompt(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "99.5")
    val = _resolve_altitude(
        _fake_args(altitude_source="prompt"), 33.96, -118.46, None, False,
    )
    assert val == pytest.approx(99.5)


def test_altitude_menu_default_lookup_no_prior(monkeypatch):
    """With no prior available, default should be [1] lookup."""
    monkeypatch.setattr("builtins.input", lambda _p: "")  # accept default
    with mock.patch(
        "scripts.trajectory.calibrate_rotation.lookup_elevation",
        return_value=2.0,
    ) as m:
        val = _altitude_menu(33.96, -118.46, prior=None, prior_available=False)
    assert val == 2.0
    m.assert_called_once()


def test_altitude_menu_prior_becomes_default(monkeypatch):
    """When prior is local, the menu's default shifts to [2] prior."""
    monkeypatch.setattr("builtins.input", lambda _p: "")  # accept default
    prior = _prior(alt=11.0)
    val = _altitude_menu(
        33.96, -118.46, prior=prior, prior_available=True,
    )
    assert val == pytest.approx(11.0)


def test_altitude_menu_lookup_failure_falls_back(monkeypatch):
    """If lookup throws RuntimeError the menu redisplays; user picks
    manual. Without a prior, the menu has only 2 options:
      [1] lookup, [2] manual."""
    answers = iter(["1", "2", "15.5"])  # try lookup → pick manual → value
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))
    with mock.patch(
        "scripts.trajectory.calibrate_rotation.lookup_elevation",
        side_effect=RuntimeError("no net"),
    ):
        val = _altitude_menu(
            33.96, -118.46, prior=None, prior_available=False,
        )
    assert val == pytest.approx(15.5)
