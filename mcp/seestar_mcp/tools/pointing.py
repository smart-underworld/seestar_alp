"""Pointing / goto / plate-solve tools."""

from typing import Any

from seestar_mcp.tools._util import call


async def goto_target_tool(
    target_name: str,
    ra: str | float,
    dec: str | float,
    is_j2000: bool = True,
    telescope_id: int = 1,
) -> Any:
    """Slew to a named target at RA/Dec (decimal or sexagesimal)."""
    return await call(
        telescope_id, lambda c: c.goto_target(target_name, ra, dec, is_j2000)
    )


async def scope_goto_tool(
    ra: str | float, dec: str | float, telescope_id: int = 1
) -> Any:
    """Slew to RA/Dec."""
    return await call(telescope_id, lambda c: c.scope_goto(ra, dec))


async def start_solve_tool(telescope_id: int = 1) -> Any:
    """Start a plate solve."""
    return await call(telescope_id, lambda c: c.start_solve())


async def get_solve_result_tool(telescope_id: int = 1) -> Any:
    """Get the latest plate-solve result."""
    return await call(telescope_id, lambda c: c.get_solve_result())


async def is_goto_completed_ok_tool(telescope_id: int = 1) -> Any:
    """Check whether the last goto completed successfully."""
    return await call(telescope_id, lambda c: c.is_goto_completed_ok())


async def stop_goto_target_tool(telescope_id: int = 1) -> Any:
    """Stop the in-progress goto."""
    return await call(telescope_id, lambda c: c.stop_goto_target())


async def polar_align_tool(telescope_id: int = 1) -> Any:
    """Start a polar alignment (3-point / 3PPA). Moves the mount; run only
    when the user asked to align. Poll get_pa_error for the result."""
    return await call(telescope_id, lambda c: c.start_polar_align())


async def get_pa_error_tool(telescope_id: int = 1) -> Any:
    """Get the current polar-alignment error (pa_error_alt / pa_error_az).
    Values of 9999.9 mean no alignment has been measured yet."""
    return await call(telescope_id, lambda c: c.get_pa_error())


async def set_3ppa_calibration_tool(enabled: bool = True, telescope_id: int = 1) -> Any:
    """Enable or disable automatic 3-point polar-align calibration
    (the auto_3ppa_calib setting)."""
    return await call(telescope_id, lambda c: c.set_3ppa_calibration(enabled))


async def get_horizon_tool(telescope_id: int = 1) -> Any:
    """Get the site's horizon profile: obstruction altitude by azimuth
    (`points`, and `limits_5deg`, the highest altitude every 5 degrees), the
    horizon file and the scheduler's skip settings. No points: flat horizon."""
    return await call(telescope_id, lambda c: c.get_horizon())


async def check_target_visibility_tool(
    ra: str | float, dec: str | float, is_j2000: bool = True, telescope_id: int = 1
) -> Any:
    """Check whether a target clears the site's horizon right now: its
    altitude and azimuth, the horizon altitude at that azimuth, and `visible`.
    Check before a goto: a target behind trees or a roof fails to plate-solve."""
    return await call(
        telescope_id, lambda c: c.check_target_visibility(ra, dec, is_j2000)
    )


def register(mcp: Any) -> None:
    for fn in (
        goto_target_tool,
        scope_goto_tool,
        start_solve_tool,
        get_solve_result_tool,
        is_goto_completed_ok_tool,
        stop_goto_target_tool,
        polar_align_tool,
        get_pa_error_tool,
        set_3ppa_calibration_tool,
        get_horizon_tool,
        check_target_visibility_tool,
    ):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
