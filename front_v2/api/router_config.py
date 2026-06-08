import logging
from typing import Any

import tomlkit
from fastapi import APIRouter, Body, HTTPException

from device.config import Config  # type: ignore
from device.version import Version  # type: ignore

router = APIRouter(prefix="/api/v1")


@router.get("/version")
def get_version():
    return {"version": Version.app_version()}


@router.get("/config")
def get_config():
    """Return SSC application config fields as JSON (read-only)."""
    seestars = getattr(Config, "seestars", [])

    raw_log_level = getattr(Config, "log_level", "INFO")
    log_level_name = (
        logging.getLevelName(raw_log_level)
        if isinstance(raw_log_level, int)
        else raw_log_level
    )

    return {
        "networking": {
            "ip_address": getattr(Config, "ip_address", ""),
            "port": getattr(Config, "port", 5555),
            "imgport": getattr(Config, "imgport", 7556),
            "stport": getattr(Config, "stport", 8090),
            "sthost": getattr(Config, "sthost", "localhost"),
            "timeout": getattr(Config, "timeout", 5),
            "rtsp_udp": getattr(Config, "rtsp_udp", False),
        },
        "webui": {
            "uiport": getattr(Config, "uiport", 5432),
            "ui_theme": getattr(Config, "uitheme", "dark"),
            "experimental": getattr(Config, "experimental", False),
            "confirm": getattr(Config, "confirm", True),
            "save_frames": getattr(Config, "save_frames", False),
            "save_frames_dir": getattr(Config, "save_frames_dir", "."),
            "frontend": getattr(Config, "frontend", "classic"),
        },
        "logging": {
            "log_level": log_level_name,
            "log_to_stdout": getattr(Config, "log_to_stdout", False),
            "max_log_size_mb": getattr(Config, "max_size_mb", 5),
            "log_num_keep": getattr(Config, "num_keep_logs", 10),
            "log_prefix": getattr(Config, "log_prefix", ""),
        },
        "init": {
            "latitude": getattr(Config, "init_lat", 0.0),
            "longitude": getattr(Config, "init_long", 0.0),
            "gain": getattr(Config, "init_gain", 80),
            "exp_ms_preview": getattr(Config, "init_expo_preview_ms", 500),
            "exp_ms_stack_l": getattr(Config, "init_expo_stack_ms", 10000),
            "dither_enabled": getattr(Config, "init_dither_enabled", True),
            "dither_length_pixel": getattr(Config, "init_dither_length_pixel", 50),
            "dither_frequency": getattr(Config, "init_dither_frequency", 10),
            "lp_filter": getattr(Config, "init_activate_LP_filter", False),
            "heater_power": getattr(Config, "init_dew_heater_power", 0),
            "save_good_frames": getattr(Config, "init_save_good_frames", True),
            "save_all_frames": getattr(Config, "init_save_all_frames", True),
            "dec_pos_index": getattr(Config, "dec_pos_index", 3),
            "battery_low_limit": getattr(Config, "battery_low_limit", 3),
            "guest_mode": getattr(Config, "init_guest_mode", True),
        },
        "devices": [
            {
                "device_num": s.get("device_num"),
                "name": s.get("name", ""),
                "ip_address": s.get("ip_address", ""),
            }
            for s in (seestars if isinstance(seestars, list) else [])
        ],
    }


@router.post("/config")
def save_config(body: dict[str, Any] = Body(...)):
    """Write editable config fields to config.toml."""
    try:
        net = body.get("networking", {})
        if "ip_address" in net:
            Config.set_toml("network", "ip_address", str(net["ip_address"]))
        if "port" in net:
            Config.set_toml("network", "port", int(net["port"]))
        if "imgport" in net:
            Config.set_toml("network", "imgport", int(net["imgport"]))
        if "stport" in net:
            Config.set_toml("network", "stport", int(net["stport"]))
        if "sthost" in net:
            Config.set_toml("network", "sthost", str(net["sthost"]))
        if "timeout" in net:
            Config.set_toml("network", "timeout", int(net["timeout"]))
        if "rtsp_udp" in net:
            Config.set_toml("network", "rtsp_udp", bool(net["rtsp_udp"]))

        ui = body.get("webui", {})
        if "uiport" in ui:
            Config.set_toml("webui_settings", "uiport", int(ui["uiport"]))
        if "ui_theme" in ui:
            Config.set_toml("webui_settings", "uitheme", str(ui["ui_theme"]))
        if "experimental" in ui:
            Config.set_toml("webui_settings", "experimental", bool(ui["experimental"]))
        if "confirm" in ui:
            Config.set_toml("webui_settings", "confirm", bool(ui["confirm"]))
        if "save_frames" in ui:
            Config.set_toml("webui_settings", "save_frames", bool(ui["save_frames"]))
        if "save_frames_dir" in ui:
            Config.set_toml(
                "webui_settings", "save_frames_dir", str(ui["save_frames_dir"])
            )
        if "frontend" in ui:
            Config.set_toml("webui_settings", "frontend", str(ui["frontend"]))

        log = body.get("logging", {})
        if "log_level" in log:
            Config.set_toml("logging", "log_level", str(log["log_level"]))
        if "log_to_stdout" in log:
            Config.set_toml("logging", "log_to_stdout", bool(log["log_to_stdout"]))
        if "max_log_size_mb" in log:
            Config.set_toml("logging", "max_size_mb", int(log["max_log_size_mb"]))
        if "log_num_keep" in log:
            Config.set_toml("logging", "num_keep_logs", int(log["log_num_keep"]))
        if "log_prefix" in log:
            Config.set_toml("logging", "log_prefix", str(log["log_prefix"]))

        ini = body.get("init", {})
        if "latitude" in ini:
            Config.set_toml("seestar_initialization", "lat", float(ini["latitude"]))
        if "longitude" in ini:
            Config.set_toml("seestar_initialization", "long", float(ini["longitude"]))
        if "gain" in ini:
            Config.set_toml("seestar_initialization", "gain", int(ini["gain"]))
        if "exp_ms_preview" in ini:
            Config.set_toml(
                "seestar_initialization",
                "exposure_length_preview_ms",
                int(ini["exp_ms_preview"]),
            )
        if "exp_ms_stack_l" in ini:
            Config.set_toml(
                "seestar_initialization",
                "exposure_length_stack_ms",
                int(ini["exp_ms_stack_l"]),
            )
        if "dither_enabled" in ini:
            Config.set_toml(
                "seestar_initialization", "dither_enabled", bool(ini["dither_enabled"])
            )
        if "dither_length_pixel" in ini:
            Config.set_toml(
                "seestar_initialization",
                "dither_length_pixel",
                int(ini["dither_length_pixel"]),
            )
        if "dither_frequency" in ini:
            Config.set_toml(
                "seestar_initialization",
                "dither_frequency",
                int(ini["dither_frequency"]),
            )
        if "lp_filter" in ini:
            Config.set_toml(
                "seestar_initialization", "activate_LP_filter", bool(ini["lp_filter"])
            )
        if "heater_power" in ini:
            Config.set_toml(
                "seestar_initialization", "dew_heater_power", int(ini["heater_power"])
            )
        if "save_good_frames" in ini:
            Config.set_toml(
                "seestar_initialization",
                "save_good_frames",
                bool(ini["save_good_frames"]),
            )
        if "save_all_frames" in ini:
            Config.set_toml(
                "seestar_initialization",
                "save_all_frames",
                bool(ini["save_all_frames"]),
            )
        if "dec_pos_index" in ini:
            Config.set_toml(
                "seestar_initialization", "dec_pos_index", int(ini["dec_pos_index"])
            )
        if "battery_low_limit" in ini:
            Config.set_toml(
                "seestar_initialization",
                "battery_low_limit",
                int(ini["battery_low_limit"]),
            )
        if "guest_mode" in ini:
            Config.set_toml(
                "seestar_initialization", "guest_mode_init", bool(ini["guest_mode"])
            )

        Config.save_toml()
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/config/devices")
def save_devices(body: dict[str, Any] = Body(...)):
    """Replace the configured Seestar device list and persist to config.toml.

    Accepts {"devices": [{"name": str, "ip_address": str}, ...]} and assigns
    sequential device numbers starting at 1, mirroring the classic UI's
    load_from_form behavior.
    """
    try:
        devices = body.get("devices", [])
        if not isinstance(devices, list):
            raise HTTPException(status_code=400, detail="devices must be a list")

        Config.seestars = []
        Config._dict["seestars"] = tomlkit.aot()

        for idx, device in enumerate(devices, start=1):
            name = str(device.get("name", "")).strip()
            ip_address = str(device.get("ip_address", "")).strip()
            if not name or not ip_address:
                raise HTTPException(
                    status_code=400,
                    detail="Each device requires a name and IP address",
                )
            entry = {"name": name, "ip_address": ip_address, "device_num": idx}
            Config.seestars.append(entry)
            Config._dict["seestars"].append(dict(entry))

        Config.save_toml()
        return {
            "status": "ok",
            "devices": [
                {
                    "device_num": s["device_num"],
                    "name": s["name"],
                    "ip_address": s["ip_address"],
                }
                for s in Config.seestars
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
