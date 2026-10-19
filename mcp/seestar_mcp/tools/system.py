"""System / physical tools. Every tool is guarded by the confirmation gate."""

from typing import Any

from seestar_mcp.safety import gate
from seestar_mcp.tools._util import call


async def scope_park_tool(confirm: bool = False, telescope_id: int = 1) -> Any:
    """Park the scope (physical motion). Requires confirm=true."""
    refusal = gate("scope_park", confirm)
    if refusal is not None:
        return refusal
    return await call(telescope_id, lambda c: c.scope_park())


async def scope_move_to_horizon_tool(
    confirm: bool = False, telescope_id: int = 1
) -> Any:
    """Move the scope to the horizon (physical motion). Requires confirm=true."""
    refusal = gate("scope_move_to_horizon", confirm)
    if refusal is not None:
        return refusal
    return await call(telescope_id, lambda c: c.scope_move_to_horizon())


async def reboot_tool(confirm: bool = False, telescope_id: int = 1) -> Any:
    """Reboot the Seestar. Requires confirm=true."""
    refusal = gate("reboot", confirm)
    if refusal is not None:
        return refusal
    return await call(telescope_id, lambda c: c.pi_reboot())


async def shutdown_tool(confirm: bool = False, telescope_id: int = 1) -> Any:
    """Shut down the Seestar. Requires confirm=true."""
    refusal = gate("shutdown", confirm)
    if refusal is not None:
        return refusal
    return await call(telescope_id, lambda c: c.pi_shutdown())


def register(mcp: Any) -> None:
    for fn in (scope_park_tool, scope_move_to_horizon_tool, reboot_tool, shutdown_tool):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
