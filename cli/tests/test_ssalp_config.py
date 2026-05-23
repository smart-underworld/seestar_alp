"""Tests for config loading and precedence."""

from __future__ import annotations

from pathlib import Path

import pytest

from ssalp_api_client.config import Config, load_config


# ── Config model validation ───────────────────────────────────────────────


class TestConfigValidation:
    def test_defaults(self):
        c = Config()
        assert c.host == "localhost"
        assert c.port == 5555
        assert c.device == 1
        assert c.timeout == 10.0
        assert c.log_level == "WARNING"
        assert c.output == "pretty"
        assert c.log_file is None

    def test_log_level_uppercased(self):
        c = Config(log_level="debug")
        assert c.log_level == "DEBUG"

    def test_invalid_log_level(self):
        with pytest.raises(ValueError, match="log_level"):
            Config(log_level="VERBOSE")

    def test_output_lowercased(self):
        c = Config(output="JSON")
        assert c.output == "json"

    def test_invalid_output(self):
        with pytest.raises(ValueError, match="output"):
            Config(output="yaml")

    def test_port_coerced_from_string(self):
        c = Config(port="8080")
        assert c.port == 8080

    def test_device_coerced_from_string(self):
        c = Config(device="2")
        assert c.device == 2

    def test_timeout_coerced_from_string(self):
        c = Config(timeout="30.5")
        assert c.timeout == 30.5

    def test_invalid_port_string(self):
        with pytest.raises(ValueError):
            Config(port="abc")

    def test_invalid_device_string(self):
        with pytest.raises(ValueError):
            Config(device="x")

    def test_timeout_must_be_positive(self):
        with pytest.raises(ValueError):
            Config(timeout=0)

    def test_timeout_negative_rejected(self):
        with pytest.raises(ValueError):
            Config(timeout=-1.0)

    def test_timeout_non_numeric_string_raises(self):
        with pytest.raises(ValueError, match="Expected a number"):
            Config(timeout="abc")


# ── load_config precedence ────────────────────────────────────────────────


class TestLoadConfigDefaults:
    def test_no_file_no_env_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for key in ("SSALP_HOST", "SSALP_PORT", "SSALP_DEVICE", "SSALP_CONFIG"):
            monkeypatch.delenv(key, raising=False)
        config = load_config()
        assert config.host == "localhost"
        assert config.port == 5555

    def test_overrides_applied(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SSALP_HOST", raising=False)
        config = load_config(overrides={"host": "192.168.1.1", "port": 7777})
        assert config.host == "192.168.1.1"
        assert config.port == 7777


class TestLoadConfigFromFile:
    def _write_toml(self, path: Path, content: str) -> Path:
        p = path / "config.toml"
        p.write_text(content)
        return p

    def test_reads_default_section(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SSALP_CONFIG", raising=False)
        monkeypatch.delenv("SSALP_HOST", raising=False)
        cfg = self._write_toml(tmp_path, '[default]\nhost = "10.0.0.1"\nport = 9000\n')
        config = load_config(config_file=str(cfg))
        assert config.host == "10.0.0.1"
        assert config.port == 9000

    def test_reads_named_profile(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SSALP_HOST", raising=False)
        content = '[default]\nhost = "localhost"\n[profiles.obs]\nhost = "10.0.0.5"\n'
        cfg = self._write_toml(tmp_path, content)
        config = load_config(config_file=str(cfg), profile="obs")
        assert config.host == "10.0.0.5"

    def test_unknown_profile_raises(self, tmp_path):
        cfg = self._write_toml(tmp_path, '[default]\nhost = "localhost"\n')
        with pytest.raises(ValueError, match="missing"):
            load_config(config_file=str(cfg), profile="missing")

    def test_invalid_toml_raises(self, tmp_path):
        p = tmp_path / "bad.toml"
        p.write_text("[[not valid toml ]][[")
        with pytest.raises(Exception):
            load_config(config_file=str(p))

    def test_local_ssalp_toml_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SSALP_CONFIG", raising=False)
        monkeypatch.delenv("SSALP_HOST", raising=False)
        (tmp_path / "ssalp.toml").write_text('[default]\nhost = "192.168.99.1"\n')
        config = load_config()
        assert config.host == "192.168.99.1"

    def test_explicit_config_overrides_local(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "ssalp.toml").write_text('[default]\nhost = "local"\n')
        explicit = tmp_path / "other.toml"
        explicit.write_text('[default]\nhost = "explicit"\n')
        config = load_config(config_file=str(explicit))
        assert config.host == "explicit"

    def test_ssalp_config_env_var_used(self, tmp_path, monkeypatch):
        cfg = tmp_path / "via_env.toml"
        cfg.write_text('[default]\nhost = "env-config-host"\n')
        monkeypatch.setenv("SSALP_CONFIG", str(cfg))
        monkeypatch.delenv("SSALP_HOST", raising=False)
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.host == "env-config-host"
        monkeypatch.delenv("SSALP_CONFIG")

    def test_user_level_config_used(self, tmp_path, monkeypatch):
        user_dir = tmp_path / ".config" / "ssalp"
        user_dir.mkdir(parents=True)
        cfg = user_dir / "config.toml"
        cfg.write_text('[default]\nhost = "user-level-host"\n')
        monkeypatch.delenv("SSALP_CONFIG", raising=False)
        monkeypatch.delenv("SSALP_HOST", raising=False)
        # No local ssalp.toml, no explicit path — patch Path.home()
        monkeypatch.chdir(tmp_path)
        import ssalp_api_client.config as cfg_mod

        original_home = cfg_mod.Path.home
        monkeypatch.setattr(cfg_mod.Path, "home", staticmethod(lambda: tmp_path))
        config = load_config()
        monkeypatch.setattr(cfg_mod.Path, "home", staticmethod(original_home))
        assert config.host == "user-level-host"


class TestLoadConfigEnvVars:
    def test_env_overrides_file(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.toml"
        cfg.write_text('[default]\nhost = "file-host"\n')
        monkeypatch.setenv("SSALP_HOST", "env-host")
        config = load_config(config_file=str(cfg))
        assert config.host == "env-host"
        monkeypatch.delenv("SSALP_HOST")

    def test_env_port_coerced(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SSALP_PORT", "7777")
        config = load_config()
        assert config.port == 7777
        monkeypatch.delenv("SSALP_PORT")

    def test_env_invalid_port_raises(self, monkeypatch):
        monkeypatch.setenv("SSALP_PORT", "notanint")
        with pytest.raises(ValueError):
            load_config()
        monkeypatch.delenv("SSALP_PORT")

    def test_env_log_level(self, monkeypatch):
        monkeypatch.setenv("SSALP_LOG_LEVEL", "DEBUG")
        config = load_config()
        assert config.log_level == "DEBUG"
        monkeypatch.delenv("SSALP_LOG_LEVEL")


class TestLoadConfigPrecedence:
    def test_override_beats_env_beats_file(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.toml"
        cfg.write_text('[default]\nhost = "file"\n')
        monkeypatch.setenv("SSALP_HOST", "env")
        config = load_config(config_file=str(cfg), overrides={"host": "cli"})
        assert config.host == "cli"
        monkeypatch.delenv("SSALP_HOST")

    def test_env_beats_file(self, tmp_path, monkeypatch):
        cfg = tmp_path / "c.toml"
        cfg.write_text('[default]\nhost = "file"\n')
        monkeypatch.setenv("SSALP_HOST", "env")
        config = load_config(config_file=str(cfg))
        assert config.host == "env"
        monkeypatch.delenv("SSALP_HOST")

    def test_none_override_not_applied(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SSALP_HOST", raising=False)
        config = load_config(overrides={"host": None})
        assert config.host == "localhost"
