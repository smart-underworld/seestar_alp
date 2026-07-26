"""
Unit tests for front_v2 live-view router (/api/v1/devices/{n}/live/*).

Regression coverage for the exposure key-mismatch bug: the real firmware's
get_setting response nests exposure as exp_ms: {stack_l, continuous}
(confirmed from a real device's alpyca.log capture), but the code read/wrote
a flat exp_ms_continuous key that never exists -- so get_exposure always
fell back to its hardcoded default (10000ms) and set_exposure's writes were
silently dropped by the firmware.
"""

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from front_v2.api import router_live  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(router_live, "check_api_state", lambda dev_num: True)
    app = FastAPI()
    app.include_router(router_live.router)
    return TestClient(app)


def _fake_method_sync(stage: str, exp_ms: dict):
    def _inner(method, dev_num, **kwargs):
        if method == "get_setting":
            return {"exp_ms": exp_ms, "gain": 999}  # gain intentionally wrong shape here
        if method == "get_view_state":
            return {"View": {"stage": stage}}
        return None

    return _inner


def test_get_exposure_returns_stack_l_while_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("Stack", {"stack_l": 20000, "continuous": 2000}),
    )
    monkeypatch.setattr(router_live, "do_action", lambda action, dev_num, params: None)
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["exp_ms"] == 20000


def test_get_exposure_returns_continuous_when_not_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("", {"stack_l": 20000, "continuous": 2000}),
    )
    monkeypatch.setattr(router_live, "do_action", lambda action, dev_num, params: None)
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["exp_ms"] == 2000


def test_set_exposure_writes_stack_l_while_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live, "method_sync", _fake_method_sync("Stack", {})
    )
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(router_live, "do_action", fake_do_action)

    r = client.post("/api/v1/devices/1/live/exposure", json={"exp_ms": 20000})
    assert r.status_code == 200
    assert captured["action"] == "set_setting"
    assert captured["params"] == {"exp_ms": {"stack_l": 20000}}


def test_set_exposure_writes_continuous_when_not_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live, "method_sync", _fake_method_sync("Idle", {})
    )
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(router_live, "do_action", fake_do_action)

    r = client.post("/api/v1/devices/1/live/exposure", json={"exp_ms": 2000})
    assert r.status_code == 200
    assert captured["params"] == {"exp_ms": {"continuous": 2000}}


def test_get_exposure_reads_gain_from_get_last_gain_action(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("Idle", {"stack_l": 20000, "continuous": 2000}),
    )
    monkeypatch.setattr(
        router_live,
        "do_action",
        lambda action, dev_num, params: {"Value": 42} if action == "get_last_gain" else None,
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["gain"] == 42


def test_set_gain_uses_set_control_value(client, monkeypatch):
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(router_live, "do_action", fake_do_action)

    r = client.post("/api/v1/devices/1/live/gain", json={"gain": 120})
    assert r.status_code == 200
    assert captured["action"] == "method_sync"
    assert captured["params"]["method"] == "set_control_value"
    assert captured["params"]["params"] == ["gain", 120]
