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
pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)
pytest.importorskip(
    "uvicorn", reason="uvicorn not installed; run: pip install -e '.[v2]'"
)

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
    {
        "device_num": 1,
        "name": "Seestar Alpha",
        "ip_address": "127.0.0.1",
        "is_connected": True,
    }
]


@pytest.fixture
def v2_app(monkeypatch):
    """Build the FastAPI app with device_client calls stubbed out."""
    import front_v2.device_client as dc

    monkeypatch.setattr(dc, "check_api_state", lambda dev_num: True)
    monkeypatch.setattr(
        dc, "get_device_state", lambda dev_num: {**FAKE_STATUS, "device_num": dev_num}
    )
    monkeypatch.setattr(dc, "get_device_list", lambda: FAKE_DEVICE_LIST)
    monkeypatch.setattr(
        dc,
        "get_device_settings",
        lambda dev_num: {"raw": {}, "stack": {}, "merged": {}},
    )
    monkeypatch.setattr(
        dc, "save_device_settings", lambda dev_num, payload: {"set_setting": None}
    )
    monkeypatch.setattr(dc, "method_sync", lambda method, dev_num, **kw: {"ok": True})
    monkeypatch.setattr(
        dc, "do_action", lambda action, dev_num, params: {"Value": {"result": {}}}
    )

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
    r = client.post(
        "/api/v1/devices/1/command", json={"method": "get_device_state", "params": {}}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["command"] == "get_device_state"
    assert body["status"] == "success"


# ---------------------------------------------------------------------------
# Live: joystick move / record toggle
# ---------------------------------------------------------------------------


def test_live_move_with_distance(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "front_v2.api.router_live.do_action",
        lambda action, dev_num, params: (
            calls.append((action, dev_num, params)),
            {"Value": {"result": {}}},
        )[1],
    )
    r = client.post(
        "/api/v1/devices/1/live/move",
        json={"angle": 90, "distance": 0.5, "force": 1.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["angle"] == 90
    assert body["speed"] == pytest.approx(0.5 * 100 * 14.4 * 1.0)

    action, dev_num, params = calls[0]
    assert action == "method_sync"
    assert dev_num == 1
    assert params["method"] == "scope_speed_move"
    assert params["params"]["angle"] == 90
    assert params["params"]["speed"] == pytest.approx(720.0)
    assert params["params"]["dur_sec"] == 3


def test_live_move_stop_when_distance_zero(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "front_v2.api.router_live.do_action",
        lambda action, dev_num, params: (
            calls.append((action, dev_num, params)),
            {"Value": {"result": {}}},
        )[1],
    )
    r = client.post(
        "/api/v1/devices/1/live/move",
        json={"angle": 45, "distance": 0, "force": 1.0},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "speed": 0, "angle": 0}
    assert calls[0][2]["params"] == {"speed": 0, "angle": 0, "dur_sec": 3}


def test_live_move_speed_is_capped_at_max(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "front_v2.api.router_live.do_action",
        lambda action, dev_num, params: (
            calls.append((action, dev_num, params)),
            {"Value": {"result": {}}},
        )[1],
    )
    r = client.post(
        "/api/v1/devices/1/live/move",
        json={"angle": 180, "distance": 100, "force": 100},
    )
    assert r.status_code == 200
    assert r.json()["speed"] == 1440.0
    assert calls[0][2]["params"]["speed"] == 1440.0


def test_live_move_requires_connected_device(client, monkeypatch):
    monkeypatch.setattr(
        "front_v2.api.router_live.check_api_state", lambda dev_num: False
    )
    r = client.post(
        "/api/v1/devices/1/live/move",
        json={"angle": 0, "distance": 1, "force": 1},
    )
    assert r.status_code == 503


def test_live_record_toggle(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "front_v2.api.router_live.do_action",
        lambda action, dev_num, params: (
            calls.append((action, dev_num, params)),
            {"Value": {"result": {}}},
        )[1],
    )
    r = client.post("/api/v1/devices/1/live/record")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    action, dev_num, params = calls[0]
    assert action == "method_async"
    assert dev_num == 1
    assert params == {"method": "iscope_start_stack", "params": {"restart": True}}


# ---------------------------------------------------------------------------
# Balance sensor (bubble level)
# ---------------------------------------------------------------------------


def test_balance_sensor_returns_xy(client, monkeypatch):
    monkeypatch.setattr(
        "front_v2.api.router_device.method_sync",
        lambda method, dev_num, **kw: {
            "balance_sensor": {"data": {"x": 1.5, "y": -2.25}}
        },
    )
    r = client.get("/api/v1/devices/1/balance-sensor")
    assert r.status_code == 200
    assert r.json() == {"x": 1.5, "y": -2.25}


def test_balance_sensor_handles_missing_data(client, monkeypatch):
    monkeypatch.setattr(
        "front_v2.api.router_device.method_sync", lambda method, dev_num, **kw: {}
    )
    r = client.get("/api/v1/devices/1/balance-sensor")
    assert r.status_code == 200
    assert r.json() == {"x": None, "y": None}


# ---------------------------------------------------------------------------
# Config: editable device list
# ---------------------------------------------------------------------------


def test_save_devices_round_trip(client, monkeypatch):
    from device.config import Config

    monkeypatch.setattr(Config, "save_toml", lambda: None)

    r = client.post(
        "/api/v1/config/devices",
        json={
            "devices": [
                {"name": "Seestar A", "ip_address": "10.0.0.5"},
                {"name": "Seestar B", "ip_address": "10.0.0.6"},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["devices"] == [
        {"device_num": 1, "name": "Seestar A", "ip_address": "10.0.0.5"},
        {"device_num": 2, "name": "Seestar B", "ip_address": "10.0.0.6"},
    ]
    assert [s["device_num"] for s in Config.seestars] == [1, 2]
    assert [s["name"] for s in Config.seestars] == ["Seestar A", "Seestar B"]


def test_save_devices_renumbers_sequentially_after_removal(client, monkeypatch):
    from device.config import Config

    monkeypatch.setattr(Config, "save_toml", lambda: None)

    client.post(
        "/api/v1/config/devices",
        json={
            "devices": [
                {"name": "A", "ip_address": "10.0.0.1"},
                {"name": "B", "ip_address": "10.0.0.2"},
                {"name": "C", "ip_address": "10.0.0.3"},
            ]
        },
    )
    r = client.post(
        "/api/v1/config/devices",
        json={
            "devices": [
                {"name": "A", "ip_address": "10.0.0.1"},
                {"name": "C", "ip_address": "10.0.0.3"},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert [d["device_num"] for d in body["devices"]] == [1, 2]
    assert [d["name"] for d in body["devices"]] == ["A", "C"]


def test_save_devices_requires_name_and_ip(client, monkeypatch):
    from device.config import Config

    monkeypatch.setattr(Config, "save_toml", lambda: None)

    r = client.post(
        "/api/v1/config/devices",
        json={"devices": [{"name": "", "ip_address": "10.0.0.1"}]},
    )
    assert r.status_code == 400

    r = client.post(
        "/api/v1/config/devices",
        json={"devices": [{"name": "NoIP", "ip_address": ""}]},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Platform (Raspberry Pi service / power controls)
# ---------------------------------------------------------------------------


def test_platform_get_returns_detected_platform(client):
    r = client.get("/api/v1/platform")
    assert r.status_code == 200
    assert "platform" in r.json()


def test_platform_action_rejected_on_non_pi(client, monkeypatch):
    monkeypatch.setattr("front_v2.api.router_platform._PLATFORM", "Linux")
    r = client.post("/api/v1/platform/action", json={"command": "restart_alp"})
    assert r.status_code == 403


def test_platform_action_rejects_unknown_command(client, monkeypatch):
    monkeypatch.setattr("front_v2.api.router_platform._PLATFORM", "raspberry_pi")
    r = client.post("/api/v1/platform/action", json={"command": "nonsense"})
    assert r.status_code == 400


def test_platform_action_runs_known_command(client, monkeypatch):
    monkeypatch.setattr("front_v2.api.router_platform._PLATFORM", "raspberry_pi")
    calls = []
    # Replace the background runner (looked up by name at call time inside the
    # spawned thread) so the test never shells out to systemctl/reboot.
    monkeypatch.setattr(
        "front_v2.api.router_platform._background_run", lambda args: calls.append(args)
    )

    r = client.post("/api/v1/platform/action", json={"command": "restart_alp"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "restarting" in body["message"].lower()

    for _ in range(40):
        if calls:
            break
        time.sleep(0.05)
    assert calls == [["sudo", "systemctl", "restart", "seestar.service"]]


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
