"""Device/view state tools."""

from typing import Any

from seestar_mcp import server


async def get_device_state_tool(telescope_id: int = 1) -> Any:
    """Get the telescope's device state."""
    return await server.call(telescope_id, lambda c: c.get_device_state())


async def get_view_state_tool(telescope_id: int = 1) -> Any:
    """Get the telescope's current view state."""
    return await server.call(telescope_id, lambda c: c.get_view_state())


def register(mcp: Any) -> None:
    mcp.tool(name="get_device_state")(get_device_state_tool)
    mcp.tool(name="get_view_state")(get_view_state_tool)
