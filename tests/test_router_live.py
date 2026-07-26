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


def _fake_method_sync(stage: str, exp_ms: dict, gain=999):
    def _inner(method, dev_num, **kwargs):
        if method == "get_setting":
            return {
                "exp_ms": exp_ms,
                "gain": 999,
            }  # gain intentionally wrong shape here -- get_setting never has it
        if method == "get_view_state":
            return {"View": {"stage": stage, "gain": gain}}
        return None

    return _inner


def test_get_exposure_returns_stack_l_while_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("Stack", {"stack_l": 20000, "continuous": 2000}),
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["exp_ms"] == 20000


def test_get_exposure_returns_continuous_when_not_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("", {"stack_l": 20000, "continuous": 2000}),
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["exp_ms"] == 2000


def test_set_exposure_writes_stack_l_while_stacking(client, monkeypatch):
    captured = {}

    def fake_method_sync(method, dev_num, **kwargs):
        if method == "get_view_state":
            return {"View": {"stage": "Stack"}}
        if method == "set_setting":
            captured["method"] = method
            captured["params"] = kwargs.get("params")
            return {"ok": True}
        return None

    monkeypatch.setattr(router_live, "method_sync", fake_method_sync)

    r = client.post("/api/v1/devices/1/live/exposure", json={"exp_ms": 20000})
    assert r.status_code == 200
    assert captured["method"] == "set_setting"
    assert captured["params"] == {"exp_ms": {"stack_l": 20000}}


def test_set_exposure_writes_continuous_when_not_stacking(client, monkeypatch):
    captured = {}

    def fake_method_sync(method, dev_num, **kwargs):
        if method == "get_view_state":
            return {"View": {"stage": "Idle"}}
        if method == "set_setting":
            captured["params"] = kwargs.get("params")
            return {"ok": True}
        return None

    monkeypatch.setattr(router_live, "method_sync", fake_method_sync)

    r = client.post("/api/v1/devices/1/live/exposure", json={"exp_ms": 2000})
    assert r.status_code == 200
    assert captured["params"] == {"exp_ms": {"continuous": 2000}}


def test_get_exposure_reads_gain_from_view_state(client, monkeypatch):
    """gain has no field in get_setting/get_stack_setting on any firmware
    version -- it's read from get_view_state's live "View" object, the same
    call already used for stage. Unlike push events (Event: "View"/
    "Exposure", which only fire on view-state transitions), get_view_state
    is an on-demand query that reflects the current gain."""
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("Idle", {"stack_l": 20000, "continuous": 2000}, gain=42),
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["gain"] == 42


def test_get_exposure_gain_zero_passthrough(client, monkeypatch):
    """Verify that a real gain=0 reading (valid, not missing) passes through unchanged."""
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("Idle", {"stack_l": 20000, "continuous": 2000}, gain=0),
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["gain"] == 0


def test_get_exposure_falls_back_to_80_when_gain_missing(client, monkeypatch):
    """If get_view_state's View has no gain field (e.g. no view active),
    fall back to the same 80 default as before rather than raising."""
    monkeypatch.setattr(
        router_live,
        "method_sync",
        lambda method, dev_num, **kwargs: {
            "exp_ms": {"stack_l": 20000, "continuous": 2000}
        }
        if method == "get_setting"
        else ({"View": {}} if method == "get_view_state" else None),
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["gain"] == 80


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
