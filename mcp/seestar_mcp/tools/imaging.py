"""Imaging / stacking / exposure tools."""

from typing import Any

from seestar_mcp.tools._util import call


async def start_stack_tool(
    gain: int, restart: bool = True, telescope_id: int = 1
) -> Any:
    """Start live-stacking at the given sensor gain."""
    return await call(telescope_id, lambda c: c.start_stack(gain, restart=restart))


async def stop_view_tool(stage: str | None = None, telescope_id: int = 1) -> Any:
    """Stop the current live view / stacking session."""
    return await call(telescope_id, lambda c: c.stop_view(stage=stage))


async def set_gain_tool(gain: int, telescope_id: int = 1) -> Any:
    """Set the sensor gain."""
    return await call(telescope_id, lambda c: c.set_gain(gain))


async def set_exposure_tool(
    stack_l_ms: int, continuous_ms: int, telescope_id: int = 1
) -> Any:
    """Set stacking and continuous exposure times in milliseconds."""
    return await call(telescope_id, lambda c: c.set_exposure(stack_l_ms, continuous_ms))


async def get_last_image_tool(telescope_id: int = 1) -> Any:
    """Get metadata (id/URL) for the last captured image; no raw bytes."""
    return await call(telescope_id, lambda c: c.get_last_image())


async def create_dark_tool(telescope_id: int = 1) -> Any:
    """Capture dark frames (dark-frame calibration). Cap the lens first."""
    return await call(telescope_id, lambda c: c.start_create_dark())


def register(mcp: Any) -> None:
    for fn in (
        start_stack_tool,
        stop_view_tool,
        set_gain_tool,
        set_exposure_tool,
        get_last_image_tool,
        create_dark_tool,
    ):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
