import json
import math
import os
import threading

import pytest
import tomlkit
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.utils import iers

from device import horizon
from device.config import Config
from device.horizon import HorizonError, HorizonProfile, HorizonSaveError
from device.seestar_util import Util


@pytest.fixture(autouse=True)
def _fresh_cache():
    horizon._cache.update(key=None, profile=None, error=None)
    yield
    horizon._cache.update(key=None, profile=None, error=None)


# ---------------------------------------------------------------------------
# parse_hrz
# ---------------------------------------------------------------------------


def test_parse_hrz_reads_pairs_comments_and_separators():
    profile = HorizonProfile.parse_hrz(
        "# exported by N.I.N.A.\n0 10\n\n90\t20.5\n180, 30 # trees\n270;5\n"
    )
    assert profile.points == [(0.0, 10.0), (90.0, 20.5), (180.0, 30.0), (270.0, 5.0)]


def test_parse_hrz_sorts_points_and_folds_360_onto_0():
    profile = HorizonProfile.parse_hrz("270 5\n90 20\n360 12\n")
    assert profile.points == [(0.0, 12.0), (90.0, 20.0), (270.0, 5.0)]


def test_parse_hrz_keeps_the_higher_of_two_points_at_one_azimuth():
    profile = HorizonProfile.parse_hrz("0 10\n0 15\n180 5\n")
    assert profile.points == [(0.0, 15.0), (180.0, 5.0)]


@pytest.mark.parametrize(
    "text, message",
    [
        ("0 10\n90\n", "line 2: expected 'azimuth altitude'"),
        ("0 10 20\n", "line 1: expected 'azimuth altitude'"),
        ("north 10\n", "line 1: expected 'azimuth altitude'"),
        ("10 95\n", "line 1: altitude must be within -90-90"),
        ("nan 10\n", "line 1: altitude must be within -90-90"),
        ("12,5,30\n", "line 1: expected 'azimuth altitude'"),
        ("# nothing\n\n", "no 'azimuth altitude' line"),
    ],
)
def test_parse_hrz_rejects_malformed_files(text, message):
    with pytest.raises(HorizonError, match=message):
        HorizonProfile.parse_hrz(text, "site.hrz")


def test_parse_hrz_reads_decimal_commas():
    profile = HorizonProfile.parse_hrz("12,5 30,25\n90;20,5\n180\t7,5\n")
    assert profile.points == [(12.5, 30.25), (90.0, 20.5), (180.0, 7.5)]


def test_parse_hrz_comma_alone_separates_the_values():
    profile = HorizonProfile.parse_hrz("12.5,30\n90, 20\n")
    assert profile.points == [(12.5, 30.0), (90.0, 20.0)]


def test_parse_hrz_folds_negative_and_large_azimuths():
    profile = HorizonProfile.parse_hrz("-10 15\n-180 5\n370 8\n")
    assert profile.points == [(10.0, 8.0), (180.0, 5.0), (350.0, 15.0)]


def test_profile_needs_a_point():
    with pytest.raises(HorizonError):
        HorizonProfile([])


# ---------------------------------------------------------------------------
# altitude_at
# ---------------------------------------------------------------------------


def test_altitude_at_interpolates_between_points():
    profile = HorizonProfile([(0, 10), (90, 30), (180, 10)])
    assert profile.altitude_at(0) == pytest.approx(10)
    assert profile.altitude_at(45) == pytest.approx(20)
    assert profile.altitude_at(90) == pytest.approx(30)
    assert profile.altitude_at(135) == pytest.approx(20)


def test_altitude_at_wraps_across_north():
    profile = HorizonProfile([(10, 20), (350, 40)])
    # From 350 (40) to 370 (20): 20 degrees of azimuth, 1 degree of altitude per degree.
    assert profile.altitude_at(355) == pytest.approx(35)
    assert profile.altitude_at(0) == pytest.approx(30)
    assert profile.altitude_at(360) == pytest.approx(30)
    assert profile.altitude_at(5) == pytest.approx(25)
    assert profile.altitude_at(-5) == pytest.approx(35)


def test_altitude_at_single_point_is_flat():
    profile = HorizonProfile([(123, 17)])
    assert profile.altitude_at(0) == 17
    assert profile.altitude_at(271.5) == 17


# ---------------------------------------------------------------------------
# step_limits
# ---------------------------------------------------------------------------


def test_step_limits_has_72_values_for_astromosaic():
    limits = HorizonProfile([(0, 12)]).step_limits()
    assert len(limits) == 72
    assert set(limits) == {12}


def test_step_limits_keeps_a_narrow_obstacle_between_step_centres():
    # A 1-degree chimney at azimuth 12, between the centres 10 and 15.
    profile = HorizonProfile([(0, 5), (11.5, 5), (12, 40), (12.5, 5), (359, 5)])
    limits = profile.step_limits()
    assert limits[2] == 40  # 7.5 to 12.5 degrees
    assert limits[3] == 5  # 12.5 to 17.5: only the chimney's foot
    assert limits[1] == 5


def test_step_limits_first_step_covers_both_sides_of_north():
    profile = HorizonProfile([(0, 5), (358, 30), (300, 5), (10, 5)])
    limits = profile.step_limits()
    assert limits[0] == 30  # 357.5 to 2.5 degrees


# ---------------------------------------------------------------------------
# configured_profile
# ---------------------------------------------------------------------------


def test_configured_profile_without_file(monkeypatch):
    monkeypatch.setattr(Config, "horizon_file", "", raising=False)
    assert horizon.configured_profile() == (None, None)


def test_configured_profile_missing_file(monkeypatch, tmp_path):
    path = tmp_path / "missing.hrz"
    monkeypatch.setattr(Config, "horizon_file", str(path), raising=False)
    profile, error = horizon.configured_profile()
    assert profile is None
    assert str(path) in error


def test_configured_profile_reads_and_rereads_on_change(monkeypatch, tmp_path):
    path = tmp_path / "site.hrz"
    path.write_text("0 10\n180 20\n")
    monkeypatch.setattr(Config, "horizon_file", str(path), raising=False)

    profile, error = horizon.configured_profile()
    assert error is None
    assert profile.points == [(0.0, 10.0), (180.0, 20.0)]
    assert horizon.configured_profile()[0] is profile  # cached

    path.write_text("0 15\n")
    stamp = os.path.getmtime(path) + 10
    os.utime(path, (stamp, stamp))
    assert horizon.configured_profile()[0].points == [(0.0, 15.0)]


def test_configured_profile_reports_a_malformed_file(monkeypatch, tmp_path):
    path = tmp_path / "site.hrz"
    path.write_text("0 10\nnot a line\n")
    monkeypatch.setattr(Config, "horizon_file", str(path), raising=False)
    profile, error = horizon.configured_profile()
    assert profile is None
    assert "line 2" in error


def test_configured_profile_logs_an_unusable_file_once(monkeypatch, tmp_path, caplog):
    path = tmp_path / "site.hrz"
    path.write_text("0 10\nnot a line\n")
    monkeypatch.setattr(Config, "horizon_file", str(path), raising=False)
    with caplog.at_level("WARNING"):
        for _ in range(5):
            assert horizon.configured_profile()[0] is None
    assert sum("Horizon file not used" in r.message for r in caplog.records) == 1


def test_configured_profile_rereads_a_same_time_rewrite_of_another_size(
    monkeypatch, tmp_path
):
    path = tmp_path / "site.hrz"
    path.write_text("0 10\n")
    stat = os.stat(path)
    monkeypatch.setattr(Config, "horizon_file", str(path), raising=False)
    assert horizon.configured_profile()[0].points == [(0.0, 10.0)]

    path.write_text("0 10\n180 25\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # same mtime
    assert horizon.configured_profile()[0].points == [(0.0, 10.0), (180.0, 25.0)]


# ---------------------------------------------------------------------------
# visibility
# ---------------------------------------------------------------------------

# Polaris from 44.06 N, 0.65 E stays near azimuth 0 at about 44.5 degrees.
POLARIS = SkyCoord(ra="02h31m49.09s", dec="+89d15m50.8s", frame="icrs")
WHEN = Time("2026-10-24T23:00:00", scale="utc")


@pytest.fixture
def astaffort(monkeypatch):
    monkeypatch.setattr(Config, "init_lat", 44.06)
    monkeypatch.setattr(Config, "init_long", 0.65)
    # The bundled Earth orientation tables are precise enough for horizon checks;
    # no download attempt from the tests.
    monkeypatch.setattr(iers.conf, "auto_download", False)


def test_visibility_against_a_flat_horizon(astaffort):
    result = horizon.visibility(POLARIS, None, when=WHEN)
    assert result["altitude"] == pytest.approx(44.5, abs=0.5)
    assert result["azimuth"] < 2 or result["azimuth"] > 358
    assert result["horizon"] == 0
    assert result["visible"] is True


def test_visibility_against_a_profile_and_margin(astaffort):
    low = HorizonProfile([(0, 30), (180, 30)])
    high = HorizonProfile([(0, 50), (180, 50)])
    assert horizon.visibility(POLARIS, low, when=WHEN)["visible"] is True
    assert horizon.visibility(POLARIS, low, margin=20, when=WHEN)["visible"] is False
    result = horizon.visibility(POLARIS, high, when=WHEN)
    assert result["horizon"] == pytest.approx(50)
    assert result["visible"] is False


def test_visibility_unknown_while_location_is_zero(monkeypatch):
    monkeypatch.setattr(Config, "init_lat", 0)
    monkeypatch.setattr(Config, "init_long", 0)
    assert horizon.visibility(POLARIS, None, when=WHEN) is None


def test_visibility_accepts_the_schedulers_jnow_coordinates(astaffort):
    # The scheduler hands over Util.parse_coordinate()'s FK5 JNow coordinates.
    jnow = Util.parse_coordinate(True, "02h31m49.09s", "+89d15m50.8s")
    result = horizon.visibility(jnow, None, when=WHEN)
    reference = horizon.visibility(POLARIS, None, when=WHEN)
    assert result["altitude"] == pytest.approx(reference["altitude"], abs=0.05)
    assert result["visible"] is True


@pytest.mark.parametrize(
    "ra, dec",
    [
        ("02h31m49.09s", "+89d15m50.8s"),  # Polaris
        ("00h42m44.3s", "+41d16m09s"),  # M31
        ("18h36m56.3s", "+38d47m01s"),  # Vega
        ("05h16m41.4s", "+45d59m53s"),  # Capella
        ("13h29m52.7s", "+47d11m43s"),  # M51
        ("07h45m18.9s", "+28d01m34s"),  # Pollux
    ],
)
def test_altaz_matches_astropy_within_a_tenth_of_a_degree(astaffort, ra, dec):
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation

    coord = SkyCoord(ra=ra, dec=dec, frame="icrs")
    altitude, azimuth = horizon.altaz(coord, 44.06, 0.65, WHEN)
    site = EarthLocation(lat=44.06 * u.deg, lon=0.65 * u.deg)
    reference = coord.transform_to(AltAz(obstime=WHEN, location=site))
    assert altitude == pytest.approx(reference.alt.deg, abs=0.1)
    gap = (azimuth - reference.az.deg + 180) % 360 - 180
    # Azimuth is ill-defined near the zenith: compare it on the sky.
    assert abs(gap) * math.cos(math.radians(altitude)) < 0.1


def test_visibility_needs_no_earth_orientation_table(astaffort, monkeypatch):
    # srvastro-like install: stale IERS tables and no way to download fresh ones.
    def stale(*args, **kwargs):
        raise ValueError("interpolating from IERS_Auto using predictive values")

    monkeypatch.setattr(iers.IERS_Auto, "open", stale)
    monkeypatch.setattr(iers.IERS, "open", stale)
    result = horizon.visibility(POLARIS, None, when=Time.now())
    # Any time of day: Polaris circles within 0.74 degree of the pole, whose
    # altitude is the latitude, 44.06.
    assert result["altitude"] == pytest.approx(44.06, abs=0.8)


# ---------------------------------------------------------------------------
# find_crossings / transit
# ---------------------------------------------------------------------------

START = Time("2026-11-25T18:00:00", scale="utc")
SITE = (44.06, 0.65)


def _track(ra, dec):
    coord = SkyCoord(ra=ra, dec=dec, frame="icrs")
    return lambda when: horizon.altaz(coord, *SITE, when)


def test_find_crossings_reports_one_up_and_one_down_for_an_equatorial_target(astaffort):
    track = _track("12h00m00s", "+00d00m00s")
    crossings = horizon.find_crossings(track, lambda az: 0.0, START)
    assert [tag for _, tag in crossings] == ["up", "down"]
    assert crossings[0][0] < crossings[1][0]
    # Each reported time sits on the threshold, to within the 1 minute bracket.
    for when, _ in crossings:
        assert abs(track(when)[0]) < 0.25


def test_find_crossings_empty_for_circumpolar_target(astaffort):
    track = _track("02h31m49.09s", "+89d15m50.8s")
    assert horizon.find_crossings(track, lambda az: 0.0, START) == []


def test_find_crossings_empty_for_never_up_target(astaffort):
    track = _track("03h00m00s", "-70d00m00s")
    assert horizon.find_crossings(track, lambda az: 0.0, START) == []


def test_find_crossings_does_not_skip_a_fast_meridian_crossing(astaffort):
    # Dec -45.99 culminates at about 0.05 degree: up for only ~25 minutes.
    track = _track("03h00m00s", "-45d59m24s")
    fine = [START + (k * 0.5) * u.min for k in range(2881)]
    above = [track(t)[0] > 0 for t in fine]
    first_up = next(t for t, a, b in zip(fine[1:], above, above[1:]) if b and not a)
    window = 0.5 * sum(above)
    # The grazing window is a few default steps, and shorter than a
    # coarse one: a step_min of 60 would sample right over it.
    assert 5 <= window <= 8 * 4.0
    assert horizon.find_crossings(track, lambda az: 0.0, START, step_min=60.0) == []
    crossings = horizon.find_crossings(track, lambda az: 0.0, START)
    assert [tag for _, tag in crossings] == ["up", "down"]
    assert abs((crossings[0][0] - first_up).to_value("min")) < 1.0


def test_find_crossings_follows_an_azimuth_dependent_threshold(astaffort):
    track = _track("12h00m00s", "+00d00m00s")
    crossings = horizon.find_crossings(track, lambda az: 20.0, START)
    assert [tag for _, tag in crossings] == ["up", "down"]
    for when, _ in crossings:
        assert abs(track(when)[0] - 20.0) < 0.5


def test_transit_finds_the_meridian_maximum(astaffort):
    track = _track("03h00m00s", "+20d00m00s")
    when, altitude = horizon.transit(track, START)
    reference = max(track(START + k * u.min)[0] for k in range(1441))
    assert altitude == pytest.approx(reference, abs=0.1)
    assert track(when)[0] == pytest.approx(altitude, abs=1e-6)


# ---------------------------------------------------------------------------
# save_panorama_profile
# ---------------------------------------------------------------------------


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    from device.config import _Config

    path = tmp_path / "config.toml"
    path.write_text(
        "[seestar_initialization]\nlat = 44.06\nlong = 0.65\n"
        'horizon_file = "/etc/seestar/old.hrz"\n'
    )
    config = _Config.__new__(_Config)
    config.path_to_dat = str(path)
    config.load_toml()
    monkeypatch.setattr(horizon, "Config", config)
    return config


def test_save_panorama_profile_writes_and_configures(config_file, tmp_path):
    record = json.dumps({"format": "horizon", "version": 1})
    path, previous, profile = horizon.save_panorama_profile("0 10\n180 20\n", record)

    assert path == str(tmp_path / "horizon.hrz")
    assert previous == "/etc/seestar/old.hrz"
    assert (tmp_path / "horizon.hrz").read_text() == "0 10\n180 20\n"
    assert json.loads((tmp_path / "horizon.horizon.json").read_text()) == {
        "format": "horizon",
        "version": 1,
    }
    assert profile.points == [(0.0, 10.0), (180.0, 20.0)]
    # In memory and on disk.
    assert config_file.horizon_file == path
    saved = tomlkit.parse((tmp_path / "config.toml").read_text())
    assert saved["seestar_initialization"]["horizon_file"] == path
    assert horizon.configured_profile()[0].points == profile.points


def test_save_panorama_profile_without_record(config_file, tmp_path):
    horizon.save_panorama_profile("0 10\n")
    assert (tmp_path / "horizon.hrz").exists()
    assert not (tmp_path / "horizon.horizon.json").exists()


@pytest.mark.parametrize(
    "hrz, record, message",
    [
        ("north 10\n", None, "line 1"),
        ("0 10\n", "{", "uploaded .horizon.json"),
        ("0 10\n", '{"format": "other"}', "not an MMhorizon file"),
        ("0 10\n", "[1, 2]", "not an MMhorizon file"),
    ],
)
def test_save_panorama_profile_rejects_invalid_input(
    config_file, tmp_path, hrz, record, message
):
    with pytest.raises(HorizonError, match=message):
        horizon.save_panorama_profile(hrz, record)
    assert not (tmp_path / "horizon.hrz").exists()
    assert config_file.horizon_file == "/etc/seestar/old.hrz"


def test_save_without_record_removes_the_record_of_an_earlier_photo(
    config_file, tmp_path
):
    record = json.dumps({"format": "horizon", "version": 1})
    horizon.save_panorama_profile("0 10\n", record)
    horizon.save_panorama_profile("0 20\n")
    assert (tmp_path / "horizon.hrz").read_text() == "0 20\n"
    assert not (tmp_path / "horizon.horizon.json").exists()


def test_a_second_save_is_used_at_once_within_one_clock_tick(config_file, tmp_path):
    horizon.save_panorama_profile("0 10\n")
    first = os.stat(tmp_path / "horizon.hrz")
    assert horizon.configured_profile()[0].points == [(0.0, 10.0)]
    # Same size, and the same modification time, as on a coarse clock.
    horizon.save_panorama_profile("0 20\n")
    os.utime(tmp_path / "horizon.hrz", ns=(first.st_atime_ns, first.st_mtime_ns))
    assert horizon.configured_profile()[0].points == [(0.0, 20.0)]


def test_a_file_replaced_within_one_clock_tick_is_read_again(monkeypatch, tmp_path):
    hrz = tmp_path / "site.hrz"
    hrz.write_text("0 10\n")
    monkeypatch.setattr(Config, "horizon_file", str(hrz), raising=False)
    assert horizon.configured_profile()[0].points == [(0.0, 10.0)]
    before = os.stat(hrz)
    # Another tool replaces it atomically: same size, same time, new inode.
    (tmp_path / "new.hrz").write_text("0 20\n")
    os.replace(tmp_path / "new.hrz", hrz)
    os.utime(hrz, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert horizon.configured_profile()[0].points == [(0.0, 20.0)]


def _no_temporary_file_left(folder):
    return not [name for name in os.listdir(folder) if name.endswith(".tmp")]


def test_a_write_failure_changes_nothing(config_file, tmp_path, monkeypatch):
    (tmp_path / "horizon.hrz").write_text("0 5\n")
    real_stage = horizon.stage_file

    def disk_full_on_the_record(path, text, encoding=None):
        if path.endswith(".json"):
            raise OSError(28, "No space left on device")
        return real_stage(path, text, encoding)

    monkeypatch.setattr(horizon, "stage_file", disk_full_on_the_record)
    record = json.dumps({"format": "horizon", "version": 1})
    with pytest.raises(HorizonSaveError, match="No space left on device"):
        horizon.save_panorama_profile("0 10\n", record)
    assert (tmp_path / "horizon.hrz").read_text() == "0 5\n"
    assert _no_temporary_file_left(tmp_path)
    assert config_file.horizon_file == "/etc/seestar/old.hrz"
    saved = tomlkit.parse((tmp_path / "config.toml").read_text())
    assert saved["seestar_initialization"]["horizon_file"] == "/etc/seestar/old.hrz"


def test_a_config_save_failure_changes_nothing(config_file, tmp_path, monkeypatch):
    def read_only(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(config_file, "save_toml", read_only)
    with pytest.raises(HorizonSaveError, match="Permission denied"):
        horizon.save_panorama_profile("0 10\n")
    assert not (tmp_path / "horizon.hrz").exists()
    assert _no_temporary_file_left(tmp_path)
    assert config_file.horizon_file == "/etc/seestar/old.hrz"


def test_a_failure_after_the_config_save_puts_it_back(
    config_file, tmp_path, monkeypatch
):
    real_replace = os.replace

    def locked(source, target):
        if str(target).endswith("horizon.hrz"):
            raise PermissionError(13, "Permission denied")
        return real_replace(source, target)

    monkeypatch.setattr(horizon.os, "replace", locked)
    with pytest.raises(HorizonSaveError):
        horizon.save_panorama_profile("0 10\n")
    assert not (tmp_path / "horizon.hrz").exists()
    assert _no_temporary_file_left(tmp_path)
    assert config_file.horizon_file == "/etc/seestar/old.hrz"
    saved = tomlkit.parse((tmp_path / "config.toml").read_text())
    assert saved["seestar_initialization"]["horizon_file"] == "/etc/seestar/old.hrz"


def test_overlapping_saves_run_one_after_the_other(config_file, tmp_path, monkeypatch):
    real_stage = horizon.stage_file
    first_staged = threading.Event()
    go_on = threading.Event()
    staged = []

    def slow_first_save(path, text, encoding=None):
        name = real_stage(path, text, encoding)
        staged.append(text)
        if text == "0 10\n":
            first_staged.set()
            go_on.wait(5)
        return name

    monkeypatch.setattr(horizon, "stage_file", slow_first_save)
    errors = []

    def save(hrz):
        try:
            horizon.save_panorama_profile(hrz)
        except Exception as e:  # checked below, in the test's own thread
            errors.append(e)

    first = threading.Thread(target=save, args=("0 10\n",), daemon=True)
    second = threading.Thread(target=save, args=("0 20\n",), daemon=True)
    try:
        first.start()
        assert first_staged.wait(5)
        second.start()
        second.join(0.3)
        # The second save waits for the first: nothing of it is written yet.
        assert staged == ["0 10\n"]
    finally:
        go_on.set()
        first.join(5)
        second.join(5)
    assert not errors
    assert staged == ["0 10\n", "0 20\n"]
    path = str(tmp_path / "horizon.hrz")
    assert (tmp_path / "horizon.hrz").read_text() == "0 20\n"
    assert config_file.horizon_file == path
    saved = tomlkit.parse((tmp_path / "config.toml").read_text())
    assert saved["seestar_initialization"]["horizon_file"] == path
    assert _no_temporary_file_left(tmp_path)


def test_an_unexpected_error_is_cleaned_up_and_reported(
    config_file, tmp_path, monkeypatch
):
    def no_table(section, key, value):
        # Config.set_toml on a config.toml without [seestar_initialization].
        raise KeyError(section)

    monkeypatch.setattr(config_file, "set_toml", no_table)
    record = json.dumps({"format": "horizon", "version": 1})
    with pytest.raises(HorizonSaveError, match="KeyError"):
        horizon.save_panorama_profile("0 10\n", record)
    assert not (tmp_path / "horizon.hrz").exists()
    assert not (tmp_path / "horizon.horizon.json").exists()
    assert _no_temporary_file_left(tmp_path)
    assert config_file.horizon_file == "/etc/seestar/old.hrz"


@pytest.mark.parametrize("had_record", [True, False])
def test_a_failed_profile_replace_puts_the_former_record_back(
    config_file, tmp_path, monkeypatch, had_record
):
    old = json.dumps({"format": "horizon", "version": 1, "photo": "old.jpg"})
    horizon.save_panorama_profile("0 5\n", old if had_record else None)
    real_replace = os.replace

    def locked(source, target):
        if str(target).endswith("horizon.hrz"):
            raise PermissionError(13, "Permission denied")
        return real_replace(source, target)

    monkeypatch.setattr(horizon.os, "replace", locked)
    new = json.dumps({"format": "horizon", "version": 1, "photo": "new.jpg"})
    with pytest.raises(HorizonSaveError, match="Permission denied"):
        horizon.save_panorama_profile("0 10\n", new)
    assert (tmp_path / "horizon.hrz").read_text() == "0 5\n"
    record = tmp_path / "horizon.horizon.json"
    if had_record:
        assert record.read_text() == old
    else:
        assert not record.exists()
    assert _no_temporary_file_left(tmp_path)


def test_a_record_that_cannot_be_removed_leaves_the_save_in_place(
    config_file, tmp_path, monkeypatch, caplog
):
    record = json.dumps({"format": "horizon", "version": 1})
    horizon.save_panorama_profile("0 5\n", record)
    real_remove = os.remove

    def busy(target):
        if str(target).endswith("horizon.horizon.json"):
            raise PermissionError(13, "Permission denied")
        return real_remove(target)

    monkeypatch.setattr(horizon.os, "remove", busy)
    with caplog.at_level("WARNING"):
        path, _, profile = horizon.save_panorama_profile("0 10\n")
    assert (tmp_path / "horizon.hrz").read_text() == "0 10\n"
    assert config_file.horizon_file == path
    assert horizon.configured_profile()[0].points == profile.points
    assert any("still describes the former photo" in r.message for r in caplog.records)
    assert _no_temporary_file_left(tmp_path)


# ---------------------------------------------------------------------------
# sun / moon
# ---------------------------------------------------------------------------

# Real lunations: new moon 2026-11-09 ~21:02 UTC, full moon 2026-11-24 ~14:53 UTC.
NEW_MOON = Time("2026-11-09T21:02:00", scale="utc")
FULL_MOON = Time("2026-11-24T14:53:00", scale="utc")


def test_sun_altitude_is_negative_at_local_midnight(astaffort):
    # Astaffort (0.65 E) is on UTC time within a few minutes: 00:00 UTC.
    midnight = Time("2026-11-25T00:00:00", scale="utc")
    altitude, azimuth = horizon.sun_alt_az(midnight, 44.06, 0.65)
    assert altitude < 0
    assert 0 <= azimuth < 360


def _az_gap(a, b):
    return abs((a - b + 180) % 360 - 180)


@pytest.mark.parametrize("hour", [0, 12, 20])
@pytest.mark.parametrize("body", ["sun", "moon"])
def test_sun_moon_match_astropy_altaz(astaffort, body, hour):
    from astropy.coordinates import AltAz, EarthLocation, get_body

    when = Time(f"2026-11-25T{hour:02d}:00:00", scale="utc")
    site = EarthLocation(lat=44.06 * u.deg, lon=0.65 * u.deg)
    truth = get_body(body, when).transform_to(AltAz(obstime=when, location=site))
    fn = horizon.sun_alt_az if body == "sun" else horizon.moon_alt_az
    altitude, azimuth = fn(when, 44.06, 0.65)
    # The Moon is geocentric here: parallax of up to about a degree.
    assert altitude == pytest.approx(truth.alt.deg, abs=1.0)
    assert _az_gap(azimuth, truth.az.deg) < 1.0


def test_moon_illumination_near_zero_at_a_known_new_moon():
    assert horizon.moon_illumination(NEW_MOON) < 0.05


def test_moon_illumination_near_one_at_a_known_full_moon():
    assert horizon.moon_illumination(FULL_MOON) > 0.95


def test_moon_is_waxing_between_new_and_full():
    assert horizon.moon_is_waxing(Time("2026-11-17T12:00:00", scale="utc")) is True
    assert horizon.moon_is_waxing(Time("2026-12-01T12:00:00", scale="utc")) is False


@pytest.mark.parametrize(
    "illumination, waxing, name",
    [
        (0.01, True, "new moon"),
        (0.01, False, "new moon"),
        (0.25, True, "waxing crescent"),
        (0.25, False, "waning crescent"),
        (0.5, True, "first quarter"),
        (0.5, False, "last quarter"),
        (0.75, True, "waxing gibbous"),
        (0.75, False, "waning gibbous"),
        (0.99, True, "full moon"),
        (0.99, False, "full moon"),
    ],
)
def test_moon_phase_name_buckets(illumination, waxing, name):
    assert horizon.moon_phase_name(illumination, waxing) == name


def test_sun_moon_need_no_earth_orientation_table(astaffort, monkeypatch):
    def stale(*args, **kwargs):
        raise ValueError("interpolating from IERS_Auto using predictive values")

    monkeypatch.setattr(iers.IERS_Auto, "open", stale)
    monkeypatch.setattr(iers.IERS, "open", stale)
    when = Time("2026-11-25T20:00:00", scale="utc")
    for fn in (horizon.sun_alt_az, horizon.moon_alt_az):
        altitude, azimuth = fn(when, 44.06, 0.65)
        assert math.isfinite(altitude) and -90 <= altitude <= 90
        assert math.isfinite(azimuth) and 0 <= azimuth < 360
    assert 0 <= horizon.moon_illumination(when) <= 1
    assert isinstance(horizon.moon_is_waxing(when), bool)


def _window(ra, dec, **extra):
    params = {"ra": ra, "dec": dec, "is_j2000": True, **extra}
    return horizon.target_window(params, now=START)


def test_target_window_rises_and_sets(astaffort):
    result = _window("12:00:00", "+00:00:00")
    assert result["state"] == "rises_and_sets"
    assert result["rises"]["iso"] < result["sets"]["iso"]
    assert result["rises"]["local"] != result["sets"]["local"]
    assert result["transit"] is not None
    assert result["rises"]["iso"] < result["transit"]["iso"] < result["sets"]["iso"]
    assert result["max_altitude"] == pytest.approx(45.9, abs=0.5)
    assert result["min_altitude_floor"] == 0.0
    assert "next_rises" not in result


def test_target_window_circumpolar(astaffort):
    result = _window("02:31:49.09", "+89:15:50.8")
    assert result["state"] == "circumpolar"
    assert result["rises"] is None and result["sets"] is None
    assert result["transit"] is not None
    assert result["max_altitude"] > 40


def test_target_window_never_up(astaffort):
    result = _window("03:00:00", "-70:00:00")
    assert result["state"] == "never_up"
    assert result["rises"] is None and result["sets"] is None


def test_target_window_up_now(astaffort):
    result = _window("22:00:00", "+00:00:00")
    assert result["state"] == "up_now"
    assert result["rises"] is None
    assert result["sets"] is not None
    assert result["next_rises"] is not None
    assert result["sets"]["iso"] < result["next_rises"]["iso"]


def test_target_window_min_altitude_floor_raises_the_effective_horizon(astaffort):
    low = _window("22:00:00", "+00:00:00")
    assert low["state"] == "up_now"
    high = _window("22:00:00", "+00:00:00", min_altitude=30)
    assert high["min_altitude_floor"] == 30
    assert high["state"] == "up_now"
    assert high["sets"]["iso"] < low["sets"]["iso"]
    too_high = _window("22:00:00", "+00:00:00", min_altitude=80)
    assert too_high["state"] == "never_up"


def test_target_window_without_profile_uses_flat_floor(astaffort, monkeypatch):
    monkeypatch.setattr(Config, "horizon_file", "")
    result = _window("12:00:00", "+00:00:00")
    assert result["uses_horizon_profile"] is False


def test_target_window_uses_the_horizon_profile(astaffort, monkeypatch, tmp_path):
    path = tmp_path / "wall.hrz"
    path.write_text("0 90\n")
    monkeypatch.setattr(Config, "horizon_file", str(path))
    result = _window("22:00:00", "+00:00:00")
    assert result["uses_horizon_profile"] is True
    assert result["state"] == "never_up"


def test_target_window_raises_SiteLocationUnknown_at_zero_location(monkeypatch):
    monkeypatch.setattr(Config, "init_lat", 0)
    monkeypatch.setattr(Config, "init_long", 0)
    with pytest.raises(horizon.SiteLocationUnknown):
        _window("12:00:00", "+00:00:00")


def test_target_window_raises_InvalidTarget_on_bad_coordinates(astaffort):
    with pytest.raises(horizon.InvalidTarget):
        _window("north", "+00:00:00")
    with pytest.raises(horizon.InvalidTarget):
        horizon.target_window({"dec": 1.0}, now=START)


def test_local_times_render_in_configured_timezone(monkeypatch):
    monkeypatch.setattr(Config, "init_timezone", "Asia/Tokyo")
    assert horizon.local_times(START) == {
        "local": "03:00",
        "iso": "2026-11-26T03:00:00+09:00",
    }
    monkeypatch.setattr(Config, "init_timezone", "UTC")
    assert horizon.local_times(START)["local"] == "18:00"


def test_local_times_fall_back_to_host_timezone(monkeypatch):
    monkeypatch.setattr(Config, "init_timezone", "")
    result = horizon.local_times(START)
    assert len(result["local"]) == 5
    assert result["iso"].startswith("2026-11-2")


# 2026-10-29 Astaffort (Europe/Paris, CET): the local noon-to-noon window
# has a moonrise but no moonset.
NIGHT_EVENING = Time("2026-10-29T17:00:00", scale="utc")  # 18:00 local
NIGHT_PAST_MIDNIGHT = Time("2026-10-29T23:30:00", scale="utc")  # 00:30 on the 30th
NIGHT_MORNING = Time(
    "2026-10-30T09:00:00", scale="utc"
)  # 10:00 local, still the 29th's night


@pytest.fixture
def paris(astaffort, monkeypatch):
    monkeypatch.setattr(Config, "init_timezone", "Europe/Paris")


def test_night_events_returns_ordered_twilight_times(paris):
    result = horizon.night_events(now=NIGHT_EVENING)
    for key in ("astronomical", "nautical", "civil"):
        assert result[key]["dusk"] is not None
        assert result[key]["dawn"] is not None
    # Going into night: civil, then nautical, then astronomical dusk.
    assert (
        result["civil"]["dusk"]["iso"]
        < result["nautical"]["dusk"]["iso"]
        < result["astronomical"]["dusk"]["iso"]
    )
    # Mirrored towards dawn.
    assert (
        result["astronomical"]["dawn"]["iso"]
        < result["nautical"]["dawn"]["iso"]
        < result["civil"]["dawn"]["iso"]
    )
    assert result["astronomical"]["dusk"]["iso"] < result["astronomical"]["dawn"]["iso"]


def test_night_events_moon_illumination_in_unit_range(paris):
    result = horizon.night_events(now=NIGHT_EVENING)
    assert 0.0 <= result["moon_illumination"] <= 1.0
    assert isinstance(result["moon_phase"], str) and result["moon_phase"]


def test_night_events_null_when_no_moonset_in_window(paris):
    result = horizon.night_events(now=NIGHT_EVENING)
    assert result["moonset"] is None
    assert result["moonrise"] is not None


def test_night_events_same_result_before_and_after_midnight(paris):
    evening = horizon.night_events(now=NIGHT_EVENING)
    past_midnight = horizon.night_events(now=NIGHT_PAST_MIDNIGHT)
    morning = horizon.night_events(now=NIGHT_MORNING)
    for other in (past_midnight, morning):
        for key in ("astronomical", "nautical", "civil"):
            assert other[key] == evening[key]
        assert other["moonrise"] == evening["moonrise"]


def test_night_events_raises_SiteLocationUnknown_at_zero_location(monkeypatch):
    monkeypatch.setattr(Config, "init_lat", 0)
    monkeypatch.setattr(Config, "init_long", 0)
    with pytest.raises(horizon.SiteLocationUnknown):
        horizon.night_events(now=NIGHT_EVENING)
