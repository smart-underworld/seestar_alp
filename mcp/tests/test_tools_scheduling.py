from unittest.mock import AsyncMock, MagicMock

import pytest

from seestar_mcp.tools.scheduling import (
    add_schedule_item_tool,
    continue_scheduler_tool,
    create_schedule_tool,
    export_schedule_tool,
    get_schedule_tool,
    import_schedule_tool,
    insert_schedule_item_before_tool,
    pause_scheduler_tool,
    remove_schedule_item_tool,
    replace_schedule_item_tool,
    reset_scheduler_cur_item_tool,
    schedule_mosaic_tool,
    skip_scheduler_cur_item_tool,
    start_mosaic_tool,
    start_scheduler_tool,
    stop_scheduler_tool,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def make_client_spy(monkeypatch, mock_client):
    spy = MagicMock(return_value=mock_client)
    monkeypatch.setattr("seestar_mcp.server.make_client", spy)
    return spy


async def test_add_schedule_item(make_client_spy, mock_client):
    await add_schedule_item_tool("wait_for", {"timer_sec": 5})
    mock_client.add_schedule_item.assert_awaited_once_with("wait_for", {"timer_sec": 5})


@pytest.mark.parametrize(
    "action", ["shutdown", "reboot", "scope_park", "scope_move_to_horizon"]
)
async def test_add_physical_item_requires_confirm(make_client_spy, mock_client, action):
    out = await add_schedule_item_tool(action)
    assert out["ok"] is False and out["requires_confirmation"] is True
    make_client_spy.assert_not_called()
    mock_client.add_schedule_item.assert_not_awaited()


async def test_add_physical_item_with_confirm(make_client_spy, mock_client):
    await add_schedule_item_tool("shutdown", confirm=True)
    mock_client.add_schedule_item.assert_awaited_once_with("shutdown", None)


@pytest.mark.parametrize("action", ["start_mosaic", "wait_for"])
async def test_add_non_physical_item_needs_no_confirm(
    make_client_spy, mock_client, action
):
    await add_schedule_item_tool(action, {"x": 1})
    mock_client.add_schedule_item.assert_awaited_once_with(action, {"x": 1})


async def test_start_scheduler_requires_confirm(make_client_spy, mock_client):
    out = await start_scheduler_tool()
    assert out["ok"] is False and out["requires_confirmation"] is True
    make_client_spy.assert_not_called()
    mock_client.start_scheduler.assert_not_awaited()


async def test_start_scheduler_threads_telescope_id(make_client_spy, mock_client):
    await start_scheduler_tool(telescope_id=2, confirm=True)
    make_client_spy.assert_called_once_with(telescope_id=2)
    mock_client.start_scheduler.assert_awaited_once_with()


async def test_schedule_mosaic(make_client_spy, mock_client):
    await schedule_mosaic_tool("M31", "00:42:44", "+41:16:09", 600, ra_num=2)
    mock_client.schedule_mosaic.assert_awaited_once_with(
        "M31", "00:42:44", "+41:16:09", 600, 2, 1, 20, 80, False, False, False
    )


async def test_start_mosaic_requires_confirm(make_client_spy, mock_client):
    out = await start_mosaic_tool("M31", 10.5, 41.2, 300)
    assert out["ok"] is False and out["requires_confirmation"] is True
    make_client_spy.assert_not_called()
    mock_client.start_mosaic.assert_not_awaited()


async def test_start_mosaic(make_client_spy, mock_client):
    await start_mosaic_tool(
        "M31", 10.5, 41.2, 300, gain=90, is_j2000=True, confirm=True
    )
    mock_client.start_mosaic.assert_awaited_once_with(
        "M31", 10.5, 41.2, 300, 1, 1, 20, 90, False, False, True
    )


async def test_import_export(make_client_spy, mock_client):
    await export_schedule_tool("/tmp/s.json")
    mock_client.export_schedule.assert_awaited_once_with("/tmp/s.json")
    await import_schedule_tool("/tmp/s.json")
    mock_client.import_schedule.assert_awaited_once_with("/tmp/s.json", False)


@pytest.mark.parametrize(
    "tool,method",
    [
        (get_schedule_tool, "get_schedule"),
        (create_schedule_tool, "create_schedule"),
        (stop_scheduler_tool, "stop_scheduler"),
    ],
)
async def test_no_arg_tools(make_client_spy, mock_client, tool, method):
    await tool()
    getattr(mock_client, method).assert_awaited_once_with()


# ── scheduler operation tools ────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool,method",
    [
        (pause_scheduler_tool, "pause_scheduler"),
        (continue_scheduler_tool, "continue_scheduler"),
        (skip_scheduler_cur_item_tool, "skip_scheduler_cur_item"),
        (reset_scheduler_cur_item_tool, "reset_scheduler_cur_item"),
    ],
)
async def test_scheduler_operation_tools(make_client_spy, mock_client, tool, method):
    await tool()
    getattr(mock_client, method).assert_awaited_once_with()


# ── schedule editing tools ───────────────────────────────────────────────


async def test_remove_schedule_item(make_client_spy, mock_client):
    await remove_schedule_item_tool("abc123")
    mock_client.remove_schedule_item.assert_awaited_once_with("abc123")


async def test_replace_schedule_item(make_client_spy, mock_client):
    await replace_schedule_item_tool("id1", "start_mosaic", {"gain": 80})
    mock_client.replace_schedule_item.assert_awaited_once_with(
        "id1", "start_mosaic", {"gain": 80}
    )


async def test_insert_schedule_item_before(make_client_spy, mock_client):
    await insert_schedule_item_before_tool("id1", "wait_for", {"timer_sec": 5})
    mock_client.insert_schedule_item_before.assert_awaited_once_with(
        "id1", "wait_for", {"timer_sec": 5}
    )


@pytest.mark.parametrize(
    "action", ["shutdown", "reboot", "scope_park", "scope_move_to_horizon"]
)
async def test_replace_physical_requires_confirm(make_client_spy, mock_client, action):
    out = await replace_schedule_item_tool("id1", action)
    assert out["ok"] is False and out["requires_confirmation"] is True
    make_client_spy.assert_not_called()
    mock_client.replace_schedule_item.assert_not_awaited()


async def test_insert_physical_with_confirm(make_client_spy, mock_client):
    await insert_schedule_item_before_tool("id1", "shutdown", confirm=True)
    mock_client.insert_schedule_item_before.assert_awaited_once_with(
        "id1", "shutdown", None
    )
