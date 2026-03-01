import json
import logging

import pytest

from device import telescope
from device import exceptions as device_exceptions
from device.shr import set_shr_logger


class DummyReq:
    method = "PUT"
    remote_addr = "127.0.0.1"
    path = "/api/v1/telescope/1/action"
    query_string = ""

    def __init__(self, action_name, params):
        self._media = {
            "Action": action_name,
            "Parameters": json.dumps(params),
            "ClientID": "1",
            "ClientTransactionID": "2",
        }
        self.content_length = len(json.dumps(self._media))

    @property
    def media(self):
        return self._media

    def get_media(self):
        return self._media


class DummyResp:
    def __init__(self):
        self.text = ""


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def warn(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class FakeDevice:
    def __init__(self, connected=True):
        self.is_connected = connected
        self.logger = DummyLogger()
        self.calls = []
        self.event_callbacks = []

    def get_event_state(self, params):
        self.calls.append(("get_event_state", params))
        return {"ok": True, "params": params}

    def start_scheduler(self, params):
        self.calls.append(("start_scheduler", params))
        return {"state": "started", "params": params}

    def send_message_param_sync(self, params):
        self.calls.append(("method_sync", params))
        return {"result": "ok", "params": params}

    def send_message_param(self, params):
        self.calls.append(("method_async", params))
        return 12345

    def reset_scheduler_cur_item(self, params):
        self.calls.append(("reset_scheduler_cur_item", params))
        return {"ok": True}

    def play_sound(self, sid):
        self.calls.append(("play_sound", sid))
        return {"ok": True}

    def start_stack(self, params):
        self.calls.append(("start_stack", params))
        return {"ok": True}

    def start_mosaic(self, params):
        self.calls.append(("start_mosaic", params))
        return {"ok": True}

    def goto_target(self, params):
        self.calls.append(("goto_target", params))
        return True

    def stop_goto_target(self):
        self.calls.append(("stop_goto_target", None))
        return {"ok": True}

    def is_goto(self):
        self.calls.append(("is_goto", None))
        return False

    def is_goto_completed_ok(self):
        self.calls.append(("is_goto_completed_ok", None))
        return True

    def adjust_focus(self, steps):
        self.calls.append(("adjust_focus", steps))
        return {"ok": True}

    def start_spectra(self, params):
        self.calls.append(("start_spectra", params))
        return {"ok": True}

    def get_schedule(self, params):
        self.calls.append(("get_schedule", params))
        return {"state": "stopped"}

    def create_schedule(self, params):
        self.calls.append(("create_schedule", params))
        return {"state": "stopped"}

    def add_schedule_item(self, params):
        self.calls.append(("add_schedule_item", params))
        return {"ok": True}

    def insert_schedule_item_before(self, params):
        self.calls.append(("insert_schedule_item_before", params))
        return {"ok": True}

    def replace_schedule_item(self, params):
        self.calls.append(("replace_schedule_item", params))
        return {"ok": True}

    def remove_schedule_item(self, params):
        self.calls.append(("remove_schedule_item", params))
        return {"ok": True}

    def stop_scheduler(self, params):
        self.calls.append(("stop_scheduler", params))
        return {"ok": True}

    def export_schedule(self, params):
        self.calls.append(("export_schedule", params))
        return {"ok": True}

    def import_schedule(self, params):
        self.calls.append(("import_schedule", params))
        return {"ok": True}

    def action_start_up_sequence(self, params):
        self.calls.append(("action_start_up_sequence", params))
        return {"ok": True}

    def action_set_dew_heater(self, params):
        self.calls.append(("action_set_dew_heater", params))
        return {"ok": True}

    def action_set_exposure(self, params):
        self.calls.append(("action_set_exposure", params))
        return {"ok": True}

    def get_last_image(self, params):
        self.calls.append(("get_last_image", params))
        return "http://img"

    def adjust_mag_declination(self, params):
        self.calls.append(("adjust_mag_declination", params))
        return {"ok": True}

    def stop_plate_solve_loop(self):
        self.calls.append(("stop_plate_solve_loop", None))
        return {"ok": True}

    def get_pa_error(self, params):
        self.calls.append(("get_pa_error", params))
        return {"ok": True}

    def pause_scheduler(self, params):
        self.calls.append(("pause_scheduler", params))
        return {"ok": True}

    def continue_scheduler(self, params):
        self.calls.append(("continue_scheduler", params))
        return {"ok": True}

    def skip_scheduler_cur_item(self, params):
        self.calls.append(("skip_scheduler_cur_item", params))
        return {"ok": True}

    def start_watch_thread(self):
        self.calls.append(("start_watch_thread", None))
        return None

    def end_watch_thread(self):
        self.calls.append(("end_watch_thread", None))
        return None


class FakeFederation(FakeDevice):
    pass


def test_action_put_routes_start_scheduler(monkeypatch):
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()

    fake = FakeDevice(connected=True)
    telescope.seestar_dev[1] = fake

    req = DummyReq("start_scheduler", {"schedule_id": "abc"})
    resp = DummyResp()
    telescope.action().on_put(req, resp, devnum=1)

    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] == 0
    assert payload["Value"]["state"] == "started"
    assert fake.calls == [("start_scheduler", {"schedule_id": "abc"})]


def test_action_put_routes_get_event_state(monkeypatch):
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()

    fake = FakeDevice(connected=True)
    telescope.seestar_dev[1] = fake

    req = DummyReq("get_event_state", {"event_name": "scheduler"})
    resp = DummyResp()
    telescope.action().on_put(req, resp, devnum=1)

    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] == 0
    assert payload["Value"]["ok"] is True
    assert fake.calls == [("get_event_state", {"event_name": "scheduler"})]


def test_action_put_returns_not_connected_error(monkeypatch):
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()

    telescope.seestar_dev[1] = FakeDevice(connected=False)
    req = DummyReq("start_scheduler", {})
    resp = DummyResp()
    telescope.action().on_put(req, resp, devnum=1)

    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] != 0


def test_action_put_devnum_zero_routes_to_federation():
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    telescope.seestar_federation = FakeFederation(connected=True)

    req = DummyReq("method_sync", {"method": "scope_get_equ_coord"})
    resp = DummyResp()
    telescope.action().on_put(req, resp, devnum=0)

    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] == 0
    assert payload["Value"]["result"] == "ok"
    assert telescope.seestar_federation.calls == [
        ("method_sync", {"method": "scope_get_equ_coord"})
    ]


def test_action_put_dispatches_many_supported_actions():
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    fake = FakeDevice(connected=True)
    telescope.seestar_dev[1] = fake

    action_cases = [
        ("reset_scheduler_cur_item", {}),
        ("play_sound", {"id": 13}),
        ("start_stack", {"gain": 80, "restart": True}),
        ("start_mosaic", {"ra": 1, "dec": 2}),
        ("goto_target", {"ra": 1, "dec": 2, "is_j2000": False}),
        ("stop_goto_target", {}),
        ("is_goto", {}),
        ("is_goto_completed_ok", {}),
        ("adjust_focus", {"steps": 10}),
        ("start_spectra", {"ra": 1, "dec": 2}),
        ("get_schedule", {}),
        ("create_schedule", {}),
        ("add_schedule_item", {"action": "wait_for"}),
        ("insert_schedule_item_before", {"before_id": "x"}),
        ("replace_schedule_item", {"item_id": "x"}),
        ("remove_schedule_item", {"schedule_item_id": "x"}),
        ("stop_scheduler", {}),
        ("export_schedule", {"filepath": "/tmp/s.json"}),
        ("import_schedule", {"filepath": "/tmp/s.json", "is_retain_state": False}),
        ("action_start_up_sequence", {"auto_focus": True}),
        ("action_set_dew_heater", {"heater": 10}),
        ("action_set_exposure", {"exp": 1000}),
        ("get_last_image", {}),
        ("adjust_mag_declination", {"offset": 1.0}),
        ("stop_plate_solve_loop", {}),
        ("get_pa_error", {}),
        ("pause_scheduler", {}),
        ("continue_scheduler", {}),
        ("skip_scheduler_cur_item", {}),
    ]
    for action_name, params in action_cases:
        req = DummyReq(action_name, params)
        resp = DummyResp()
        telescope.action().on_put(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] == 0, action_name


def test_action_put_method_async_and_deprecated_path():
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    fake = FakeDevice(connected=True)
    telescope.seestar_dev[1] = fake

    req_async = DummyReq("method_async", {"method": "scope_get_equ_coord"})
    resp_async = DummyResp()
    telescope.action().on_put(req_async, resp_async, devnum=1)
    payload_async = json.loads(resp_async.text)
    assert payload_async["ErrorNumber"] == 0

    req_depr = DummyReq("start_plate_solve_loop", {})
    resp_depr = DummyResp()
    telescope.action().on_put(req_depr, resp_depr, devnum=1)
    payload_depr = json.loads(resp_depr.text)
    assert payload_depr["ErrorNumber"] == 0


def test_action_put_emits_event_callbacks():
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    fake = FakeDevice(connected=True)

    fired = []

    class CB:
        def fireOnEvents(self):
            return ["action_*"]

        def eventFired(self, _dev, payload):
            fired.append(payload)

    fake.event_callbacks = [CB()]
    telescope.seestar_dev[1] = fake

    req = DummyReq("start_stack", {"gain": 80, "restart": True})
    resp = DummyResp()
    telescope.action().on_put(req, resp, devnum=1)
    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] == 0
    assert len(fired) == 1
    assert fired[0]["Event"] == "action_start_stack"


def test_connected_and_command_responder_paths():
    set_shr_logger(logging.getLogger("test-telescope"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    fake = FakeDevice(connected=True)
    telescope.seestar_dev[1] = fake

    req_get = DummyReq("noop", {})
    req_get.method = "GET"
    req_get.params = {"ClientID": "1", "ClientTransactionID": "2"}
    resp_get = DummyResp()
    telescope.connected().on_get(req_get, resp_get, devnum=1)
    assert json.loads(resp_get.text)["Value"] is True

    req_put_on = DummyReq("noop", {})
    req_put_on.method = "PUT"
    req_put_on._media["Connected"] = "true"
    resp_put_on = DummyResp()
    telescope.connected().on_put(req_put_on, resp_put_on, devnum=1)
    assert json.loads(resp_put_on.text)["ErrorNumber"] == 0

    req_put_off = DummyReq("noop", {})
    req_put_off.method = "PUT"
    req_put_off._media["Connected"] = "false"
    resp_put_off = DummyResp()
    telescope.connected().on_put(req_put_off, resp_put_off, devnum=1)
    assert json.loads(resp_put_off.text)["ErrorNumber"] == 0

    req_cmd = DummyReq("noop", {})
    req_cmd.method = "PUT"
    for cls in [telescope.commandblind, telescope.commandbool, telescope.commandstring]:
        with pytest.raises(TypeError):
            cls().on_put(req_cmd, DummyResp(), devnum=1)
