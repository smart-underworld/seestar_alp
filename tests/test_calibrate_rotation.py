"""Unit tests for scripts.trajectory.calibrate_rotation.

Synthetic-data tests only — no hardware, no network. The REPL + mount
control paths are out of scope; we exercise the solver against
known-rotation synthesized sightings.
"""

from __future__ import annotations

import json

import pytest

from device.target_frame import MountFrame
from scripts.trajectory.calibrate_rotation import (
    RotationSolution,
    Sighting,
    solve_rotation,
    terrestrial_refraction_deg,
    write_calibration,
)
from scripts.trajectory.faa_dof import (
    CULVER_CITY_06_001087,
    HYPERION_06_000301,
    Landmark,
)
from scripts.trajectory.observer import build_site


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
