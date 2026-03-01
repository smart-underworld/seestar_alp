import collections
import json
import sys

import pytest
from device import seestar_util as _seestar_util

sys.modules.setdefault("seestar_util", _seestar_util)
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
        self.schedule = {"state": "stopped", "list": []}

    def get_event_state(self, params):
        self.called.append(("get_event_state", params))
        return {"state": "ok"}

    def send_message_param_sync(self, data):
        self.called.append(("send_message_param_sync", data))
        return {"result": "ok"}

    def goto_target(self, params):
        self.called.append(("goto_target", params))
        return True

    def stop_slew(self):
        self.called.append(("stop_slew", None))
        return {"ok": True}

    def play_sound(self, sid):
        self.called.append(("play_sound", sid))
        return {"ok": True}

    def start_stack(self, params):
        self.called.append(("start_stack", params))
        return {"ok": True}

    def is_client_master(self):
        return True

    def get_schedule(self, params):
        self.called.append(("get_schedule", params))
        return self.schedule

    def create_schedule(self, params):
        self.called.append(("create_schedule", params))
        self.schedule = {"state": "stopped", "list": []}
        return self.schedule

    def add_schedule_item(self, item):
        self.called.append(("add_schedule_item", item))
        self.schedule["list"].append(item)
        return self.schedule

    def start_scheduler(self, params):
        self.called.append(("start_scheduler", params))
        self.schedule["state"] = "working"
        return self.schedule

    def stop_scheduler(self, params):
        self.called.append(("stop_scheduler", params))
        self.schedule["state"] = "stopped"
        return {"ok": True}

    def stop_goto_target(self):
        self.called.append(("stop_goto_target", None))
        return {"ok": True}

    def is_goto(self):
        self.called.append(("is_goto", None))
        return False

    def is_goto_completed_ok(self):
        self.called.append(("is_goto_completed_ok", None))
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


def test_federation_control_fanout_methods():
    dev1 = FakeDevice(connected=True)
    dev2 = FakeDevice(connected=False)
    federation = Seestar_Federation(DummyLogger(), {1: dev1, 2: dev2})

    out_slew = federation.stop_slew()
    out_sound = federation.play_sound(80)
    out_stack = federation.start_stack({"gain": 90, "restart": True})

    assert 1 in out_slew and 2 not in out_slew
    assert 1 in out_sound and 2 not in out_sound
    assert 1 in out_stack and 2 not in out_stack
    assert ("stop_slew", None) in dev1.called
    assert ("play_sound", 80) in dev1.called
    assert ("start_stack", {"gain": 90, "restart": True}) in dev1.called


def test_federation_create_schedule_resets_state():
    federation = Seestar_Federation(DummyLogger(), {})
    federation.schedule["list"].append({"action": "wait_for"})
    federation.schedule["state"] = "working"

    out = federation.create_schedule({})
    assert out["state"] == "stopped"
    assert len(out["list"]) == 0
    assert "schedule_id" in out


def test_federation_additional_fanout_methods():
    dev1 = FakeDevice(connected=True)
    dev2 = FakeDevice(connected=False)
    federation = Seestar_Federation(DummyLogger(), {1: dev1, 2: dev2})

    assert 1 in federation.stop_goto_target()
    assert 2 not in federation.stop_goto_target()
    assert 1 in federation.is_goto()
    assert 1 in federation.is_goto_completed_ok()


def test_get_section_array_for_mosaic_modes():
    federation = Seestar_Federation(DummyLogger(), {})

    by_auto = federation.get_section_array_for_mosaic(
        [1, 2],
        {"ra_num": 2, "dec_num": 2, "selected_panels": ""},
    )
    assert set(by_auto.keys()) == {1, 2}
    assert all(v for v in by_auto.values())

    by_list = federation.get_section_array_for_mosaic(
        [1, 2],
        {"ra_num": 3, "dec_num": 1, "selected_panels": "11;21;31"},
    )
    assert by_list[1].startswith("11")
    assert "31" in by_list[2] or "31" in by_list[1]


def test_get_section_array_for_mosaic_raises_without_devices():
    federation = Seestar_Federation(DummyLogger(), {})
    with pytest.raises(Exception):
        federation.get_section_array_for_mosaic([], {"ra_num": 1, "dec_num": 1})


def test_schedule_item_remove_and_insert_before():
    federation = Seestar_Federation(DummyLogger(), {})
    a = federation.construct_schedule_item({"action": "wait_for", "params": {}})
    b = federation.construct_schedule_item({"action": "wait_for", "params": {}})
    federation.schedule["list"] = collections.deque([a, b])

    federation.remove_schedule_item({"schedule_item_id": a["schedule_item_id"]})
    assert len(federation.schedule["list"]) == 1

    federation.insert_schedule_item_before(
        {"before_id": b["schedule_item_id"], "action": "wait_for", "params": {}}
    )
    assert len(federation.schedule["list"]) == 2


def test_working_schedule_blocks_insert_or_remove_before_current():
    federation = Seestar_Federation(DummyLogger(), {})
    first = federation.construct_schedule_item({"action": "wait_for", "params": {}})
    current = federation.construct_schedule_item({"action": "wait_for", "params": {}})
    federation.schedule["list"] = collections.deque([first, current])
    federation.schedule["state"] = "working"
    federation.schedule["current_item_id"] = current["schedule_item_id"]

    out = federation.remove_schedule_item(
        {"schedule_item_id": first["schedule_item_id"]}
    )
    assert len(out["list"]) == 2

    out2 = federation.insert_schedule_item_before(
        {"before_id": first["schedule_item_id"], "action": "wait_for", "params": {}}
    )
    assert len(out2["list"]) == 2


def test_schedule_export_and_import(tmp_path):
    federation = Seestar_Federation(DummyLogger(), {})
    federation.add_schedule_item({"action": "wait_for", "params": {}})
    path = tmp_path / "sched.json"

    federation.export_schedule({"filepath": str(path)})
    content = json.loads(path.read_text())
    assert content["state"] == "stopped"

    federation.schedule["state"] = "complete"
    imported = federation.import_schedule(
        {"filepath": str(path), "is_retain_state": False}
    )
    assert imported["state"] == "stopped"
    assert isinstance(imported["list"], collections.deque)


def test_start_scheduler_and_start_mosaic_distribution(monkeypatch):
    dev1 = FakeDevice(connected=True)
    dev2 = FakeDevice(connected=True)
    federation = Seestar_Federation(DummyLogger(), {1: dev1, 2: dev2})

    federation.add_schedule_item(
        {
            "action": "start_mosaic",
            "params": {
                "ra": 1.2,
                "dec": 3.4,
                "is_j2000": True,
                "federation_mode": "by_panels",
                "ra_num": 2,
                "dec_num": 1,
                "selected_panels": "11;21",
                "panel_time_sec": 10,
            },
        }
    )
    federation.add_schedule_item({"action": "wait_for", "params": {"seconds": 2}})

    monkeypatch.setattr("device.seestar_federation.random.shuffle", lambda x: None)
    result = federation.start_scheduler({"max_devices": 2})
    assert "available_device_list" in result
    assert any(call[0] == "start_scheduler" for call in dev1.called)
    assert any(call[0] == "start_scheduler" for call in dev2.called)

    dev1.schedule["state"] = "stopped"
    dev2.schedule["state"] = "stopped"

    # start_mosaic shortcut path when devices exist
    out = federation.start_mosaic(
        {
            "ra": 1.2,
            "dec": 3.4,
            "is_j2000": True,
            "ra_num": 1,
            "dec_num": 1,
            "selected_panels": "",
            "panel_time_sec": 10,
        }
    )
    assert "device" in out


def test_start_scheduler_empty_or_no_available_devices():
    federation = Seestar_Federation(DummyLogger(), {})
    err = federation.start_scheduler({})
    assert "error" in err

    out = federation.start_mosaic(
        {
            "ra": 1.2,
            "dec": 3.4,
            "is_j2000": True,
            "ra_num": 1,
            "dec_num": 1,
            "selected_panels": "",
            "panel_time_sec": 10,
        }
    )
    assert "error" in out
