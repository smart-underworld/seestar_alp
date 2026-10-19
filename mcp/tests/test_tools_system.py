from unittest.mock import AsyncMock, MagicMock

import pytest

from seestar_mcp.tools.system import (
    reboot_tool,
    scope_move_to_horizon_tool,
    scope_park_tool,
    shutdown_tool,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def make_client_spy(monkeypatch, mock_client):
    spy = MagicMock(return_value=mock_client)
    monkeypatch.setattr("seestar_mcp.server.make_client", spy)
    return spy


CASES = [
    (scope_park_tool, "scope_park"),
    (scope_move_to_horizon_tool, "scope_move_to_horizon"),
    (reboot_tool, "pi_reboot"),
    (shutdown_tool, "pi_shutdown"),
]


@pytest.mark.parametrize("tool,method", CASES)
async def test_blocked_without_confirm(make_client_spy, mock_client, tool, method):
    out = await tool(confirm=False)
    assert out["requires_confirmation"] is True
    assert out["ok"] is False
    getattr(mock_client, method).assert_not_awaited()
    make_client_spy.assert_not_called()


@pytest.mark.parametrize("tool,method", CASES)
async def test_default_is_blocked(make_client_spy, mock_client, tool, method):
    out = await tool()
    assert out["requires_confirmation"] is True
    getattr(mock_client, method).assert_not_awaited()


@pytest.mark.parametrize("tool,method", CASES)
async def test_runs_with_confirm(make_client_spy, mock_client, tool, method):
    await tool(confirm=True, telescope_id=2)
    getattr(mock_client, method).assert_awaited_once_with()
    make_client_spy.assert_called_once_with(telescope_id=2)
