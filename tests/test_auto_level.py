"""Unit tests for device.auto_level: joint fit, tilt derivation, sign flip, I/O."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from device.auto_level import (
    AutoLevelSample,
    apply_sign_flip,
    azimuth_to_compass,
    build_guidance,
    collect_samples,
    fit_auto_level,
    load_run,
    planned_azimuths,
    positions_to_rows,
    save_run,
)


def _synth_samples(
    azimuths_deg: list[float],
    amplitude: float,
    uphill_az_deg: float,
    x_offset: float,
    y_offset: float,
    noise: float = 0.0,
    sensor_z: float | None = 1.0,
    angle_scale_deg_per_unit: float | None = None,
    seed: int = 0,
) -> list[AutoLevelSample]:
    """Generate synthetic samples matching the joint-fit model.

    Model:
      x(θ) = A·cos(θ − φ) + x₀
      y(θ) = A·sin(θ − φ) + y₀
    (y-axis is 90° CCW from x-axis in body frame.)
    """
    rng = np.random.default_rng(seed)
    samples: list[AutoLevelSample] = []
    for az_deg in azimuths_deg:
        phase = math.radians(az_deg - uphill_az_deg)
        x = amplitude * math.cos(phase) + x_offset
        y = amplitude * math.sin(phase) + y_offset
        if noise:
            x += rng.normal(0.0, noise)
            y += rng.normal(0.0, noise)
        angle: float | None = None
        if angle_scale_deg_per_unit is not None:
            # Device reports angle ≈ 0° when level; grows with tilt magnitude.
            raw_tilt_mag = amplitude
            angle = raw_tilt_mag * angle_scale_deg_per_unit
        samples.append(
            AutoLevelSample(
                azimuth_deg=az_deg,
                sensor_x=x,
                sensor_y=y,
                sensor_z=sensor_z,
                angle=angle,
            )
        )
    return samples


def test_fit_recovers_known_parameters_clean():
    azs = planned_azimuths(12)
    amplitude = 0.15
    uphill = 137.0
    x0, y0 = 0.03, -0.07
    samples = _synth_samples(azs, amplitude, uphill, x0, y0)

    fit = fit_auto_level(samples)

    assert fit.n_samples == 12
    assert fit.amplitude == pytest.approx(amplitude, abs=1e-9)
    assert fit.tilt_mount_az_deg == pytest.approx(uphill, abs=1e-4)
    assert fit.x_offset == pytest.approx(x0, abs=1e-9)
    assert fit.y_offset == pytest.approx(y0, abs=1e-9)
    assert fit.rms_residual < 1e-12


def test_fit_tolerates_noise():
    azs = planned_azimuths(12)
    amplitude = 0.2
    uphill = 42.0
    x0, y0 = 0.01, 0.02
    samples = _synth_samples(
        azs, amplitude, uphill, x0, y0, noise=0.01, seed=7
    )

    fit = fit_auto_level(samples)

    assert fit.amplitude == pytest.approx(amplitude, abs=0.02)
    assert fit.tilt_mount_az_deg == pytest.approx(uphill, abs=5.0)
    assert fit.x_offset == pytest.approx(x0, abs=0.01)
    assert fit.y_offset == pytest.approx(y0, abs=0.01)


def test_fit_level_tripod_gives_near_zero_amplitude():
    azs = planned_azimuths(12)
    samples = _synth_samples(
        azs, amplitude=0.0, uphill_az_deg=0.0,
        x_offset=0.02, y_offset=-0.03, noise=0.005, seed=3,
    )

    fit = fit_auto_level(samples)

    assert fit.amplitude < 0.02
    assert fit.tilt_deg < math.degrees(0.02)
    assert fit.x_offset == pytest.approx(0.02, abs=0.01)
    assert fit.y_offset == pytest.approx(-0.03, abs=0.01)


def test_tilt_deg_is_degrees_of_amplitude_over_mean_z():
    """The new derivation: tilt_deg = degrees(A / mean_z). No angle-field ratio."""
    azs = planned_azimuths(12)
    amplitude = 0.1
    samples = _synth_samples(
        azs, amplitude, uphill_az_deg=0.0,
        x_offset=0.0, y_offset=0.0, sensor_z=1.0,
    )
    fit = fit_auto_level(samples)

    assert fit.mean_z == pytest.approx(1.0)
    assert fit.tilt_deg == pytest.approx(math.degrees(amplitude), abs=1e-6)


def test_tilt_deg_uses_mean_z_as_scale_normalizer():
    """If sensor gain drifts (mean_z != 1), tilt_deg compensates correctly."""
    azs = planned_azimuths(12)
    amplitude = 0.1
    gain = 1.05  # sensor reports 5% too high
    samples = _synth_samples(
        azs, amplitude * gain, uphill_az_deg=0.0,
        x_offset=0.0, y_offset=0.0, sensor_z=gain,
    )
    fit = fit_auto_level(samples)

    # Recovered A would be amplitude*gain, but divided by mean_z=gain gives
    # back the true tilt-in-radians.
    assert fit.tilt_deg == pytest.approx(math.degrees(amplitude), abs=1e-6)


def test_tilt_deg_defaults_to_mean_z_one_when_z_missing():
    azs = planned_azimuths(12)
    amplitude = 0.1
    samples = _synth_samples(
        azs, amplitude, uphill_az_deg=0.0,
        x_offset=0.0, y_offset=0.0, sensor_z=None,
    )
    fit = fit_auto_level(samples)
    assert fit.mean_z == pytest.approx(1.0)
    assert fit.tilt_deg == pytest.approx(math.degrees(amplitude), abs=1e-6)


def test_joint_fit_tighter_than_per_axis_on_noisy_data():
    """Joint fit should match per-axis fits on clean data, and not diverge on noise."""
    azs = planned_azimuths(12)
    amplitude = 0.15
    uphill = 80.0
    samples = _synth_samples(
        azs, amplitude, uphill, x_offset=0.0, y_offset=0.0,
        noise=0.005, seed=42,
    )
    fit = fit_auto_level(samples)

    # Both per-axis fits should recover similar amplitudes (within the noise).
    assert abs(fit.x_axis.amplitude - fit.y_axis.amplitude) < 0.02
    # With y = A·sin(θ − φ) and x = A·cos(θ − φ), the y-axis per-axis fit
    # reports a phase 90° ahead of the x-axis phase (mod 360).
    dp = (fit.y_axis.phase_deg - fit.x_axis.phase_deg) % 360.0
    # Normalize distance-from-90 into [0, 180].
    off = min(abs(dp - 90.0), abs(dp - 90.0 - 360.0), abs(dp - 90.0 + 360.0))
    assert off < 10.0  # within noise tolerance
    # Joint amplitude should agree with per-axis averages to noise scale.
    axis_mean = 0.5 * (fit.x_axis.amplitude + fit.y_axis.amplitude)
    assert abs(fit.amplitude - axis_mean) < 0.01


def test_fit_requires_minimum_samples():
    with pytest.raises(ValueError):
        fit_auto_level([
            AutoLevelSample(0, 0, 0),
            AutoLevelSample(90, 0, 0),
            AutoLevelSample(180, 0, 0),
        ])


def test_planned_azimuths_spacing():
    azs = planned_azimuths(12)
    assert len(azs) == 12
    # Values are wrapped into [-180, +180): -180 inclusive, +180 exclusive.
    assert azs[0] == 0.0
    assert azs[1] == pytest.approx(30.0)
    assert azs[5] == pytest.approx(150.0)
    assert azs[6] == pytest.approx(-180.0)  # 180 wraps to -180
    assert azs[-1] == pytest.approx(-30.0)
    # All values inside the half-open range.
    assert all(-180.0 <= a < 180.0 for a in azs)


def test_azimuth_to_compass_cardinals():
    assert azimuth_to_compass(0) == "N"
    assert azimuth_to_compass(90) == "E"
    assert azimuth_to_compass(180) == "S"
    assert azimuth_to_compass(270) == "W"
    assert azimuth_to_compass(45) == "NE"
    assert azimuth_to_compass(359) == "N"
    # New-range inputs should also classify correctly.
    assert azimuth_to_compass(-180) == "S"
    assert azimuth_to_compass(-90) == "W"
    assert azimuth_to_compass(-1) == "N"


def test_planned_azimuths_wrap_boundary_is_inclusive_at_minus_180():
    """With num_samples=2 starting at 0°, the step of 180° must land at -180,
    never at +180. -180 is inclusive, +180 is exclusive."""
    azs = planned_azimuths(2)
    assert azs == [0.0, -180.0]


def test_fit_phase_stays_in_pm180():
    """Fits whose phase lands near ±180° must report it as -180, not +180."""
    azs = planned_azimuths(12)
    samples = _synth_samples(azs, 0.1, 180.0, 0.0, 0.0)
    fit = fit_auto_level(samples)
    assert -180.0 <= fit.tilt_mount_az_deg < 180.0
    assert fit.tilt_mount_az_deg == pytest.approx(-180.0, abs=1e-4)


def test_apply_sign_flip_rotates_by_180_when_true():
    azs = planned_azimuths(12)
    samples = _synth_samples(azs, 0.1, 45.0, 0.0, 0.0)
    fit = fit_auto_level(samples)
    assert fit.tilt_mount_az_deg == pytest.approx(45.0, abs=1e-4)

    unflipped = apply_sign_flip(fit, False)
    assert unflipped.uphill_world_az_deg == pytest.approx(45.0, abs=1e-4)

    # 45 + 180 = 225 wraps to -135 in the [-180, +180) range.
    flipped = apply_sign_flip(fit, True)
    assert flipped.uphill_world_az_deg == pytest.approx(-135.0, abs=1e-4)


def test_build_guidance_without_anchor_mentions_mount_az_only():
    azs = planned_azimuths(12)
    samples = _synth_samples(azs, 0.1, 45.0, 0.0, 0.0)
    fit = fit_auto_level(samples)  # no apply_sign_flip

    guidance = build_guidance(fit, tolerance_deg=0.1)
    assert guidance.is_level is False
    assert guidance.uphill_world_az_deg is None
    assert guidance.uphill_compass is None
    assert "mount-az" in guidance.message.lower()


def test_build_guidance_with_anchor_names_compass_side():
    azs = planned_azimuths(12)
    samples = _synth_samples(azs, 0.1, 90.0, 0.0, 0.0)
    fit = apply_sign_flip(fit_auto_level(samples), False)  # uphill=E

    guidance = build_guidance(fit, tolerance_deg=0.1)
    assert guidance.is_level is False
    assert guidance.uphill_compass == "E"
    assert "E" in guidance.message


def test_build_guidance_level_state():
    azs = planned_azimuths(12)
    samples = _synth_samples(
        azs, amplitude=0.0, uphill_az_deg=0.0,
        x_offset=0.01, y_offset=0.02, noise=0.0001, seed=1,
    )
    fit = fit_auto_level(samples)
    guidance = build_guidance(fit, tolerance_deg=0.1)

    assert guidance.is_level is True
    assert "level" in guidance.message.lower()


def test_collect_samples_drives_loop_and_round_trips_fit():
    """End-to-end: drive orchestrator with a fake scope, confirm fit matches."""
    amplitude = 0.25
    uphill = -160.0  # equivalently 200°, but in the new [-180, +180) range
    x0, y0 = 0.05, -0.1

    class FakeScope:
        def __init__(self):
            self.current_az = 0.0

        def move_to_az(self, az_deg, alt_deg):
            self.current_az = az_deg

        def read_sensor(self):
            phase = math.radians(self.current_az - uphill)
            return (
                amplitude * math.cos(phase) + x0,
                amplitude * math.sin(phase) + y0,
                90.0 - amplitude * 30.0,
            )

    scope = FakeScope()
    samples = collect_samples(
        scope.move_to_az, scope.read_sensor,
        num_samples=12, altitude_deg=5.0,
        settle_seconds=0.0, sleep=lambda _: None,
    )
    assert len(samples) == 12

    # collect_samples doesn't capture z; add sensor_z=1.0 for the fit.
    for s in samples:
        s.sensor_z = 1.0

    fit = fit_auto_level(samples)
    assert fit.amplitude == pytest.approx(amplitude, abs=1e-6)
    assert fit.tilt_mount_az_deg == pytest.approx(uphill, abs=1e-3)
    assert fit.x_offset == pytest.approx(x0, abs=1e-6)
    assert fit.y_offset == pytest.approx(y0, abs=1e-6)


# ---------------------------------------------------------------------------
# save_run / load_run round-trip
# ---------------------------------------------------------------------------


def _mk_run_positions():
    positions = []
    for i, az in enumerate(planned_azimuths(4)):
        positions.append({
            "index": i,
            "azimuth_deg": az,
            "target_alt_deg": 10.0,
            "target_ra_h": 0.5 + 0.01 * i,
            "target_dec_deg": 60.0,
            "arrived_dist_deg": 0.3,
            "slew_attempts": 1,
            "nudged": True,
            "reads": [
                {"t_offset_s": 0.0, "x": 0.01, "y": 0.02, "z": 0.999, "angle": 1.2, "heading": 100.0 + i},
                {"t_offset_s": 0.1, "x": 0.011, "y": 0.019, "z": 0.9995, "angle": 1.25, "heading": 100.0 + i},
            ],
        })
    return positions


def test_save_run_and_load_run_round_trip(tmp_path):
    positions = _mk_run_positions()
    meta = {
        "run_id": "test-run-1",
        "started_at": "2026-04-20T07:30:00.000Z",
        "config": {"samples": 4, "alt_deg": 10.0, "reads_per_position": 2, "lat": 33.98, "long": -118.45},
    }
    path = tmp_path / "run.json"
    save_run(path, meta, positions)

    loaded_meta, loaded_positions, samples = load_run(path)
    assert loaded_meta["run_id"] == "test-run-1"
    assert loaded_meta["config"]["samples"] == 4
    assert len(loaded_positions) == len(positions)
    assert len(samples) == len(positions)
    # Verify sample means are computed correctly.
    for pos, sample in zip(positions, samples):
        reads = pos["reads"]
        exp_x = sum(r["x"] for r in reads) / len(reads)
        exp_y = sum(r["y"] for r in reads) / len(reads)
        exp_z = sum(r["z"] for r in reads) / len(reads)
        exp_a = sum(r["angle"] for r in reads) / len(reads)
        assert sample.azimuth_deg == pos["azimuth_deg"]
        assert sample.sensor_x == pytest.approx(exp_x)
        assert sample.sensor_y == pytest.approx(exp_y)
        assert sample.sensor_z == pytest.approx(exp_z)
        assert sample.angle == pytest.approx(exp_a)


def test_load_run_rejects_unknown_version(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 999, "positions": []}))
    with pytest.raises(ValueError):
        load_run(path)


def test_save_run_writes_atomically_and_is_rereadable_after_rewrite(tmp_path):
    """Incremental writes: after each rewrite the file should be valid JSON."""
    path = tmp_path / "run.json"
    meta = {"run_id": "r", "started_at": "t0", "config": {}}

    positions: list[dict] = []
    for i in range(3):
        positions.append({
            "index": i,
            "azimuth_deg": i * 120.0,
            "reads": [{"t_offset_s": 0.0, "x": i * 0.01, "y": 0.0, "z": 1.0, "angle": 0.0, "heading": 0.0}],
        })
        save_run(path, meta, positions)
        data = json.loads(path.read_text())
        assert len(data["positions"]) == i + 1


def test_positions_to_rows_includes_means_and_stds():
    positions = _mk_run_positions()
    rows = positions_to_rows(positions)
    assert len(rows) == 4
    for row in rows:
        assert "az" in row
        assert "x_mean" in row and "x_std" in row
        # With 2 reads per position, stdev is defined.
        assert row["n"] == 2
        assert row["x_std"] is not None
