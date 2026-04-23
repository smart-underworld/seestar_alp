"""Unit tests for device.plant_limits — cable-wrap limits + cum-az tracker
persistence."""

import json

import pytest

from device.plant_limits import AzimuthLimits, CumulativeAzTracker


def test_tracker_update_integrates_deltas():
    t = CumulativeAzTracker()
    assert t.update(10.0) == 10.0  # first update anchors
    assert t.update(15.0) == 15.0
    # Wrap through +180° → -175° is a +5° delta, not -355°.
    assert t.update(179.0) == pytest.approx(179.0)
    cum = t.update(-179.0)
    assert cum == pytest.approx(181.0)


def test_tracker_reset():
    t = CumulativeAzTracker()
    t.update(10.0)
    t.reset(cum_az_deg=200.0, wrapped_az_deg=-160.0)
    assert t.cum_az_deg == 200.0
    # Next update from wrapped=-159 gives +1° delta → 201.
    assert t.update(-159.0) == pytest.approx(201.0)


def test_save_load_roundtrip(tmp_path):
    path = str(tmp_path / "state.json")
    t = CumulativeAzTracker()
    t.reset(cum_az_deg=250.5, wrapped_az_deg=-109.5)
    t.save(path)

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["cum_az_deg"] == pytest.approx(250.5)
    assert payload["wrapped_az_deg"] == pytest.approx(-109.5)
    assert payload["initialized"] is True
    assert "saved_at_iso" in payload

    # Load with current matching saved → cum preserved (within drift).
    loaded = CumulativeAzTracker.load_or_fresh(
        current_wrapped_az_deg=-109.5,
        path=path,
    )
    assert loaded._initialized is True
    assert loaded.cum_az_deg == pytest.approx(250.5)


def test_load_or_fresh_missing_file(tmp_path):
    path = str(tmp_path / "does_not_exist.json")
    t = CumulativeAzTracker.load_or_fresh(
        current_wrapped_az_deg=42.0,
        path=path,
    )
    assert t._initialized is False
    assert t.cum_az_deg == 0.0
    # First update after a fresh load should anchor to the passed-in reading.
    assert t.update(42.0) == 42.0


def test_load_or_fresh_mismatch_resets(tmp_path, capsys):
    # Simulate a power-cycle: saved at wrapped=-109, current is +5 (home reset).
    path = str(tmp_path / "state.json")
    saved = CumulativeAzTracker()
    saved.reset(cum_az_deg=250.0, wrapped_az_deg=-109.0)
    saved.save(path)

    loaded = CumulativeAzTracker.load_or_fresh(
        current_wrapped_az_deg=5.0,
        path=path,
        tol_deg=2.0,
    )
    # Drift is 114°, far beyond 2° tolerance → fresh tracker.
    assert loaded._initialized is False
    assert loaded.cum_az_deg == 0.0
    err = capsys.readouterr().err
    assert "power-cycle" in err or "reset" in err


def test_load_or_fresh_absorbs_small_drift(tmp_path):
    path = str(tmp_path / "state.json")
    saved = CumulativeAzTracker()
    saved.reset(cum_az_deg=250.0, wrapped_az_deg=-110.0)
    saved.save(path)

    # Current is 0.5° away from saved — within 2° tolerance, so state loads
    # and the drift is absorbed into cum_az.
    loaded = CumulativeAzTracker.load_or_fresh(
        current_wrapped_az_deg=-109.5,
        path=path,
        tol_deg=2.0,
    )
    assert loaded._initialized is True
    assert loaded.cum_az_deg == pytest.approx(250.5)
    # Subsequent update from the same wrapped position produces no motion.
    assert loaded.update(-109.5) == pytest.approx(250.5)


def test_load_or_fresh_corrupt_json(tmp_path, capsys):
    path = str(tmp_path / "state.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("not-json }{{{")
    t = CumulativeAzTracker.load_or_fresh(
        current_wrapped_az_deg=10.0,
        path=path,
    )
    assert t._initialized is False
    err = capsys.readouterr().err
    assert "failed to load" in err


def test_azimuth_limits_contains_cum():
    lim = AzimuthLimits(
        ccw_hard_stop_cum_deg=-450.0,
        cw_hard_stop_cum_deg=450.0,
        padding_deg=15.0,
    )
    assert lim.usable_ccw_cum_deg == -435.0
    assert lim.usable_cw_cum_deg == 435.0
    assert lim.contains_cum(0.0)
    assert lim.contains_cum(-435.0)
    assert lim.contains_cum(435.0)
    assert not lim.contains_cum(-440.0)
    assert not lim.contains_cum(500.0)
