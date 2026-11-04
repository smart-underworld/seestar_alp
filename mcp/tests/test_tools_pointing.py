from unittest.mock import AsyncMock, MagicMock

import pytest

from seestar_mcp.tools.pointing import (
    check_target_visibility_tool,
    get_horizon_tool,
    get_pa_error_tool,
    get_solve_result_tool,
    goto_target_tool,
    is_goto_completed_ok_tool,
    polar_align_tool,
    scope_goto_tool,
    set_3ppa_calibration_tool,
    start_solve_tool,
    stop_goto_target_tool,
)
from seestar_mcp.tools.state import get_device_state_tool, get_view_state_tool


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def make_client_spy(monkeypatch, mock_client):
    spy = MagicMock(return_value=mock_client)
    monkeypatch.setattr("seestar_mcp.server.make_client", spy)
    return spy


async def test_goto_target_accepts_sexagesimal(make_client_spy, mock_client):
    await goto_target_tool(target_name="M31", ra="00:42:44", dec="+41:16:09")
    mock_client.goto_target.assert_awaited_once_with(
        "M31", "00:42:44", "+41:16:09", True
    )


async def test_get_device_state_threads_telescope_id(make_client_spy):
    await get_device_state_tool(telescope_id=0)
    make_client_spy.assert_called_once_with(telescope_id=0)


async def test_get_view_state(make_client_spy, mock_client):
    await get_view_state_tool()
    mock_client.get_view_state.assert_awaited_once_with()


async def test_polar_align(make_client_spy, mock_client):
    await polar_align_tool()
    mock_client.start_polar_align.assert_awaited_once_with()


async def test_get_pa_error(make_client_spy, mock_client):
    await get_pa_error_tool(telescope_id=0)
    make_client_spy.assert_called_once_with(telescope_id=0)
    mock_client.get_pa_error.assert_awaited_once_with()


async def test_set_3ppa_calibration(make_client_spy, mock_client):
    await set_3ppa_calibration_tool(enabled=False)
    mock_client.set_3ppa_calibration.assert_awaited_once_with(False)


async def test_scope_goto(make_client_spy, mock_client):
    await scope_goto_tool(ra=1.5, dec=-2.0)
    mock_client.scope_goto.assert_awaited_once_with(1.5, -2.0)


@pytest.mark.parametrize(
    "tool,method",
    [
        (start_solve_tool, "start_solve"),
        (get_solve_result_tool, "get_solve_result"),
        (is_goto_completed_ok_tool, "is_goto_completed_ok"),
        (stop_goto_target_tool, "stop_goto_target"),
    ],
)
async def test_no_arg_tools(make_client_spy, mock_client, tool, method):
    await tool()
    getattr(mock_client, method).assert_awaited_once_with()


async def test_client_error_mapped(make_client_spy, mock_client):
    from ssalp_api_client import SSAlpError

    mock_client.start_solve.side_effect = SSAlpError("boom")
    assert await start_solve_tool() == {"ok": False, "error": "boom"}


async def test_get_horizon(make_client_spy, mock_client):
    await get_horizon_tool(telescope_id=0)
    make_client_spy.assert_called_once_with(telescope_id=0)
    mock_client.get_horizon.assert_awaited_once_with()


async def test_check_target_visibility_accepts_sexagesimal(
    make_client_spy, mock_client
):
    await check_target_visibility_tool(ra="00:42:44", dec="+41:16:09")
    mock_client.check_target_visibility.assert_awaited_once_with(
        "00:42:44", "+41:16:09", True
    )
