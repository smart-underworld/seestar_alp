"""emulator.firmware.wait_ready must not mistake Docker's port proxy (accepts,
then closes with FIN or RST) for the firmware listening (issue #798)."""

import socket
import struct
import threading

import pytest

from emulator.firmware.wait_ready import probe, wait_ready


def _listener(behaviour):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    stop = threading.Event()
    held = []

    def run():
        srv.settimeout(0.1)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if behaviour == "fin":
                conn.close()
            elif behaviour == "rst":
                conn.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                conn.close()
            elif behaviour == "talk":
                conn.sendall(b'{"Event":"PiStatus"}\r\n')
                held.append(conn)
            else:  # hold
                held.append(conn)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    def close():
        stop.set()
        t.join(timeout=2)
        for c in held:
            c.close()
        srv.close()

    return srv.getsockname()[1], close


@pytest.mark.parametrize(
    "behaviour,expected",
    [("fin", False), ("rst", False), ("hold", True), ("talk", True)],
)
def test_probe_tells_proxy_from_firmware(behaviour, expected):
    port, close = _listener(behaviour)
    try:
        assert probe("127.0.0.1", port, hold_s=0.5) is expected
    finally:
        close()


def test_probe_refused_port_is_not_ready():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert probe("127.0.0.1", port, hold_s=0.5) is False


def test_wait_ready_waits_until_every_port_is_up():
    calls = []
    up_after = {4700: 3, 4800: 1}

    def fake_probe(host, port, hold_s):
        calls.append(port)
        return calls.count(port) >= up_after[port]

    assert wait_ready("h", [4700, 4800], 60, sleep=lambda s: None, probe_fn=fake_probe)
    # 4800 came up first and is not probed again.
    assert calls == [4700, 4800, 4700, 4700]


def test_wait_ready_times_out():
    now = [0.0]

    def sleep(s):
        now[0] += s

    assert not wait_ready(
        "h",
        [4700],
        10,
        interval_s=2,
        clock=lambda: now[0],
        sleep=sleep,
        probe_fn=lambda *a: False,
    )
