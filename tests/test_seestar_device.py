import collections
import socket
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

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


@pytest.fixture
def seestar():
    return Seestar(DummyLogger(), "127.0.0.1", 4700, "TestScope", 1, True)


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
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True

        # Pre-7.06 firmware: verify injected as a key inside the dict params.
        seestar.firmware_ver_int = 2705
        msg = {"method": "set_setting", "params": {"a": 1}}
        out = seestar.transform_message_for_verify(msg)
        assert out["params"]["verify"] is True
        assert "verify" not in msg["params"]  # original not mutated

        # 7.06+ firmware: verify must NOT be injected into dict params at all.
        # Both {"verify": true} (code 109) and [dict, "verify"] (code 107) are rejected.
        # The device is SSL-authenticated so dict-param commands don't need verify.
        seestar.firmware_ver_int = 2706
        out = seestar.transform_message_for_verify(
            {"method": "set_setting", "params": {"a": 1}}
        )
        assert out["params"] == {"a": 1}
        assert "verify" not in out["params"]

        seestar.firmware_ver_int = 3000
        out = seestar.transform_message_for_verify(
            {"method": "set_setting", "params": {"a": 1}}
        )
        assert out["params"] == {"a": 1}
        assert "verify" not in out["params"]
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


def test_transform_message_for_verify_no_params_adds_verify(seestar):
    seestar.firmware_ver_int = 3000
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        out = seestar.transform_message_for_verify({"method": "noop"})
        assert out["params"] == ["verify"]
    finally:
        Config.verify_injection = old_setting


def test_transform_message_for_verify_keeps_existing_verify_list(seestar):
    seestar.firmware_ver_int = 3000
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        out = seestar.transform_message_for_verify(
            {"method": "scope_goto", "params": [[1.0, 2.0], "verify"]}
        )
        assert out["params"] == [[1.0, 2.0], "verify"]
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


def test_slew_to_ra_dec_refuses_inside_sun_cone(monkeypatch, seestar):
    """Spec: _slew_to_ra_dec converts (ra, dec) to sky (az, alt) and
    refuses (returns False, no scope_goto sent) when the target is
    inside the sun-avoidance cone."""
    from device import sun_safety as ss
    # Have the method's altaz conversion return a concrete (alt, az).
    seestar.get_altaz_from_eq = lambda *_a, **_kw: [33.0, 180.0]
    # Force is_sun_safe to refuse.
    monkeypatch.setattr(
        ss, "is_sun_safe",
        lambda *a, **kw: (False, "sun_avoidance: forced by test"),
    )
    seestar.mark_op_state = lambda *_a, **_kw: None

    sent = []
    seestar.send_message_param_sync = lambda payload: (sent.append(payload) or {"result": "ok"})

    ok = seestar._slew_to_ra_dec([5.0, 30.0])
    assert ok is False
    assert sent == [], "scope_goto must not be sent when sun-safety refuses"


def test_slew_to_ra_dec_proceeds_when_altaz_conversion_unavailable(monkeypatch, seestar):
    """If get_altaz_from_eq returns the 9999.9 sentinel (frame not set
    up yet), the pre-flight check falls through and the slew still
    goes out — the SunSafetyMonitor is the runtime backstop."""
    # Sentinel return from get_altaz_from_eq.
    seestar.get_altaz_from_eq = lambda *_a, **_kw: [9999.9, 9999.9]
    seestar.mark_op_state = lambda *_a, **_kw: None
    seestar.wait_end_op = lambda *_a, **_kw: True

    sent = []
    seestar.send_message_param_sync = lambda payload: (sent.append(payload) or {"result": "ok"})

    ok = seestar._slew_to_ra_dec([5.0, 30.0])
    assert ok is True
    assert len(sent) == 1
    assert sent[0]["method"] == "scope_goto"


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
    seestar.send_message_param_sync = lambda payload: (
        captured.setdefault("payload", payload) or {"result": "ok"}
    )
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
    assert seestar.parse_dec_to_float("-12:30:00") == -12.5


def test_parse_dec_to_float_sign_applies_to_whole_value(seestar):
    """Regression: sign must apply to the full degrees+minutes+seconds sum, not just degrees."""
    # -0:30:00 = -0.5, not +0.5
    assert seestar.parse_dec_to_float("-0:30:00") == -0.5
    # -89:59:59.9 ≈ -89.9999... (close to south pole)
    result = seestar.parse_dec_to_float("-89:59:60")
    assert result < -89.9
    # +0:15:00 = +0.25
    assert seestar.parse_dec_to_float("0:15:00") == 0.25


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


class _DummySocket:
    def __init__(self, *, recv_value=None, recv_error=None, send_error=None):
        self.recv_value = recv_value
        self.recv_error = recv_error
        self.send_error = send_error
        self.closed = False
        self.sent = []

    def recv(self, _n):
        if self.recv_error is not None:
            raise self.recv_error
        return self.recv_value

    def sendall(self, payload):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(payload)

    def close(self):
        self.closed = True


def test_repr_and_get_name(seestar):
    assert "Seestar(host=127.0.0.1, port=4700)" == repr(seestar)
    assert seestar.get_name() == "TestScope"


def test_fixed_size_ordered_dict_drops_oldest():
    from device.seestar_device import FixedSizeOrderedDict

    d = FixedSizeOrderedDict(maxsize=2)
    d["a"] = 1
    d["b"] = 2
    d["c"] = 3
    assert list(d.keys()) == ["b", "c"]


def test_deque_encoder_serializes_deque():
    from device.seestar_device import DequeEncoder
    import json

    encoded = json.dumps({"v": collections.deque([1, 2])}, cls=DequeEncoder)
    assert encoded == '{"v": [1, 2]}'


def test_send_message_paths(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    seestar.s = None
    assert seestar.send_message("x") is False

    seestar.s = _DummySocket(send_error=socket.timeout())
    assert seestar.send_message("x") is False

    disconnected = {"count": 0}
    monkeypatch.setattr(
        seestar, "disconnect", lambda: disconnected.__setitem__("count", 1)
    )
    monkeypatch.setattr(seestar, "reconnect", lambda: False)
    seestar.is_watch_events = True
    seestar.s = _DummySocket(send_error=socket.error("boom"))
    assert seestar.send_message("x") is False
    assert disconnected["count"] == 1

    class GeneralSock:
        def sendall(self, _payload):
            raise RuntimeError("nope")

    seestar.s = GeneralSock()
    assert seestar.send_message("x") is False


def test_socket_force_close_and_disconnect(seestar):
    s = _DummySocket()
    seestar.s = s
    seestar.socket_force_close()
    assert s.closed is True
    assert seestar.s is None

    seestar.s = _DummySocket()
    seestar.is_connected = True
    seestar.disconnect()
    assert seestar.is_connected is False
    assert seestar.s is None


def test_reconnect_success_and_fail_paths(monkeypatch, seestar):
    monkeypatch.setattr(seestar, "send_udp_intro", lambda: None)
    monkeypatch.setattr(seestar, "disconnect", lambda: None)

    class Sock:
        def __init__(self):
            self.connected = None

        def settimeout(self, _v):
            return None

        def connect(self, addr):
            self.connected = addr

    monkeypatch.setattr("device.seestar_device.socket.socket", lambda *_args: Sock())
    seestar.is_connected = False
    assert seestar.reconnect() is True

    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)

    class BadSock:
        def settimeout(self, _v):
            return None

        def connect(self, _addr):
            raise socket.error("bad")

    seestar.is_connected = False
    monkeypatch.setattr("device.seestar_device.socket.socket", lambda *_args: BadSock())
    assert seestar.reconnect() is False


def test_get_socket_msg_paths(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    seestar.s = None
    assert seestar.get_socket_msg() is None

    seestar.s = _DummySocket(recv_error=socket.timeout())
    assert seestar.get_socket_msg() is None

    disconnected = {"count": 0}
    monkeypatch.setattr(
        seestar, "disconnect", lambda: disconnected.__setitem__("count", 1)
    )
    monkeypatch.setattr(seestar, "reconnect", lambda: False)
    seestar.is_watch_events = True
    seestar.s = _DummySocket(recv_error=socket.error("x"))
    assert seestar.get_socket_msg() is None
    assert disconnected["count"] == 1

    seestar.s = _DummySocket(recv_value=b"")
    assert seestar.get_socket_msg() is None

    seestar.s = _DummySocket(recv_value=b"hello")
    assert seestar.get_socket_msg() == "hello"


def test_update_equ_coord_and_view_state(seestar):
    assert seestar.has_equ_coord is False
    seestar.update_equ_coord(
        {"method": "scope_get_equ_coord", "result": {"ra": "1.25", "dec": "2.5"}}
    )
    assert seestar.ra == 1.25
    assert seestar.dec == 2.5
    assert seestar.has_equ_coord is True

    seestar.update_view_state(
        {"method": "get_view_state", "result": {"View": {"a": 1}}}
    )
    assert seestar.view_state == {"a": 1}


def test_json_message_increments_cmdid(monkeypatch, seestar):
    sent = []
    monkeypatch.setattr(seestar, "send_message", lambda payload: sent.append(payload))
    start = seestar.cmdid
    seestar.json_message("scope_get_equ_coord", id=420)
    assert seestar.cmdid == start + 1
    assert '"method": "scope_get_equ_coord"' in sent[0]


def test_send_message_param_sync_shutdown_and_wait_paths(monkeypatch, seestar):
    started = {"thread": 0}

    class FakeThread:
        def __init__(self, name=None, target=None):
            self.target = target
            self.name = name

        def start(self):
            started["thread"] += 1

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    out = seestar.send_message_param_sync({"method": "pi_shutdown"})
    assert out["method"] == "pi_shutdown"
    assert started["thread"] == 1

    monkeypatch.setattr(seestar, "send_message_param", lambda _d: 55)
    seestar.response_dict[55] = {"id": 55, "result": "ok"}
    out2 = seestar.send_message_param_sync({"method": "scope_get_equ_coord"})
    assert out2["result"] == "ok"


def test_send_message_param_sync_timeout(monkeypatch, seestar):
    monkeypatch.setattr(seestar, "send_message_param", lambda _d: 999)
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    times = iter([0.0, 2.1, 11.2])
    monkeypatch.setattr("device.seestar_device.time.time", lambda: next(times))
    out = seestar.send_message_param_sync({"method": "scope_get_equ_coord"})
    assert "Error: Exceeded allotted wait time for result" in out["result"]


def test_get_event_state_and_is_client_master(seestar):
    seestar.schedule["state"] = "working"
    seestar.event_state["3PPA"] = {"eq_offset_alt": 0, "eq_offset_az": 0}
    seestar.cur_pa_error_x = 9.8
    seestar.cur_pa_error_y = 7.6
    out = seestar.get_event_state({"event_name": "3PPA"})
    assert out["code"] == 0
    assert out["result"]["eq_offset_alt"] == 7.6

    assert seestar.is_client_master() is True
    seestar.event_state["Client"] = {"is_master": False}
    assert seestar.is_client_master() is False


def test_get_altaz_from_eq_paths(monkeypatch, seestar):
    seestar.site_altaz_frame = None
    assert seestar.get_altaz_from_eq(1.0, 2.0, "obs") == [9999.9, 9999.9]

    class AltAzObj:
        az = SimpleNamespace(deg=11.0)
        alt = SimpleNamespace(deg=22.0)

    class Coord:
        def transform_to(self, _x):
            return AltAzObj()

    monkeypatch.setattr(
        "device.seestar_device.Util.parse_coordinate", lambda **_k: Coord()
    )
    monkeypatch.setattr("device.seestar_device.AltAz", lambda **_kwargs: object())
    seestar.site_altaz_frame = object()
    assert seestar.get_altaz_from_eq(1.0, 2.0, "obs") == [22.0, 11.0]


def test_set_setting_emits_expected_sequence(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    calls = []

    def fake_sync(payload):
        calls.append(payload)
        if payload["method"] == "get_setting":
            return {"result": {"ok": True}}
        return {"ok": True}

    monkeypatch.setattr(seestar, "send_message_param_sync", fake_sync)
    out = seestar.set_setting(1, 2, 3, 4, True, False, True)
    assert out == {"ok": True}
    assert len(calls) == 6
    assert calls[-1]["method"] == "get_setting"


def test_sync_and_move_helpers(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    seestar.event_state["AutoGoto"] = {"state": "working"}
    assert seestar.is_goto() is True
    seestar.event_state["AutoGoto"] = {"state": "start"}
    assert seestar.is_goto() is True
    seestar.event_state["AutoGoto"] = {"state": "complete"}
    assert seestar.is_goto_completed_ok() is True

    seestar.is_goto = lambda: True
    assert seestar.move_scope(10, 100) is False
    seestar.is_goto = lambda: False
    assert seestar.stop_goto_target() == "goto stopped already: no action taken"

    seestar.send_message_param_sync = lambda _d: {"ok": True}
    assert seestar.move_scope(10, 100) is True

    # sync_target: blocked when scheduler is working
    seestar.schedule["state"] = "working"
    msg = seestar.sync_target([1.0, 2.0])
    assert "Cannot sync target while scheduler is active" in msg

    # sync_target: allowed when scheduler is stopped or complete
    seestar.send_message_param_sync = lambda _d: {"result": "ok"}
    seestar.schedule["state"] = "stopped"
    assert seestar.sync_target([1.0, 2.0]) == {"result": "ok"}
    seestar.schedule["state"] = "complete"
    assert seestar.sync_target([1.0, 2.0]) == {"result": "ok"}


def test_receive_message_thread_updates_state_and_callbacks(monkeypatch, seestar):
    fired = []

    class CB:
        def fireOnEvents(self):
            return ["EqModePA", "event_*"]

        def eventFired(self, _dev, event):
            fired.append(event["Event"])

    seestar.event_callbacks = [CB()]
    seestar.is_watch_events = True

    messages = (
        '{"jsonrpc":"2.0","method":"scope_get_equ_coord","result":{"ra":1.1,"dec":2.2},"id":1}\r\n'
        '{"jsonrpc":"2.0","method":"get_view_state","result":{"View":{"stage":"RTSP"}},"id":2}\r\n'
        '{"Event":"EqModePA","state":"complete","x":3.3,"y":4.4}\r\n'
        '{"Event":"Simu_Stack","stack_status":{"ok":1},"stacked_frame":5,"dropped_frame":1}\r\n'
    )
    monkeypatch.setattr(seestar, "get_socket_msg", lambda: messages)

    def fake_sleep(_s):
        seestar.is_watch_events = False

    monkeypatch.setattr("device.seestar_device.time.sleep", fake_sleep)
    monkeypatch.setattr("device.seestar_device.Config.log_events_in_info", False)

    seestar.receive_message_thread_fn()

    assert seestar.ra == 1.1
    assert seestar.dec == 2.2
    assert seestar.view_state == {"stage": "RTSP"}
    assert seestar.response_dict[1]["method"] == "scope_get_equ_coord"
    assert seestar.response_dict[2]["method"] == "get_view_state"
    assert seestar.event_state["EqModePA"]["state"] == "complete"
    assert seestar.cur_pa_error_x == 3.3
    assert seestar.cur_pa_error_y == 4.4
    assert seestar.event_state["Stack"]["stacked_frame"] == 5
    assert "Simu_Stack" not in seestar.event_state
    assert "EqModePA" in fired


def test_start_stack_and_stop_plate_and_last_image(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    calls = []

    def fake_sync(payload):
        calls.append(payload)
        if payload["method"] == "iscope_start_stack" and len(calls) == 1:
            return {"error": "retry"}
        if payload["method"] == "get_albums":
            return {
                "result": {
                    "path": "albums",
                    "list": [
                        {
                            "files": [
                                {"name": "img-sub", "thn": "a_thn.jpg"},
                                {"name": "img", "thn": "b_thn.jpg"},
                            ]
                        }
                    ],
                }
            }
        return {"result": "ok"}

    monkeypatch.setattr(seestar, "send_message_param_sync", fake_sync)
    assert seestar.start_stack({"gain": 100, "restart": True}) is True
    assert seestar.schedule["is_stacking"] is True

    out_thumb = seestar.get_last_image({"is_subframe": True, "is_thumb": True})
    assert out_thumb["url"].endswith("/albums/a_thn.jpg")
    out_full = seestar.get_last_image({"is_subframe": False, "is_thumb": False})
    assert out_full["url"].endswith("/albums/b.jpg")

    assert seestar.stop_plate_solve_loop() is True
    assert any(c["method"] == "stop_polar_align" for c in calls)


def test_start_stack_failure_path(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        seestar, "send_message_param_sync", lambda _payload: {"error": "fail"}
    )
    assert seestar.start_stack({"gain": 80, "restart": True}) is False


def test_auto_focus_and_dark_frame_paths(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    seestar.event_state["AutoFocus"] = {"state": "working"}

    responses = {
        "start_auto_focuse": {"result": "ok"},
        "iscope_stop_view": {"result": "ok"},
        "start_create_dark": {"result": "ok"},
        "set_control_value": {"result": "ok"},
    }

    def fake_sync(payload):
        return responses.get(payload["method"], {"result": "ok"})

    monkeypatch.setattr(seestar, "send_message_param_sync", fake_sync)
    monkeypatch.setattr(seestar, "wait_end_op", lambda _evt: True)

    assert seestar._start_auto_focus() is True
    assert seestar.try_auto_focus(2) is True
    assert seestar.event_state["AutoFocus"]["state"] == "complete"

    seestar.event_state["AutoFocus"] = {"state": "working"}
    assert seestar._try_dark_frame() is True
    assert seestar.event_state["AutoFocus"]["state"] == "complete"


def test_adjust_mag_declination(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.geomag.declination", lambda *_a: 2.0)

    def fake_sync(payload):
        if payload["method"] == "get_device_state":
            return {"result": {"location_lon_lat": [10.0, 20.0]}}
        if payload["method"] == "get_sensor_calibration":
            return {
                "result": {
                    "compassSensor": {
                        "x": 1,
                        "y": 2,
                        "z": 3,
                        "x11": 1.0,
                        "x12": 0.0,
                        "y11": 0.0,
                        "y12": 1.0,
                    }
                }
            }
        if payload["method"] == "set_sensor_calibration":
            return {"result": "ok"}
        return {"result": "ok"}

    monkeypatch.setattr(seestar, "send_message_param_sync", fake_sync)
    out = seestar.adjust_mag_declination({"adjust_mag_dec": True, "fudge_angle": 1.0})
    assert (
        "Adjusted compass calibration to offset by total of 3.0 degrees."
        in out["result"]
    )


def test_scheduler_pause_continue_skip_and_actions(monkeypatch, seestar):
    seestar.schedule["state"] = "working"
    seestar.schedule["is_stacking"] = True
    seestar.schedule["is_stacking_paused"] = False
    monkeypatch.setattr(seestar, "stop_stack", lambda: {"ok": True})
    assert seestar.pause_scheduler({}) == {"ok": True}

    seestar.schedule["is_stacking"] = False
    seestar.schedule["is_stacking_paused"] = True
    monkeypatch.setattr(seestar, "start_stack", lambda _p: True)
    assert seestar.continue_scheduler({})["code"] == 0

    seestar.schedule["is_skip_requested"] = False
    assert seestar.skip_scheduler_cur_item({})["code"] == 0
    assert seestar.skip_scheduler_cur_item({})["code"] == -1

    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda payload: {"method": payload["method"]},
    )
    assert seestar.action_set_dew_heater({"heater": 0})["method"] == "pi_output_set2"
    out = seestar.action_set_exposure({"exp": 1200})
    assert out["set_response"]["method"] == "set_setting"
    assert out["dark_response"]["method"] == "start_create_dark"


def test_action_start_up_sequence_paths(monkeypatch, seestar):
    seestar.schedule["state"] = "working"
    busy = seestar.action_start_up_sequence({})
    assert busy["code"] == -1

    seestar.schedule["state"] = "stopped"
    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _p: {"result": "ok"})
    monkeypatch.setattr(seestar, "is_client_master", lambda: False)
    not_master = seestar.action_start_up_sequence({})
    assert not_master["code"] == -1

    started = {"count": 0}

    class FakeThread:
        def __init__(self, name=None, target=None):
            self.target = target
            self.name = name

        def start(self):
            started["count"] += 1

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    monkeypatch.setattr(seestar, "is_client_master", lambda: True)
    ok = seestar.action_start_up_sequence({})
    assert ok["code"] == 0
    assert started["count"] == 1


def test_start_up_thread_fn_success_and_old_firmware(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone_name", lambda: "UTC"
    )

    import datetime as _dt

    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone", lambda: _dt.timezone.utc
    )
    monkeypatch.setattr("device.seestar_device.EarthLocation", lambda **_k: object())
    monkeypatch.setattr(
        "device.seestar_device.Util.get_current_gps_coordinates", lambda: [3.0, 4.0]
    )
    monkeypatch.setattr(seestar, "set_setting", lambda *a, **k: {"ok": True})

    calls = []

    def fake_sync(payload):
        calls.append(payload["method"])
        if payload["method"] == "get_device_state":
            return {"result": {"device": {"firmware_ver_int": 2500}}}
        return {"result": "ok"}

    monkeypatch.setattr(seestar, "send_message_param_sync", fake_sync)

    played = []
    monkeypatch.setattr(seestar, "play_sound", lambda sid: played.append(sid))

    seestar.start_up_thread_fn(
        {
            "lat": 1.1,
            "lon": 2.2,
            "auto_focus": False,
            "3ppa": False,
            "dark_frames": False,
        }
    )
    assert seestar.schedule["state"] == "complete"
    assert played[0] == 80 and played[-1] == 82
    assert "get_device_state" in calls

    # old firmware branch should stop
    def old_fw(payload):
        if payload["method"] == "get_device_state":
            return {"result": {"device": {"firmware_ver_int": 2400}}}
        return {"result": "ok"}

    monkeypatch.setattr(seestar, "send_message_param_sync", old_fw)
    seestar.schedule["state"] = "stopped"
    seestar.start_up_thread_fn({"lat": 1.1, "lon": 2.2}, is_from_schedule=True)
    assert seestar.schedule["state"] == "stopped"


def test_spectra_thread_and_start_item(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    class FakeCoord:
        ra = SimpleNamespace(hour=1.5)
        dec = SimpleNamespace(deg=22.0)

    monkeypatch.setattr(
        "device.seestar_device.Util.parse_coordinate", lambda *_a, **_k: FakeCoord
    )
    monkeypatch.setattr(seestar, "_slew_to_ra_dec", lambda _p: True)
    monkeypatch.setattr(seestar, "set_target_name", lambda _n: {"ok": True})
    monkeypatch.setattr(seestar, "start_stack", lambda _p: True)
    monkeypatch.setattr(seestar, "stop_stack", lambda: {"ok": True})
    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _p: {"result": "ok"})
    seestar.schedule["state"] = "working"
    seestar.schedule["current_item_id"] = "item-1"
    seestar.schedule["is_skip_requested"] = False

    params = {
        "ra": 1.0,
        "dec": 2.0,
        "is_j2000": False,
        "target_name": "Vega",
        "panel_time_sec": 10,
        "gain": 80,
    }
    seestar.spectra_thread_fn(params)
    assert (
        seestar.event_state["scheduler"]["cur_scheduler_item"]["action"] == "complete"
    )
    assert seestar.is_cur_scheduler_item_working is False

    # start_spectra_item branch: not working
    seestar.schedule["state"] = "stopped"
    assert seestar.start_spectra_item(params) is None

    # start_spectra_item branch: working
    started = {"count": 0}

    class FakeThread:
        def __init__(self, name=None, target=None):
            self.name = name
            self.target = target

        def start(self):
            started["count"] += 1

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    seestar.schedule["state"] = "working"
    assert seestar.start_spectra_item(params) == "spectra mosiac started"
    assert started["count"] == 1


def test_mosaic_goto_inner_worker_paths(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    seestar.event_state["scheduler"] = {"cur_scheduler_item": {}}

    monkeypatch.setattr(seestar, "goto_target", lambda _p: False)
    assert seestar.mosaic_goto_inner_worker(1.0, 2.0, "x", False, False) is False

    monkeypatch.setattr(seestar, "goto_target", lambda _p: True)
    monkeypatch.setattr(seestar, "wait_end_op", lambda _e: True)
    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _p: {"result": "ok"})
    monkeypatch.setattr(seestar, "try_auto_focus", lambda _n: False)
    assert seestar.mosaic_goto_inner_worker(1.0, 2.0, "x", True, True) is True


def test_udp_intro_and_heartbeat_helpers(monkeypatch, seestar):
    class UdpSock:
        def __init__(self):
            self.sent = []
            self.closed = False
            self.recv_count = 0

        def setsockopt(self, *_a):
            return None

        def settimeout(self, _v):
            return None

        def sendto(self, payload, addr):
            self.sent.append((payload, addr))

        def recvfrom(self, _n):
            self.recv_count += 1
            if self.recv_count == 1:
                return (b"ok", ("127.0.0.1", 4720))
            raise socket.timeout()

        def close(self):
            self.closed = True

    sock = UdpSock()
    monkeypatch.setattr("device.seestar_device.socket.socket", lambda *_a: sock)
    seestar.send_udp_intro()
    assert sock.closed is True
    assert sock.sent

    sent = []
    monkeypatch.setattr(seestar, "json_message", lambda *a, **k: sent.append((a, k)))
    seestar.heartbeat()
    assert sent[0][0][0] == "scope_get_equ_coord"


def test_heartbeat_thread_and_plate_solve(monkeypatch, seestar):
    seestar.is_watch_events = True
    seestar.is_connected = False
    reconnect_calls = {"n": 0}

    def fake_reconnect():
        reconnect_calls["n"] += 1
        seestar.is_connected = True
        return True

    monkeypatch.setattr(seestar, "reconnect", fake_reconnect)
    monkeypatch.setattr(
        seestar, "heartbeat", lambda: setattr(seestar, "is_watch_events", False)
    )
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    seestar.heartbeat_message_thread_fn()
    assert reconnect_calls["n"] == 1

    payloads = []
    monkeypatch.setattr(
        seestar, "send_message_param_sync", lambda p: payloads.append(p) or {"ok": True}
    )
    seestar.request_plate_solve_for_BPA()
    assert payloads[0]["method"] == "start_solve"


def test_slew_sync_stop_and_sound_paths(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _d: {"error": "x"})
    assert seestar._slew_to_ra_dec([1.0, 2.0]) is False

    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _d: {"result": "ok"})
    monkeypatch.setattr(seestar, "wait_end_op", lambda _e: True)
    assert seestar._slew_to_ra_dec([1.0, 2.0]) is True

    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _d: {"error": "bad"})
    assert seestar._sync_target([1.0, 2.0])["error"] == "bad"

    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _d: {"result": "ok"})
    assert seestar._sync_target([1.0, 2.0])["result"] == "ok"

    assert seestar.stop_slew()["result"] == "ok"
    assert seestar.play_sound(3)["result"] == "ok"
    assert seestar.stop_stack()["result"] == "ok"


def test_send_message_and_shutdown_thread(monkeypatch, seestar):
    class Sock:
        def __init__(self):
            self.sent = []

        def sendall(self, payload):
            self.sent.append(payload)

    seestar.s = Sock()
    assert seestar.send_message("abc") is True

    calls = []
    monkeypatch.setattr(seestar, "play_sound", lambda x: calls.append(("sound", x)))
    monkeypatch.setattr(
        seestar, "mark_op_state", lambda a, b: calls.append(("mark", a, b))
    )
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda p: calls.append(("sync", p)) or {"result": "ok"},
    )
    monkeypatch.setattr(seestar, "wait_end_op", lambda _e: True)
    monkeypatch.setattr(
        seestar, "send_message_param", lambda p: calls.append(("async", p)) or 1
    )
    seestar.shut_down_thread({"method": "pi_shutdown"})
    assert any(c[0] == "async" for c in calls)


def test_start_up_thread_full_sequence(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone_name", lambda: "UTC"
    )
    import datetime as _dt

    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone", lambda: _dt.timezone.utc
    )
    monkeypatch.setattr("device.seestar_device.EarthLocation", lambda **_k: object())
    monkeypatch.setattr(seestar, "play_sound", lambda _sid: None)
    monkeypatch.setattr(seestar, "set_setting", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(seestar, "mark_op_state", lambda *a, **k: None)
    monkeypatch.setattr(seestar, "wait_end_op", lambda _e: True)
    monkeypatch.setattr(seestar, "try_auto_focus", lambda _n: True)
    monkeypatch.setattr(seestar, "_try_dark_frame", lambda: True)
    monkeypatch.setattr("device.seestar_device.Config.init_lat", 1.0)
    monkeypatch.setattr("device.seestar_device.Config.init_long", 2.0)

    def fake_sync(payload):
        if payload["method"] == "get_device_state":
            return {"result": {"device": {"firmware_ver_int": 2600}}}
        return {"result": "ok"}

    monkeypatch.setattr(seestar, "send_message_param_sync", fake_sync)
    seestar.schedule["state"] = "stopped"
    seestar.start_up_thread_fn(
        {
            "lat": 1.1,
            "lon": 2.2,
            "auto_focus": True,
            "3ppa": True,
            "dark_frames": True,
            "dec_pos_index": 3,
        }
    )
    assert seestar.schedule["state"] == "complete"


def test_schedule_crud_import_export_and_shortcuts(monkeypatch, seestar, tmp_path):
    seestar.schedule["state"] = "working"
    assert seestar.create_schedule({}) == "scheduler is still active"

    seestar.schedule["state"] = "stopping"
    out = seestar.create_schedule({"schedule_id": "abc"})
    assert out["schedule_id"] == "abc"
    assert out["state"] == "stopped"

    item = seestar.construct_schedule_item(
        {"action": "start_mosaic", "params": {"ra": -1.0, "dec": 2.0, "is_j2000": True}}
    )
    assert item["params"]["is_j2000"] is False
    assert "schedule_item_id" in item

    seestar.schedule["list"].clear()
    seestar.add_schedule_item({"action": "wait_for", "params": {"timer_sec": 5}})
    first = seestar.schedule["list"][0]["schedule_item_id"]
    seestar.replace_schedule_item(
        {"item_id": first, "action": "wait_for", "params": {"timer_sec": 3}}
    )
    seestar.insert_schedule_item_before(
        {"before_id": first, "action": "wait_for", "params": {"timer_sec": 2}}
    )
    seestar.remove_schedule_item({"schedule_item_id": first})
    assert len(seestar.schedule["list"]) == 1

    path = tmp_path / "sched.json"
    seestar.export_schedule({"filepath": str(path)})
    seestar.schedule["state"] = "working"
    assert (
        seestar.import_schedule({"filepath": str(path), "is_retain_state": True})[
            "code"
        ]
        == -1
    )
    seestar.schedule["state"] = "stopped"
    imported = seestar.import_schedule(
        {"filepath": str(path), "is_retain_state": False}
    )
    assert imported["state"] == "stopped"

    monkeypatch.setattr(seestar, "start_scheduler", lambda _p: {"ok": True})
    seestar.schedule["state"] = "stopped"
    assert (
        seestar.start_mosaic({"ra": 1.0, "dec": 2.0, "is_j2000": False})["ok"] is True
    )
    assert (
        seestar.start_spectra({"ra": 1.0, "dec": 2.0, "is_j2000": False})["ok"] is True
    )


def test_json_result_adjust_focus_and_reset(monkeypatch, seestar):
    warn_calls = []
    debug_calls = []
    seestar.logger.warning = lambda *a, **k: warn_calls.append(a)
    seestar.logger.debug = lambda *a, **k: debug_calls.append(a)

    assert seestar.json_result("x", -1, "bad")["code"] == -1
    assert warn_calls
    assert seestar.json_result("x", 0, "ok")["code"] == 0
    assert debug_calls

    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    vals = iter([{"result": 100}, {"result": "moved"}, {"result": 105}])
    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _p: next(vals))
    assert "Final focus position: 105" in seestar.adjust_focus(5)

    seestar.reset_scheduler_cur_item()
    assert "cur_scheduler_item" in seestar.event_state["scheduler"]


def test_scheduler_thread_fn_multiple_actions(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    seestar.schedule["list"] = collections.deque(
        [
            {"schedule_item_id": "m1", "action": "start_mosaic", "params": {}},
            {"schedule_item_id": "s1", "action": "start_spectra", "params": {}},
            {
                "schedule_item_id": "a1",
                "action": "auto_focus",
                "params": {"try_count": 1},
            },
            {
                "schedule_item_id": "f1",
                "action": "adjust_focus",
                "params": {"steps": 3},
            },
            {
                "schedule_item_id": "w1",
                "action": "wait_for",
                "params": {"timer_sec": 5},
            },
            {
                "schedule_item_id": "u1",
                "action": "wait_until",
                "params": {"local_time": "00:00"},
            },
            {
                "schedule_item_id": "d1",
                "action": "action_set_dew_heater",
                "params": {"heater": 10},
            },
            {
                "schedule_item_id": "e1",
                "action": "action_set_exposure",
                "params": {"exp": 1000},
            },
            {"schedule_item_id": "o1", "action": "scope_get_equ_coord"},
        ]
    )
    seestar.schedule["item_number"] = 1
    seestar.schedule["state"] = "stopped"
    seestar.schedule["is_skip_requested"] = False

    monkeypatch.setattr(seestar, "play_sound", lambda _sid: None)
    monkeypatch.setattr(
        seestar,
        "start_mosaic_item",
        lambda _p: setattr(seestar, "is_cur_scheduler_item_working", False),
    )
    monkeypatch.setattr(
        seestar,
        "start_spectra_item",
        lambda _p: setattr(seestar, "is_cur_scheduler_item_working", False),
    )
    monkeypatch.setattr(seestar, "try_auto_focus", lambda _n: True)
    monkeypatch.setattr(seestar, "adjust_focus", lambda _s: "ok")
    monkeypatch.setattr(seestar, "action_set_dew_heater", lambda _p: {"ok": True})
    monkeypatch.setattr(seestar, "action_set_exposure", lambda _p: {"ok": True})
    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _p: {"ok": True})

    import datetime as _dt

    monkeypatch.setattr(
        "device.seestar_device.datetime",
        SimpleNamespace(now=lambda: _dt.datetime(2000, 1, 1, 0, 0)),
    )

    seestar.scheduler_thread_fn()
    assert seestar.schedule["state"] == "complete"
    assert seestar.schedule["item_number"] == 0


def test_scheduler_thread_fn_shutdown_branch(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    seestar.schedule["list"] = collections.deque(
        [{"schedule_item_id": "x", "action": "shutdown", "params": {}}]
    )
    seestar.schedule["item_number"] = 1
    seestar.schedule["state"] = "stopped"

    calls = []
    monkeypatch.setattr(seestar, "play_sound", lambda _sid: None)
    monkeypatch.setattr(
        seestar, "send_message_param_sync", lambda p: calls.append(p) or {"ok": True}
    )
    seestar.scheduler_thread_fn()
    assert any(c["method"] == "pi_shutdown" for c in calls)


def test_stop_scheduler_mark_wait_guest_and_watch(monkeypatch, seestar, tmp_path):
    # stop_scheduler states
    seestar.schedule["state"] = "working"
    monkeypatch.setattr(seestar, "stop_slew", lambda: {"ok": True})
    monkeypatch.setattr(seestar, "stop_stack", lambda: {"ok": True})
    monkeypatch.setattr(seestar, "play_sound", lambda _sid: None)
    assert seestar.stop_scheduler({})["code"] == 0

    seestar.schedule["state"] = "complete"
    assert seestar.stop_scheduler({})["code"] == -4
    seestar.schedule["state"] = "stopped"
    assert seestar.stop_scheduler({})["code"] == -3
    seestar.schedule["state"] = "weird"
    assert seestar.stop_scheduler({})["code"] == -5
    assert seestar.stop_scheduler({"schedule_id": "bad"})["code"] == 0

    seestar.mark_op_state("x", "working")
    assert seestar.event_state["x"]["state"] == "working"
    monkeypatch.setattr(seestar, "is_goto", lambda: False)
    monkeypatch.setattr(seestar, "is_goto_completed_ok", lambda: True)
    assert seestar.wait_end_op("goto_target") is True
    seestar.event_state["DarkLibrary"] = {"state": "complete"}
    assert seestar.wait_end_op("DarkLibrary") is True

    # guest_mode_init and event_callbacks_init
    seestar.firmware_ver_int = 2400
    monkeypatch.setattr("device.seestar_device.socket.gethostname", lambda: "hostx")
    msg_calls = []
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda p: msg_calls.append(p) or {"result": "ok"},
    )
    seestar.guest_mode_init()
    assert any(p["params"].get("master_cli") is not None for p in msg_calls)

    hooks = tmp_path / "user_hooks"
    hooks.mkdir()
    (hooks / "ok.conf").write_text('events=["PiStatus"]\nexecute=["/bin/true"]\n')
    (hooks / "bad.conf").write_text("not: valid: hocon:")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "device.seestar_device.ConfigFactory.parse_file",
        lambda fp: (
            {"events": ["PiStatus"], "execute": ["/bin/true"]}
            if "ok" in str(fp)
            else (_ for _ in ()).throw(Exception("bad"))
        ),
    )
    seestar.event_callbacks_init(
        {
            "pi_status": {
                "battery_capacity": 50,
                "charger_status": "Charging",
                "charge_online": True,
            }
        }
    )
    assert len(seestar.event_callbacks) >= 1

    # start/end watch thread and get_events
    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon
            self.name = ""

        def start(self):
            return None

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return False

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    monkeypatch.setattr(seestar, "reconnect", lambda: True)
    monkeypatch.setattr(seestar, "guest_mode_init", lambda: None)
    monkeypatch.setattr(seestar, "event_callbacks_init", lambda _s: None)
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda _p: {"result": {"device": {"firmware_ver_int": 2600}}},
    )
    seestar.start_watch_thread()
    assert seestar.is_watch_events is True

    seestar.is_connected = True
    seestar.s = _DummySocket()
    seestar.get_msg_thread = FakeThread()
    seestar.heartbeat_msg_thread = FakeThread()
    seestar.end_watch_thread()
    assert seestar.is_connected is False

    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    seestar.event_queue.append(
        {"Event": "FocuserMove", "position": 123, "Timestamp": "x"}
    )
    frame = next(seestar.get_events())
    assert b"focusMove" in frame


def test_mosaic_thread_fn_happy_path(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    monkeypatch.setattr(
        "device.seestar_device.Util.mosaic_next_center_spacing", lambda *_a: [0.1, 0.2]
    )
    monkeypatch.setattr(seestar, "mosaic_goto_inner_worker", lambda *_a, **_k: True)
    monkeypatch.setattr(seestar, "set_target_name", lambda _n: {"ok": True})
    monkeypatch.setattr(seestar, "start_stack", lambda _p: True)
    monkeypatch.setattr(seestar, "stop_stack", lambda: {"ok": True})
    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _p: {"ok": True})
    seestar.schedule["state"] = "working"
    seestar.schedule["is_skip_requested"] = False
    seestar.schedule["current_item_id"] = "m1"
    seestar.event_state["scheduler"] = {"cur_scheduler_item": {}}

    seestar.mosaic_thread_fn(
        "T1",
        1.0,
        2.0,
        False,
        5,
        1,
        1,
        10,
        80,
        False,
        "",
        1,
        5,
    )
    assert (
        seestar.event_state["scheduler"]["cur_scheduler_item"]["action"] == "complete"
    )
    assert seestar.is_cur_scheduler_item_working is False


def test_start_mosaic_item_paths(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)

    class FakeCoord:
        ra = SimpleNamespace(hour=1.5)
        dec = SimpleNamespace(deg=2.5)

    monkeypatch.setattr(
        "device.seestar_device.Util.parse_coordinate", lambda *_a, **_k: FakeCoord
    )
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda _p: {
            "result": {
                "exp_ms": {"stack_l": 1},
                "stack_dither": {"pix": 1, "interval": 1},
            }
        },
    )

    started = {"count": 0}

    class FakeThread:
        def __init__(self, target=None):
            self.target = target
            self.name = ""

        def start(self):
            started["count"] += 1

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    monkeypatch.setattr(seestar, "mosaic_thread_fn", lambda *a, **k: None)

    # scheduler not working branch
    seestar.schedule["state"] = "stopped"
    assert seestar.start_mosaic_item({"target_name": "T", "ra": 1, "dec": 2}) is None

    # invalid mosaic size
    seestar.schedule["state"] = "working"
    bad = {
        "target_name": "T",
        "ra": 1.0,
        "dec": 2.0,
        "is_j2000": False,
        "is_use_lp_filter": False,
        "panel_time_sec": 5,
        "ra_num": 0,
        "dec_num": 1,
        "panel_overlap_percent": 10,
        "gain": 80,
    }
    assert seestar.start_mosaic_item(bad) is None

    # session_time_sec compatibility + start thread
    good = {
        "target_name": "T",
        "ra": -1.0,
        "dec": -1.0,
        "is_j2000": False,
        "is_use_lp_filter": False,
        "session_time_sec": 5,
        "ra_num": 1,
        "dec_num": 1,
        "panel_overlap_percent": 10,
        "gain": 80,
        "num_tries": 1,
        "retry_wait_s": 5,
    }
    seestar.ra = 3.2
    seestar.dec = 4.3
    seestar.schedule["state"] = "working"
    seestar.start_mosaic_item(good)
    assert started["count"] == 1


def test_startup_sequence_error_branches(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone_name", lambda: "UTC"
    )
    import datetime as _dt

    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone", lambda: _dt.timezone.utc
    )
    monkeypatch.setattr("device.seestar_device.EarthLocation", lambda **_k: object())
    monkeypatch.setattr(
        "device.seestar_device.Util.get_current_gps_coordinates", lambda: [7.7, 8.8]
    )
    monkeypatch.setattr(seestar, "play_sound", lambda _sid: None)
    monkeypatch.setattr(seestar, "set_setting", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(seestar, "mark_op_state", lambda *a, **k: None)
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda _p: {"result": {"device": {"firmware_ver_int": 2600}}},
    )

    # do_3ppa true but EQ mode false => forced skip
    seestar.is_EQ_mode = False
    seestar.schedule["state"] = "stopped"
    seestar.start_up_thread_fn(
        {"lat": 0, "lon": 0, "3ppa": True}, is_from_schedule=True
    )
    assert seestar.schedule["state"] == "working"

    # 3PPA failure path
    seestar.is_EQ_mode = True
    monkeypatch.setattr(seestar, "wait_end_op", lambda _e: False)
    seestar.schedule["state"] = "stopped"
    seestar.start_up_thread_fn(
        {"lat": 1.0, "lon": 2.0, "3ppa": True}, is_from_schedule=True
    )
    assert seestar.schedule["state"] == "working"

    # AF failure path
    monkeypatch.setattr(seestar, "wait_end_op", lambda _e: True)
    monkeypatch.setattr(seestar, "try_auto_focus", lambda _n: False)
    seestar.schedule["state"] = "stopped"
    seestar.start_up_thread_fn(
        {"lat": 1.0, "lon": 2.0, "3ppa": True, "auto_focus": True},
        is_from_schedule=True,
    )
    assert seestar.schedule["state"] == "stopped"

    # dark frame failure path
    monkeypatch.setattr(seestar, "try_auto_focus", lambda _n: True)
    monkeypatch.setattr(seestar, "_try_dark_frame", lambda: False)
    seestar.schedule["state"] = "stopped"
    seestar.start_up_thread_fn(
        {"lat": 1.0, "lon": 2.0, "dark_frames": True}, is_from_schedule=True
    )
    assert seestar.schedule["state"] == "stopped"


def test_mosaic_thread_branch_variants(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    monkeypatch.setattr(
        "device.seestar_device.Util.mosaic_next_center_spacing", lambda *_a: [0.1, 0.2]
    )
    monkeypatch.setattr(seestar, "send_message_param_sync", lambda _p: {"ok": True})
    monkeypatch.setattr(seestar, "set_target_name", lambda _n: {"ok": True})
    monkeypatch.setattr(seestar, "stop_stack", lambda: {"ok": True})
    seestar.schedule["current_item_id"] = "m2"
    seestar.event_state["scheduler"] = {"cur_scheduler_item": {}}

    # selected panels skip path + goto fail retry path
    attempts = {"n": 0}

    def fail_then_fail(*_a, **_k):
        attempts["n"] += 1
        return False

    monkeypatch.setattr(seestar, "mosaic_goto_inner_worker", fail_then_fail)
    monkeypatch.setattr(seestar, "start_stack", lambda _p: True)
    seestar.schedule["state"] = "working"
    seestar.schedule["is_skip_requested"] = False
    seestar.mosaic_thread_fn(
        "T",
        1.0,
        2.0,
        False,
        5,
        2,
        1,
        10,
        80,
        False,
        "11",
        2,
        10,
    )
    assert attempts["n"] >= 1

    # stacking start failure branch
    monkeypatch.setattr(seestar, "mosaic_goto_inner_worker", lambda *_a, **_k: True)
    monkeypatch.setattr(seestar, "start_stack", lambda _p: False)
    seestar.schedule["state"] = "working"
    seestar.mosaic_thread_fn("T", 1.0, 2.0, False, 5, 1, 1, 10, 80, False, "", 1, 5)

    # stop requested during loop
    monkeypatch.setattr(seestar, "start_stack", lambda _p: True)

    def stop_after_first_sleep(_s):
        seestar.schedule["state"] = "stopping"

    monkeypatch.setattr("device.seestar_device.time.sleep", stop_after_first_sleep)
    seestar.schedule["state"] = "working"
    seestar.mosaic_thread_fn("T", 1.0, 2.0, False, 5, 1, 1, 10, 80, False, "", 1, 5)


def test_scheduler_and_schedule_guard_branches(monkeypatch, seestar):
    # get_schedule mismatch
    seestar.schedule["schedule_id"] = "abc"
    assert seestar.get_schedule({"schedule_id": "zzz"}) == {}

    # start shortcuts while busy
    seestar.schedule["state"] = "working"
    assert seestar.start_mosaic({"ra": 1, "dec": 2, "is_j2000": False})["code"] == -1
    assert seestar.start_spectra({"ra": 1, "dec": 2, "is_j2000": False})["code"] == -1

    # start_scheduler guards
    seestar.schedule["state"] = "stopped"
    seestar.schedule["schedule_id"] = "id1"
    assert seestar.start_scheduler({"schedule_id": "id2"})["code"] == 0
    seestar.is_client_master = lambda: False
    assert seestar.start_scheduler({})["code"] == -1
    seestar.is_client_master = lambda: True
    seestar.schedule["state"] = "working"
    assert seestar.start_scheduler({})["code"] == -1

    # start_item branch
    seestar.schedule["state"] = "stopped"
    started = {"n": 0}

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon
            self.name = ""

        def start(self):
            started["n"] += 1

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    out = seestar.start_scheduler({"start_item": 3})
    assert out["item_number"] == 3
    assert started["n"] == 1


def test_scheduler_thread_extra_branches(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    seestar.schedule["list"] = collections.deque(
        [
            {
                "schedule_item_id": "w1",
                "action": "wait_for",
                "params": {"timer_sec": 5},
            },
            {
                "schedule_item_id": "u1",
                "action": "wait_until",
                "params": {"local_time": "23:59"},
            },
            {"schedule_item_id": "s1", "action": "start_up_sequence", "params": {}},
            {"schedule_item_id": "o1", "action": "scope_get_equ_coord", "params": {}},
            {"schedule_item_id": "o2", "action": "scope_get_time"},
        ]
    )
    seestar.schedule["state"] = "stopped"
    seestar.schedule["item_number"] = 1
    seestar.schedule["is_skip_requested"] = True
    seestar.play_sound = lambda _sid: None
    seestar.send_message_param_sync = lambda _p: {"ok": True}

    class StartupThread:
        def __init__(self, name=None, target=None):
            self._alive = True
            self.target = target

        def start(self):
            self._alive = False

        def is_alive(self):
            return self._alive

    monkeypatch.setattr("device.seestar_device.threading.Thread", StartupThread)
    import datetime as _dt

    monkeypatch.setattr(
        "device.seestar_device.datetime",
        SimpleNamespace(now=lambda: _dt.datetime(2000, 1, 1, 23, 59)),
    )
    seestar.scheduler_thread_fn()
    assert seestar.schedule["state"] == "complete"


def test_wait_guest_watch_and_events_extra(monkeypatch, seestar, tmp_path):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)

    # wait_end_op loop branches
    vals = iter([True, False])
    monkeypatch.setattr(seestar, "is_goto", lambda: next(vals))
    monkeypatch.setattr(seestar, "is_goto_completed_ok", lambda: False)
    assert seestar.wait_end_op("goto_target") is False
    seestar.event_state["X"] = {"state": "working"}
    flips = {"n": 0}

    def _sleep(_s):
        flips["n"] += 1
        if flips["n"] == 1:
            seestar.event_state["X"]["state"] = "fail"

    monkeypatch.setattr("device.seestar_device.time.sleep", _sleep)
    assert seestar.wait_end_op("X") is False

    # guest mode with empty hostname
    monkeypatch.setattr("device.seestar_device.socket.gethostname", lambda: "")
    sent = []
    monkeypatch.setattr(
        seestar, "send_message_param_sync", lambda p: sent.append(p) or {"ok": True}
    )
    seestar.firmware_ver_int = 2400
    seestar.guest_mode_init()
    assert any(p["params"].get("cli_name") == "SSC" for p in sent if "params" in p)

    # callbacks parse warning path
    hooks = tmp_path / "user_hooks"
    hooks.mkdir()
    (hooks / "bad.conf").write_text("x")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "device.seestar_device.ConfigFactory.parse_file",
        lambda _p: (_ for _ in ()).throw(Exception("bad")),
    )
    seestar.event_callbacks_init(
        {
            "pi_status": {
                "battery_capacity": 1,
                "charger_status": "Charging",
                "charge_online": True,
            }
        }
    )

    # start_watch_thread early return + reconnect fail path
    seestar.is_watch_events = True
    assert seestar.start_watch_thread() is None
    seestar.is_watch_events = False
    monkeypatch.setattr(seestar, "reconnect", lambda: False)
    monkeypatch.setattr(
        "device.seestar_device.threading.Thread",
        lambda *a, **k: (_ for _ in ()).throw(Exception("thread boom")),
    )
    seestar.start_watch_thread()

    # get_events branches: no timestamp + PiStatus + AviRecord + generic except
    class BadQueue:
        def __len__(self):
            return 1

        def popleft(self):
            raise RuntimeError("boom")

    seestar.event_queue = collections.deque(
        [
            {"Event": "PiStatus", "temp": 1, "battery_capacity": 2},
            {"Event": "AviRecord", "state": "start"},
        ]
    )
    frame1 = next(seestar.get_events())
    frame2 = next(seestar.get_events())
    assert b"event: temp" in frame1
    assert b"video_record_status" in frame2

    seestar.event_queue = BadQueue()

    def stop_sleep(_s):
        raise GeneratorExit

    monkeypatch.setattr("device.seestar_device.time.sleep", stop_sleep)
    gen = seestar.get_events()
    with pytest.raises(GeneratorExit):
        next(gen)


def test_schedule_item_guards_for_working_scheduler(seestar):
    seestar.schedule["list"] = collections.deque(
        [
            {"schedule_item_id": "a", "action": "wait_for", "params": {"timer_sec": 1}},
            {"schedule_item_id": "b", "action": "wait_for", "params": {"timer_sec": 2}},
            {"schedule_item_id": "c", "action": "wait_for", "params": {"timer_sec": 3}},
        ]
    )
    seestar.schedule["state"] = "working"
    seestar.schedule["current_item_id"] = "b"

    # Disallow editing/removing items already executed.
    seestar.replace_schedule_item(
        {"item_id": "a", "action": "wait_for", "params": {"timer_sec": 9}}
    )
    seestar.insert_schedule_item_before(
        {"before_id": "a", "action": "wait_for", "params": {"timer_sec": 8}}
    )
    seestar.remove_schedule_item({"schedule_item_id": "a"})
    assert [x["schedule_item_id"] for x in seestar.schedule["list"]] == ["a", "b", "c"]

    # Allow edits/removals after current item.
    seestar.schedule["current_item_id"] = "a"
    seestar.replace_schedule_item(
        {"item_id": "c", "action": "wait_for", "params": {"timer_sec": 30}}
    )
    replaced_id = seestar.schedule["list"][2]["schedule_item_id"]
    seestar.insert_schedule_item_before(
        {"before_id": replaced_id, "action": "wait_for", "params": {"timer_sec": 20}}
    )
    inserted_id = seestar.schedule["list"][2]["schedule_item_id"]
    assert seestar.schedule["list"][3]["params"]["timer_sec"] == 30
    seestar.remove_schedule_item({"schedule_item_id": inserted_id})
    assert [x["schedule_item_id"] for x in list(seestar.schedule["list"])[:2]] == [
        "a",
        "b",
    ]
    assert seestar.schedule["list"][2]["params"]["timer_sec"] == 30


def test_get_events_focus_empty_queue_and_watch_firmware_init(monkeypatch, seestar):
    # Cover focus event formatting and timestamp stripping.
    seestar.event_queue = collections.deque(
        [{"Event": "FocuserMove", "position": 1234, "Timestamp": "1.23"}]
    )
    frame = next(seestar.get_events())
    assert b"event: focusMove" in frame
    assert b"1234" in frame

    # Cover empty queue branch.
    seestar.event_queue = collections.deque()

    def stop_quick(_s):
        raise GeneratorExit

    monkeypatch.setattr("device.seestar_device.time.sleep", stop_quick)
    gen = seestar.get_events()
    with pytest.raises(StopIteration):
        next(gen)

    # Cover watch init firmware extraction path.
    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon
            self.name = ""

        def start(self):
            return None

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    monkeypatch.setattr(seestar, "reconnect", lambda: True)
    monkeypatch.setattr(seestar, "guest_mode_init", lambda: None)
    monkeypatch.setattr(seestar, "event_callbacks_init", lambda _s: None)
    seestar.is_watch_events = False
    seestar.firmware_ver_int = 0
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda _p: {"result": {"device": {"firmware_ver_int": 2600}}},
    )
    seestar.start_watch_thread()
    assert seestar.firmware_ver_int == 2600
