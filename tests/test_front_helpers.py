import threading

import front.app as front_app
from front.app import (
    check_dec_value,
    check_ra_value,
    determine_file_type,
    hms_to_sec,
    import_csv_schedule,
    respond_204_if_unchanged,
)


class DummyResp:
    def __init__(self, text):
        self.text = text
        self.status = None


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
