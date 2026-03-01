import socket

from device.protocols.socket_base import SocketBase


class DummyLogger:
    def __init__(self):
        self.records = []

    def info(self, msg):
        self.records.append(("info", msg))

    def error(self, msg):
        self.records.append(("error", msg))


class DummyListener:
    def __init__(self):
        self.connected = 0
        self.disconnected = 0
        self.heartbeats = 0

    def on_connect(self):
        self.connected += 1

    def on_heartbeat(self):
        self.heartbeats += 1

    def on_disconnect(self):
        self.disconnected += 1


class FakeThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.name = ""
        self.started = False

    def start(self):
        self.started = True


class FakeSocket:
    def __init__(self, fail_connect=False):
        self.fail_connect = fail_connect
        self.timeout_values = []
        self.connected_to = None
        self.closed = False

    def settimeout(self, value):
        self.timeout_values.append(value)

    def connect(self, addr):
        if self.fail_connect:
            raise socket.error("connect failed")
        self.connected_to = addr

    def close(self):
        self.closed = True


def test_socket_start_creates_heartbeat_thread_and_connects(monkeypatch):
    logger = DummyLogger()
    base = SocketBase(logger, "dev", "127.0.0.1", 1234)

    thread_holder = {}

    def fake_thread(target, daemon):
        thread = FakeThread(target, daemon)
        thread_holder["thread"] = thread
        return thread

    monkeypatch.setattr("device.protocols.socket_base.threading.Thread", fake_thread)

    called = {"connect": 0}
    monkeypatch.setattr(
        base, "connect", lambda: called.__setitem__("connect", 1) or True
    )

    base.start()

    assert base.is_started() is True
    assert called["connect"] == 1
    assert thread_holder["thread"].started is True
    assert "SocketHeartbeatMessageThread.dev" == thread_holder["thread"].name


def test_socket_start_is_noop_if_already_started(monkeypatch):
    logger = DummyLogger()
    base = SocketBase(logger, "dev", "127.0.0.1", 1234)
    base._is_started = True

    monkeypatch.setattr(
        "device.protocols.socket_base.threading.Thread",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not build thread")
        ),
    )
    monkeypatch.setattr(
        base,
        "connect",
        lambda: (_ for _ in ()).throw(AssertionError("should not connect")),
    )

    base.start()

    assert base.is_started() is True


def test_connect_success_notifies_listeners(monkeypatch):
    logger = DummyLogger()
    base = SocketBase(logger, "dev", "127.0.0.1", 1234)
    base._is_started = True
    listener = DummyListener()
    base.add_listener(listener)

    fake_sock = FakeSocket()
    monkeypatch.setattr(
        "device.protocols.socket_base.socket.socket", lambda *_args: fake_sock
    )

    assert base.connect() is True
    assert base.is_connected() is True
    assert fake_sock.connected_to == ("127.0.0.1", 1234)
    assert listener.connected == 1


def test_connect_failure_sets_disconnected(monkeypatch):
    logger = DummyLogger()
    base = SocketBase(logger, "dev", "127.0.0.1", 1234)
    base._is_started = True

    fake_sock = FakeSocket(fail_connect=True)
    monkeypatch.setattr(
        "device.protocols.socket_base.socket.socket", lambda *_args: fake_sock
    )
    monkeypatch.setattr("device.protocols.socket_base.time.sleep", lambda _s: None)

    assert base.connect() is False
    assert base.is_connected() is False


def test_disconnect_with_socket_notifies_listeners():
    logger = DummyLogger()
    base = SocketBase(logger, "dev", "127.0.0.1", 1234)
    listener = DummyListener()
    base.add_listener(listener)

    fake_sock = FakeSocket()
    base._s = fake_sock
    base._is_connected = True

    base.disconnect()

    assert base.is_connected() is False
    assert fake_sock.closed is True
    assert listener.disconnected == 1


def test_reconnect_short_circuit_and_error_path(monkeypatch):
    logger = DummyLogger()
    base = SocketBase(logger, "dev", "127.0.0.1", 1234)

    base._is_connected = True
    assert base.reconnect() is True

    base._is_connected = False
    monkeypatch.setattr(
        base, "disconnect", lambda: (_ for _ in ()).throw(socket.error("boom"))
    )
    monkeypatch.setattr("device.protocols.socket_base.time.sleep", lambda _s: None)

    assert base.reconnect() is False
    assert base._is_connected is False


def test_heartbeat_thread_invokes_reconnect_then_listener(monkeypatch):
    logger = DummyLogger()
    base = SocketBase(logger, "dev", "127.0.0.1", 1234)
    listener = DummyListener()
    base.add_listener(listener)
    base._is_started = True

    state = {"reconnect_calls": 0}

    def fake_reconnect():
        state["reconnect_calls"] += 1
        base._is_connected = True
        base._s = object()
        return True

    monkeypatch.setattr(base, "reconnect", fake_reconnect)
    monkeypatch.setattr(
        base, "is_connected", lambda: base._is_connected and base._s is not None
    )

    class StopLoop(Exception):
        pass

    def fake_sleep(_s):
        raise StopLoop

    monkeypatch.setattr("device.protocols.socket_base.time.sleep", fake_sleep)

    try:
        base._heartbeat_message_thread_fn()
    except StopLoop:
        pass

    assert state["reconnect_calls"] == 1
    assert listener.heartbeats == 1
