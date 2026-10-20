"""Filter-wheel tools."""

from typing import Any

from seestar_mcp.tools._util import call


async def get_wheel_position_tool(telescope_id: int = 1) -> Any:
    """Get the current filter-wheel position."""
    return await call(telescope_id, lambda c: c.get_wheel_position())


async def get_wheel_state_tool(telescope_id: int = 1) -> Any:
    """Get the filter-wheel state."""
    return await call(telescope_id, lambda c: c.get_wheel_state())


async def get_wheel_setting_tool(telescope_id: int = 1) -> Any:
    """Get the filter-wheel setting."""
    return await call(telescope_id, lambda c: c.get_wheel_setting())


async def set_wheel_position_tool(position: int, telescope_id: int = 1) -> Any:
    """Move the filter wheel to a position."""
    return await call(telescope_id, lambda c: c.set_wheel_position(position))


async def set_lp_filter_tool(enabled: bool, telescope_id: int = 1) -> Any:
    """Engage or disengage the light-pollution / duo-band filter."""
    return await call(telescope_id, lambda c: c.set_lp_filter(enabled))


def register(mcp: Any) -> None:
    for fn in (
        get_wheel_position_tool,
        get_wheel_state_tool,
        get_wheel_setting_tool,
        set_wheel_position_tool,
        set_lp_filter_tool,
    ):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
