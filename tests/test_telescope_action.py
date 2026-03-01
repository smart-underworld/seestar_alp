import json
import logging

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

    def get_event_state(self, params):
        self.calls.append(("get_event_state", params))
        return {"ok": True, "params": params}

    def start_scheduler(self, params):
        self.calls.append(("start_scheduler", params))
        return {"state": "started", "params": params}

    def send_message_param_sync(self, params):
        self.calls.append(("method_sync", params))
        return {"result": "ok", "params": params}


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
