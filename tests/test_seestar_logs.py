import socket
from struct import pack

from device.seestar_logs import SeestarLogging


class DummyLogger:
    def __init__(self):
        self.records = []

    def info(self, msg):
        self.records.append(("info", msg))

    def debug(self, msg):
        self.records.append(("debug", msg))

    def error(self, msg):
        self.records.append(("error", msg))


class FakeSocket:
    def __init__(
        self, *, fail_connect=False, send_error=None, recv_error=None, recv_value=None
    ):
        self.fail_connect = fail_connect
        self.send_error = send_error
        self.recv_error = recv_error
        self.recv_value = recv_value
        self.sent = []
        self.closed = False

    def connect(self, addr):
        if self.fail_connect:
            raise socket.error("connect failed")
        self.addr = addr

    def sendall(self, data):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    def recv(self, _num, _flags):
        if self.recv_error is not None:
            raise self.recv_error
        return self.recv_value

    def close(self):
        self.closed = True


class FakeThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.name = ""
        self.started = False

    def start(self):
        self.started = True


def make_logs():
    return SeestarLogging(DummyLogger(), "127.0.0.1", 9000, "scope", 1)


def test_repr_and_reconnect_success(monkeypatch):
    logs = make_logs()
    fake_sock = FakeSocket()

    monkeypatch.setattr("device.seestar_logs.socket.socket", lambda *_args: fake_sock)

    assert "SeestarLogging(host=127.0.0.1, port=9000)" == repr(logs)
    assert logs.reconnect() is True
    assert logs.is_connected is True


def test_reconnect_short_circuit_and_failure(monkeypatch):
    logs = make_logs()
    logs.is_connected = True
    assert logs.reconnect() is True

    logs.is_connected = False
    monkeypatch.setattr(
        "device.seestar_logs.socket.socket",
        lambda *_args: FakeSocket(fail_connect=True),
    )
    monkeypatch.setattr("device.seestar_logs.sleep", lambda _s: None)

    assert logs.reconnect() is False
    assert logs.is_connected is False


def test_disconnect_send_and_retry_paths(monkeypatch):
    logs = make_logs()

    s = FakeSocket()
    logs.s = s
    logs.is_connected = True
    logs.disconnect()
    assert logs.is_connected is False
    assert s.closed is True

    logs.s = FakeSocket()
    assert logs.send_message("abc") is True

    logs.s = FakeSocket(send_error=socket.timeout())
    assert logs.send_message("abc") is False

    logs.s = FakeSocket(send_error=socket.error("boom"))
    monkeypatch.setattr(logs, "disconnect", lambda: None)
    monkeypatch.setattr(logs, "reconnect", lambda: False)
    assert logs.send_message("abc") is False


def test_send_get_server_log(monkeypatch):
    logs = make_logs()
    sent = []
    monkeypatch.setattr(
        logs, "send_message", lambda payload: sent.append(payload) or True
    )

    logs.send_get_server_log()

    assert sent == ['{"id": 44, "method": "get_server_log"}\r\n']


def test_parse_header_and_read_bytes_paths(monkeypatch):
    logs = make_logs()

    header = (
        pack(
            ">HHHIHHBBHH",
            1,
            2,
            3,
            2048,
            5,
            6,
            7,
            44,
            640,
            480,
        )
        + b"x" * 60
    )
    assert logs.parse_header(header) == (2048, 44)
    assert logs.parse_header(b"tiny") == (0, None)

    logs.is_connected = False
    assert logs.read_bytes(10) is None

    logs.is_connected = True
    logs.s = FakeSocket(recv_value=b"data")
    assert logs.read_bytes(4) == b"data"

    logs.s = FakeSocket(recv_value=b"")
    assert logs.read_bytes(4) is None

    logs.s = FakeSocket(recv_error=socket.timeout())
    assert logs.read_bytes(4) is None

    disconnected = {"count": 0}
    monkeypatch.setattr(
        logs, "disconnect", lambda: disconnected.__setitem__("count", 1)
    )
    logs.s = FakeSocket(recv_error=socket.error("read failed"))
    assert logs.read_bytes(4) is None
    assert disconnected["count"] == 1


def test_start_stop_and_get_logs_sync(monkeypatch):
    logs = make_logs()

    monkeypatch.setattr(logs, "reconnect", lambda: True)

    thread_holder = {}

    def fake_thread(target, daemon):
        thread = FakeThread(target, daemon)
        thread_holder["thread"] = thread
        return thread

    monkeypatch.setattr("device.seestar_logs.threading.Thread", fake_thread)

    logs.start()
    assert thread_holder["thread"].started is True
    assert thread_holder["thread"].name == "LoggingReceiveImageThread.scope"

    called = {"disconnect": 0}
    monkeypatch.setattr(logs, "disconnect", lambda: called.__setitem__("disconnect", 1))
    logs.stop()
    assert called["disconnect"] == 1

    logs.raw_log = None
    monkeypatch.setattr(logs, "start", lambda: setattr(logs, "raw_log", b"zip-bytes"))
    monkeypatch.setattr(logs, "send_get_server_log", lambda: None)
    monkeypatch.setattr(logs, "stop", lambda: None)

    assert logs.get_logs_sync() == b"zip-bytes"
