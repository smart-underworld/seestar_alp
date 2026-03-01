import json

import front.app as front_app
from device.config import Config


class DummyReq:
    def __init__(self, host="localhost:5432", scheme="http"):
        self.host = host
        self.scheme = scheme
        self.relative_uri = "/1/live"


class DummyResp:
    def __init__(self):
        self.cookies = []

    def set_cookie(self, key, value, path="/"):
        self.cookies.append((key, value, path))


def test_flash_and_get_messages_roundtrip():
    front_app.messages.clear()
    resp = DummyResp()
    front_app.flash(resp, "hello")

    assert resp.cookies == [("flash_cookie", "hello", "/")]
    assert front_app.get_messages() == ["hello"]
    assert front_app.get_messages() == []


def test_get_root_and_imager_root(monkeypatch):
    monkeypatch.setattr(
        Config,
        "seestars",
        [
            {"device_num": 1, "name": "A", "ip_address": "a.local"},
            {"device_num": 2, "name": "B", "ip_address": "b.local"},
        ],
    )
    monkeypatch.setattr(Config, "imgport", 7556)
    req = DummyReq(host="myhost:1234")

    assert front_app.get_root(0) == "/0"
    assert front_app.get_root(2) == "/2"
    assert front_app.get_imager_root(2, req) == "http://myhost:7556/2"


def test_get_imager_root_strips_incoming_port_and_preserves_scheme(monkeypatch):
    monkeypatch.setattr(
        Config,
        "seestars",
        [
            {"device_num": 2, "name": "B", "ip_address": "b.local"},
        ],
    )
    monkeypatch.setattr(Config, "imgport", 7556)
    req = DummyReq(host="securehost.example:8443", scheme="https")

    assert front_app.get_imager_root(2, req) == "https://securehost.example:7556/2"


def test_process_queue_dispatches_actions(monkeypatch):
    calls = []
    front_app.queue.clear()
    front_app.queue[1] = [
        {"Parameters": json.dumps({"action": "wait_for", "params": {"timer_sec": 5}})},
        {"Parameters": json.dumps({"action": "noop", "params": None})},
    ]
    monkeypatch.setattr(front_app, "check_api_state", lambda telescope_id: True)
    monkeypatch.setattr(
        front_app,
        "do_schedule_action_device",
        lambda action, params, telescope_id: (
            calls.append((action, params, telescope_id)) or {"ok": True}
        ),
    )

    front_app.process_queue(DummyResp(), 1)
    assert calls == [("wait_for", {"timer_sec": 5}, 1), ("noop", None, 1)]


def test_process_queue_offline_flashes_error(monkeypatch):
    monkeypatch.setattr(front_app, "check_api_state", lambda telescope_id: False)
    resp = DummyResp()
    front_app.process_queue(resp, 1)
    msgs = front_app.get_messages()
    assert any("API is Offline" in msg for msg in msgs)


def test_get_nearest_csc_uses_result_cache(monkeypatch):
    monkeypatch.setattr(Config, "init_lat", 42.0)
    monkeypatch.setattr(Config, "init_long", -71.0)
    front_app._nearest_csc_cache.clear()

    calls = {"count": 0}

    def fake_get_csc_sites_data():
        calls["count"] += 1
        return {
            "42": {
                "-71": [
                    {"id": "TEST", "lat": 42.0, "lng": -71.0},
                ]
            }
        }

    monkeypatch.setattr(front_app, "get_csc_sites_data", fake_get_csc_sites_data)

    first = front_app.get_nearest_csc()
    second = front_app.get_nearest_csc()

    assert first["status_msg"] == "SUCCESS"
    assert second["status_msg"] == "SUCCESS"
    assert first["href"] == "https://www.cleardarksky.com/c/TESTkey.html"
    assert calls["count"] == 1


def test_get_planning_cards_uses_file_mtime_cache(monkeypatch, tmp_path):
    planning_file = tmp_path / "planning.json"
    planning_file.write_text(
        json.dumps(
            [
                {
                    "card_name": "twilight_times",
                    "planning_page_enable": True,
                    "planning_page_collapsed": False,
                }
            ]
        )
    )

    original_json_load = front_app.json.load
    calls = {"count": 0}

    def counting_json_load(fp):
        calls["count"] += 1
        return original_json_load(fp)

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    monkeypatch.setattr(front_app.json, "load", counting_json_load)
    front_app._planning_cards_cache = None
    front_app._planning_cards_cache_mtime = None

    first = front_app.get_planning_cards()
    second = front_app.get_planning_cards()

    assert first[0]["card_name"] == "twilight_times"
    assert second[0]["card_name"] == "twilight_times"
    assert calls["count"] == 1


def test_update_planning_card_state_invalidates_cache(monkeypatch, tmp_path):
    planning_file = tmp_path / "planning.json"
    planning_file.write_text(
        json.dumps(
            [
                {
                    "card_name": "twilight_times",
                    "planning_page_enable": True,
                    "planning_page_collapsed": False,
                }
            ]
        )
    )

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    front_app._planning_cards_cache = None
    front_app._planning_cards_cache_mtime = None

    cards = front_app.get_planning_cards()
    assert cards[0]["planning_page_enable"] is True
    assert front_app._planning_cards_cache is not None

    front_app.update_planning_card_state(
        "twilight_times", "planning_page_enable", False
    )

    assert front_app._planning_cards_cache is None
    updated_cards = front_app.get_planning_cards()
    assert updated_cards[0]["planning_page_enable"] is False


def test_get_csc_sites_data_uses_in_memory_cache(monkeypatch, tmp_path):
    csc_file = tmp_path / "csc_sites.json"
    csc_file.write_text(json.dumps({"42": {"-71": [{"id": "A"}]}}))

    original_json_load = front_app.json.load
    calls = {"count": 0}

    def counting_json_load(fp):
        calls["count"] += 1
        return original_json_load(fp)

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    monkeypatch.setattr(front_app.json, "load", counting_json_load)
    front_app._csc_sites_cache = None

    first = front_app.get_csc_sites_data()
    second = front_app.get_csc_sites_data()

    assert first == second
    assert calls["count"] == 1
