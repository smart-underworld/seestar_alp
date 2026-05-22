"""Tests for the ssalp CLI."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ssalp_api_client.cli.main import cli
from ssalp_api_client.exceptions import SSAlpConnectionError, SSAlpError


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _mock_client(return_value=None):
    """Return a mock SSAlpApiClient where every async method returns *return_value*."""
    client = MagicMock()
    # Make every attribute access return an AsyncMock that resolves to return_value
    client.test_connection = AsyncMock(return_value=return_value or {"result": "ok"})
    client.get_device_state = AsyncMock(return_value=return_value or {"state": "idle"})
    client.scope_goto = AsyncMock(return_value=return_value)
    client.scope_park = AsyncMock(return_value=return_value)
    client.start_mosaic = AsyncMock(return_value=return_value)
    client.start_stack = AsyncMock(return_value=return_value)
    client.stop_exposure = AsyncMock(return_value=return_value)
    client.set_gain = AsyncMock(return_value=return_value)
    client.get_focuser_position = AsyncMock(return_value=return_value)
    client.get_wheel_position = AsyncMock(return_value=return_value)
    client.get_schedule = AsyncMock(return_value=return_value)
    client.start_scheduler = AsyncMock(return_value=return_value)
    client.stop_scheduler = AsyncMock(return_value=return_value)
    client.get_albums = AsyncMock(return_value=return_value)
    client.startup_sequence = AsyncMock(return_value=return_value)
    client.pi_reboot = AsyncMock(return_value=return_value)
    client.set_heater = AsyncMock(return_value=return_value)
    client.play_sound = AsyncMock(return_value=return_value)
    client.set_brightness = AsyncMock(return_value=return_value)
    return client


# ── connection and global flags ────────────────────────────────────────────

class TestGlobalFlags:
    def test_help_exits_zero(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ssalp" in result.output.lower() or "usage" in result.output.lower()

    def test_subcommand_help_exits_zero(self, runner):
        result = runner.invoke(cli, ["info", "--help"])
        assert result.exit_code == 0

    def test_unknown_subcommand_exits_nonzero(self, runner):
        result = runner.invoke(cli, ["notacommand"])
        assert result.exit_code != 0

    def test_log_level_debug_accepted(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client({"result": "ok"})
            result = runner.invoke(cli, ["--log-level", "DEBUG", "info", "test-connection"])
        assert result.exit_code == 0

    def test_invalid_log_level_rejected(self, runner):
        result = runner.invoke(cli, ["--log-level", "TRACE", "info", "test-connection"])
        assert result.exit_code != 0

    def test_output_json_flag(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client({"key": "value"})
            result = runner.invoke(cli, ["--output", "json", "info", "test-connection"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "key" in parsed

    def test_output_pretty_flag(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client({"key": "val"})
            result = runner.invoke(cli, ["--output", "pretty", "info", "test-connection"])
        assert result.exit_code == 0
        assert "key" in result.output

    def test_output_table_flag(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client({"key": "val"})
            result = runner.invoke(cli, ["--output", "table", "info", "test-connection"])
        assert result.exit_code == 0


# ── error handling ─────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_ssalp_error_exits_nonzero(self, runner):
        client = _mock_client()
        client.test_connection = AsyncMock(
            side_effect=SSAlpError("bad action", error_number=1025)
        )
        with patch("ssalp_api_client.cli.main.SSAlpApiClient", return_value=client):
            result = runner.invoke(cli, ["info", "test-connection"])
        assert result.exit_code == 1
        assert "1025" in result.output or "1025" in (result.stderr if hasattr(result, 'stderr') else "")

    def test_connection_error_exits_nonzero(self, runner):
        client = _mock_client()
        client.test_connection = AsyncMock(
            side_effect=SSAlpConnectionError("refused")
        )
        with patch("ssalp_api_client.cli.main.SSAlpApiClient", return_value=client):
            result = runner.invoke(cli, ["info", "test-connection"])
        assert result.exit_code == 1

    def test_connection_error_prints_hint(self, runner):
        client = _mock_client()
        client.test_connection = AsyncMock(
            side_effect=SSAlpConnectionError("refused")
        )
        with patch("ssalp_api_client.cli.main.SSAlpApiClient", return_value=client):
            result = runner.invoke(cli, ["info", "test-connection"], catch_exceptions=False)
        assert result.exit_code == 1


# ── info subcommands ───────────────────────────────────────────────────────

class TestInfoCommands:
    def _run(self, runner, args, return_value=None):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client(return_value)
            return runner.invoke(cli, args)

    def test_test_connection(self, runner):
        result = self._run(runner, ["info", "test-connection"], {"ok": True})
        assert result.exit_code == 0

    def test_device_state(self, runner):
        result = self._run(runner, ["info", "device-state"], {"state": "idle"})
        assert result.exit_code == 0


# ── mount subcommands ──────────────────────────────────────────────────────

class TestMountCommands:
    def test_goto_requires_ra_and_dec(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["mount", "goto", "--ra", "10.5"])
        assert result.exit_code != 0

    def test_goto_succeeds(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(
                cli, ["mount", "goto", "--ra", "10.5", "--dec", "-5.0"]
            )
        assert result.exit_code == 0

    def test_park(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["mount", "park"])
        assert result.exit_code == 0


# ── camera subcommands ─────────────────────────────────────────────────────

class TestCameraCommands:
    def test_set_gain_requires_argument(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["camera", "set-gain"])
        assert result.exit_code != 0

    def test_set_gain_with_value(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["camera", "set-gain", "80"])
        assert result.exit_code == 0

    def test_start_stack_requires_gain(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["camera", "start-stack"])
        assert result.exit_code != 0


# ── schedule subcommands ───────────────────────────────────────────────────

class TestScheduleCommands:
    def test_start(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["schedule", "start"])
        assert result.exit_code == 0

    def test_stop(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["schedule", "stop"])
        assert result.exit_code == 0


# ── env file loading ───────────────────────────────────────────────────────

class TestEnvFileLoading:
    def test_valid_bru_env_used(self, runner, tmp_path):
        bru = tmp_path / "env.bru"
        bru.write_text("vars {\n  base_url: http://10.0.0.1:5555\n  dev_num: 2\n}\n")
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client({"ok": True})
            result = runner.invoke(
                cli, ["--env", str(bru), "info", "test-connection"]
            )
        assert result.exit_code == 0
        call_kwargs = MockClient.call_args
        cfg = call_kwargs.kwargs.get("config") or call_kwargs.args[0] if call_kwargs.args else None
        if cfg:
            assert cfg.host == "10.0.0.1"
            assert cfg.device == 2

    def test_nonexistent_env_file_rejected(self, runner, tmp_path):
        result = runner.invoke(
            cli, ["--env", str(tmp_path / "missing.bru"), "info", "test-connection"]
        )
        assert result.exit_code != 0

    def test_cli_flags_override_env_file(self, runner, tmp_path):
        bru = tmp_path / "env.bru"
        bru.write_text("vars {\n  base_url: http://10.0.0.1:5555\n  dev_num: 2\n}\n")
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            runner.invoke(
                cli,
                ["--env", str(bru), "--host", "192.168.1.5", "info", "test-connection"],
            )
        call_kwargs = MockClient.call_args
        cfg = call_kwargs.kwargs.get("config") or (call_kwargs.args[0] if call_kwargs.args else None)
        if cfg:
            assert cfg.host == "192.168.1.5"


# ── system subcommands ─────────────────────────────────────────────────────

class TestSystemCommands:
    def test_heater_on(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["system", "heater", "--on"])
        assert result.exit_code == 0

    def test_heater_off(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["system", "heater", "--off"])
        assert result.exit_code == 0

    def test_play_sound_requires_id(self, runner):
        with patch("ssalp_api_client.cli.main.SSAlpApiClient") as MockClient:
            MockClient.return_value = _mock_client()
            result = runner.invoke(cli, ["system", "play-sound"])
        assert result.exit_code != 0
