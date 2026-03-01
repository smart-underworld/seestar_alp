from types import SimpleNamespace

import device.exceptions as ex


class DummyLogger:
    def __init__(self):
        self.lines = []

    def error(self, msg):
        self.lines.append(msg)


def test_success_defaults():
    s = ex.Success()
    assert s.Number == 0
    assert s.Message == ""


def test_basic_exception_classes_emit_expected_codes():
    logger = DummyLogger()
    ex.logger = logger

    bad = ex.InvalidValueException("bad value")
    assert bad.number == 0x401
    assert bad.Message == "bad value"

    op = ex.InvalidOperationException("bad operation")
    assert op.number == 0x40B

    park = ex.ParkedException()
    assert park.number == 0x408

    assert any("InvalidValueException" in line for line in logger.lines)


def test_dev_driver_exception_formats_underlying_exception(monkeypatch):
    logger = DummyLogger()
    ex.logger = logger
    monkeypatch.setattr(ex, "Config", SimpleNamespace(verbose_driver_exceptions=False))

    try:
        raise ValueError("boom")
    except ValueError as err:
        drv = ex.DevDriverException(0x501, "wrapped", err)

    assert drv.number == 0x501
    assert "wrapped" in drv.Message
    assert "ValueError" in drv.Message


def test_action_not_implemented_code():
    ex.logger = DummyLogger()
    err = ex.ActionNotImplementedException()
    assert err.Number == 0x40C
