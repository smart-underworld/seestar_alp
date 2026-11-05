import json
import math
import os

import pytest
import tomlkit
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.utils import iers

from device import horizon
from device.config import Config
from device.horizon import HorizonError, HorizonProfile
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
# sun_altaz
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when",
    [
        "2026-10-23T13:59:04",
        "2026-06-21T12:00:00",
        "2026-03-20T17:30:00",
        "2026-01-15T08:45:00",
    ],
)
def test_sun_altaz_matches_astropy(astaffort, when):
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation, get_sun

    t = Time(when, scale="utc")
    altitude, azimuth = horizon.sun_altaz(44.06, 0.65, t)
    site = EarthLocation(lat=44.06 * u.deg, lon=0.65 * u.deg)
    reference = get_sun(t).transform_to(AltAz(obstime=t, location=site))
    assert altitude == pytest.approx(reference.alt.deg, abs=0.05)
    gap = (azimuth - reference.az.deg + 180) % 360 - 180
    assert abs(gap) * math.cos(math.radians(altitude)) < 0.05


def test_sun_of_the_first_real_panorama():
    # MMhorizon's first panorama, 2026-10-23 15:59:04 (UTC+2), was oriented on
    # the Sun: azimuth 218.0, altitude 26.3 by astronomy-engine.
    t = Time("2026-10-23T13:59:04", scale="utc")
    altitude, azimuth = horizon.sun_altaz(44.06504, 0.65041, t)
    assert azimuth == pytest.approx(218.0, abs=0.1)
    assert altitude == pytest.approx(26.3, abs=0.1)


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


@pytest.mark.parametrize(
    "altitude, lift",
    [(25.0, 0.036), (5.0, 0.161), (0.0, 0.483), (-5.0, 0.0), (90.0, 0.0)],
)
def test_refraction(altitude, lift):
    assert horizon.refraction(altitude) == pytest.approx(lift, abs=0.002)
