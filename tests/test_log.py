import logging
from types import SimpleNamespace

import device.log as log_mod


class FakeHandler:
    def __init__(self):
        self.level = None
        self.formatter = None
        self.rolled = False

    def setFormatter(self, fmt):
        self.formatter = fmt

    def setLevel(self, level):
        self.level = level

    def doRollover(self):
        self.rolled = True


class FakeRootLogger:
    def __init__(self, stdout_handler):
        self.handlers = [stdout_handler]
        self.level = None
        self.removed = []
        self.added = []

    def addHandler(self, h):
        self.handlers.append(h)
        self.added.append(h)

    def removeHandler(self, h):
        self.removed.append(h)
        if h in self.handlers:
            self.handlers.remove(h)

    def setLevel(self, level):
        self.level = level

    def debug(self, *_args, **_kwargs):
        return None


def test_init_logging_creates_rotating_handler_and_disables_stdout(monkeypatch):
    stdout_handler = FakeHandler()
    root_logger = FakeRootLogger(stdout_handler)
    file_handler = FakeHandler()

    monkeypatch.setattr(log_mod, "logger", None)
    monkeypatch.setattr(log_mod.logging, "basicConfig", lambda **kwargs: None)
    monkeypatch.setattr(log_mod.logging, "getLogger", lambda: root_logger)
    monkeypatch.setattr(
        log_mod.logging.handlers,
        "RotatingFileHandler",
        lambda *args, **kwargs: file_handler,
    )
    monkeypatch.setattr(
        log_mod,
        "Config",
        SimpleNamespace(
            log_level=logging.INFO,
            log_prefix="",
            max_size_mb=1,
            num_keep_logs=2,
            log_to_stdout=False,
        ),
    )

    out = log_mod.init_logging()
    assert out is root_logger
    assert file_handler in root_logger.added
    assert file_handler.rolled is True
    assert stdout_handler in root_logger.removed


def test_reinit_logging_updates_logger_and_handler_levels(monkeypatch):
    h1 = FakeHandler()
    h2 = FakeHandler()
    fake_logger = FakeRootLogger(h1)
    fake_logger.handlers.append(h2)
    log_mod.logger = fake_logger
    monkeypatch.setattr(log_mod, "Config", SimpleNamespace(log_level=logging.DEBUG))

    out = log_mod.reinit_logging()
    assert out is fake_logger
    assert fake_logger.level == logging.DEBUG
    assert h1.level == logging.DEBUG
    assert h2.level == logging.DEBUG


def test_get_logger_returns_global_logger():
    fake = FakeRootLogger(FakeHandler())
    log_mod.logger = fake
    assert log_mod.get_logger() is fake
