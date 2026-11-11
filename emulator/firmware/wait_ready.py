"""Wait until the emulated firmware is really listening on its TCP ports.

``nc -z`` is not enough: Docker's port proxy accepts on the host port as soon
as the container starts, ~20 s before the firmware binds 4700/4800, and then
closes each early connection (FIN or RST). A client that connects in that
window sees a dead socket (issue #798).

A port is ready when a connection to it survives: the peer sends bytes, or
keeps the connection open for ``hold_s`` without closing it. Refused, reset or
an immediate EOF means the proxy answered, not the firmware.

Usage:
    python3 -m emulator.firmware.wait_ready [--host H] [--timeout S] PORT...
"""

from __future__ import annotations

import argparse
import socket
import sys
import time


def probe(host: str, port: int, hold_s: float = 2.0) -> bool:
    """True if ``host:port`` holds a connection open (or talks) for hold_s."""
    try:
        sock = socket.create_connection((host, port), timeout=hold_s)
    except OSError:
        return False
    try:
        sock.settimeout(hold_s)
        try:
            data = sock.recv(1)
        except socket.timeout:
            return True  # still open and silent: a real listener
        except OSError:
            return False  # reset by the proxy
        return bool(data)  # b"" is EOF: the proxy closed it
    finally:
        sock.close()


def wait_ready(
    host: str,
    ports: list[int],
    timeout_s: float,
    hold_s: float = 2.0,
    interval_s: float = 2.0,
    clock=time.monotonic,
    sleep=time.sleep,
    probe_fn=probe,
) -> bool:
    deadline = clock() + timeout_s
    pending = list(ports)
    while True:
        pending = [p for p in pending if not probe_fn(host, p, hold_s)]
        if not pending:
            return True
        if clock() >= deadline:
            print(
                f"firmware not listening on {host}:{pending} after {timeout_s}s",
                file=sys.stderr,
            )
            return False
        sleep(interval_s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ports", nargs="+", type=int)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--hold", type=float, default=2.0)
    args = ap.parse_args(argv)
    ok = wait_ready(args.host, args.ports, args.timeout, hold_s=args.hold)
    if ok:
        print(f"firmware listening on {args.host}:{args.ports}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
