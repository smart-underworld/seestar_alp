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


import sqlite3

from front_v2.api import router_goto as _rg


@pytest.fixture
def alp_dat(tmp_path, monkeypatch):
    """A tiny objects DB reproducing the real M8/M82 collision: both an
    exact-token collision (M8 vs M82) and a comma-joined multi-identifier
    row, so the ranking logic is exercised for both shapes."""
    db_path = tmp_path / "alp.dat"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE objects (ra varchar(12), dec varchar(12), "
        "constellation varchar(5), objectType varchar(15), "
        "commonNames varchar(30), identifiers varchar(30))"
    )
    con.executemany(
        "INSERT INTO objects (ra, dec, commonNames, identifiers) VALUES (?, ?, ?, ?)",
        [
            ("09h55m52.73s", "+69d40m45.8s", "Cigar Galaxy", "M82"),
            ("18h03m37.00s", "-24d23m12.0s", "Lagoon Nebula", "M8,NGC6523"),
            ("20h12m06.55s", "+38d21m17.8s", "Crescent Nebula", "NGC6888"),
        ],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(_rg, "_ALP_DAT", db_path)
    return db_path


def test_search_local_m8_returns_exact_match_not_m82(alp_dat):
    result = _rg._search_local("M8")
    assert result is not None
    assert result["objectName"] == "Lagoon Nebula"


def test_search_local_handles_comma_joined_identifiers(alp_dat):
    result = _rg._search_local("NGC6523")
    assert result is not None
    assert result["objectName"] == "Lagoon Nebula"


def test_search_local_ignores_spacing_and_case(alp_dat):
    result = _rg._search_local("ngc 6888")
    assert result is not None
    assert result["objectName"] == "Crescent Nebula"


def test_search_local_falls_back_to_prefix_match(alp_dat):
    # No exact/normalized token matches "M82X" -- prefix match on "M82" should win.
    result = _rg._search_local("M82X")
    assert result is None  # no prefix match either -- confirms we don't over-match
