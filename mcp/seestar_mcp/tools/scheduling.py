"""Scheduler and mosaic tools."""

from typing import Any

from seestar_mcp.safety import PHYSICAL_ACTIONS, gate, require_confirm
from seestar_mcp.tools._util import call


async def get_schedule_tool(telescope_id: int = 1) -> Any:
    """Get the current schedule."""
    return await call(telescope_id, lambda c: c.get_schedule())


async def create_schedule_tool(telescope_id: int = 1) -> Any:
    """Create a new (empty) schedule."""
    return await call(telescope_id, lambda c: c.create_schedule())


async def add_schedule_item_tool(
    action: str,
    params: dict | None = None,
    telescope_id: int = 1,
    confirm: bool = False,
) -> Any:
    """Add an item with the given action and params to the schedule.

    Physical actions (park, horizon, reboot, shutdown) run unattended when the
    scheduler starts, so they require confirm=true after the user confirms."""
    if action in PHYSICAL_ACTIONS:
        refusal = gate(action, confirm)
        if refusal is not None:
            return refusal
    return await call(telescope_id, lambda c: c.add_schedule_item(action, params))


async def schedule_mosaic_tool(
    target_name: str,
    ra: str | float,
    dec: str | float,
    session_time_sec: int,
    ra_num: int = 1,
    dec_num: int = 1,
    panel_overlap_percent: int = 20,
    gain: int = 80,
    is_use_lp_filter: bool = False,
    is_use_autofocus: bool = False,
    is_j2000: bool = False,
    telescope_id: int = 1,
) -> Any:
    """Add a mosaic imaging item to the schedule."""
    return await call(
        telescope_id,
        lambda c: c.schedule_mosaic(
            target_name,
            ra,
            dec,
            session_time_sec,
            ra_num,
            dec_num,
            panel_overlap_percent,
            gain,
            is_use_lp_filter,
            is_use_autofocus,
            is_j2000,
        ),
    )


async def start_mosaic_tool(
    target_name: str,
    ra: str | float,
    dec: str | float,
    session_time_sec: int,
    ra_num: int = 1,
    dec_num: int = 1,
    panel_overlap_percent: int = 20,
    gain: int = 80,
    is_use_lp_filter: bool = False,
    is_use_autofocus: bool = False,
    is_j2000: bool = False,
    telescope_id: int = 1,
    confirm: bool = False,
) -> Any:
    """Start a mosaic capture immediately (outside the scheduler).

    Begins an unattended capture that moves the mount, so it requires
    confirm=true after the user confirms (like start_scheduler)."""
    refusal = require_confirm(
        "start_mosaic",
        confirm,
        "start_mosaic begins an unattended capture that moves the mount; "
        "pass confirm=true after the user confirms",
    )
    if refusal is not None:
        return refusal
    return await call(
        telescope_id,
        lambda c: c.start_mosaic(
            target_name,
            ra,
            dec,
            session_time_sec,
            ra_num,
            dec_num,
            panel_overlap_percent,
            gain,
            is_use_lp_filter,
            is_use_autofocus,
            is_j2000,
        ),
    )


async def start_scheduler_tool(telescope_id: int = 1, confirm: bool = False) -> Any:
    """Start the scheduler (an unattended run; requires confirm=true after the user confirms)."""
    refusal = require_confirm(
        "start_scheduler",
        confirm,
        "start_scheduler launches an unattended run; pass confirm=true after the user confirms",
    )
    if refusal is not None:
        return refusal
    return await call(telescope_id, lambda c: c.start_scheduler())


async def stop_scheduler_tool(telescope_id: int = 1) -> Any:
    """Stop the scheduler."""
    return await call(telescope_id, lambda c: c.stop_scheduler())


async def export_schedule_tool(filepath: str, telescope_id: int = 1) -> Any:
    """Export the schedule to a file."""
    return await call(telescope_id, lambda c: c.export_schedule(filepath))


async def import_schedule_tool(
    filepath: str, retain_state: bool = False, telescope_id: int = 1
) -> Any:
    """Import a schedule from a file."""
    return await call(telescope_id, lambda c: c.import_schedule(filepath, retain_state))


async def pause_scheduler_tool(telescope_id: int = 1) -> Any:
    """Pause a running scheduler (it can be resumed with continue_scheduler)."""
    return await call(telescope_id, lambda c: c.pause_scheduler())


async def continue_scheduler_tool(telescope_id: int = 1) -> Any:
    """Resume a paused scheduler."""
    return await call(telescope_id, lambda c: c.continue_scheduler())


async def skip_scheduler_cur_item_tool(telescope_id: int = 1) -> Any:
    """Skip the scheduler's current item and advance to the next one."""
    return await call(telescope_id, lambda c: c.skip_scheduler_cur_item())


async def reset_scheduler_cur_item_tool(telescope_id: int = 1) -> Any:
    """Restart the scheduler's current item from the beginning."""
    return await call(telescope_id, lambda c: c.reset_scheduler_cur_item())


async def remove_schedule_item_tool(
    schedule_item_id: str, telescope_id: int = 1
) -> Any:
    """Remove the schedule item with the given id."""
    return await call(telescope_id, lambda c: c.remove_schedule_item(schedule_item_id))


async def replace_schedule_item_tool(
    item_id: str,
    action: str,
    params: dict | None = None,
    telescope_id: int = 1,
    confirm: bool = False,
) -> Any:
    """Replace the schedule item with the given id with a new action/params.

    A physical action (park, horizon, reboot, shutdown) requires confirm=true,
    as with add_schedule_item."""
    if action in PHYSICAL_ACTIONS:
        refusal = gate(action, confirm)
        if refusal is not None:
            return refusal
    return await call(
        telescope_id, lambda c: c.replace_schedule_item(item_id, action, params)
    )


async def insert_schedule_item_before_tool(
    before_id: str,
    action: str,
    params: dict | None = None,
    telescope_id: int = 1,
    confirm: bool = False,
) -> Any:
    """Insert a new item with the given action/params before the item with
    before_id.

    A physical action (park, horizon, reboot, shutdown) requires confirm=true,
    as with add_schedule_item."""
    if action in PHYSICAL_ACTIONS:
        refusal = gate(action, confirm)
        if refusal is not None:
            return refusal
    return await call(
        telescope_id,
        lambda c: c.insert_schedule_item_before(before_id, action, params),
    )


def register(mcp: Any) -> None:
    for fn in (
        get_schedule_tool,
        create_schedule_tool,
        add_schedule_item_tool,
        schedule_mosaic_tool,
        start_mosaic_tool,
        start_scheduler_tool,
        stop_scheduler_tool,
        pause_scheduler_tool,
        continue_scheduler_tool,
        skip_scheduler_cur_item_tool,
        reset_scheduler_cur_item_tool,
        remove_schedule_item_tool,
        replace_schedule_item_tool,
        insert_schedule_item_before_tool,
        export_schedule_tool,
        import_schedule_tool,
    ):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
