"""Horizon page: panorama analysed in the browser, profile saved by the server."""

import hashlib
import json
import math
import re
from pathlib import Path

import falcon
import pytest
from astropy.utils import iers
from falcon import testing

import front.app as front_app
from device import horizon

PUBLIC = Path(__file__).resolve().parent.parent / "front" / "public"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        front_app,
        "get_context",
        lambda telescope_id, req: {
            "online": True,
            "client_master": True,
            "root": f"/{telescope_id}",
            "telescope": {"device_num": telescope_id},
        },
    )
    app = falcon.App()
    app.add_route("/horizon", front_app.HorizonResource())
    app.add_route("/{telescope_id:int}/horizon", front_app.HorizonResource())
    app.add_route("/horizon/sun", front_app.HorizonSunResource())
    return testing.TestClient(app)


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    from device.config import _Config

    path = tmp_path / "config.toml"
    path.write_text(
        '[seestar_initialization]\nlat = 44.06\nlong = 0.65\nhorizon_file = ""\n'
    )
    config = _Config.__new__(_Config)
    config.path_to_dat = str(path)
    config.load_toml()
    monkeypatch.setattr(horizon, "Config", config)
    return config


def test_page_renders_the_panorama_tool(client, monkeypatch):
    monkeypatch.setattr(front_app.Config, "init_lat", 44.06, raising=False)
    monkeypatch.setattr(front_app.Config, "init_long", 0.65, raising=False)
    monkeypatch.setattr(horizon, "configured_profile", lambda: (None, None))
    resp = client.simulate_get("/1/horizon")
    assert resp.status_code == 200
    assert 'id="hz-page" data-lat="44.06" data-lon="0.65"' in resp.text
    assert 'src="/public/horizon_panorama.js"' in resp.text
    assert 'type="file" id="hz-photo"' in resp.text
    assert "flat horizon at 30" in resp.text


def test_page_shows_the_current_profile(client, monkeypatch):
    profile = horizon.HorizonProfile([(0, 10), (180, 20)])
    monkeypatch.setattr(horizon, "configured_profile", lambda: (profile, None))
    monkeypatch.setattr(
        front_app.Config, "horizon_file", "/etc/seestar/site.hrz", raising=False
    )
    resp = client.simulate_get("/horizon")
    assert resp.status_code == 200
    assert "/etc/seestar/site.hrz &middot; 2 points" in resp.text


def test_post_saves_the_profile(client, config_file, tmp_path):
    record = json.dumps({"format": "horizon", "version": 1})
    resp = client.simulate_post(
        "/horizon", json={"hrz": "0 10\n90 25\n180 5\n", "horizon_json": record}
    )
    assert resp.status_code == 200
    assert resp.json == {
        "file": str(tmp_path / "horizon.hrz"),
        "previous_file": "",
        "points": 3,
    }
    assert (tmp_path / "horizon.hrz").read_text() == "0 10\n90 25\n180 5\n"
    assert config_file.horizon_file == str(tmp_path / "horizon.hrz")


@pytest.mark.parametrize(
    "body, message",
    [
        ({"hrz": "north 10\n"}, "line 1"),
        ({"horizon": "0 10\n"}, "Expected"),
        ({"hrz": "0 10\n", "horizon_json": 3}, "must be a string"),
        ({"hrz": "0 10\n", "horizon_json": '{"format": "x"}'}, "not an MMhorizon"),
    ],
)
def test_post_rejects_invalid_profiles(client, config_file, tmp_path, body, message):
    resp = client.simulate_post("/horizon", json=body)
    assert resp.status_code == 400
    assert message in resp.json["description"]
    assert not (tmp_path / "horizon.hrz").exists()


def test_post_refuses_a_large_body(client, config_file):
    resp = client.simulate_post("/horizon", json={"hrz": "0 10\n" * 200_000})
    assert resp.status_code == 413


def test_post_refuses_a_large_body_under_falcon_3(client, config_file, monkeypatch):
    # Falcon 3 (requirements_full_overload.txt) names it HTTPPayloadTooLarge.
    monkeypatch.delattr(falcon, "HTTPContentTooLarge")
    resp = client.simulate_post("/horizon", json={"hrz": "0 10\n" * 200_000})
    assert resp.status_code == 413


def test_post_reports_a_write_failure(client, config_file, tmp_path, monkeypatch):
    def read_only(path, text, encoding=None):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(horizon, "stage_file", read_only)
    resp = client.simulate_post("/horizon", json={"hrz": "0 10\n"})
    assert resp.status_code == 500
    assert "Permission denied" in resp.json["description"]
    assert "previous horizon is still in use" in resp.json["description"]
    assert config_file.horizon_file == ""
    assert not (tmp_path / "horizon.hrz").exists()


@pytest.mark.parametrize(
    "when",
    [
        "2026-10-23T13:59:04Z",
        "2026-06-21T12:00:00Z",
        "2026-03-20T17:30:00Z",
        "2026-01-15T08:45:00Z",
    ],
)
def test_sun_position_matches_astropy(client, monkeypatch, when):
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation, get_sun
    from astropy.time import Time

    monkeypatch.setattr(iers.conf, "auto_download", False)
    resp = client.simulate_get(
        "/horizon/sun", params={"when": when, "lat": "44.06", "lon": "0.65"}
    )
    assert resp.status_code == 200
    # Apparent position, with the same atmosphere as ephem's default.
    t = Time(when.rstrip("Z"), scale="utc")
    frame = AltAz(
        obstime=t,
        location=EarthLocation(lat=44.06 * u.deg, lon=0.65 * u.deg),
        pressure=1010 * u.hPa,
        temperature=15 * u.deg_C,
        relative_humidity=0,
        obswl=0.55 * u.micron,
    )
    reference = get_sun(t).transform_to(frame)
    altitude, azimuth = resp.json["altitude"], resp.json["azimuth"]
    assert altitude == pytest.approx(reference.alt.deg, abs=0.02)
    gap = (azimuth - reference.az.deg + 180) % 360 - 180
    assert abs(gap) * math.cos(math.radians(altitude)) < 0.02


def test_sun_of_the_first_real_panorama(client):
    # MMhorizon's first panorama, 2026-10-23 15:59:04 (UTC+2), was oriented on
    # the Sun: azimuth 218.0, altitude 26.3 by astronomy-engine.
    resp = client.simulate_get(
        "/horizon/sun",
        params={"when": "2026-10-23T15:59:04+02:00", "lat": "44.06", "lon": "0.65"},
    )
    assert resp.status_code == 200
    assert resp.json["azimuth"] == pytest.approx(218.0, abs=0.1)
    assert resp.json["altitude"] == pytest.approx(26.3, abs=0.1)
    # The browser sends UTC.
    utc = client.simulate_get(
        "/horizon/sun",
        params={"when": "2026-10-23T13:59:04.000Z", "lat": "44.06", "lon": "0.65"},
    )
    assert utc.json == resp.json


def test_sun_position_at_the_site_when_the_photo_has_no_location(client, monkeypatch):
    monkeypatch.setattr(horizon, "site_location", lambda: (44.06, 0.65))
    resp = client.simulate_get("/horizon/sun", params={"when": "2026-10-23T13:59:04Z"})
    assert resp.status_code == 200
    assert (resp.json["latitude"], resp.json["longitude"]) == (44.06, 0.65)
    assert resp.json["azimuth"] == pytest.approx(218.0, abs=0.1)


@pytest.mark.parametrize("params", [{}, {"lat": "0", "lon": "0"}])
def test_sun_position_refuses_an_unknown_site(client, monkeypatch, params):
    # Settings never filled in (0, 0) and no location in the photo: no Sun
    # computed for 0 N 0 E, which would turn north by tens of degrees.
    monkeypatch.setattr(horizon, "site_location", lambda: None)
    resp = client.simulate_get(
        "/horizon/sun", params={"when": "2026-10-23T13:59:04Z", **params}
    )
    assert resp.status_code == 400
    assert "Site location unknown" in resp.json["description"]


@pytest.mark.parametrize(
    "params",
    [
        {"when": "yesterday", "lat": "44", "lon": "0.6"},
        {"when": "2026-10-23T15:59:04+02:00", "lon": "0.6"},
        {"when": "2026-10-23T15:59:04+02:00", "lat": "95", "lon": "0.6"},
    ],
)
def test_sun_position_rejects_bad_parameters(client, params):
    assert client.simulate_get("/horizon/sun", params=params).status_code == 400


def test_sun_position_reads_a_time_without_offset_in_the_site_time_zone(
    client, monkeypatch
):
    # EXIF without OffsetTimeOriginal: the site's clock, not the browser's.
    monkeypatch.setattr(
        front_app.Config, "init_timezone", "Europe/Paris", raising=False
    )
    place = {"lat": "44.06", "lon": "0.65"}
    local = client.simulate_get(
        "/horizon/sun", params={"when": "2026-10-23T15:59:04", **place}
    )
    assert local.status_code == 200
    assert local.json["time_zone"] == "Europe/Paris"
    offset = client.simulate_get(
        "/horizon/sun", params={"when": "2026-10-23T15:59:04+02:00", **place}
    )
    assert offset.json["time_zone"] is None
    assert local.json["azimuth"] == offset.json["azimuth"]
    assert local.json["altitude"] == offset.json["altitude"]


def test_sun_position_near_the_equator_and_the_prime_meridian(client):
    # str(1e-05) is "1e-05": the place goes to ephem as an angle, not a str.
    resp = client.simulate_get(
        "/horizon/sun",
        params={"when": "2026-03-20T12:00:00Z", "lat": "0.00001", "lon": "-0.00002"},
    )
    assert resp.status_code == 200
    # Close to the equinox, near noon: the Sun is almost overhead.
    assert resp.json["altitude"] > 87


def test_bundled_mmhorizon_module_matches_its_readme():
    readme = (PUBLIC / "mmhorizon" / "README.md").read_text()
    listed = dict(re.findall(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", readme))
    assert set(listed) == {"mmhorizon_wasm.js", "mmhorizon_wasm_bg.wasm"}
    for name, digest in listed.items():
        assert (
            hashlib.sha256((PUBLIC / "mmhorizon" / name).read_bytes()).hexdigest()
            == digest
        )
