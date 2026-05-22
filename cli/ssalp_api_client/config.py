from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, field_validator

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_VALID_OUTPUT_FMTS = {"json", "table", "pretty"}


class Config(BaseModel):
    host: str = "localhost"
    port: int = 5555
    device: int = 1
    timeout: float = 10.0
    log_level: str = "WARNING"
    log_file: str | None = None
    output: str = "pretty"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {_VALID_LOG_LEVELS}, got {v!r}")
        return upper

    @field_validator("output")
    @classmethod
    def _validate_output(cls, v: str) -> str:
        lower = v.lower()
        if lower not in _VALID_OUTPUT_FMTS:
            raise ValueError(f"output must be one of {_VALID_OUTPUT_FMTS}, got {v!r}")
        return lower

    @field_validator("port", "device", mode="before")
    @classmethod
    def _coerce_int(cls, v: object) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError(f"Expected an integer, got {v!r}")

    @field_validator("timeout", mode="before")
    @classmethod
    def _coerce_float(cls, v: object) -> float:
        try:
            val = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Expected a number, got {v!r}")
        if val <= 0:
            raise ValueError("timeout must be positive")
        return val


def _find_config_file(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).resolve()

    env_path = os.environ.get("SSALP_CONFIG")
    if env_path:
        return Path(env_path).resolve()

    local = Path("ssalp.toml")
    if local.exists():
        return local.resolve()

    user = Path.home() / ".config" / "ssalp" / "config.toml"
    if user.exists():
        return user

    return None


def _read_toml(path: Path, profile: str) -> dict:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    data: dict = dict(raw.get("default", {}))

    if profile != "default":
        profiles = raw.get("profiles", {})
        if profile not in profiles:
            raise ValueError(
                f"Profile {profile!r} not found in {path}. "
                f"Available profiles: {list(profiles)}"
            )
        data.update(profiles[profile])

    return data


_ENV_MAP = {
    "SSALP_HOST": "host",
    "SSALP_PORT": "port",
    "SSALP_DEVICE": "device",
    "SSALP_TIMEOUT": "timeout",
    "SSALP_LOG_LEVEL": "log_level",
    "SSALP_LOG_FILE": "log_file",
    "SSALP_OUTPUT": "output",
}


def load_config(
    config_file: str | None = None,
    profile: str = "default",
    overrides: dict | None = None,
) -> Config:
    """Merge config file → env vars → CLI overrides and return a Config.

    Priority (highest wins): overrides > env vars > config file > built-in defaults.
    """
    data: dict = {}

    path = _find_config_file(config_file)
    if path:
        data.update(_read_toml(path, profile))

    for env_key, config_key in _ENV_MAP.items():
        val = os.environ.get(env_key)
        if val is not None:
            data[config_key] = val

    if overrides:
        for key, val in overrides.items():
            if val is not None:
                data[key] = val

    return Config(**data)
