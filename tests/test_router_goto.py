"""
Unit tests for front_v2 goto router (/api/v1/devices/{n}/goto).

Regression coverage for the action name bugs:
  - goto  used "scope_goto" (unregistered) instead of "goto_target"
  - cancel used "stop_goto"  (unregistered) instead of "stop_goto_target"
Both produced empty Alpaca responses → JSONDecodeError in do_action.
"""

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from front_v2.api import router_goto  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(router_goto, "check_api_state", lambda dev_num: True)
    app = FastAPI()
    app.include_router(router_goto.router)
    return TestClient(app)


def test_goto_uses_goto_target_action(client, monkeypatch):
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        captured["params"] = params
        return {"ErrorNumber": 0, "Value": ""}

    monkeypatch.setattr(router_goto, "do_action", fake_do_action)

    r = client.post(
        "/api/v1/devices/1/goto",
        json={
            "ra": "16h03m01.48s",
            "dec": "-25d53m21.4s",
            "target_name": "Moon",
            "is_j2000": True,
        },
    )
    assert r.status_code == 200
    assert captured["action"] == "goto_target"
    assert captured["params"]["target_name"] == "Moon"


def test_cancel_goto_uses_stop_goto_target_action(client, monkeypatch):
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        return {"ErrorNumber": 0, "Value": ""}

    monkeypatch.setattr(router_goto, "do_action", fake_do_action)

    r = client.delete("/api/v1/devices/1/goto")
    assert r.status_code == 200
    assert captured["action"] == "stop_goto_target"


def test_force_stop_goto_uses_force_action(client, monkeypatch):
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        captured["params"] = params
        return {"ok": True, "stop_slew_result": {"result": "ok"}}

    monkeypatch.setattr(router_goto, "do_action", fake_do_action)

    r = client.post("/api/v1/devices/1/goto/force-stop")
    assert r.status_code == 200
    assert captured["action"] == "force_stop_goto"
    assert captured["params"] == {}
    assert r.json()["ok"] is True


def test_force_stop_goto_reports_no_response(client, monkeypatch):
    monkeypatch.setattr(router_goto, "do_action", lambda *a: None)

    r = client.post("/api/v1/devices/1/goto/force-stop")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "reason": "no response"}
