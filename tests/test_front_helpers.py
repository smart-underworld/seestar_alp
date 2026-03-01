import threading

import front.app as front_app
from front.app import (
    EventStatus,
    check_dec_value,
    check_ra_value,
    determine_file_type,
    get_request_cache_identity,
    hms_to_sec,
    import_csv_schedule,
    respond_204_if_unchanged,
)


class DummyResp:
    def __init__(self, text):
        self.text = text
        self.status = None


class DummyReq:
    def __init__(
        self,
        action="goto",
        headers=None,
        relative_uri="/1/goto",
        remote_addr="192.168.1.10",
    ):
        self._action = action
        self._headers = headers or {}
        self.relative_uri = relative_uri
        self.remote_addr = remote_addr

    def get_param(self, name, default=None):
        if name == "action":
            return self._action
        return default

    def get_header(self, name):
        return self._headers.get(name)


def test_check_ra_value_accepts_multiple_formats():
    assert check_ra_value("12h 30m 10.5s")
    assert check_ra_value("12.5")
    assert check_ra_value("12 30 10.5")


def test_check_dec_value_accepts_multiple_formats():
    assert check_dec_value("+12d 30m 10.5s")
    assert check_dec_value("-10.25")
    assert check_dec_value("-10 20 30")


def test_hms_to_sec_parsing_and_passthrough():
    assert hms_to_sec("1h2m3s") == 3723
    assert hms_to_sec("90") == 90
    assert hms_to_sec("bad-input") == "bad-input"


def test_determine_file_type(tmp_path):
    json_file = tmp_path / "test.json"
    csv_file = tmp_path / "test.csv"
    unknown_file = tmp_path / "test.unknown"

    json_file.write_text('{"a": 1}', encoding="utf-8")
    csv_file.write_text("col1,col2\n1,2\n", encoding="utf-8")
    unknown_file.write_text("", encoding="utf-8")

    assert determine_file_type(str(json_file)) == "json"
    assert determine_file_type(str(csv_file)) == "csv"
    assert determine_file_type(str(unknown_file)) == "unknown"


def test_respond_204_if_unchanged_sets_status():
    cache = {}
    lock = threading.Lock()
    key = "fragment-key"

    first = DummyResp("<div>hello</div>")
    respond_204_if_unchanged(first, cache, lock, key)
    assert first.status is None
    assert first.text == "<div>hello</div>"

    second = DummyResp("<div>hello</div>")
    respond_204_if_unchanged(second, cache, lock, key)
    assert second.status == "204 No Content"
    assert second.text == ""


def test_import_csv_schedule_wait_for_dispatch(monkeypatch):
    calls = []

    def fake_dispatch(action, params, telescope_id):
        calls.append((action, params, telescope_id))

    monkeypatch.setattr(front_app, "do_schedule_action_device", fake_dispatch)
    csv_input = "action,timer_sec\nwait_for,30\n"
    import_csv_schedule([csv_input], telescope_id=1)

    assert calls == [("wait_for", {"timer_sec": 30}, 1)]


def test_import_csv_schedule_startup_3ppa_to_polar_align(monkeypatch):
    calls = []

    def fake_dispatch(action, params, telescope_id):
        calls.append((action, params, telescope_id))

    monkeypatch.setattr(front_app, "do_schedule_action_device", fake_dispatch)
    csv_input = (
        "action,3ppa,auto_focus,dark_frames\nstart_up_sequence,true,false,true\n"
    )
    import_csv_schedule([csv_input], telescope_id=2)

    assert calls == [
        (
            "start_up_sequence",
            {"auto_focus": False, "3ppa": True, "dark_frames": True},
            2,
        )
    ]


def test_get_request_cache_identity_uses_headers_and_remote():
    req = DummyReq(
        headers={"User-Agent": "UA-1", "HX-Current-URL": "http://host/1/goto"},
        remote_addr="10.0.0.5",
    )
    ident = get_request_cache_identity(req)
    assert ident == ("10.0.0.5", "UA-1", "http://host/1/goto")


def test_event_status_cache_is_scoped_per_client(monkeypatch):
    EventStatus._last_render_by_key.clear()

    monkeypatch.setattr(front_app, "get_context", lambda telescope_id, req: {})
    monkeypatch.setattr(
        front_app,
        "do_action_device",
        lambda action, telescope_id, params: {"Value": {}},
    )

    def fake_render_template(req, resp, template_name, **context):
        resp.status = "200 OK"
        resp.content_type = "text/html"
        resp.text = "<div>same-status</div>"

    monkeypatch.setattr(front_app, "render_template", fake_render_template)

    req_desktop = DummyReq(
        action="goto",
        headers={"User-Agent": "Desktop-UA", "HX-Current-URL": "http://host/1/goto"},
        remote_addr="192.168.1.20",
    )
    req_phone = DummyReq(
        action="goto",
        headers={"User-Agent": "Phone-UA", "HX-Current-URL": "http://host/1/goto"},
        remote_addr="192.168.1.21",
    )

    resp_desktop = DummyResp("")
    EventStatus.on_get(req_desktop, resp_desktop, telescope_id=1)
    assert resp_desktop.status == "200 OK"

    resp_phone = DummyResp("")
    EventStatus.on_get(req_phone, resp_phone, telescope_id=1)
    assert resp_phone.status == "200 OK"

    resp_desktop_repeat = DummyResp("")
    EventStatus.on_get(req_desktop, resp_desktop_repeat, telescope_id=1)
    assert resp_desktop_repeat.status == "204 No Content"


def test_event_status_command_polar_align_not_suppressed_across_clients(monkeypatch):
    EventStatus._last_render_by_key.clear()

    monkeypatch.setattr(front_app, "get_context", lambda telescope_id, req: {})
    monkeypatch.setattr(
        front_app,
        "do_action_device",
        lambda action, telescope_id, params: {"Value": {}},
    )

    def fake_render_template(req, resp, template_name, **context):
        # Keep html stable to exercise the 204 dedupe path.
        resp.status = "200 OK"
        resp.content_type = "text/html"
        resp.text = "<div>3PPA running</div>"

    monkeypatch.setattr(front_app, "render_template", fake_render_template)

    req_phone_a = DummyReq(
        action="command",
        headers={"User-Agent": "Phone-A", "HX-Current-URL": "http://host/1/command"},
        remote_addr="192.168.1.31",
    )
    req_phone_b = DummyReq(
        action="command",
        headers={"User-Agent": "Phone-B", "HX-Current-URL": "http://host/1/command"},
        remote_addr="192.168.1.32",
    )

    resp_a_first = DummyResp("")
    EventStatus.on_get(req_phone_a, resp_a_first, telescope_id=1)
    assert resp_a_first.status == "200 OK"

    resp_b_first = DummyResp("")
    EventStatus.on_get(req_phone_b, resp_b_first, telescope_id=1)
    assert resp_b_first.status == "200 OK"

    resp_a_repeat = DummyResp("")
    EventStatus.on_get(req_phone_a, resp_a_repeat, telescope_id=1)
    assert resp_a_repeat.status == "204 No Content"
