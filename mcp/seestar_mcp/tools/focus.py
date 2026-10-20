"""Focuser / autofocus tools."""

from typing import Any

from seestar_mcp.tools._util import call


async def get_focuser_position_tool(telescope_id: int = 1) -> Any:
    """Get the current focuser position (step)."""
    return await call(telescope_id, lambda c: c.get_focuser_position())


async def adjust_focus_tool(steps: int, telescope_id: int = 1) -> Any:
    """Move the focuser by a relative number of steps."""
    return await call(telescope_id, lambda c: c.adjust_focus(steps))


async def start_auto_focus_tool(telescope_id: int = 1) -> Any:
    """Start an autofocus run."""
    return await call(telescope_id, lambda c: c.start_auto_focus())


async def stop_auto_focus_tool(telescope_id: int = 1) -> Any:
    """Stop an in-progress autofocus run."""
    return await call(telescope_id, lambda c: c.stop_auto_focus())


def register(mcp: Any) -> None:
    for fn in (
        get_focuser_position_tool,
        adjust_focus_tool,
        start_auto_focus_tool,
        stop_auto_focus_tool,
    ):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
