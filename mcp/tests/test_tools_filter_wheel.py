from unittest.mock import AsyncMock, MagicMock

import pytest

from seestar_mcp.tools.filter_wheel import (
    get_wheel_position_tool,
    set_lp_filter_tool,
    set_wheel_position_tool,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def make_client_spy(monkeypatch, mock_client):
    spy = MagicMock(return_value=mock_client)
    monkeypatch.setattr("seestar_mcp.server.make_client", spy)
    return spy


async def test_get_wheel_position(make_client_spy, mock_client):
    await get_wheel_position_tool(telescope_id=0)
    make_client_spy.assert_called_once_with(telescope_id=0)
    mock_client.get_wheel_position.assert_awaited_once_with()


async def test_set_wheel_position(make_client_spy, mock_client):
    await set_wheel_position_tool(2)
    mock_client.set_wheel_position.assert_awaited_once_with(2)


async def test_set_lp_filter(make_client_spy, mock_client):
    await set_lp_filter_tool(True)
    mock_client.set_lp_filter.assert_awaited_once_with(True)
