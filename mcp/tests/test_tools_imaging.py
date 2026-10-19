from unittest.mock import AsyncMock, MagicMock

import pytest

from seestar_mcp.tools.imaging import (
    get_last_image_tool,
    set_exposure_tool,
    set_gain_tool,
    start_stack_tool,
    stop_view_tool,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def make_client_spy(monkeypatch, mock_client):
    spy = MagicMock(return_value=mock_client)
    monkeypatch.setattr("seestar_mcp.server.make_client", spy)
    return spy


async def test_start_stack_passes_gain_and_restart(make_client_spy, mock_client):
    await start_stack_tool(gain=80, restart=False)
    mock_client.start_stack.assert_awaited_once_with(80, restart=False)


async def test_start_stack_default_restart(make_client_spy, mock_client):
    await start_stack_tool(gain=80)
    mock_client.start_stack.assert_awaited_once_with(80, restart=True)


async def test_stop_view_with_stage(make_client_spy, mock_client):
    await stop_view_tool(stage="AutoGoto")
    mock_client.stop_view.assert_awaited_once_with(stage="AutoGoto")


async def test_stop_view_default_stage(make_client_spy, mock_client):
    await stop_view_tool()
    mock_client.stop_view.assert_awaited_once_with(stage=None)


async def test_set_gain(make_client_spy, mock_client):
    await set_gain_tool(gain=60)
    mock_client.set_gain.assert_awaited_once_with(60)


async def test_set_exposure(make_client_spy, mock_client):
    await set_exposure_tool(stack_l_ms=10000, continuous_ms=500)
    mock_client.set_exposure.assert_awaited_once_with(10000, 500)


async def test_get_last_image_returns_dict_as_is(make_client_spy, mock_client):
    mock_client.get_last_image.return_value = {"id": 7, "url": "/img/7"}
    assert await get_last_image_tool() == {"id": 7, "url": "/img/7"}
    mock_client.get_last_image.assert_awaited_once_with()


async def test_telescope_id_threaded(make_client_spy):
    await set_gain_tool(gain=1, telescope_id=2)
    make_client_spy.assert_called_once_with(telescope_id=2)
