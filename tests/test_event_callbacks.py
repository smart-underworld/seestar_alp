import json

from device.config import Config
from device.event_callbacks import BatteryWatch, SensorTempWatch, UserScriptEvent


class DummyLogger:
    def __init__(self):
        self.infos = []
        self.warns = []

    def info(self, msg):
        self.infos.append(msg)

    def warn(self, msg):
        self.warns.append(msg)


class DummyDevice:
    def __init__(self):
        self.logger = DummyLogger()
        self.device_num = 2
        self.device_name = "Seestar Alpha"
        self.sync_calls = []

    def send_message_param_sync(self, payload):
        self.sync_calls.append(payload)
        return {"ok": True}


def test_battery_watch_init_from_state_and_fire_events():
    device = DummyDevice()
    watch = BatteryWatch(
        device,
        {
            "pi_status": {
                "charger_status": "Discharging",
                "charge_online": False,
                "battery_capacity": 17,
            }
        },
    )

    assert watch.discharging is True
    assert watch.charge_online is False
    assert watch.battery_capacity == 17
    assert watch.fireOnEvents() == ["PiStatus"]


def test_battery_watch_init_defaults_when_pi_status_missing():
    device = DummyDevice()
    watch = BatteryWatch(device, {})

    assert watch.discharging is False
    assert watch.charge_online is True
    assert watch.battery_capacity == 100


def test_battery_watch_shutdown_triggers_once(monkeypatch):
    device = DummyDevice()
    watch = BatteryWatch(
        device,
        {
            "pi_status": {
                "charger_status": "Charging",
                "charge_online": True,
                "battery_capacity": 50,
            }
        },
    )
    monkeypatch.setattr(Config, "battery_low_limit", 7)

    watch.eventFired(
        device,
        {
            "charger_status": "Discharging",
            "charge_online": False,
            "battery_capacity": 7,
        },
    )
    watch.eventFired(device, {"battery_capacity": 6})

    assert watch.triggered is True
    assert device.sync_calls == [{"method": "pi_shutdown"}]


def test_sensor_temp_watch_init_and_events_without_temp_do_not_change_state():
    device = DummyDevice()
    watch = SensorTempWatch(device, {"pi_status": {"temp": 11.2}})

    watch.eventFired(device, {"not_temp": 1})

    assert watch.temp == 11.2
    assert watch.fireOnEvents() == ["PiStatus"]


def test_sensor_temp_watch_sets_initial_temp_when_unknown():
    device = DummyDevice()
    watch = SensorTempWatch(device, {})

    watch.eventFired(device, {"temp": 4.5})

    assert watch.temp == 4.5


def test_user_script_event_dispatches_subprocess(monkeypatch):
    device = DummyDevice()
    script = {"events": ["GotoComplete"], "execute": ["/bin/echo", "ok"]}
    callback = UserScriptEvent(device, {}, script)

    captured = {}

    def fake_run(cmd, env):
        captured["cmd"] = cmd
        captured["env"] = env

    monkeypatch.setattr("device.event_callbacks.subprocess.run", fake_run)

    payload = {"Event": "GotoComplete", "ra": 1.2}
    callback.eventFired(device, payload)

    assert callback.fireOnEvents() == ["GotoComplete"]
    assert captured["cmd"] == ["/bin/echo", "ok"]
    assert captured["env"]["DEVNUM"] == "2"
    assert captured["env"]["DEVICENAME"] == "Seestar Alpha"
    assert captured["env"]["NAME"] == "GotoComplete"
    assert json.loads(captured["env"]["EVENT_DATA"]) == payload


def test_user_script_event_no_events_key_returns_empty_list():
    device = DummyDevice()
    callback = UserScriptEvent(device, {}, {"execute": ["/bin/true"]})

    assert callback.fireOnEvents() == []
