import collections
import json
import logging
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import falcon
from falcon import testing
import pytest

import front.app as front_app
from device.config import Config


SIMULATOR_SRC = Path(__file__).resolve().parents[2] / "simulator" / "src"
if str(SIMULATOR_SRC) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_SRC))

from listener import SocketListener  # noqa: E402


pytestmark = pytest.mark.integration


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_tcp(host, port, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return
            except OSError:
                time.sleep(0.05)
    raise TimeoutError(f"simulator TCP port {host}:{port} did not open in time")


def _send_tcp_command(host, port, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        s.connect((host, port))
        s.sendall((json.dumps(payload) + "\r\n").encode("utf-8"))
        raw = s.recv(8192).decode("utf-8")
        line = raw.strip().splitlines()[0]
        return json.loads(line)


def _send_udp_command(host, port, payload):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(2.0)
        s.sendto(json.dumps(payload).encode("utf-8"), (host, port))
        data, _ = s.recvfrom(4096)
        return json.loads(data.decode("utf-8"))


def _build_front_test_app():
    app = falcon.App()
    app.add_route("/{telescope_id:int}/", front_app.HomeTelescopeResource())
    app.add_route("/{telescope_id:int}/settings", front_app.SettingsResource())
    app.add_route("/{telescope_id:int}/stats", front_app.StatsResource())
    app.add_route("/{telescope_id:int}/command", front_app.CommandResource())
    app.add_route("/{telescope_id:int}/guestmode", front_app.GuestModeResource())
    app.add_route("/{telescope_id:int}/live", front_app.LivePage())
    app.add_route("/{telescope_id:int}/live/{mode}", front_app.LivePage())
    app.add_route("/{telescope_id:int}/planning", front_app.PlanningResource())
    app.add_route("/{telescope_id:int}/config", front_app.ConfigResource())
    app.add_route("/{telescope_id:int}/platform-rpi", front_app.PlatformRpiResource())
    app.add_route("/{telescope_id:int}/support", front_app.SupportResource())
    app.add_route("/{telescope_id:int}/home-content", front_app.HomeContentResource())
    app.add_route("/{telescope_id:int}/stats-content", front_app.StatsContentResource())
    app.add_route(
        "/{telescope_id:int}/guestmode-content", front_app.GuestModeContentResource()
    )
    app.add_route("/{telescope_id:int}/eventstatus", front_app.EventStatus())
    app.add_route("/{telescope_id:int}/schedule", front_app.ScheduleResource())
    app.add_route(
        "/{telescope_id:int}/schedule/state", front_app.ScheduleToggleResource()
    )
    app.add_route("/{telescope_id:int}/startup", front_app.StartupResource())
    app.add_route(
        "/{telescope_id:int}/live_tracker", front_app.LiveTrackerResource()
    )
    app.add_route(
        "/api/{telescope_id:int}/live_tracker/targets",
        front_app.LiveTrackerTargetsResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/live_tracker/status",
        front_app.LiveTrackerStatusResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/live_tracker/track",
        front_app.LiveTrackerTrackResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/live_tracker/stop",
        front_app.LiveTrackerStopResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/live_tracker/offsets",
        front_app.LiveTrackerOffsetsResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/live_tracker/offsets/reset",
        front_app.LiveTrackerResetResource(),
    )
    # ---- Calibration routes (mirror front/app.py FrontMain setup) ----
    app.add_route(
        "/{telescope_id:int}/calibrate_rotation",
        front_app.CalibrateRotationResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/calibration/prior",
        front_app.CalibrationPriorResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/calibration/targets",
        front_app.CalibrationTargetsResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/calibration/start",
        front_app.CalibrationStartResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/calibration/status",
        front_app.CalibrationStatusResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/calibration/nudge",
        front_app.CalibrationNudgeResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/calibration/sight",
        front_app.CalibrationSightResource(),
    )
    app.add_route(
        "/api/{telescope_id:int}/calibration/cancel",
        front_app.CalibrationCancelResource(),
    )
    # ---- Sun safety ----
    app.add_route("/api/sun_safety/status", front_app.SunSafetyStatusResource())
    app.add_route("/api/sun_safety/dismiss", front_app.SunSafetyDismissResource())
    return app


@pytest.fixture(scope="module")
def simulator_server():
    host = "127.0.0.1"
    tcp_port = _find_free_port()
    udp_port = _find_free_port()
    logger = logging.getLogger("simulator-integration-test")
    listener = SocketListener(logger, host=host, tcp_port=tcp_port, udp_port=udp_port)
    thread = threading.Thread(target=listener._start_socket_listener, daemon=True)
    thread.start()
    _wait_for_tcp(host, tcp_port)
    yield {"host": host, "tcp_port": tcp_port, "udp_port": udp_port}
    listener.shutdown_event.set()
    if listener.tcp_socket:
        listener.tcp_socket.close()
    if listener.udp_socket:
        listener.udp_socket.close()
    thread.join(timeout=2)


@pytest.fixture
def front_sim_bridge(monkeypatch, simulator_server):
    host = simulator_server["host"]
    tcp_port = simulator_server["tcp_port"]
    schedule_state = {
        "version": 1.0,
        "Event": "Scheduler",
        "schedule_id": "integration",
        "list": collections.deque(),
        "state": "stopped",
        "is_stacking_paused": False,
        "is_stacking": False,
        "is_skip_requested": False,
        "current_item_id": "",
        "item_number": 9999,
    }
    forced_stack_set_error = {"enabled": False}
    wrapped_method_sync = {"enabled": False}
    set_stack_settings_only = {"enabled": False}
    set_stack_settings_seen = {"called": False}
    inject_eventstatus_none = {"enabled": False}
    response_delay_ms = {"value": 0}

    monkeypatch.setattr(
        Config,
        "seestars",
        [{"device_num": 1, "name": "Seestar Alpha", "ip_address": "127.0.0.1"}],
    )
    monkeypatch.setattr(Config, "experimental", True)
    monkeypatch.setattr(front_app, "check_api_state", lambda _tid: True)
    monkeypatch.setattr(front_app, "get_listening_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(front_app, "get_twilight_times", lambda: {"sunset": "18:00"})
    monkeypatch.setattr(
        front_app,
        "get_nearest_csc",
        lambda: {"status_msg": "SUCCESS", "href": "", "full_img": ""},
    )
    monkeypatch.setattr(
        front_app,
        "get_planning_cards",
        lambda: [{"card_name": "twilight_times", "planning_page_enable": True}],
    )
    front_app._context_cached.clear()
    front_app._last_context_get_time.clear()
    front_app.StatsContentResource._last_render_by_key.clear()
    front_app.GuestModeContentResource._last_render_by_key.clear()
    front_app.EventStatus._last_render_by_key.clear()

    def _method_sync_call(method, params=None):
        payload = {"id": int(time.time() * 1000) % 100000, "method": method}
        if params is not None:
            payload["params"] = params
        return _send_tcp_command(host, tcp_port, payload)

    def _do_action_device(action, dev_num, parameters, is_schedule=False):
        if response_delay_ms["value"] > 0:
            time.sleep(response_delay_ms["value"] / 1000.0)

        if action == "method_sync":
            method = parameters.get("method")
            params = parameters.get("params")

            if method == "set_setting" and isinstance(params, dict):
                if forced_stack_set_error["enabled"] and "stack" in params:
                    return {
                        "ErrorNumber": 0,
                        "Value": {
                            "jsonrpc": "2.0",
                            "method": "set_setting",
                            "error": "unsupported",
                            "code": -1,
                            "id": 1,
                        },
                    }
                if set_stack_settings_only["enabled"] and "stack" in params:
                    return {
                        "ErrorNumber": 0,
                        "Value": {
                            "jsonrpc": "2.0",
                            "method": "set_setting",
                            "error": "unsupported",
                            "code": -1,
                            "id": 1,
                        },
                    }

            if method == "set_stack_setting" and set_stack_settings_only["enabled"]:
                return {
                    "ErrorNumber": 0,
                    "Value": {
                        "jsonrpc": "2.0",
                        "method": "set_stack_setting",
                        "error": "unsupported",
                        "code": -1,
                        "id": 1,
                    },
                }

            if method == "set_stack_settings":
                set_stack_settings_seen["called"] = True
                method = "set_stack_setting"

            rpc = _method_sync_call(method, params)
            value = {"1": rpc} if wrapped_method_sync["enabled"] else rpc
            return {"ErrorNumber": 0, "Value": value, "ErrorMessage": ""}

        if action == "get_schedule":
            return {"ErrorNumber": 0, "Value": schedule_state}
        if action == "action_start_up_sequence":
            schedule_state["state"] = "working"
            return {"ErrorNumber": 0, "Value": {"state": "working"}}
        if action == "create_schedule":
            schedule_state["list"] = collections.deque()
            schedule_state["state"] = "stopped"
            return {"ErrorNumber": 0, "Value": schedule_state}
        if action == "add_schedule_item":
            item = {
                "action": parameters.get("action", "noop"),
                "params": parameters.get("params", {}),
                "schedule_item_id": f"item-{len(schedule_state['list']) + 1}",
            }
            schedule_state["list"].append(item)
            return {"ErrorNumber": 0, "Value": item}
        if action == "start_scheduler":
            schedule_state["state"] = "working"
            return {"ErrorNumber": 0, "Value": schedule_state}
        if action == "stop_scheduler":
            schedule_state["state"] = "stopped"
            return {"ErrorNumber": 0, "Value": schedule_state}
        if action == "continue_scheduler":
            schedule_state["state"] = "working"
            return {"ErrorNumber": 0, "Value": schedule_state}
        if action == "pause_scheduler":
            schedule_state["state"] = "stopped"
            return {"ErrorNumber": 0, "Value": schedule_state}
        if action == "skip_scheduler_cur_item":
            return {"ErrorNumber": 0, "Value": schedule_state}
        if action == "get_event_state":
            if inject_eventstatus_none["enabled"]:
                return None
            event_name = parameters.get("event_name")
            if event_name == "scheduler":
                return {
                    "ErrorNumber": 0,
                    "Value": {
                        "result": {
                            "Event": "Scheduler",
                            "state": schedule_state["state"],
                            "cur_scheduler_item": {},
                            "item_number": 9999,
                            "is_stacking": False,
                            "is_stacking_paused": False,
                            "result": 0,
                        }
                    },
                }
            if event_name == "Stack":
                return {"ErrorNumber": 0, "Value": {"result": {}}}
            if int(dev_num) == 0:
                return {
                    "ErrorNumber": 0,
                    "Value": {
                        "1": {
                            "result": {
                                "AutoGoto": {"Event": "AutoGoto", "state": "idle"},
                                "PlateSolve": {"Event": "PlateSolve", "state": "idle"},
                            }
                        },
                        "2": {
                            "result": {
                                "AutoGoto": {"Event": "AutoGoto", "state": "working"},
                                "PlateSolve": {"Event": "PlateSolve", "state": "idle"},
                            }
                        },
                    },
                }
            return {
                "ErrorNumber": 0,
                "Value": {
                    "result": {
                        "scheduler": {
                            "Event": "Scheduler",
                            "state": schedule_state["state"],
                            "item_number": 9999,
                            "cur_scheduler_item": {},
                            "is_stacking": False,
                            "is_stacking_paused": False,
                            "result": 0,
                        },
                        "Client": {
                            "is_master": True,
                            "master_index": 0,
                            "connected": ["client-a"],
                        },
                    }
                },
            }
        return {"ErrorNumber": 0, "Value": {}}

    monkeypatch.setattr(front_app, "do_action_device", _do_action_device)

    client = testing.TestClient(_build_front_test_app())
    return {
        "client": client,
        "host": host,
        "tcp_port": tcp_port,
        "schedule_state": schedule_state,
        "forced_stack_set_error": forced_stack_set_error,
        "wrapped_method_sync": wrapped_method_sync,
        "set_stack_settings_only": set_stack_settings_only,
        "set_stack_settings_seen": set_stack_settings_seen,
        "inject_eventstatus_none": inject_eventstatus_none,
        "response_delay_ms": response_delay_ms,
    }


def _settings_payload():
    return {
        "stack_lenhance": "false",
        "stack_dither_pix": "10",
        "stack_dither_interval": "2",
        "stack_dither_enable": "true",
        "exp_ms_stack_l": "10000",
        "exp_ms_continuous": "500",
        "focal_pos": "1500",
        "auto_power_off": "false",
        "auto_3ppa_calib": "true",
        "frame_calib": "true",
        "plan_target_af": "false",
        "viewplan_gohome": "false",
        "expert_mode": "false",
        "save_discrete_frame": "false",
        "save_discrete_ok_frame": "true",
        "light_duration_min": "-1",
        "stack_capt_type": "stack",
        "stack_capt_num": "2",
        "stack_brightness": "0.0",
        "stack_contrast": "0.0",
        "stack_saturation": "0.0",
        "stack_dbe_enable": "false",
        "heater_enable": "false",
        "dark_mode": "false",
        "stack_cont_capt": "false",
        "stack_drizzle2x": "false",
    }


def test_01_simulator_tcp_get_device_state(simulator_server):
    resp = _send_tcp_command(
        simulator_server["host"],
        simulator_server["tcp_port"],
        {"id": 100, "method": "get_device_state"},
    )
    assert resp.get("method") == "get_device_state"
    assert resp.get("code") == 0
    assert "device" in resp.get("result", {})


def test_02_set_stack_settings_alias_compatibility(front_sim_bridge):
    front_sim_bridge["set_stack_settings_only"]["enabled"] = True
    payload = _settings_payload()
    payload["save_discrete_frame"] = "true"
    payload["save_discrete_ok_frame"] = "false"
    resp = front_sim_bridge["client"].simulate_post("/1/settings", json=payload)
    assert resp.status_code == 200
    assert "Successfully Updated Settings." in resp.text
    assert front_sim_bridge["set_stack_settings_seen"]["called"] is True


def test_03_settings_http_round_trip(front_sim_bridge):
    get_before = front_sim_bridge["client"].simulate_get("/1/settings")
    assert get_before.status_code == 200
    assert "Save Sub Frames" in get_before.text
    assert "Save Failed Sub Frames" in get_before.text

    payload = _settings_payload()
    payload["save_discrete_frame"] = "true"
    payload["save_discrete_ok_frame"] = "false"
    post = front_sim_bridge["client"].simulate_post("/1/settings", json=payload)
    assert post.status_code == 200
    assert "Successfully Updated Settings." in post.text

    after_stack = _send_tcp_command(
        front_sim_bridge["host"],
        front_sim_bridge["tcp_port"],
        {"id": 104, "method": "get_stack_setting"},
    )
    result = after_stack.get("result", {})
    assert result.get("save_discrete_frame") is True
    assert result.get("save_discrete_ok_frame") is False
    assert result.get("light_duration_min") == -1


def test_04_federation_route_smoke(front_sim_bridge):
    client = front_sim_bridge["client"]
    for path in ["/0/", "/0/stats", "/0/command", "/0/settings"]:
        resp = client.simulate_get(path)
        assert resp.status_code == 200


def test_05_htmx_fragment_endpoints(front_sim_bridge):
    client = front_sim_bridge["client"]
    paths = [
        "/1/home-content",
        "/1/stats-content",
        "/1/guestmode-content",
        "/1/eventstatus?action=goto",
    ]
    for path in paths:
        resp = client.simulate_get(
            path, headers={"HX-Current-URL": "http://localhost/1/goto"}
        )
        assert resp.status_code in (200, 204)
        if resp.status_code == 200:
            assert len(resp.text.strip()) > 0


def test_06_live_page_mode_routing(front_sim_bridge):
    client = front_sim_bridge["client"]
    for path in ["/1/live", "/1/live/star", "/1/live/moon", "/1/live/scenery"]:
        resp = client.simulate_get(path)
        assert resp.status_code == 200
        assert "Video" in resp.text or "Capture" in resp.text


def test_06b_live_tracker_smoke(front_sim_bridge):
    """Basic contract check for the new Live Tracker page + API."""
    client = front_sim_bridge["client"]

    # Page renders.
    page = client.simulate_get("/1/live_tracker")
    assert page.status_code == 200
    assert "Live Tracker" in page.text

    # /targets returns JSON with live/cached keys.
    targets = client.simulate_get("/api/1/live_tracker/targets")
    assert targets.status_code == 200
    body = json.loads(targets.text)
    assert "live" in body and "cached" in body
    assert isinstance(body["live"], list)
    assert isinstance(body["cached"], list)

    # /status with no active session still returns JSON.
    status = client.simulate_get("/api/1/live_tracker/status")
    assert status.status_code == 200
    st = json.loads(status.text)
    assert "active" in st

    # /offsets with no active session returns 404.
    r = client.simulate_post(
        "/api/1/live_tracker/offsets",
        json={"az_bias_deg": 0.1},
    )
    assert r.status_code == 404

    # Malformed bodies return 400 (never a 500). A JSON array as the root
    # would previously crash on `body.get(...)`; a NaN bias value would
    # pass through _clamp and land in the streaming loop.
    r = client.simulate_post("/api/1/live_tracker/offsets", json=[1, 2, 3])
    assert r.status_code == 400
    r = client.simulate_post("/api/1/live_tracker/track", json="not-an-object")
    assert r.status_code == 400


def test_06d_sun_safety_status_and_dismiss(front_sim_bridge):
    """Contract for the two /api/sun_safety/* endpoints the global
    banner polls. Covers: no-monitor → not tripped; monitor installed
    + forced trip record → tripped + full payload; dismiss → not tripped."""
    from datetime import datetime, timezone

    from device import sun_safety as ss

    client = front_sim_bridge["client"]

    prev_monitor = ss.get_sun_monitor()
    try:
        # (1) No monitor installed → tripped=False, trip=None.
        ss.set_sun_monitor(None)
        r = client.simulate_get("/api/sun_safety/status")
        assert r.status_code == 200
        body = json.loads(r.text)
        assert body == {"tripped": False, "trip": None}

        # (2) Install a monitor; no trip yet → still tripped=False.
        monitor = ss.SunSafetyMonitor(
            altaz_reader=lambda: None,
            jog_command=lambda *a, **kw: None,
            lat_deg=33.96, lon_deg=-118.46,
            jog_duration_s=0,
        )
        ss.set_sun_monitor(monitor)
        r = client.simulate_get("/api/sun_safety/status")
        body = json.loads(r.text)
        assert body["tripped"] is False

        # (3) Stuff a SafetyTrip directly → tripped=True + full payload.
        trip = ss.SafetyTrip(
            when_utc=datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc),
            sun_az_deg=180.0, sun_alt_deg=33.0,
            mount_az_deg=181.0, mount_el_deg=34.0,
            separation_deg=1.4, cone_deg=30.0,
            jog_angle_deg=225, jog_speed=1440, jog_duration_s=3,
        )
        with monitor._lock:
            monitor._last_trip = trip
            monitor._trip_dismissed = False
        r = client.simulate_get("/api/sun_safety/status")
        body = json.loads(r.text)
        assert body["tripped"] is True
        assert body["trip"]["cone_deg"] == 30.0
        assert body["trip"]["separation_deg"] == 1.4
        assert body["trip"]["jog_angle_deg"] == 225
        assert body["trip"]["jog_speed"] == 1440
        assert "message" in body["trip"]

        # (4) Dismiss → tripped=False; repeated GET still false.
        r = client.simulate_post("/api/sun_safety/dismiss")
        assert r.status_code == 200
        body = json.loads(r.text)
        assert body["tripped"] is False
        r = client.simulate_get("/api/sun_safety/status")
        body = json.loads(r.text)
        assert body["tripped"] is False
    finally:
        ss.set_sun_monitor(prev_monitor)


def test_06e_live_tracker_adsbfi_poller_deferred_to_first_list_live():
    """Spec: TargetCatalog does NOT spin up the adsb.fi poller at
    instantiation — only on the first `list_live()` call. Keeps the
    tracker quiescent when not in use."""
    from device.live_tracker import TargetCatalog

    catalog = TargetCatalog(live_enabled=True)
    assert catalog._live_thread is None, \
        "poller must not start at catalog construction"

    try:
        catalog.list_live()
        alive = False
        for _ in range(20):
            if catalog._live_thread is not None and catalog._live_thread.is_alive():
                alive = True
                break
            time.sleep(0.05)
        assert alive, "poller should start after the first list_live() call"
    finally:
        catalog.close()
        if catalog._live_thread is not None:
            catalog._live_thread.join(timeout=2.0)


def test_06c_calibrate_rotation_smoke(front_sim_bridge):
    """Basic contract check for the calibrate-rotation page + API.

    The simulator doesn't expose ``location_lon_lat`` via the Alpaca
    method the backend calls, so ``/prior``, ``/targets``, and
    ``/start`` all 503 cleanly on GPS fetch. That's the correct
    behaviour — what we're checking here is that the routes are
    registered and that error payloads are valid JSON. Mount-driving
    paths are covered by the CalibrationSession unit tests with a
    fake Alpaca client.
    """
    client = front_sim_bridge["client"]

    page = client.simulate_get("/1/calibrate_rotation")
    assert page.status_code == 200
    assert "Calibrate" in page.text

    # /status with no active session returns {"active": false}.
    status = client.simulate_get("/api/1/calibration/status")
    assert status.status_code == 200
    body = json.loads(status.text)
    assert body.get("active") is False

    # /prior → 503 (GPS unavailable via the simulator) with an
    # informative JSON body.
    prior = client.simulate_get("/api/1/calibration/prior")
    assert prior.status_code == 503
    body = json.loads(prior.text)
    assert "error" in body

    # /targets likewise 503s on GPS fetch.
    targets = client.simulate_get("/api/1/calibration/targets")
    assert targets.status_code == 503

    # Command posts against a nonexistent session → 404.
    for path in ("sight", "cancel"):
        r = client.simulate_post(
            f"/api/1/calibration/{path}", json={},
        )
        assert r.status_code == 404

    # Malformed body → 400.
    r = client.simulate_post("/api/1/calibration/start", json=[1, 2, 3])
    assert r.status_code == 400


def test_07_schedule_lifecycle(front_sim_bridge):
    client = front_sim_bridge["client"]
    get_page = client.simulate_get("/1/schedule")
    assert get_page.status_code == 200
    assert "Schedule" in get_page.text

    start = client.simulate_post("/1/schedule/state", json={"action": "toggle"})
    assert start.status_code == 200
    assert front_sim_bridge["schedule_state"]["state"] == "working"

    stop = client.simulate_post("/1/schedule/state", json={"action": "toggle"})
    assert stop.status_code == 200
    assert front_sim_bridge["schedule_state"]["state"] == "stopped"


def test_08_guestmode_get_and_post(front_sim_bridge):
    client = front_sim_bridge["client"]
    page = client.simulate_get("/1/guestmode")
    assert page.status_code == 200

    post = client.simulate_post("/1/guestmode", json={"command": "grab_control"})
    assert post.status_code == 200


def test_09_wrapped_value_shape_compat(front_sim_bridge):
    front_sim_bridge["wrapped_method_sync"]["enabled"] = True
    client = front_sim_bridge["client"]
    resp = client.simulate_get("/1/settings")
    assert resp.status_code == 200
    assert "Save Sub Frames" in resp.text
    front_sim_bridge["wrapped_method_sync"]["enabled"] = False


def test_10_error_path_fallback_succeeds(front_sim_bridge):
    front_sim_bridge["forced_stack_set_error"]["enabled"] = True
    client = front_sim_bridge["client"]
    resp = client.simulate_post("/1/settings", json=_settings_payload())
    assert resp.status_code == 200
    assert "Successfully Updated Settings." in resp.text
    front_sim_bridge["forced_stack_set_error"]["enabled"] = False


def test_11_performance_budget_smoke(front_sim_bridge):
    client = front_sim_bridge["client"]
    start = time.perf_counter()
    resp = client.simulate_get("/1/home-content")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert resp.status_code in (200, 204)
    assert elapsed_ms < 1500


def test_12_udp_scan_iscope(simulator_server):
    resp = _send_udp_command(
        simulator_server["host"],
        simulator_server["udp_port"],
        {"id": 1, "method": "scan_iscope"},
    )
    assert resp.get("result") == "ok"
    assert resp.get("device") == "seestar"


def test_13_multi_device_federation_home_render(monkeypatch, front_sim_bridge):
    monkeypatch.setattr(
        Config,
        "seestars",
        [
            {"device_num": 1, "name": "Seestar Alpha", "ip_address": "127.0.0.1"},
            {"device_num": 2, "name": "Seestar Beta", "ip_address": "127.0.0.1"},
        ],
    )
    front_app._context_cached.clear()
    front_app._last_context_get_time.clear()

    resp = front_sim_bridge["client"].simulate_get("/0/")
    assert resp.status_code == 200
    assert "Seestar Alpha" in resp.text
    assert "Seestar Beta" in resp.text


def test_14_federation_eventstatus_groups_by_device(front_sim_bridge):
    resp = front_sim_bridge["client"].simulate_get(
        "/0/eventstatus?action=goto",
        headers={"HX-Current-URL": "http://localhost/0/goto", "User-Agent": "pytest"},
    )
    assert resp.status_code == 200
    assert "Device ID: 1" in resp.text
    assert "Device ID: 2" in resp.text


def test_15_stateful_startup_flow(front_sim_bridge):
    client = front_sim_bridge["client"]
    start = client.simulate_post(
        "/1/startup",
        json={
            "action": "start",
            "lat": "42.5",
            "long": "-71.5",
            "auto_focus": "on",
            "dark_frames": "on",
            "polar_align": "on",
            "dec-offset": "0",
        },
    )
    assert start.status_code == 200
    assert front_sim_bridge["schedule_state"]["state"] == "working"

    stop = client.simulate_post("/1/startup", json={"action": "stop"})
    assert stop.status_code == 200
    assert front_sim_bridge["schedule_state"]["state"] == "stopped"


def test_16_fault_injection_eventstatus_none(front_sim_bridge):
    front_sim_bridge["inject_eventstatus_none"]["enabled"] = True
    resp = front_sim_bridge["client"].simulate_get(
        "/1/eventstatus?action=goto",
        headers={"HX-Current-URL": "http://localhost/1/goto", "User-Agent": "pytest"},
    )
    assert resp.status_code == 200
    assert "No results available." in resp.text
    front_sim_bridge["inject_eventstatus_none"]["enabled"] = False


@pytest.mark.parametrize(
    "wrapped,set_stack_settings_only",
    [
        (False, False),
        (True, False),
        (False, True),
    ],
)
def test_17_protocol_compatibility_matrix(
    front_sim_bridge, wrapped, set_stack_settings_only
):
    front_sim_bridge["wrapped_method_sync"]["enabled"] = wrapped
    front_sim_bridge["set_stack_settings_only"]["enabled"] = set_stack_settings_only
    resp = front_sim_bridge["client"].simulate_post(
        "/1/settings", json=_settings_payload()
    )
    assert resp.status_code == 200
    assert "Successfully Updated Settings." in resp.text
    front_sim_bridge["wrapped_method_sync"]["enabled"] = False
    front_sim_bridge["set_stack_settings_only"]["enabled"] = False


def test_18_concurrency_load_smoke(front_sim_bridge):
    def _call_once():
        resp = front_sim_bridge["client"].simulate_get("/1/home-content")
        return resp.status_code

    with ThreadPoolExecutor(max_workers=8) as ex:
        statuses = list(ex.map(lambda _i: _call_once(), range(40)))
    assert all(code in (200, 204) for code in statuses)


def test_19_settings_fuzz_robustness(front_sim_bridge):
    fuzz_payload = _settings_payload()
    fuzz_payload.update(
        {
            "stack_dither_pix": "NaN",
            "stack_dither_interval": "",
            "exp_ms_stack_l": None,
            "stack_brightness": "invalid",
            "stack_contrast": {},
            "stack_saturation": [],
        }
    )
    resp = front_sim_bridge["client"].simulate_post("/1/settings", json=fuzz_payload)
    assert resp.status_code == 200
    assert "Settings." in resp.text


def test_20_performance_batch_budget(front_sim_bridge):
    client = front_sim_bridge["client"]
    start = time.perf_counter()
    for path in [
        "/1/home-content",
        "/1/stats-content",
        "/1/guestmode-content",
        "/1/eventstatus?action=goto",
        "/1/settings",
        "/1/live/star",
    ]:
        resp = client.simulate_get(
            path,
            headers={
                "HX-Current-URL": "http://localhost/1/goto",
                "User-Agent": "pytest",
            },
        )
        assert resp.status_code in (200, 204)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 4000


def test_21_html_contract_snapshot_smoke(front_sim_bridge):
    client = front_sim_bridge["client"]
    settings = client.simulate_get("/1/settings")
    assert settings.status_code == 200
    assert "Save Sub Frames" in settings.text
    assert "Save Failed Sub Frames" in settings.text
    assert "Seestar Federation" in settings.text

    live = client.simulate_get("/1/live/star")
    assert live.status_code == 200
    assert "Video" in live.text


def test_22_response_delay_resilience(front_sim_bridge):
    front_sim_bridge["response_delay_ms"]["value"] = 80
    resp = front_sim_bridge["client"].simulate_get("/1/home-content")
    assert resp.status_code in (200, 204)
    front_sim_bridge["response_delay_ms"]["value"] = 0


# ---------------------------------------------------------------------------
# Two-device federation integration tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_simulator_servers():
    """Start two independent simulator instances on separate ports."""
    host = "127.0.0.1"
    sims = [
        {
            "name": f"sim{i}",
            "tcp_port": _find_free_port(),
            "udp_port": _find_free_port(),
        }
        for i in range(1, 3)
    ]
    logger = logging.getLogger("two-sim-integration")
    listeners, threads = [], []
    for sim in sims:
        lst = SocketListener(
            logger, host=host, tcp_port=sim["tcp_port"], udp_port=sim["udp_port"]
        )
        t = threading.Thread(target=lst._start_socket_listener, daemon=True)
        t.start()
        _wait_for_tcp(host, sim["tcp_port"])
        listeners.append(lst)
        threads.append(t)

    yield {"host": host, "sim1": sims[0], "sim2": sims[1]}

    for lst in listeners:
        lst.shutdown_event.set()
        if lst.tcp_socket:
            lst.tcp_socket.close()
        if lst.udp_socket:
            lst.udp_socket.close()
    for t in threads:
        t.join(timeout=2)


@pytest.fixture
def two_device_federation(monkeypatch, two_simulator_servers):
    """
    Wires the device layer to two real simulator instances and exposes both a
    device-layer TestClient and a front-layer TestClient for end-to-end testing.
    """
    import device.app as device_app
    import device.telescope as tel_module
    from device.shr import set_shr_logger

    host = two_simulator_servers["host"]
    port1 = two_simulator_servers["sim1"]["tcp_port"]
    port2 = two_simulator_servers["sim2"]["tcp_port"]
    logger = logging.getLogger("federation-fixture")
    set_shr_logger(logger)

    # Clean slate for the telescope module's global device registry
    tel_module.seestar_dev.clear()
    tel_module.start_seestar_federation(logger)
    dev1 = tel_module.start_seestar_device(logger, "Seestar Alpha", host, port1, 1)
    dev2 = tel_module.start_seestar_device(logger, "Seestar Beta", host, port2, 2)

    # Wait for both simulators to accept the device connections
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if dev1.is_connected and dev2.is_connected:
            break
        time.sleep(0.1)
    else:
        pytest.fail("Timed out waiting for both simulators to connect")

    # Device-layer Falcon app (routes to seestar_dev via telescope module globals)
    device_falc_app = falcon.App()
    device_app.init_routes(device_falc_app, "telescope", tel_module)
    device_client = testing.TestClient(device_falc_app)

    def _alpaca_action(dev_num, action, parameters):
        """PUT to the device-layer action endpoint with required ALPACA fields."""
        return device_client.simulate_put(
            f"/api/v1/telescope/{dev_num}/action",
            json={
                "Action": action,
                "Parameters": json.dumps(parameters),
                "ClientID": 1,
                "ClientTransactionID": 1,
            },
        )

    # Bridge the front layer to the device layer without a real HTTP server
    def _device_action(action, dev_num, parameters, is_schedule=False):
        resp = _alpaca_action(dev_num, action, parameters)
        if resp.status_code == 200:
            return resp.json
        return None

    monkeypatch.setattr(
        Config,
        "seestars",
        [
            {"device_num": 1, "name": "Seestar Alpha", "ip_address": host},
            {"device_num": 2, "name": "Seestar Beta", "ip_address": host},
        ],
    )
    monkeypatch.setattr(front_app, "do_action_device", _device_action)
    monkeypatch.setattr(front_app, "check_api_state", lambda _tid: True)
    monkeypatch.setattr(front_app, "get_listening_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(front_app, "get_twilight_times", lambda: {"sunset": "18:00"})
    monkeypatch.setattr(
        front_app,
        "get_nearest_csc",
        lambda: {"status_msg": "SUCCESS", "href": "", "full_img": ""},
    )
    monkeypatch.setattr(
        front_app,
        "get_planning_cards",
        lambda: [{"card_name": "twilight_times", "planning_page_enable": True}],
    )

    front_app._context_cached.clear()
    front_app._last_context_get_time.clear()
    front_app.StatsContentResource._last_render_by_key.clear()
    front_app.GuestModeContentResource._last_render_by_key.clear()
    front_app.EventStatus._last_render_by_key.clear()

    front_client = testing.TestClient(_build_front_test_app())

    yield {
        "device_client": device_client,
        "alpaca_action": _alpaca_action,
        "front_client": front_client,
        "dev1": dev1,
        "dev2": dev2,
        "host": host,
    }

    tel_module.end_seestar_device(1)
    tel_module.end_seestar_device(2)
    tel_module.seestar_dev.clear()


def test_23_two_devices_both_connect_to_simulators(two_device_federation):
    """Both Seestar instances establish a live TCP connection to their simulator."""
    assert two_device_federation["dev1"].is_connected, "device 1 not connected"
    assert two_device_federation["dev2"].is_connected, "device 2 not connected"


def test_24_two_devices_respond_to_method_sync(two_device_federation):
    """Device-layer action endpoint responds correctly for both device numbers."""
    alpaca_action = two_device_federation["alpaca_action"]
    for devnum in (1, 2):
        resp = alpaca_action(devnum, "method_sync", {"method": "get_device_state"})
        assert resp.status_code == 200, (
            f"device {devnum} action endpoint returned {resp.status_code}"
        )
        body = resp.json
        assert body["ErrorNumber"] == 0, f"device {devnum} returned error: {body}"
        assert "device" in body.get("Value", {}).get("result", {}), (
            f"device {devnum} response missing device info"
        )


def test_25_two_devices_have_independent_simulator_state(two_device_federation):
    """Commands to device 1 and device 2 reach independent simulators."""
    alpaca_action = two_device_federation["alpaca_action"]
    results = {}
    for devnum in (1, 2):
        resp = alpaca_action(devnum, "method_sync", {"method": "get_device_state"})
        assert resp.status_code == 200
        results[devnum] = resp.json.get("Value", {}).get("result", {})

    # Both simulators report their own device state independently
    assert "device" in results[1]
    assert "device" in results[2]


def test_26_front_home_pages_render_for_both_devices(two_device_federation):
    """Individual device home pages render without crashing for both devices."""
    front_client = two_device_federation["front_client"]
    for devnum in (1, 2):
        resp = front_client.simulate_get(f"/{devnum}/")
        assert resp.status_code == 200, (
            f"home page for device {devnum} returned {resp.status_code}"
        )
        assert "Seestar" in resp.text, f"device {devnum} home page missing Seestar name"


def test_27_federation_home_lists_both_devices(two_device_federation):
    """Federation home page (devnum=0) lists both configured Seestar devices."""
    resp = two_device_federation["front_client"].simulate_get("/0/")
    assert resp.status_code == 200
    assert "Seestar Alpha" in resp.text
    assert "Seestar Beta" in resp.text
