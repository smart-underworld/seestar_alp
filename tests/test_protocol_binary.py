import errno
import socket
from struct import pack

from device.protocols.binary import SeestarBinaryProtocol


class DummyLogger:
    def __init__(self):
        self.messages = []

    def debug(self, msg):
        self.messages.append(("debug", msg))

    def info(self, msg):
        self.messages.append(("info", msg))

    def error(self, msg):
        self.messages.append(("error", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))


class DummySocket:
    def __init__(self, *, send_error=None, recv_value=None, recv_error=None):
        self.send_error = send_error
        self.recv_value = recv_value
        self.recv_error = recv_error
        self.sent = []

    def sendall(self, data):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    def recv(self, _num, _flags):
        if self.recv_error is not None:
            raise self.recv_error
        return self.recv_value


def make_protocol(monkeypatch):
    logger = DummyLogger()
    proto = SeestarBinaryProtocol(logger, "scope", 1, "127.0.0.1", 1234)
    monkeypatch.setattr(proto, "is_connected", lambda: proto._s is not None)
    return proto, logger


def test_binary_listener_heartbeat_sends_test_connection(monkeypatch):
    proto, _logger = make_protocol(monkeypatch)

    sent = []
    monkeypatch.setattr(
        proto, "send_message", lambda payload: sent.append(payload) or True
    )

    proto.binary_listener.on_heartbeat()

    assert sent == ['{ "id" : 2,  "method" : "test_connection"}\r\n']


def test_parse_header_valid_and_short(monkeypatch):
    proto, _logger = make_protocol(monkeypatch)

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
            21,
            640,
            480,
        )
        + b"x" * 60
    )

    size, frame_id, width, height = proto.parse_header(header)
    assert (size, frame_id, width, height) == (2048, 21, 640, 480)
    assert proto.parse_header(b"short") == (0, None, None, None)


def test_send_message_not_connected(monkeypatch):
    proto, logger = make_protocol(monkeypatch)
    proto._s = None

    ok = proto.send_message("hello")

    assert ok is False
    assert any(level == "warning" for level, _ in logger.messages)


def test_send_message_success(monkeypatch):
    proto, _logger = make_protocol(monkeypatch)
    sock = DummySocket()
    proto._s = sock

    ok = proto.send_message("hello")

    assert ok is True
    assert sock.sent == [b"hello"]


def test_send_message_timeout(monkeypatch):
    proto, _logger = make_protocol(monkeypatch)
    proto._s = DummySocket(send_error=socket.timeout())

    assert proto.send_message("hello") is False


def test_send_message_socket_error(monkeypatch):
    proto, logger = make_protocol(monkeypatch)
    proto._s = DummySocket(send_error=socket.error("boom"))

    assert proto.send_message("hello") is None
    assert not any(level == "error" for level, _ in logger.messages)


def test_send_message_epipe_reconnect_and_retry(monkeypatch):
    proto, _logger = make_protocol(monkeypatch)

    first = DummySocket(send_error=OSError(errno.EPIPE, "pipe"))
    second = DummySocket()
    proto._s = first

    monkeypatch.setattr(proto, "disconnect", lambda: None)

    def fake_reconnect():
        proto._s = second
        return True

    monkeypatch.setattr(proto, "reconnect", fake_reconnect)

    assert proto.send_message("retry") is True
    assert second.sent == [b"retry"]


def test_recv_exact_connected_success_and_empty(monkeypatch):
    proto, _logger = make_protocol(monkeypatch)
    proto._s = DummySocket(recv_value=b"abc")

    assert proto.recv_exact(3) == b"abc"

    proto._s = DummySocket(recv_value=b"")
    assert proto.recv_exact(3) is None


def test_recv_exact_timeout_and_socket_error(monkeypatch):
    proto, logger = make_protocol(monkeypatch)

    proto._s = DummySocket(recv_error=socket.timeout())
    assert proto.recv_exact(5) is None

    disconnected = {"called": 0}
    monkeypatch.setattr(
        proto, "disconnect", lambda: disconnected.__setitem__("called", 1)
    )
    proto._s = DummySocket(recv_error=socket.error("read fail"))
    assert proto.recv_exact(5) is None
    assert disconnected["called"] == 1
    assert any(level == "error" for level, _ in logger.messages)


def test_recv_exact_when_not_connected(monkeypatch):
    proto, _logger = make_protocol(monkeypatch)
    proto._s = None

    assert proto.recv_exact(8) is None
