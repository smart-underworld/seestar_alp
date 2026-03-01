import json
import logging

from device.config import Config
from device.management import apiversions, configureddevices, description
from device.shr import set_shr_logger


class DummyReq:
    method = "GET"
    remote_addr = "127.0.0.1"
    path = "/management"
    query_string = ""
    content_length = 0

    def __init__(self):
        self.params = {"ClientTransactionID": "1"}


class DummyResp:
    def __init__(self):
        self.text = ""


def test_apiversions_returns_v1():
    set_shr_logger(logging.getLogger("test-management"))
    req = DummyReq()
    resp = DummyResp()
    apiversions().on_get(req, resp)

    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] == 0
    assert payload["Value"] == [1]


def test_description_uses_config_location(monkeypatch):
    set_shr_logger(logging.getLogger("test-management"))
    monkeypatch.setattr(Config, "location", "Observatory X")
    req = DummyReq()
    resp = DummyResp()
    description().on_get(req, resp)

    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] == 0
    assert payload["Value"]["Location"] == "Observatory X"
    assert "ServerName" in payload["Value"]


def test_configureddevices_matches_seestars(monkeypatch):
    set_shr_logger(logging.getLogger("test-management"))
    monkeypatch.setattr(
        Config,
        "seestars",
        [
            {"name": "Alpha", "device_num": 1},
            {"name": "Beta", "device_num": 2},
        ],
    )
    req = DummyReq()
    resp = DummyResp()
    configureddevices().on_get(req, resp)

    payload = json.loads(resp.text)
    assert payload["ErrorNumber"] == 0
    assert len(payload["Value"]) == 2
    assert payload["Value"][0]["DeviceName"] == "Alpha"
    assert payload["Value"][1]["DeviceNumber"] == 2
