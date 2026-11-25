import os

import pytest

from device.startup_schedule import run_startup_schedule


class FakeDevice:
    def __init__(
        self,
        connected=True,
        master=True,
        import_result=None,
        start_result=None,
        import_exc=None,
    ):
        self.is_connected = connected
        self._master = master
        self._import_result = (
            import_result if import_result is not None else {"state": "stopped"}
        )
        self._start_result = (
            start_result if start_result is not None else {"state": "working"}
        )
        self._import_exc = import_exc
        self.import_params = None
        self.start_called = False

    def is_client_master(self):
        return self._master

    def import_schedule(self, params):
        self.import_params = params
        if self._import_exc:
            raise self._import_exc
        return self._import_result

    def start_scheduler(self, params):
        self.start_called = True
        return self._start_result


def test_happy_path_imports_and_starts(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice()
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is True
    assert dev.import_params["is_retain_state"] is False
    assert dev.start_called is True


def test_resolves_relative_path_to_absolute(tmp_path, monkeypatch):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    monkeypatch.chdir(tmp_path)
    dev = FakeDevice()
    run_startup_schedule(dev, "sched.json", connect_timeout=1, poll_interval=0.01)
    assert os.path.isabs(dev.import_params["filepath"])
    assert dev.import_params["filepath"].endswith("sched.json")


def test_retain_state_passed_through(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice()
    run_startup_schedule(dev, str(f), retain_state=True, connect_timeout=1, poll_interval=0.01)
    assert dev.import_params["is_retain_state"] is True


def test_waits_then_proceeds_when_readiness_is_late(tmp_path):
    # The device is connected but not yet master; it becomes master after a
    # couple of polls. Proves the gate waits and then proceeds. (is_connected
    # stays True because run_startup_schedule short-circuits
    # `is_connected and is_client_master()`.)
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(connected=True, master=False)

    calls = {"n": 0}

    def become_master_after_two_polls():
        calls["n"] += 1
        return calls["n"] >= 3

    dev.is_client_master = become_master_after_two_polls
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is True
    assert dev.start_called is True
    assert calls["n"] >= 3


def test_times_out_when_never_connected(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(connected=False)
    assert run_startup_schedule(dev, str(f), connect_timeout=0.05, poll_interval=0.01) is False
    assert dev.import_params is None
    assert dev.start_called is False


def test_times_out_when_connected_but_not_master(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(connected=True, master=False)
    assert run_startup_schedule(dev, str(f), connect_timeout=0.05, poll_interval=0.01) is False
    assert dev.import_params is None
    assert dev.start_called is False


def test_import_exception_returns_false_without_starting(tmp_path):
    f = tmp_path / "missing.json"
    dev = FakeDevice(import_exc=FileNotFoundError("nope"))
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is False
    assert dev.start_called is False


def test_import_error_code_returns_false_without_starting(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(import_result={"code": -1, "result": "scheduler active"})
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is False
    assert dev.start_called is False


def test_start_refusal_returns_false(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(start_result={"code": -1, "result": "grab control first"})
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is False


def test_none_device_returns_false(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    assert run_startup_schedule(None, str(f), connect_timeout=0.05, poll_interval=0.01) is False
