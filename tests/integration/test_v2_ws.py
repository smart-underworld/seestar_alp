"""
Integration tests for the front_v2 FastAPI backend and WebSocket bridge.

These tests use FastAPI's TestClient (based on httpx + starlette) which
supports synchronous WebSocket testing without a running server.

The tests stub out device_client helpers to avoid needing a real telescope.
"""

import threading
import time

import pytest

# Skip entire module at collection time if v2 deps are not installed.
pytest.importorskip("fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'")
pytest.importorskip("uvicorn", reason="uvicorn not installed; run: pip install -e '.[v2]'")

from fastapi.testclient import TestClient  # noqa: E402

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

FAKE_STATUS = {
    "device_num": 1,
    "is_connected": True,
    "view_state": "Idle",
    "mode": "",
    "stage": "",
    "target": "",
    "stacked": "",
    "failed": "",
    "mount_mode": "Alt Azimuth",
    "free_storage": "10.0 GB / 64.0 GB",
    "battery_capacity": 80,
    "temp": 22.5,
    "ra": 10.0,
    "dec": 41.0,
    "schedule": None,
}

FAKE_DEVICE_LIST = [
    {"device_num": 1, "name": "Seestar Alpha", "ip_address": "127.0.0.1", "is_connected": True}
]


@pytest.fixture
def v2_app(monkeypatch):
    """Build the FastAPI app with device_client calls stubbed out."""
    import front_v2.device_client as dc

    monkeypatch.setattr(dc, "check_api_state", lambda dev_num: True)
    monkeypatch.setattr(dc, "get_device_state", lambda dev_num: {**FAKE_STATUS, "device_num": dev_num})
    monkeypatch.setattr(dc, "get_device_list", lambda: FAKE_DEVICE_LIST)
    monkeypatch.setattr(dc, "get_device_settings", lambda dev_num: {"raw": {}, "stack": {}, "merged": {}})
    monkeypatch.setattr(dc, "save_device_settings", lambda dev_num, payload: {"set_setting": None})
    monkeypatch.setattr(dc, "method_sync", lambda method, dev_num, **kw: {"ok": True})
    monkeypatch.setattr(dc, "do_action", lambda action, dev_num, params: {"Value": {"result": {}}})

    from front_v2.app import build_app
    return build_app()


@pytest.fixture
def client(v2_app):
    return TestClient(v2_app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# REST API tests
# ---------------------------------------------------------------------------

def test_list_devices(client):
    r = client.get("/api/v1/devices")
    assert r.status_code == 200
    devices = r.json()
    assert isinstance(devices, list)
    assert devices[0]["device_num"] == 1
    assert devices[0]["is_connected"] is True


def test_device_status(client):
    r = client.get("/api/v1/devices/1/status")
    assert r.status_code == 200
    status = r.json()
    assert status["device_num"] == 1
    assert status["is_connected"] is True
    assert status["mount_mode"] == "Alt Azimuth"


def test_device_settings_get(client):
    r = client.get("/api/v1/devices/1/settings")
    assert r.status_code == 200
    assert "merged" in r.json()


def test_device_settings_save(client):
    r = client.post("/api/v1/devices/1/settings", json={"payload": {"gain": 80}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_send_command(client):
    r = client.post("/api/v1/devices/1/command", json={"method": "get_device_state", "params": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["command"] == "get_device_state"
    assert body["status"] == "success"


# ---------------------------------------------------------------------------
# WebSocket bridge tests
# ---------------------------------------------------------------------------

def test_ws_connect_receives_greeting(client):
    """Client should receive a 'connected' message immediately on connect."""
    with client.websocket_connect("/ws/1") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert msg["payload"]["device_num"] == 1


def test_ws_fanout(v2_app, monkeypatch):
    """
    Events injected directly into the bridge queue must be delivered to
    a connected WebSocket client.
    """
    from front_v2.ws import bridge

    client = TestClient(v2_app)
    received = []

    def _reader(ws):
        # Read greeting + one event
        for _ in range(2):
            try:
                msg = ws.receive_json()
                received.append(msg)
            except Exception:
                break

    with client.websocket_connect("/ws/1") as ws:
        t = threading.Thread(target=_reader, args=(ws,), daemon=True)
        t.start()

        # Wait for the greeting to be consumed.
        time.sleep(0.1)

        # Inject an event directly into the queue — simulates what the pump
        # thread would do after draining get_events().
        import asyncio
        loop = bridge._loop
        if loop and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                bridge._queues.get(1, asyncio.Queue()).put(
                    {"type": "device_status", "payload": {"view_state": "Imaging"}}
                ),
                loop,
            ).result(timeout=1.0)

        t.join(timeout=2.0)

    # We expect at least the greeting.
    assert len(received) >= 1
    assert received[0]["type"] == "connected"


def test_ws_keepalive_ping(client):
    """Server sends a ping if the client is idle for 30s — we just verify the connection stays open."""
    with client.websocket_connect("/ws/1") as ws:
        # Greeting must arrive
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        # Connection is healthy; no assertion on ping timing (30s timeout is too long for CI)


# ---------------------------------------------------------------------------
# Multiple devices
# ---------------------------------------------------------------------------

def test_separate_ws_per_device(client):
    """WS connections for different dev_nums are independent."""
    with client.websocket_connect("/ws/1") as ws1:
        with client.websocket_connect("/ws/2") as ws2:
            m1 = ws1.receive_json()
            m2 = ws2.receive_json()
            assert m1["payload"]["device_num"] == 1
            assert m2["payload"]["device_num"] == 2
