import logging

from fastapi import APIRouter

from device.config import Config  # type: ignore

router = APIRouter(prefix="/api/v1")


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
