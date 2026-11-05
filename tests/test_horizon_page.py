"""Horizon page: panorama analysed in the browser, profile saved by the server."""

import hashlib
import json
import re
from pathlib import Path

import falcon
import pytest
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
    # Reachable from the Functions menu of every page.
    assert 'href="/1/horizon">Horizon (MMhorizon)</a>' in resp.text


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


def test_sun_position(client):
    resp = client.simulate_get(
        "/horizon/sun",
        params={
            "when": "2026-10-23T15:59:04+02:00",
            "lat": "44.06504",
            "lon": "0.65041",
        },
    )
    assert resp.status_code == 200
    assert resp.json["azimuth"] == pytest.approx(218.0, abs=0.1)
    assert resp.json["altitude"] == pytest.approx(26.3, abs=0.1)
    # Apparent altitude: the geometric one lifted by refraction.
    geometric, _ = horizon.sun_altaz(
        44.06504, 0.65041, horizon.Time("2026-10-23T13:59:04", scale="utc")
    )
    assert resp.json["altitude"] - geometric == pytest.approx(0.034, abs=0.002)
    # The browser sends UTC.
    utc = client.simulate_get(
        "/horizon/sun",
        params={
            "when": "2026-10-23T13:59:04.000Z",
            "lat": "44.06504",
            "lon": "0.65041",
        },
    )
    assert utc.json == resp.json


@pytest.mark.parametrize(
    "params",
    [
        {"when": "2026-10-23T15:59:04", "lat": "44", "lon": "0.6"},  # no offset
        {"when": "yesterday", "lat": "44", "lon": "0.6"},
        {"when": "2026-10-23T15:59:04+02:00", "lon": "0.6"},
        {"when": "2026-10-23T15:59:04+02:00", "lat": "95", "lon": "0.6"},
    ],
)
def test_sun_position_rejects_bad_parameters(client, params):
    assert client.simulate_get("/horizon/sun", params=params).status_code == 400


def test_bundled_mmhorizon_module_matches_its_readme():
    readme = (PUBLIC / "mmhorizon" / "README.md").read_text()
    listed = dict(re.findall(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", readme))
    assert set(listed) == {"mmhorizon_wasm.js", "mmhorizon_wasm_bg.wasm"}
    for name, digest in listed.items():
        assert (
            hashlib.sha256((PUBLIC / "mmhorizon" / name).read_bytes()).hexdigest()
            == digest
        )
