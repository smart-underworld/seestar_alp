"""Pointing / goto / plate-solve tools."""

from typing import Any

from seestar_mcp import server


async def goto_target_tool(
    target_name: str,
    ra: str | float,
    dec: str | float,
    is_j2000: bool = True,
    telescope_id: int = 1,
) -> Any:
    """Slew to a named target at RA/Dec (decimal or sexagesimal)."""
    return await server.call(
        telescope_id, lambda c: c.goto_target(target_name, ra, dec, is_j2000)
    )


async def scope_goto_tool(
    ra: str | float, dec: str | float, telescope_id: int = 1
) -> Any:
    """Slew to RA/Dec."""
    return await server.call(telescope_id, lambda c: c.scope_goto(ra, dec))


async def start_solve_tool(telescope_id: int = 1) -> Any:
    """Start a plate solve."""
    return await server.call(telescope_id, lambda c: c.start_solve())


async def get_solve_result_tool(telescope_id: int = 1) -> Any:
    """Get the latest plate-solve result."""
    return await server.call(telescope_id, lambda c: c.get_solve_result())


async def is_goto_completed_ok_tool(telescope_id: int = 1) -> Any:
    """Check whether the last goto completed successfully."""
    return await server.call(telescope_id, lambda c: c.is_goto_completed_ok())


async def stop_goto_target_tool(telescope_id: int = 1) -> Any:
    """Stop the in-progress goto."""
    return await server.call(telescope_id, lambda c: c.stop_goto_target())


def register(mcp: Any) -> None:
    for fn in (
        goto_target_tool,
        scope_goto_tool,
        start_solve_tool,
        get_solve_result_tool,
        is_goto_completed_ok_tool,
        stop_goto_target_tool,
    ):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
