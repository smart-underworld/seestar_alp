"""
Unit tests for front_v2.device_client.get_device_settings wide-angle camera
gating, mirroring the equivalent classic-UI behavior in
front/app.py:get_device_settings (Config.experimental + "S30" in model).
"""

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)

from device.config import Config  # noqa: E402
from front_v2 import device_client  # noqa: E402


def _device_state(model: str):
    return {"device": {"firmware_ver_int": 2775, "product_model": model}}


def _wide_cam_get_setting_response():
    return {
        "wide_cam": True,
        "wide_4k": False,
        "wide_focal_pos": 1500,
        "stack": {},
    }


def test_wide_cam_fields_hidden_for_s50_even_when_firmware_reports_them(monkeypatch):
    monkeypatch.setattr(Config, "experimental", True)

    def fake_method_sync(method, dev_num, **kwargs):
        if method == "get_setting":
            return _wide_cam_get_setting_response()
        if method == "get_stack_setting":
            return {"wide_denoise": True}
        if method == "get_device_state":
            return _device_state("Seestar S50")
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(device_client, "method_sync", fake_method_sync)

    settings = device_client.get_device_settings(1)

    assert "wide_cam" not in settings["merged"]
    assert "wide_4k" not in settings["merged"]
    assert "wide_denoise" not in settings["merged"]
    assert "wide_focal_pos" not in settings["merged"]


def test_wide_cam_fields_shown_for_s30_with_experimental(monkeypatch):
    monkeypatch.setattr(Config, "experimental", True)

    def fake_method_sync(method, dev_num, **kwargs):
        if method == "get_setting":
            return _wide_cam_get_setting_response()
        if method == "get_stack_setting":
            return {"wide_denoise": True}
        if method == "get_device_state":
            return _device_state("Seestar S30")
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(device_client, "method_sync", fake_method_sync)

    settings = device_client.get_device_settings(1)

    assert settings["merged"]["wide_cam"] is True
    assert settings["merged"]["wide_4k"] is False
    assert settings["merged"]["wide_denoise"] is True
    assert settings["merged"]["wide_focal_pos"] == 1500


def test_wide_cam_fields_shown_for_s30_pro(monkeypatch):
    monkeypatch.setattr(Config, "experimental", True)

    def fake_method_sync(method, dev_num, **kwargs):
        if method == "get_setting":
            return _wide_cam_get_setting_response()
        if method == "get_stack_setting":
            return {}
        if method == "get_device_state":
            return _device_state("Seestar S30 Pro")
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(device_client, "method_sync", fake_method_sync)

    settings = device_client.get_device_settings(1)

    assert "wide_cam" in settings["merged"]
    assert "wide_4k" in settings["merged"]


def test_wide_cam_fields_hidden_when_experimental_off(monkeypatch):
    monkeypatch.setattr(Config, "experimental", False)

    def fake_method_sync(method, dev_num, **kwargs):
        if method == "get_setting":
            return _wide_cam_get_setting_response()
        if method == "get_stack_setting":
            return {}
        if method == "get_device_state":
            return _device_state("Seestar S30")
        raise AssertionError(f"Unexpected method: {method}")

    monkeypatch.setattr(device_client, "method_sync", fake_method_sync)

    settings = device_client.get_device_settings(1)

    assert "wide_cam" not in settings["merged"]
    assert "wide_4k" not in settings["merged"]
