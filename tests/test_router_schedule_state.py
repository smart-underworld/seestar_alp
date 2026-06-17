"""
Unit tests for POST /api/v1/devices/{n}/schedule/state action mapping.

Covers the "resume" action added alongside "start"/"stop"/"pause" so a
paused scheduler can actually be un-paused from the UI (continue_scheduler).
"""

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from front_v2.api import router_schedule  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(router_schedule, "check_api_state", lambda dev_num: True)
    app = FastAPI()
    app.include_router(router_schedule.router)
    return TestClient(app)


@pytest.mark.parametrize(
    "state,expected_action",
    [
        ("start", "start_scheduler"),
        ("stop", "stop_scheduler"),
        ("pause", "pause_scheduler"),
        ("resume", "continue_scheduler"),
    ],
)
def test_toggle_schedule_action_mapping(client, monkeypatch, state, expected_action):
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        return {"ok": True}

    monkeypatch.setattr(router_schedule, "do_action", fake_do_action)

    r = client.post(f"/api/v1/devices/1/schedule/state?state={state}")
    assert r.status_code == 200
    assert captured["action"] == expected_action
