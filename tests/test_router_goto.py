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
    row, so the ranking logic is exercised for both shapes. A fourth
    "Decoy Object" row (identifier "XNGC688") is inserted before the
    Crescent Nebula row specifically to test that prefix-tier matches
    outrank substring-tier matches regardless of row order."""
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
            ("21h00m00.00s", "+40d00m00.0s", "Decoy Object", "XNGC688"),
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


def test_search_local_comma_delimiter_is_not_a_real_substring(alp_dat):
    """Verify comma-joined identifiers are split into real tokens, not
    treated as one raw string.

    "8,NGC" is a literal substring of the raw stored identifiers field
    "M8,NGC6523" (characters at index 1-5 are '8', ',', 'N', 'G', 'C'), so
    the old pre-fix code (LIKE '%q%' against the raw unsplit
    identifiers/commonNames columns) would incorrectly match this row and
    return "Lagoon Nebula". But once "M8,NGC6523" is split on its comma
    into the real tokens "M8" and "NGC6523", neither individual token
    contains "8,NGC" as a substring -- so the fixed, correctly-tokenized
    code returns None. Verified this query doesn't accidentally match any
    other fixture row either way. This is the one query in the suite that
    actually depends on comma-splitting rather than matching the raw
    concatenated/unsplit field.
    """
    result = _rg._search_local("8,NGC")
    assert result is None


def test_search_local_ignores_spacing_and_case(alp_dat):
    result = _rg._search_local("ngc 6888")
    assert result is not None
    assert result["objectName"] == "Crescent Nebula"


def test_search_local_no_match_when_query_exceeds_token_length(alp_dat):
    """Verify we don't over-match: 'M82X' has no token that starts with it.

    Even though 'M82' exists, 'M82X' is not a prefix of any token (it's
    longer and diverges), so we correctly return None instead of matching
    'M82' and over-matching.
    """
    result = _rg._search_local("M82X")
    assert result is None


def test_search_local_prefix_match_beats_substring_match(alp_dat):
    """Verify prefix-tier matching outranks substring-tier matching.

    Querying "NGC688" matches two rows: "XNGC688" only as a substring (it
    does NOT start with "NGC688" -- it starts with "X"), and "NGC6888" as a
    genuine prefix. The decoy row is inserted with a LOWER rowid than the
    "NGC6888" row (see fixture), so the old unranked `LIKE '%q%' LIMIT 1`
    query (no ORDER BY) returns the decoy "Decoy Object" first in scan
    order. This test only returns the correct "Crescent Nebula" if prefix
    tier is explicitly ranked above substring tier -- verified by hand
    tracing both the old and new code against this exact fixture.
    """
    result = _rg._search_local("NGC688")
    assert result is not None
    assert result["objectName"] == "Crescent Nebula"


def test_search_local_substring_match(alp_dat):
    """Verify the substring-tier return path works: '6523' is not an exact
    token nor a prefix of any token, but it is a substring of 'NGC6523', so
    it should return Lagoon Nebula via the substring fallback tier.

    Note: this query has only one matching row, so unlike
    test_search_local_prefix_match_beats_substring_match above, it does not
    by itself discriminate old vs. new behavior -- it only confirms the
    substring tier's positive-match return path still works.
    """
    result = _rg._search_local("6523")
    assert result is not None
    assert result["objectName"] == "Lagoon Nebula"


def test_search_planet_resolves_sun():
    result = _rg._search_planet("sun")
    assert result is not None
    assert result["name"] == "Sun"
    assert result["ra"]
    assert result["dec"]


def test_search_planet_resolves_moon():
    result = _rg._search_planet("moon")
    assert result is not None
    assert result["name"] == "Moon"
    assert result["ra"]
    assert result["dec"]
