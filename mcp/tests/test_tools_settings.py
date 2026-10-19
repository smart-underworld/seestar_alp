from unittest.mock import AsyncMock, MagicMock

import pytest
from ssalp_api_client import SSAlpError

from seestar_mcp.tools.settings import read_settings_tool, write_setting_tool


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture(autouse=True)
def make_client_spy(monkeypatch, mock_client):
    spy = MagicMock(return_value=mock_client)
    monkeypatch.setattr("seestar_mcp.server.make_client", spy)
    return spy


async def test_read_settings_merges_both_paths(mock_client):
    mock_client.get_setting.return_value = {"a": 1}
    mock_client.get_stack_setting.return_value = {"b": 2}
    out = await read_settings_tool()
    mock_client.get_setting.assert_awaited_once()
    mock_client.get_stack_setting.assert_awaited_once()
    assert out == {"setting": {"a": 1}, "stack_setting": {"b": 2}}


async def test_read_settings_tolerates_stack_path_error(mock_client):
    mock_client.get_setting.return_value = {"a": 1}
    mock_client.get_stack_setting.side_effect = SSAlpError("no method")
    out = await read_settings_tool()
    assert out["setting"] == {"a": 1}
    assert "stack_setting" not in out
    assert "no method" in out["errors"]["stack_setting"]


async def test_read_settings_tolerates_setting_path_error(mock_client):
    mock_client.get_setting.side_effect = SSAlpError("old fw")
    mock_client.get_stack_setting.return_value = {"b": 2}
    out = await read_settings_tool()
    assert out["stack_setting"] == {"b": 2}
    assert "setting" not in out


async def test_write_setting_auto_uses_plural_for_many_keys(mock_client):
    await write_setting_tool(values={"exp_ms": 10000, "gain": 80})
    mock_client.set_stack_settings.assert_awaited_once_with(exp_ms=10000, gain=80)
    mock_client.set_stack_setting.assert_not_awaited()


async def test_write_setting_auto_uses_singular_for_one_key(mock_client):
    await write_setting_tool(values={"exp_ms": 10000})
    mock_client.set_stack_setting.assert_awaited_once_with(exp_ms=10000)
    mock_client.set_stack_settings.assert_not_awaited()


async def test_write_setting_explicit_variant_forced(mock_client):
    await write_setting_tool(values={"exp_ms": 1}, variant="set_setting")
    mock_client.set_setting.assert_awaited_once_with(exp_ms=1)


async def test_write_setting_unsupported_variant_returns_not_ok(mock_client):
    mock_client.set_stack_settings.side_effect = SSAlpError("unknown method")
    out = await write_setting_tool(
        values={"a": 1, "b": 2}, variant="set_stack_settings"
    )
    assert out["ok"] is False
    assert "unknown method" in out["error"]


async def test_write_setting_invalid_variant(mock_client):
    out = await write_setting_tool(values={"a": 1}, variant="bogus")
    assert out["ok"] is False


async def test_write_setting_empty_values(mock_client):
    out = await write_setting_tool(values={})
    assert out["ok"] is False
