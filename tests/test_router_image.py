"""
Unit tests for the front_v2 image router (/api/v1/devices/{n}/image/*).

Covers the regression where start_stack was called without "restart",
which raises a KeyError deep in device/seestar_device.py.start_stack and
silently returns a 200 with an Alpaca error body instead of failing loudly.
"""

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from front_v2.api import router_image  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(router_image, "check_api_state", lambda dev_num: True)
    app = FastAPI()
    app.include_router(router_image.router)
    return TestClient(app)


def test_start_imaging_sends_restart_param(client, monkeypatch):
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        captured["params"] = params
        return {"ErrorNumber": 0, "Value": True}

    monkeypatch.setattr(router_image, "do_action", fake_do_action)

    r = client.post(
        "/api/v1/devices/1/image/start",
        json={"exp_ms": 10000, "gain": 80, "count": 0, "target_name": "M13"},
    )
    assert r.status_code == 200
    assert captured["action"] == "start_stack"
    assert captured["params"]["restart"] is True


def test_start_imaging_surfaces_device_error(client, monkeypatch):
    monkeypatch.setattr(
        router_image,
        "do_action",
        lambda *a, **k: {"ErrorNumber": 1280, "ErrorMessage": "'restart'"},
    )

    r = client.post(
        "/api/v1/devices/1/image/start",
        json={"exp_ms": 10000, "gain": 80, "count": 0},
    )
    assert r.status_code == 502
    assert r.json()["detail"] == "'restart'"


def test_start_imaging_offline_device(monkeypatch):
    monkeypatch.setattr(router_image, "check_api_state", lambda dev_num: False)
    app = FastAPI()
    app.include_router(router_image.router)
    client = TestClient(app)

    r = client.post("/api/v1/devices/1/image/start", json={})
    assert r.status_code == 503
