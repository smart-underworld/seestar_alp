import collections

import pytest

from device.seestar_federation import Seestar_Federation


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
        self.called = []

    def get_event_state(self, params):
        self.called.append(("get_event_state", params))
        return {"state": "ok"}

    def send_message_param_sync(self, data):
        self.called.append(("send_message_param_sync", data))
        return {"result": "ok"}

    def goto_target(self, params):
        self.called.append(("goto_target", params))
        return True


def test_federation_only_calls_connected_devices():
    dev1 = FakeDevice(connected=True)
    dev2 = FakeDevice(connected=False)
    federation = Seestar_Federation(DummyLogger(), {1: dev1, 2: dev2})

    out = federation.get_event_state({"event_name": "scheduler"})
    assert 1 in out
    assert 2 not in out
    assert dev1.called == [("get_event_state", {"event_name": "scheduler"})]
    assert dev2.called == []


def test_federation_sync_and_goto_fan_out():
    dev1 = FakeDevice(connected=True)
    dev2 = FakeDevice(connected=True)
    federation = Seestar_Federation(DummyLogger(), {1: dev1, 2: dev2})

    sync_out = federation.send_message_param_sync({"method": "scope_get_equ_coord"})
    goto_out = federation.goto_target({"ra": 1.0, "dec": 2.0})

    assert sync_out[1]["result"] == "ok"
    assert sync_out[2]["result"] == "ok"
    assert goto_out[1] is True
    assert goto_out[2] is True


def test_construct_schedule_item_rounds_float_coords():
    federation = Seestar_Federation(DummyLogger(), {})
    item = federation.construct_schedule_item(
        {
            "action": "start_mosaic",
            "params": {"ra": 1.234567, "dec": 2.987654, "is_j2000": True},
        }
    )
    assert item["params"]["ra"] == 1.2346
    assert item["params"]["dec"] == 2.9877
    assert "schedule_item_id" in item


def test_construct_schedule_item_rejects_negative_ra_float():
    federation = Seestar_Federation(DummyLogger(), {})
    with pytest.raises(Exception):
        federation.construct_schedule_item(
            {
                "action": "start_mosaic",
                "params": {"ra": -1.0, "dec": 2.0, "is_j2000": True},
            }
        )


def test_add_schedule_item_appends_deque():
    federation = Seestar_Federation(DummyLogger(), {})
    out = federation.add_schedule_item(
        {
            "action": "start_mosaic",
            "params": {"ra": 1.1, "dec": 2.2, "is_j2000": True},
        }
    )
    assert isinstance(out["list"], collections.deque)
    assert len(out["list"]) == 1
