"""End-to-end test of the seestar-mcp tools against the simulator.

Path under test: MCP tool -> ssalp_api_client -> real HTTP -> seestar_alp Alpaca
device server (served on a real TCP port) -> simulator.
"""

import asyncio
import logging
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("seestar_mcp")
pytest.importorskip("falcon")

import device.app as device_app  # noqa: E402
from device.config import Config  # noqa: E402
from seestar_mcp.tools import (  # noqa: E402
    pointing,
    scheduling,
    settings,
    state,
    system,
)

SIMULATOR_SRC = Path(__file__).resolve().parents[2] / "simulator" / "src"
if str(SIMULATOR_SRC) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_SRC))

from listener import SocketListener  # noqa: E402

pytestmark = pytest.mark.integration

HOST = "127.0.0.1"


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_for_tcp(host, port, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return
            except OSError:
                time.sleep(0.05)
    raise TimeoutError(f"{host}:{port} did not open in time")


class _NoDiscovery:
    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(scope="module")
def device_server():
    """Boot the simulator, then the real Alpaca device server pointed at it."""
    sim_tcp, sim_udp, api_port = _find_free_port(), _find_free_port(), _find_free_port()
    logger = logging.getLogger("mcp-simulator-e2e")
    listener = SocketListener(logger, host=HOST, tcp_port=sim_tcp, udp_port=sim_udp)
    sim_thread = threading.Thread(target=listener._start_socket_listener, daemon=True)
    sim_thread.start()
    _wait_for_tcp(HOST, sim_tcp)

    mp = pytest.MonkeyPatch()
    # Don't read/write the developer's config.toml; configure in memory.
    mp.setattr(Config, "load_toml", lambda *a, **k: None)
    mp.setattr(Config, "ip_address", HOST)
    mp.setattr(Config, "port", api_port)
    mp.setattr(
        Config,
        "seestars",
        [
            {
                "device_num": 1,
                "name": "Seestar Sim",
                "ip_address": HOST,
                "simulator": True,
            }
        ],
    )
    # DeviceMain hardcodes the seestar port 4700; redirect to the simulator.
    real_start = device_app.telescope.start_seestar_device
    mp.setattr(
        device_app.telescope,
        "start_seestar_device",
        lambda logger, name, ip, port, num: real_start(logger, name, ip, sim_tcp, num),
    )
    mp.setattr(device_app, "DiscoveryResponder", _NoDiscovery)
    old_excepthook = sys.excepthook

    main = device_app.DeviceMain()
    api_thread = threading.Thread(target=main.start, daemon=True)
    api_thread.start()
    try:
        _wait_for_tcp(HOST, api_port, timeout=30.0)
    except TimeoutError:
        mp.undo()
        pytest.skip("Alpaca device server could not be booted in this environment")

    yield {"base_url": f"http://{HOST}:{api_port}", "listener": listener}

    main.stop()
    api_thread.join(timeout=5)
    sys.excepthook = old_excepthook
    mp.undo()
    listener.shutdown_event.set()
    for sock in (listener.tcp_socket, listener.udp_socket):
        if sock:
            sock.close()
    sim_thread.join(timeout=2)


@pytest.fixture
def tools_env(monkeypatch, device_server):
    monkeypatch.setenv("SEESTAR_BASE_URL", device_server["base_url"])
    return device_server


def test_get_device_state_returns_dict(tools_env):
    result = asyncio.run(state.get_device_state_tool())
    assert isinstance(result, dict)


def test_goto_target_round_trip(tools_env):
    goto = asyncio.run(pointing.goto_target_tool("M31", 0.712, 41.27))
    assert not (isinstance(goto, dict) and goto.get("ok") is False), goto
    done = asyncio.run(pointing.is_goto_completed_ok_tool())
    assert not (isinstance(done, dict) and done.get("ok") is False), done


def test_read_and_write_settings(tools_env):
    before = asyncio.run(settings.read_settings_tool())
    assert before.get("setting") is not None or before.get("stack_setting") is not None
    write = asyncio.run(settings.write_setting_tool({"stack_lenhance": True}))
    assert not (isinstance(write, dict) and write.get("ok") is False), write
    after = asyncio.run(settings.read_settings_tool())
    assert after.get("setting") is not None or after.get("stack_setting") is not None
    # The simulator persists the field; confirm the write is reflected on read.
    flat = repr(after)
    assert "'stack_lenhance': True" in flat, after


def test_schedule_flow(tools_env):
    created = asyncio.run(scheduling.create_schedule_tool())
    assert not (isinstance(created, dict) and created.get("ok") is False), created
    added = asyncio.run(scheduling.add_schedule_item_tool("wait_for", {"timer_sec": 1}))
    assert not (isinstance(added, dict) and added.get("ok") is False), added
    schedule = asyncio.run(scheduling.get_schedule_tool())
    assert "wait_for" in repr(schedule)
    for fn in (scheduling.start_scheduler_tool, scheduling.stop_scheduler_tool):
        res = asyncio.run(fn())
        assert not (isinstance(res, dict) and res.get("ok") is False), res


def test_shutdown_without_confirm_makes_no_device_call(tools_env, monkeypatch):
    import seestar_mcp.tools.system as system_mod

    def _boom(*a, **k):
        raise AssertionError("device call made for unconfirmed shutdown")

    monkeypatch.setattr(system_mod, "call", _boom)
    result = asyncio.run(system.shutdown_tool(confirm=False))
    assert result["requires_confirmation"] is True
    assert result["ok"] is False
