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


async def startup_sequence_tool(lat: float, lon: float, telescope_id: int = 1) -> Any:
    """Run the Seestar startup/initialization sequence for a location
    (lat/lon in degrees). Moves the mount; run only when the user is setting up."""
    return await call(telescope_id, lambda c: c.startup_sequence(lat, lon))


async def set_heater_tool(state: bool, value: int = 90, telescope_id: int = 1) -> Any:
    """Turn the dew heater on/off (value is the heater level when on)."""
    return await call(telescope_id, lambda c: c.set_heater(state, value))


def register(mcp: Any) -> None:
    for fn in (
        scope_park_tool,
        scope_move_to_horizon_tool,
        reboot_tool,
        shutdown_tool,
        startup_sequence_tool,
        set_heater_tool,
    ):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
