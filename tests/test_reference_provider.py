"""Tests for device.reference_provider.JsonlECEFProvider.

Use the same synthetic straight-flight fixture from test_trajectory_pipeline
so the provider's output can be checked against analytically-known geometry
and against the vetted smoothed-finite-diff arrays already used by replay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from device.reference_provider import JsonlECEFProvider, ReferenceSample
from device.target_frame import MountFrame
from tests.test_trajectory_pipeline import make_straight_aircraft


@pytest.fixture
def fixture_path(tmp_path) -> Path:
    header, samples = make_straight_aircraft()
    path = tmp_path / "TEST123_abcdef_1700000000.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for s in samples:
            f.write(json.dumps(s) + "\n")
    return path


def test_valid_range_matches_input(fixture_path):
    mf = MountFrame.from_identity_enu()
    p = JsonlECEFProvider(fixture_path, mf)
    t0, t1 = p.valid_range()
    assert t0 == 1_700_000_000.0
    assert t1 == pytest.approx(1_700_000_000.0 + 120.0, abs=1e-6)


def test_sample_at_head_matches_raw(fixture_path):
    """Spline at the boundary should equal the raw JSONL az/el."""
    mf = MountFrame.from_identity_enu()
    p = JsonlECEFProvider(fixture_path, mf)
    t0, _ = p.valid_range()
    s = p.sample(t0)
    # Raw first sample from the fixture has az/el computed via the same
    # chain; identity MountFrame + same observer == same values within
    # numerical tolerance.
    assert isinstance(s, ReferenceSample)
    assert not s.stale
    assert not s.extrapolated
    # On a west-east flight starting 6 km west + 5 km north of observer
    # the azimuth at t=0 is in the low 300s (≈ 309°).
    assert 300.0 <= s.az_cum_deg <= 320.0


def test_sample_interior_smooth(fixture_path):
    """A point between raw samples should give interpolated v, a consistent
    with the spline derivative (i.e. position + 0.01·velocity ≈ next position)."""
    mf = MountFrame.from_identity_enu()
    p = JsonlECEFProvider(fixture_path, mf)
    t0, _ = p.valid_range()
    s1 = p.sample(t0 + 60.0)
    s2 = p.sample(t0 + 60.01)
    # Finite-difference check: position predicted from v matches next sample.
    predicted_az = s1.az_cum_deg + s1.v_az_degs * 0.01
    predicted_el = s1.el_deg + s1.v_el_degs * 0.01
    assert s2.az_cum_deg == pytest.approx(predicted_az, abs=0.01)
    assert s2.el_deg == pytest.approx(predicted_el, abs=0.01)


def test_sample_before_head_raises(fixture_path):
    mf = MountFrame.from_identity_enu()
    p = JsonlECEFProvider(fixture_path, mf)
    t0, _ = p.valid_range()
    with pytest.raises(ValueError):
        p.sample(t0 - 1.0)


def test_sample_within_extrapolation_not_stale(fixture_path):
    mf = MountFrame.from_identity_enu()
    p = JsonlECEFProvider(fixture_path, mf, extrapolation_s=1.0)
    _, t1 = p.valid_range()
    s = p.sample(t1 + 0.5)
    assert s.extrapolated
    assert not s.stale


def test_sample_past_extrapolation_stale(fixture_path):
    mf = MountFrame.from_identity_enu()
    p = JsonlECEFProvider(fixture_path, mf, extrapolation_s=1.0)
    _, t1 = p.valid_range()
    s = p.sample(t1 + 1.5)
    assert s.extrapolated
    assert s.stale


def test_iter_ticks_covers_range(fixture_path):
    mf = MountFrame.from_identity_enu()
    p = JsonlECEFProvider(fixture_path, mf)
    ticks = p.iter_ticks(tick_dt=0.5)
    # 120 s range, 0.5 s ticks, inclusive → 241 samples.
    assert len(ticks) == 241
    assert all(not s.stale and not s.extrapolated for s in ticks)


def test_rejects_too_few_samples(tmp_path):
    path = tmp_path / "short.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "header", "source": "adsb"}) + "\n")
        for i in range(3):
            f.write(json.dumps({
                "kind": "sample", "t_unix": float(i),
                "ecef_x": 0.0, "ecef_y": 0.0, "ecef_z": 0.0,
                "az_deg": 0.0, "el_deg": 0.0, "slant_m": 0.0,
            }) + "\n")
    mf = MountFrame.from_identity_enu()
    with pytest.raises(ValueError):
        JsonlECEFProvider(path, mf)
