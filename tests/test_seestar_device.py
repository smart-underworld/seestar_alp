import collections
from types import SimpleNamespace

import pytest

from device.config import Config
from device.seestar_device import Seestar


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def warn(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


@pytest.fixture
def seestar():
    return Seestar(DummyLogger(), "127.0.0.1", 4700, "TestScope", 1, False, True)


def test_should_inject_verify_respects_config_and_firmware(seestar):
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        seestar.firmware_ver_int = 0
        assert seestar.should_inject_verify() is True

        seestar.firmware_ver_int = 2582
        assert seestar.should_inject_verify() is False

        seestar.firmware_ver_int = 2583
        assert seestar.should_inject_verify() is True

        Config.verify_injection = False
        assert seestar.should_inject_verify() is False
    finally:
        Config.verify_injection = old_setting


def test_transform_message_for_verify_dict_params(seestar):
    seestar.firmware_ver_int = 3000
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        msg = {"method": "set_setting", "params": {"a": 1}}
        out = seestar.transform_message_for_verify(msg)
        assert out["params"]["verify"] is True
        assert "verify" not in msg["params"]
    finally:
        Config.verify_injection = old_setting


def test_transform_message_for_verify_list_params(seestar):
    seestar.firmware_ver_int = 3000
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        out = seestar.transform_message_for_verify(
            {"method": "scope_goto", "params": [12.3, 45.6]}
        )
        assert out["params"] == [[12.3, 45.6], "verify"]

        wheel = seestar.transform_message_for_verify(
            {"method": "set_wheel_position", "params": [1]}
        )
        assert wheel["params"] == [1, "verify"]
    finally:
        Config.verify_injection = old_setting


def test_send_message_param_assigns_id_and_serializes(monkeypatch, seestar):
    sent = {}

    def fake_send_message(payload):
        sent["payload"] = payload
        return True

    seestar.send_message = fake_send_message
    seestar.firmware_ver_int = 2000

    cmd_id = seestar.send_message_param({"method": "scope_get_equ_coord"})
    assert cmd_id == 10000
    assert '"id": 10000' in sent["payload"]
    assert sent["payload"].endswith("\r\n")


def test_schedule_create_and_add_item(seestar):
    new_schedule = seestar.create_schedule({})
    assert new_schedule["state"] == "stopped"
    assert isinstance(new_schedule["list"], collections.deque)

    seestar.add_schedule_item({"action": "wait_for", "params": {"timer_sec": 5}})
    assert len(seestar.schedule["list"]) == 1
    assert seestar.schedule["list"][0]["action"] == "wait_for"
    assert "schedule_item_id" in seestar.schedule["list"][0]


def test_start_scheduler_rejects_when_not_master(monkeypatch, seestar):
    seestar.is_client_master = lambda: False
    seestar.schedule["state"] = "stopped"
    result = seestar.start_scheduler({})
    assert result["code"] == -1


def test_start_scheduler_starts_thread(monkeypatch, seestar):
    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon
            self.name = ""
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    seestar.is_client_master = lambda: True
    seestar.schedule["state"] = "stopped"

    result = seestar.start_scheduler({})
    assert result is seestar.schedule
    assert seestar.scheduler_thread.started is True


def test_stop_scheduler_transitions_and_calls_ops(seestar):
    called = {"slew": 0, "stack": 0, "sound": 0}
    seestar.stop_slew = lambda: called.__setitem__("slew", called["slew"] + 1)
    seestar.stop_stack = lambda: called.__setitem__("stack", called["stack"] + 1)
    seestar.play_sound = lambda *_: called.__setitem__("sound", called["sound"] + 1)
    seestar.schedule["state"] = "working"

    result = seestar.stop_scheduler({})
    assert result["code"] == 0
    assert seestar.schedule["state"] == "stopped"
    assert called == {"slew": 1, "stack": 1, "sound": 1}


def test_goto_target_returns_false_if_already_in_goto(seestar):
    seestar.is_goto = lambda: True
    ok = seestar.goto_target(
        {"is_j2000": False, "ra": "12h00m00s", "dec": "+10d00m00s", "target_name": "x"}
    )
    assert ok is False


def test_goto_target_sends_expected_request(monkeypatch, seestar):
    class FakeCoord:
        ra = SimpleNamespace(hour=1.5)
        dec = SimpleNamespace(deg=22.25)

    captured = {}
    seestar.is_goto = lambda: False
    seestar.mark_op_state = lambda *args, **kwargs: None
    seestar.send_message_param_sync = lambda payload: captured.setdefault(
        "payload", payload
    ) or {"result": "ok"}
    monkeypatch.setattr(
        "device.seestar_device.Util.parse_coordinate", lambda *args, **kwargs: FakeCoord
    )

    ok = seestar.goto_target(
        {"is_j2000": True, "ra": "01h30m00s", "dec": "+22d15m00s", "target_name": "M42"}
    )
    assert ok is True
    req = captured["payload"]
    assert req["method"] == "iscope_start_view"
    assert req["params"]["target_ra_dec"] == [1.5, 22.25]
    assert req["params"]["target_name"] == "M42"


def test_parse_dec_to_float_positive_and_negative(seestar):
    assert seestar.parse_dec_to_float("12:30:00") == 12.5
    assert seestar.parse_dec_to_float("-12:30:00") == -11.5


def test_get_pa_error_defaults_when_unknown(seestar):
    seestar.cur_pa_error_x = None
    seestar.cur_pa_error_y = None
    out = seestar.get_pa_error({})
    assert out == {"pa_error_alt": 9999.9, "pa_error_az": 9999.9}


def test_get_pa_error_returns_current_values(seestar):
    seestar.cur_pa_error_x = 1.23
    seestar.cur_pa_error_y = 4.56
    out = seestar.get_pa_error({})
    assert out == {"pa_error_alt": 4.56, "pa_error_az": 1.23}
