import types

import pytest
from falcon import HTTPInternalServerError

import device.app as device_app


class DummyFalconApp:
    def __init__(self):
        self.routes = []

    def add_route(self, uri, controller):
        self.routes.append((uri, controller))


def test_init_routes_adds_routes_for_module_local_classes():
    module = types.ModuleType("fake_module")

    class LocalResponder:
        pass

    class ForeignResponder:
        pass

    LocalResponder.__module__ = module.__name__
    ForeignResponder.__module__ = "elsewhere"
    module.LocalResponder = LocalResponder
    module.ForeignResponder = ForeignResponder

    app = DummyFalconApp()
    device_app.init_routes(app, "telescope", module)

    assert len(app.routes) == 1
    uri, controller = app.routes[0]
    assert uri == "/api/v1/telescope/{devnum:int(min=0)}/localresponder"
    assert isinstance(controller, LocalResponder)


def test_custom_excepthook_logs_exception_and_traceback(monkeypatch):
    logs = []
    monkeypatch.setattr(
        device_app.log, "logger", types.SimpleNamespace(error=logs.append)
    )
    monkeypatch.setattr(device_app.Config, "verbose_driver_exceptions", True)
    monkeypatch.setattr(
        device_app.traceback,
        "format_tb",
        lambda tb: ["trace line"],
    )

    try:
        raise ValueError("boom")
    except ValueError as ex:
        exc_type, exc_value, exc_tb = type(ex), ex, ex.__traceback__
        device_app.custom_excepthook(exc_type, exc_value, exc_tb)

    assert any("ValueError" in str(line) for line in logs)
    assert any("boom" in str(line) for line in logs)
    assert any("trace line" in str(line) for line in logs)


def test_custom_excepthook_keyboard_interrupt_calls_system_hook(monkeypatch):
    called = {"count": 0}

    def fake_hook(*_args):
        called["count"] += 1

    monkeypatch.setattr(device_app.sys, "__excepthook__", fake_hook)
    device_app.custom_excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert called["count"] == 1


def test_falcon_uncaught_exception_handler_raises_http_500(monkeypatch):
    called = {"count": 0}

    def fake_hook(*_args):
        called["count"] += 1

    monkeypatch.setattr(device_app, "custom_excepthook", fake_hook)
    monkeypatch.setattr(
        device_app.sys, "exc_info", lambda: (Exception, Exception("x"), None)
    )

    with pytest.raises(HTTPInternalServerError):
        device_app.falcon_uncaught_exception_handler(None, None, Exception("x"), {})

    assert called["count"] == 1


def test_device_main_reload_calls_config_load(monkeypatch):
    called = {"count": 0}
    monkeypatch.setattr(
        device_app.Config, "load_toml", lambda: called.__setitem__("count", 1)
    )
    dm = device_app.DeviceMain()
    dm.reload()
    assert called["count"] == 1


def test_device_main_get_imager_delegates(monkeypatch):
    monkeypatch.setattr(
        device_app.telescope, "get_seestar_imager", lambda dev: f"imager-{dev}"
    )
    dm = device_app.DeviceMain()
    assert dm.get_imager(2) == "imager-2"


def test_device_main_stop_ends_devices_and_shutdowns_server(monkeypatch):
    monkeypatch.setattr(
        device_app.Config,
        "seestars",
        [{"device_num": 1}, {"device_num": 2}],
    )
    ended = []
    monkeypatch.setattr(
        device_app.telescope, "end_seestar_device", lambda devnum: ended.append(devnum)
    )

    class FakeHTTPD:
        def __init__(self):
            self.shutdown_called = 0

        def shutdown(self):
            self.shutdown_called += 1

    dm = device_app.DeviceMain()
    dm.httpd = FakeHTTPD()
    dm.stop()

    assert ended == [1, 2]
    assert dm.httpd.shutdown_called == 1
