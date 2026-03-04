import json
import pytest
import front.app as front_app
from device.config import Config


class DummyReq:
    def __init__(self, host="localhost:5432", scheme="http"):
        self.host = host
        self.scheme = scheme
        self.relative_uri = "/1/live"


class DummyResp:
    def __init__(self):
        self.cookies = []

    def set_cookie(self, key, value, path="/"):
        self.cookies.append((key, value, path))

    def unset_cookie(self, key, path="/"):
        self.cookies = [c for c in self.cookies if c[0] != key]


class DummyHTMXReq(DummyReq):
    def __init__(
        self,
        host="localhost:5432",
        scheme="http",
        relative_uri="/1/",
        params=None,
        headers=None,
    ):
        super().__init__(host=host, scheme=scheme)
        self.relative_uri = relative_uri
        self._params = params or {}
        self._headers = headers or {}

    def get_param(self, key, default=None):
        return self._params.get(key, default)

    def get_header(self, key):
        return self._headers.get(key)

    def get_cookie_values(self, _key):
        return []


def _render_nav(partial_path):
    template = front_app.fetch_template("nav.html")
    telescopes = [
        {"device_num": 1, "name": "Seestar Alpha", "ip_address": "192.168.11.124"},
    ]
    context = {
        "root": "/1",
        "telescope": telescopes[0],
        "telescopes": telescopes,
        "partial_path": partial_path,
        "experimental": True,
        "platform": "raspberry_pi",
        "uitheme": "dark",
    }
    return template.render(**context)


def _minimal_context(partial_path, online=True):
    telescope = {
        "device_num": 1,
        "name": "Seestar Alpha",
        "ip_address": "192.168.11.124",
    }
    return {
        "telescope": telescope,
        "telescopes": [telescope],
        "root": "/1",
        "partial_path": partial_path,
        "online": online,
        "imager_root": "http://localhost:7556/1",
        "experimental": True,
        "confirm": False,
        "uitheme": "dark",
        "webui_text_color": None,
        "webui_font_family": None,
        "webui_font_url": None,
        "webui_link_color": None,
        "webui_accent_color": None,
        "client_master": True,
        "current_item": None,
        "current_stack": None,
        "platform": "raspberry_pi",
        "defgain": 80,
        "current_exp": None,
    }


def test_flash_and_get_messages_roundtrip():
    front_app.messages.clear()
    resp = DummyResp()
    front_app.flash(resp, "hello")

    assert resp.cookies == [("flash_cookie", "hello", "/")]
    assert front_app.get_messages() == ["hello"]
    assert front_app.get_messages() == []


def test_nav_shows_federation_option_on_home():
    html = _render_nav("")
    assert "Seestar Federation" in html
    assert 'href="/0/"' in html


def test_nav_shows_federation_option_for_supported_pages():
    partial_paths = [
        "command",
        "guestmode",
        "live",
        "planning",
        "config",
        "stats",
        "platform-rpi",
        "support",
    ]
    for path in partial_paths:
        html = _render_nav(path)
        assert "Seestar Federation" in html
        assert f'href="/0/{path}"' in html


def test_get_root_and_imager_root(monkeypatch):
    monkeypatch.setattr(
        Config,
        "seestars",
        [
            {"device_num": 1, "name": "A", "ip_address": "a.local"},
            {"device_num": 2, "name": "B", "ip_address": "b.local"},
        ],
    )
    monkeypatch.setattr(Config, "imgport", 7556)
    req = DummyReq(host="myhost:1234")

    assert front_app.get_root(0) == "/0"
    assert front_app.get_root(2) == "/2"
    assert front_app.get_imager_root(2, req) == "http://myhost:7556/2"


def test_get_imager_root_strips_incoming_port_and_preserves_scheme(monkeypatch):
    monkeypatch.setattr(
        Config,
        "seestars",
        [
            {"device_num": 2, "name": "B", "ip_address": "b.local"},
        ],
    )
    monkeypatch.setattr(Config, "imgport", 7556)
    req = DummyReq(host="securehost.example:8443", scheme="https")

    assert front_app.get_imager_root(2, req) == "https://securehost.example:7556/2"


def test_process_queue_dispatches_actions(monkeypatch):
    calls = []
    front_app.queue.clear()
    front_app.queue[1] = [
        {"Parameters": json.dumps({"action": "wait_for", "params": {"timer_sec": 5}})},
        {"Parameters": json.dumps({"action": "noop", "params": None})},
    ]
    monkeypatch.setattr(front_app, "check_api_state", lambda telescope_id: True)
    monkeypatch.setattr(
        front_app,
        "do_schedule_action_device",
        lambda action, params, telescope_id: (
            calls.append((action, params, telescope_id)) or {"ok": True}
        ),
    )

    front_app.process_queue(DummyResp(), 1)
    assert calls == [("wait_for", {"timer_sec": 5}, 1), ("noop", None, 1)]


def test_process_queue_offline_flashes_error(monkeypatch):
    monkeypatch.setattr(front_app, "check_api_state", lambda telescope_id: False)
    resp = DummyResp()
    front_app.process_queue(resp, 1)
    msgs = front_app.get_messages()
    assert any("API is Offline" in msg for msg in msgs)


def test_get_nearest_csc_uses_result_cache(monkeypatch):
    monkeypatch.setattr(Config, "init_lat", 42.0)
    monkeypatch.setattr(Config, "init_long", -71.0)
    front_app._nearest_csc_cache.clear()

    calls = {"count": 0}

    def fake_get_csc_sites_data():
        calls["count"] += 1
        return {
            "42": {
                "-71": [
                    {"id": "TEST", "lat": 42.0, "lng": -71.0},
                ]
            }
        }

    monkeypatch.setattr(front_app, "get_csc_sites_data", fake_get_csc_sites_data)

    first = front_app.get_nearest_csc()
    second = front_app.get_nearest_csc()

    assert first["status_msg"] == "SUCCESS"
    assert second["status_msg"] == "SUCCESS"
    assert first["href"] == "https://www.cleardarksky.com/c/TESTkey.html"
    assert calls["count"] == 1


def test_get_planning_cards_uses_file_mtime_cache(monkeypatch, tmp_path):
    planning_file = tmp_path / "planning.json"
    planning_file.write_text(
        json.dumps(
            [
                {
                    "card_name": "twilight_times",
                    "planning_page_enable": True,
                    "planning_page_collapsed": False,
                }
            ]
        )
    )

    original_json_load = front_app.json.load
    calls = {"count": 0}

    def counting_json_load(fp):
        calls["count"] += 1
        return original_json_load(fp)

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    monkeypatch.setattr(front_app.json, "load", counting_json_load)
    front_app._planning_cards_cache = None
    front_app._planning_cards_cache_mtime = None

    first = front_app.get_planning_cards()
    second = front_app.get_planning_cards()

    assert first[0]["card_name"] == "twilight_times"
    assert second[0]["card_name"] == "twilight_times"
    assert calls["count"] == 1


def test_update_planning_card_state_invalidates_cache(monkeypatch, tmp_path):
    planning_file = tmp_path / "planning.json"
    planning_file.write_text(
        json.dumps(
            [
                {
                    "card_name": "twilight_times",
                    "planning_page_enable": True,
                    "planning_page_collapsed": False,
                }
            ]
        )
    )

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    front_app._planning_cards_cache = None
    front_app._planning_cards_cache_mtime = None

    cards = front_app.get_planning_cards()
    assert cards[0]["planning_page_enable"] is True
    assert front_app._planning_cards_cache is not None

    front_app.update_planning_card_state(
        "twilight_times", "planning_page_enable", False
    )

    assert front_app._planning_cards_cache is None
    updated_cards = front_app.get_planning_cards()
    assert updated_cards[0]["planning_page_enable"] is False


def test_get_csc_sites_data_uses_in_memory_cache(monkeypatch, tmp_path):
    csc_file = tmp_path / "csc_sites.json"
    csc_file.write_text(json.dumps({"42": {"-71": [{"id": "A"}]}}))

    original_json_load = front_app.json.load
    calls = {"count": 0}

    def counting_json_load(fp):
        calls["count"] += 1
        return original_json_load(fp)

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    monkeypatch.setattr(front_app.json, "load", counting_json_load)
    front_app._csc_sites_cache = None

    first = front_app.get_csc_sites_data()
    second = front_app.get_csc_sites_data()

    assert first == second
    assert calls["count"] == 1


def test_get_device_settings_uses_fallback_keys_for_newer_firmware(monkeypatch):
    monkeypatch.setattr(front_app, "get_client_master", lambda _tid: True)
    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2670)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")

    def fake_method_sync(method, telescope_id=1, **kwargs):
        if method == "get_setting":
            return {
                "stack_dither": {"pix": 10, "interval": 2, "enable": True},
                "exp_ms": {"stack_l": 10000, "continuous": 500},
                "auto_3ppa_calib": True,
                "frame_calib": True,
                "focal_pos": 1500,
                "heater_enable": False,
                "auto_power_off": False,
                "stack_lenhance": False,
                "dark_mode": False,
                "stack_cont_capt": True,
                "stack": {"drizzle2x": False},
                "plan": {"target_af": True},
                "viewplan_go_home": True,
                "expert_mode": False,
            }
        if method == "get_stack_setting":
            return {}
        raise AssertionError(f"Unexpected method call: {method}")

    monkeypatch.setattr(front_app, "method_sync", fake_method_sync)

    settings = front_app.get_device_settings(1)

    assert settings["stack_cont_capt"] is True
    assert settings["plan_target_af"] is True
    assert settings["viewplan_gohome"] is True


def test_settings_post_tries_fallback_variants_for_firmware_specific_keys(monkeypatch):
    class DummyReq:
        def __init__(self):
            self.media = {
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
                "plan_target_af": "true",
                "viewplan_gohome": "true",
                "expert_mode": "false",
                "save_discrete_frame": "false",
                "save_discrete_ok_frame": "true",
                "light_duration_min": "10",
                "stack_capt_type": "stack",
                "stack_capt_num": "1",
                "stack_brightness": "0",
                "stack_contrast": "0",
                "stack_saturation": "0",
                "stack_dbe_enable": "false",
                "heater_enable": "false",
                "dark_mode": "false",
                "stack_cont_capt": "true",
                "stack_drizzle2x": "false",
            }

    captured = {"output": None, "calls": []}

    def fake_do_action_device(action, dev_num, parameters, is_schedule=False):
        captured["calls"].append((action, parameters))
        if action == "method_async":
            return {"ErrorNumber": 0, "Value": {"code": 0}}

        method = parameters.get("method")
        params = parameters.get("params", {})
        if method != "set_setting":
            return {"ErrorNumber": 0, "Value": {"code": 0}}

        if params == {"stack": {"cont_capt": True}}:
            return {"ErrorNumber": 0, "Value": {"code": -1, "error": "unsupported"}}
        if params == {"stack_cont_capt": True}:
            return {"ErrorNumber": 0, "Value": {"code": 0}}

        if params == {"plan_target_af": True}:
            return {"ErrorNumber": 0, "Value": {"code": -1, "error": "unsupported"}}
        if params == {"plan": {"target_af": True}}:
            return {"ErrorNumber": 0, "Value": {"code": 0}}

        if params == {"viewplan_gohome": True}:
            return {"ErrorNumber": 0, "Value": {"code": -1, "error": "unsupported"}}
        if params == {"viewplan_go_home": True}:
            return {"ErrorNumber": 0, "Value": {"code": 0}}

        return {"ErrorNumber": 0, "Value": {"code": 0}}

    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2670)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")
    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)
    monkeypatch.setattr(
        front_app.SettingsResource,
        "render_settings",
        staticmethod(
            lambda _req, _resp, _tid, output: captured.__setitem__("output", output)
        ),
    )

    front_app.SettingsResource().on_post(DummyReq(), object(), 1)

    assert captured["output"] == "Successfully Updated Settings."
    assert (
        "method_sync",
        {"method": "set_setting", "params": {"stack_cont_capt": True}},
    ) in captured["calls"]
    assert (
        "method_sync",
        {"method": "set_setting", "params": {"plan": {"target_af": True}}},
    ) in captured["calls"]
    assert (
        "method_sync",
        {"method": "set_setting", "params": {"viewplan_go_home": True}},
    ) in captured["calls"]


def test_get_device_settings_loads_discrete_save_flags_from_get_stack_setting(
    monkeypatch,
):
    monkeypatch.setattr(front_app, "get_client_master", lambda _tid: True)
    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2500)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")

    def fake_method_sync(method, telescope_id=1, **kwargs):
        if method == "get_setting":
            return {
                "stack_dither": {"pix": 10, "interval": 2, "enable": True},
                "exp_ms": {"stack_l": 10000, "continuous": 500},
                "auto_3ppa_calib": True,
                "frame_calib": True,
                "focal_pos": 1500,
                "heater_enable": False,
                "auto_power_off": False,
                "stack_lenhance": False,
                "dark_mode": False,
                "stack_cont_capt": True,
                "stack": {"drizzle2x": False},
            }
        if method == "get_stack_setting":
            return {
                "save_discrete_frame": True,
                "save_discrete_ok_frame": False,
            }
        raise AssertionError(f"Unexpected method call: {method}")

    monkeypatch.setattr(front_app, "method_sync", fake_method_sync)

    settings = front_app.get_device_settings(1)

    assert settings["save_discrete_frame"] is True
    assert settings["save_discrete_ok_frame"] is False


def test_method_sync_handles_wrapped_single_device_value(monkeypatch):
    def fake_do_action_device(action, dev_num, parameters, is_schedule=False):
        assert action == "method_sync"
        return {
            "ServerTransactionID": 1,
            "ClientTransactionID": 999,
            "Value": {
                "1": {
                    "jsonrpc": "2.0",
                    "method": "get_stack_setting",
                    "result": {
                        "save_discrete_frame": True,
                        "save_discrete_ok_frame": True,
                        "light_duration_min": -1,
                    },
                    "code": 0,
                    "id": 27207,
                }
            },
            "ErrorNumber": 0,
            "ErrorMessage": "",
        }

    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)

    result = front_app.method_sync("get_stack_setting", telescope_id=1)

    assert result["save_discrete_frame"] is True
    assert result["save_discrete_ok_frame"] is True
    assert result["light_duration_min"] == -1


def test_settings_post_saves_discrete_flags_under_stack_payload(monkeypatch):
    class DummyReq:
        def __init__(self):
            self.media = {
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
                "save_discrete_frame": "true",
                "save_discrete_ok_frame": "false",
                "light_duration_min": "10",
                "stack_capt_type": "stack",
                "stack_capt_num": "2",
                "stack_brightness": "1.1",
                "stack_contrast": "2.2",
                "stack_saturation": "3.3",
                "stack_dbe_enable": "true",
                "heater_enable": "false",
                "dark_mode": "false",
                "stack_cont_capt": "false",
                "stack_drizzle2x": "false",
            }

    captured = {"stack_payload": None}

    def fake_do_action_device(action, dev_num, parameters, is_schedule=False):
        method = parameters.get("method")
        params = parameters.get("params", {})
        if (
            action == "method_sync"
            and method == "set_setting"
            and isinstance(params, dict)
            and "stack" in params
        ):
            captured["stack_payload"] = params["stack"]
        return {"ErrorNumber": 0, "Value": {"code": 0}}

    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2670)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")
    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)
    monkeypatch.setattr(
        front_app.SettingsResource,
        "render_settings",
        staticmethod(lambda _req, _resp, _tid, _output: None),
    )

    front_app.SettingsResource().on_post(DummyReq(), object(), 1)

    assert captured["stack_payload"] is not None
    assert captured["stack_payload"]["save_discrete_frame"] is True
    assert captured["stack_payload"]["save_discrete_ok_frame"] is False


def test_settings_post_falls_back_to_set_stack_setting_for_discrete_flags(monkeypatch):
    class DummyReq:
        def __init__(self):
            self.media = {
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
                "save_discrete_frame": "true",
                "save_discrete_ok_frame": "false",
                "light_duration_min": "15",
                "stack_capt_type": "stack",
                "stack_capt_num": "2",
                "stack_brightness": "0",
                "stack_contrast": "0",
                "stack_saturation": "0",
                "stack_dbe_enable": "false",
                "heater_enable": "false",
                "dark_mode": "false",
                "stack_cont_capt": "false",
                "stack_drizzle2x": "false",
            }

    captured = {"output": None, "stack_fallback_called": False}

    def fake_do_action_device(action, dev_num, parameters, is_schedule=False):
        if action == "method_async":
            return {"ErrorNumber": 0, "Value": {"code": 0}}

        method = parameters.get("method")
        params = parameters.get("params", {})
        if method == "set_setting" and params == {"stack": {"cont_capt": False}}:
            return {"ErrorNumber": 0, "Value": {"code": 0}}
        if method == "set_setting" and isinstance(params, dict) and "stack" in params:
            # Simulate firmware that rejects stack payload via set_setting.
            return {"ErrorNumber": 0, "Value": {"code": -1, "error": "unsupported"}}
        if method == "set_stack_setting":
            captured["stack_fallback_called"] = True
            return {"ErrorNumber": 0, "Value": {"code": 0}}
        return {"ErrorNumber": 0, "Value": {"code": 0}}

    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2670)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")
    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)
    monkeypatch.setattr(
        front_app.SettingsResource,
        "render_settings",
        staticmethod(
            lambda _req, _resp, _tid, output: captured.__setitem__("output", output)
        ),
    )

    front_app.SettingsResource().on_post(DummyReq(), object(), 1)

    assert captured["stack_fallback_called"] is True
    assert captured["output"] == "Successfully Updated Settings."


def test_settings_post_older_firmware_uses_stack_setting_methods(monkeypatch):
    class DummyReq:
        def __init__(self):
            self.media = {
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
                "save_discrete_frame": "true",
                "save_discrete_ok_frame": "false",
                "light_duration_min": "20",
                "stack_capt_type": "stack",
                "stack_capt_num": "3",
                "stack_brightness": "0",
                "stack_contrast": "0",
                "stack_saturation": "0",
                "stack_dbe_enable": "false",
                "heater_enable": "false",
                "dark_mode": "false",
                "stack_cont_capt": "false",
                "stack_drizzle2x": "false",
            }

    captured = {"stack_method_calls": []}

    def fake_do_action_device(action, dev_num, parameters, is_schedule=False):
        method = parameters.get("method")
        params = parameters.get("params", {})
        if action == "method_async":
            return {"ErrorNumber": 0, "Value": {"code": 0}}
        if method in {"set_stack_setting", "set_stack_settings"}:
            captured["stack_method_calls"].append((method, params))
            return {"ErrorNumber": 0, "Value": {"code": 0}}
        return {"ErrorNumber": 0, "Value": {"code": 0}}

    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2500)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")
    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)
    monkeypatch.setattr(
        front_app.SettingsResource,
        "render_settings",
        staticmethod(lambda _req, _resp, _tid, _output: None),
    )

    front_app.SettingsResource().on_post(DummyReq(), object(), 1)

    assert captured["stack_method_calls"]
    method_name, payload = captured["stack_method_calls"][0]
    assert method_name in {"set_stack_setting", "set_stack_settings"}
    assert payload["save_discrete_frame"] is True
    assert payload["save_discrete_ok_frame"] is False


def test_settings_post_missing_light_duration_min_does_not_raise(monkeypatch):
    class DummyReq:
        def __init__(self):
            self.media = {
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
                "save_discrete_frame": "true",
                "save_discrete_ok_frame": "false",
                "heater_enable": "false",
                "dark_mode": "false",
                "stack_cont_capt": "false",
                "stack_drizzle2x": "false",
            }

    captured = {"stack_payload": None}

    def fake_do_action_device(action, dev_num, parameters, is_schedule=False):
        method = parameters.get("method")
        params = parameters.get("params", {})
        if method in {"set_stack_setting", "set_stack_settings"}:
            captured["stack_payload"] = params
            return {"ErrorNumber": 0, "Value": {"code": 0}}
        return {"ErrorNumber": 0, "Value": {"code": 0}}

    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2500)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")
    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)
    monkeypatch.setattr(
        front_app.SettingsResource,
        "render_settings",
        staticmethod(lambda _req, _resp, _tid, _output: None),
    )

    front_app.SettingsResource().on_post(DummyReq(), object(), 1)

    assert captured["stack_payload"] is not None
    assert captured["stack_payload"]["light_duration_min"] == -1


def test_home_content_endpoint_returns_non_empty_html(monkeypatch):
    monkeypatch.setattr(
        front_app,
        "get_telescopes_state",
        lambda: [
            {
                "device_num": 1,
                "name": "Seestar Alpha",
                "ip_address": "192.168.11.124",
                "stats": {"View State": "Idle", "Wi-Fi Signal": "-62 dBm"},
            }
        ],
    )
    monkeypatch.setattr(
        front_app,
        "get_context",
        lambda _tid, _req: _minimal_context("home-content", online=True),
    )
    req = DummyHTMXReq(relative_uri="/1/home-content")
    resp = DummyResp()

    front_app.HomeContentResource.on_get(req, resp, telescope_id=1)

    assert "Welcome to the Simple Seestar" in resp.text
    assert "Seestar Alpha" in resp.text


def test_stats_content_endpoint_returns_non_empty_html(monkeypatch):
    front_app.StatsContentResource._last_render_by_key.clear()
    monkeypatch.setattr(
        front_app,
        "get_device_state",
        lambda _tid: {"View State": "Idle", "Wi-Fi Signal": "-62 dBm"},
    )
    monkeypatch.setattr(
        front_app,
        "get_context",
        lambda _tid, _req: _minimal_context("stats-content", online=True),
    )
    req = DummyHTMXReq(relative_uri="/1/stats-content")
    resp = DummyResp()

    front_app.StatsContentResource.on_get(req, resp, telescope_id=1)

    assert "Wi-Fi Signal" in resp.text


def test_guestmode_content_endpoint_handles_sparse_state(monkeypatch):
    front_app.GuestModeContentResource._last_render_by_key.clear()
    monkeypatch.setattr(
        front_app,
        "get_context",
        lambda _tid, _req: _minimal_context("guestmode-content", online=True),
    )
    monkeypatch.setattr(
        front_app,
        "get_guestmode_state",
        lambda _tid: {"guest_mode": False},
    )
    req = DummyHTMXReq(relative_uri="/1/guestmode-content")
    resp = DummyResp()

    front_app.GuestModeContentResource.on_get(req, resp, telescope_id=1)

    assert "Guest mode is unavailable" in resp.text


def test_eventstatus_endpoint_handles_empty_event_result(monkeypatch):
    front_app.EventStatus._last_render_by_key.clear()
    monkeypatch.setattr(
        front_app,
        "get_context",
        lambda _tid, _req: _minimal_context("eventstatus", online=True),
    )
    monkeypatch.setattr(
        front_app,
        "do_action_device",
        lambda *_args, **_kwargs: {"Value": {"result": {}}},
    )
    req = DummyHTMXReq(
        relative_uri="/1/eventstatus",
        params={"action": "goto"},
        headers={
            "User-Agent": "pytest-agent",
            "HX-Current-URL": "http://localhost/1/goto",
        },
    )
    resp = DummyResp()

    front_app.EventStatus.on_get(req, resp, telescope_id=1)

    assert "Current Status of Devices" in resp.text
    assert "No results available." in resp.text


@pytest.mark.parametrize(
    "stack_from_get_setting,stack_from_get_stack_setting,expected_discrete",
    [
        (
            {"save_discrete_frame": False, "save_discrete_ok_frame": True},
            {},
            (False, True),
        ),
        (
            {},
            {"save_discrete_frame": True, "save_discrete_ok_frame": False},
            (True, False),
        ),
    ],
)
def test_get_device_settings_discrete_flags_compat_matrix(
    monkeypatch,
    stack_from_get_setting,
    stack_from_get_stack_setting,
    expected_discrete,
):
    monkeypatch.setattr(front_app, "get_client_master", lambda _tid: True)
    monkeypatch.setattr(front_app, "get_firmware_ver_int", lambda _tid: 2670)
    monkeypatch.setattr(front_app, "get_device_model", lambda _tid: "Seestar S50")

    def fake_method_sync(method, telescope_id=1, **kwargs):
        if method == "get_setting":
            return {
                "stack_dither": {"pix": 10, "interval": 2, "enable": True},
                "exp_ms": {"stack_l": 10000, "continuous": 500},
                "auto_3ppa_calib": True,
                "frame_calib": True,
                "focal_pos": 1500,
                "heater_enable": False,
                "auto_power_off": False,
                "stack_lenhance": False,
                "dark_mode": False,
                "stack_cont_capt": True,
                "stack": {"drizzle2x": False, **stack_from_get_setting},
                "plan": {"target_af": True},
                "viewplan_go_home": True,
                "expert_mode": False,
            }
        if method == "get_stack_setting":
            return stack_from_get_stack_setting
        raise AssertionError(f"Unexpected method call: {method}")

    monkeypatch.setattr(front_app, "method_sync", fake_method_sync)

    settings = front_app.get_device_settings(1)

    assert settings["save_discrete_frame"] is expected_discrete[0]
    assert settings["save_discrete_ok_frame"] is expected_discrete[1]


@pytest.mark.parametrize(
    "template_name,context",
    [
        (
            "partials/home_content.html",
            {
                "telescopes": [
                    {
                        "device_num": 1,
                        "name": "Seestar Alpha",
                        "ip_address": "192.168.11.124",
                        "stats": {},
                    }
                ],
                "version": "test",
            },
        ),
        (
            "partials/guestmode_content.html",
            {
                "online": True,
                "state": {"guest_mode": False},
                "action": "/1/guestmode",
                "version": "test",
            },
        ),
        (
            "eventstatus.html",
            {"results": [], "events": [], "now": "now"},
        ),
    ],
)
def test_sparse_template_contexts_render_without_error(template_name, context):
    template = front_app.fetch_template(template_name)
    html = template.render(**context)
    assert isinstance(html, str)
    assert len(html) > 0
