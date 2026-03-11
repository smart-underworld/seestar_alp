import requests

from device import events
from device.seestar_remote import SeestarRemote
from device.seestar_remote_imaging import SeestarRemoteImaging


class DummyLogger:
    def __init__(self):
        self.records = []

    def info(self, msg, *args):
        self.records.append(("info", msg, args))

    def debug(self, msg, *args):
        self.records.append(("debug", msg, args))

    def warn(self, msg, *args):
        self.records.append(("warn", msg, args))

    def error(self, msg, *args):
        self.records.append(("error", msg, args))


class _RemoteImpl(SeestarRemote):
    def reset_scheduler_cur_item(self, params):
        return self._do_action_device("reset_scheduler_cur_item", params)


class FakeResponse:
    def __init__(self, payload=None, lines=None, chunks=None):
        self._payload = payload or {}
        self._lines = lines or []
        self._chunks = chunks or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self):
        for line in self._lines:
            yield line

    def iter_content(self, chunk_size=None):
        _ = chunk_size
        for chunk in self._chunks:
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def make_remote():
    return _RemoteImpl(DummyLogger(), "127.0.0.1", 5555, "remote", 5, "lab", 1)


def test_remote_basic_properties_and_wrappers(monkeypatch):
    remote = make_remote()
    assert remote.get_name() == "remote"
    assert remote.ra == -1000.0
    assert remote.dec == -1000.0
    assert remote.remote_id == 4

    monkeypatch.setattr(
        remote, "_do_action_device", lambda action, p: {"a": action, "p": p}
    )
    monkeypatch.setattr(remote, "put_remote", lambda path, p: {"path": path, "p": p})

    assert remote.get_event_state({"x": 1})["a"] == "get_event_state"
    assert remote.send_message_param_sync({"m": 1})["a"] == "method_sync"
    assert remote.goto_target({"ra": 1})["a"] == "goto_target"
    assert remote.stop_goto_target()["a"] == "stop_goto_target"
    assert remote.start_spectra({})["a"] == "start_spectra"
    assert remote.is_goto()["a"] == "is_goto"
    assert remote.is_goto_completed_ok()["a"] == "is_goto_completed_ok"
    assert remote.play_sound(7)["p"]["id"] == 7
    assert remote.action_set_dew_heater({"v": 1})["a"] == "action_set_dew_heater"
    assert remote.action_set_exposure({"v": 1})["a"] == "action_set_exposure"
    assert remote.action_start_up_sequence({"v": 1})["a"] == "action_start_up_sequence"
    assert remote.get_schedule({})["a"] == "get_schedule"
    assert remote.create_schedule({})["a"] == "create_schedule"
    assert remote.add_schedule_item({})["a"] == "add_schedule_item"
    assert remote.insert_schedule_item_before({})["a"] == "insert_schedule_item_before"
    assert remote.replace_schedule_item({})["a"] == "replace_schedule_item"
    assert remote.remove_schedule_item({})["a"] == "remove_schedule_item"
    assert remote.start_mosaic({})["a"] == "start_mosaic"
    assert remote.start_scheduler({})["a"] == "start_scheduler"
    assert remote.stop_scheduler({})["a"] == "stop_scheduler"
    assert remote.send_message_param({})["a"] == "method_async"

    assert remote.stop_slew()["path"] == "abortslew"
    assert remote.move_scope(2, 3)["path"] == "moveaxis"
    assert remote.start_watch_thread()["p"]["Connected"] is True
    assert remote.end_watch_thread()["p"]["Connected"] is False


def test_remote_put_get_and_connectivity(monkeypatch):
    remote = make_remote()

    monkeypatch.setattr(
        "device.seestar_remote.requests.put", lambda *a, **k: FakeResponse({"ok": True})
    )
    out_put = remote.put_remote("connected", {"Connected": True})
    assert out_put["ok"] is True

    monkeypatch.setattr(
        "device.seestar_remote.requests.get",
        lambda *a, **k: FakeResponse({"Value": True, "ErrorNumber": 0}),
    )
    out_get = remote.get_remote("connected")
    assert out_get["Value"] is True
    assert remote._is_remote_connected() is True

    monkeypatch.setattr(
        "device.seestar_remote.requests.get",
        lambda *a, **k: FakeResponse({"Value": False, "ErrorNumber": 0}),
    )
    assert remote._is_remote_connected() is False

    monkeypatch.setattr(
        "device.seestar_remote.requests.get",
        lambda *a, **k: FakeResponse({"ErrorNumber": 1031, "Value": True}),
    )
    assert remote._is_remote_connected() is False


def test_remote_put_get_exception_paths(monkeypatch):
    remote = make_remote()

    def raise_conn(*_a, **_k):
        raise requests.exceptions.ConnectionError()

    def raise_req(*_a, **_k):
        raise requests.exceptions.RequestException()

    monkeypatch.setattr("device.seestar_remote.requests.put", raise_conn)
    assert remote.put_remote("x", {}) is None

    monkeypatch.setattr("device.seestar_remote.requests.put", raise_req)
    assert remote.put_remote("x", {}) is None

    monkeypatch.setattr("device.seestar_remote.requests.get", raise_conn)
    assert remote.get_remote("x") is None

    monkeypatch.setattr("device.seestar_remote.requests.get", raise_req)
    assert remote.get_remote("x") is None


def test_remote_action_device_and_get_events(monkeypatch):
    remote = make_remote()

    monkeypatch.setattr(remote, "_is_remote_connected", lambda: True)
    monkeypatch.setattr(
        "device.seestar_remote.requests.put",
        lambda *a, **k: FakeResponse({"Value": {"ok": True}}),
    )
    assert remote._do_action_device("x", {"y": 1}) == {"ok": True}

    monkeypatch.setattr(
        "device.seestar_remote.requests.put",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert remote._do_action_device("x", {"y": 1}) is None

    monkeypatch.setattr(remote, "_is_remote_connected", lambda: False)
    assert remote._do_action_device("x", {"y": 1}) is None

    monkeypatch.setattr(
        "device.seestar_remote.requests.get",
        lambda *a, **k: FakeResponse(lines=[b"a", b"b"]),
    )
    assert list(remote.get_events()) == [b"a\n", b"b\n"]


def test_remote_start_stack_and_stop_stack(monkeypatch):
    remote = make_remote()
    calls = []

    def fake_sync(payload):
        calls.append(payload)
        return {"result": "ok"}

    monkeypatch.setattr(remote, "send_message_param_sync", fake_sync)

    assert remote.start_stack({"gain": 90, "restart": True}) is True
    assert calls[0]["method"] == "iscope_start_stack"
    assert calls[1]["method"] == "set_control_value"

    out = remote.stop_stack()
    assert out["result"] == "ok"


def test_remote_imaging_and_events(monkeypatch):
    imaging = SeestarRemoteImaging(DummyLogger(), "127.0.0.1", 7000, "img", 5, "lab", 1)

    monkeypatch.setattr(
        "device.seestar_remote_imaging.requests.get",
        lambda *a, **k: FakeResponse(chunks=[b"c1", b"c2"], lines=[b"l1"]),
    )
    assert list(imaging.get_frame()) == [b"c1", b"c2"]
    assert list(imaging.get_live_status()) == [b"l1\n"]

    assert events.PORT4700_EVENTS("x") == []
    assert events.PORT4800_EVENTS("x") == []
    assert events.PORT4801_EVENTS("x") == []
