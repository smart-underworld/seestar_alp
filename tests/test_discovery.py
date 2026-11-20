import pytest

import device.discovery as discovery


class DummyLogger:
    def __init__(self):
        self.info_lines = []
        self.error_lines = []

    def info(self, msg):
        self.info_lines.append(msg)

    def error(self, msg):
        self.error_lines.append(msg)

    def warning(self, msg):
        self.error_lines.append(msg)


class FakeSocket:
    def __init__(self, recv_packets=None):
        self.recv_packets = recv_packets or []
        self.bound = None
        self.sent = []
        self.closed = False
        self.opts = []

    def setsockopt(self, level, optname, value):
        self.opts.append((level, optname, value))

    def bind(self, addr):
        self.bound = addr

    def recvfrom(self, _size):
        if not self.recv_packets:
            # Break run()'s otherwise-infinite loop with a BaseException so the
            # responder's `except Exception` guard does not swallow it.
            raise KeyboardInterrupt()
        return self.recv_packets.pop(0)

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


def test_set_disc_logger():
    logger = DummyLogger()
    discovery.set_disc_logger(logger)
    assert discovery.logger is logger


def test_discovery_responder_init_binds_and_sets_response(monkeypatch):
    recv_sock = FakeSocket()
    tx_sock = FakeSocket()
    sockets = [recv_sock, tx_sock]

    monkeypatch.setattr(
        discovery.socket,
        "socket",
        lambda *args, **kwargs: sockets.pop(0),
    )
    monkeypatch.setattr(discovery.Thread, "start", lambda self: None)
    discovery.set_disc_logger(DummyLogger())

    responder = discovery.DiscoveryResponder("127.0.0.1", 5555)
    assert responder.device_address == ("127.0.0.1", 32227)
    assert responder.alpaca_response == '{"AlpacaPort": 5555}'
    assert recv_sock.bound == ("127.0.0.1", 32227)
    assert tx_sock.bound == ("127.0.0.1", 0)


def test_discovery_run_replies_on_matching_probe(monkeypatch):
    recv_sock = FakeSocket(
        recv_packets=[
            (b"alpacadiscovery1", ("10.0.0.9", 40000)),
        ]
    )
    tx_sock = FakeSocket()
    sockets = [recv_sock, tx_sock]
    logger = DummyLogger()

    monkeypatch.setattr(
        discovery.socket,
        "socket",
        lambda *args, **kwargs: sockets.pop(0),
    )
    monkeypatch.setattr(discovery.Thread, "start", lambda self: None)
    discovery.set_disc_logger(logger)

    responder = discovery.DiscoveryResponder("127.0.0.1", 5555)
    with pytest.raises(KeyboardInterrupt):
        responder.run()

    assert tx_sock.sent == [(b'{"AlpacaPort": 5555}', ("10.0.0.9", 40000))]
    assert any("alpacadiscovery1" in line for line in logger.info_lines)


def test_discovery_run_survives_a_non_ascii_datagram(monkeypatch):
    # Regression: a single non-ASCII datagram raised UnicodeDecodeError and
    # killed the responder thread for good. It must survive and keep answering.
    recv_sock = FakeSocket(
        recv_packets=[
            (b"\xff\xfe\x00bad", ("10.0.0.5", 40001)),  # non-ASCII, previously fatal
            (b"alpacadiscovery1", ("10.0.0.9", 40000)),  # good probe afterwards
        ]
    )
    tx_sock = FakeSocket()
    sockets = [recv_sock, tx_sock]
    logger = DummyLogger()

    monkeypatch.setattr(
        discovery.socket,
        "socket",
        lambda *args, **kwargs: sockets.pop(0),
    )
    monkeypatch.setattr(discovery.Thread, "start", lambda self: None)
    discovery.set_disc_logger(logger)

    responder = discovery.DiscoveryResponder("127.0.0.1", 5555)
    with pytest.raises(KeyboardInterrupt):
        responder.run()

    # Survived the bad datagram and still answered the good probe.
    assert tx_sock.sent == [(b'{"AlpacaPort": 5555}', ("10.0.0.9", 40000))]
