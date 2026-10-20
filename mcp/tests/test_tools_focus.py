from unittest.mock import AsyncMock, MagicMock

import pytest

from seestar_mcp.tools.focus import (
    adjust_focus_tool,
    get_focuser_position_tool,
    start_auto_focus_tool,
    stop_auto_focus_tool,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def make_client_spy(monkeypatch, mock_client):
    spy = MagicMock(return_value=mock_client)
    monkeypatch.setattr("seestar_mcp.server.make_client", spy)
    return spy


async def test_get_focuser_position(make_client_spy, mock_client):
    await get_focuser_position_tool(telescope_id=0)
    make_client_spy.assert_called_once_with(telescope_id=0)
    mock_client.get_focuser_position.assert_awaited_once_with()


async def test_adjust_focus(make_client_spy, mock_client):
    await adjust_focus_tool(50)
    mock_client.adjust_focus.assert_awaited_once_with(50)


async def test_start_auto_focus(make_client_spy, mock_client):
    await start_auto_focus_tool()
    mock_client.start_auto_focus.assert_awaited_once_with()


async def test_stop_auto_focus(make_client_spy, mock_client):
    await stop_auto_focus_tool()
    mock_client.stop_auto_focus.assert_awaited_once_with()
