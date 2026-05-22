from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.mount")


class MountMixin:
    async def scope_goto(self, ra: float, dec: float) -> dict:
        """Slew to equatorial coordinates (RA in hours, Dec in degrees)."""
        logger.info("scope_goto ra=%s dec=%s", ra, dec)
        return await self.method_sync("scope_goto", [ra, dec])

    async def goto_target(
        self,
        target_name: str,
        ra: str | float,
        dec: str | float,
        is_j2000: bool = True,
    ) -> dict:
        """Slew to a named target. RA/Dec may be decimal or sexagesimal strings."""
        logger.info("goto_target name=%s ra=%s dec=%s j2000=%s", target_name, ra, dec, is_j2000)
        return await self.action(
            "goto_target",
            {"target_name": target_name, "ra": ra, "dec": dec, "is_j2000": is_j2000},
        )

    async def scope_park(self) -> dict:
        logger.info("scope_park")
        return await self.method_sync("scope_park")

    async def scope_move_to_horizon(self) -> dict:
        logger.info("scope_move_to_horizon")
        return await self.method_sync("scope_move_to_horizon")

    async def scope_get_equ_coord(self) -> dict:
        logger.info("scope_get_equ_coord")
        return await self.method_sync("scope_get_equ_coord")

    async def scope_get_horiz_coord(self) -> dict:
        logger.info("scope_get_horiz_coord")
        return await self.method_sync("scope_get_horiz_coord")

    async def scope_get_ra_dec(self) -> dict:
        logger.info("scope_get_ra_dec")
        return await self.method_sync("scope_get_ra_dec")

    async def scope_get_track_state(self) -> dict:
        logger.info("scope_get_track_state")
        return await self.method_sync("scope_get_track_state")

    async def scope_set_track_state(self, enabled: bool) -> dict:
        logger.info("scope_set_track_state enabled=%s", enabled)
        return await self.method_sync("scope_set_track_state", enabled)

    async def scope_speed_move(self, speed: int, angle: float, dur_sec: float) -> dict:
        """Move the mount at a given speed and angle for a duration.

        Args:
            speed: Move speed (0 = stop).
            angle: Direction angle in degrees.
            dur_sec: Duration in seconds.
        """
        logger.info("scope_speed_move speed=%s angle=%s dur_sec=%s", speed, angle, dur_sec)
        return await self.method_sync(
            "scope_speed_move", {"speed": speed, "angle": angle, "dur_sec": dur_sec}
        )

    async def scope_sync(self, ra: float, dec: float) -> dict:
        """Sync the mount to the given RA/Dec position."""
        logger.info("scope_sync ra=%s dec=%s", ra, dec)
        return await self.method_sync("scope_sync", [ra, dec])

    async def start_solve(self) -> dict:
        logger.info("start_solve")
        return await self.method_sync("start_solve")

    async def get_solve_result(self) -> dict:
        logger.info("get_solve_result")
        return await self.method_sync("get_solve_result")

    async def get_last_solve_result(self) -> dict:
        logger.info("get_last_solve_result")
        return await self.method_sync("get_last_solve_result")

    async def stop_plate_solve_loop(self) -> dict:
        logger.info("stop_plate_solve_loop")
        return await self.action("stop_plate_solve_loop", {})

    async def start_polar_align(self) -> dict:
        logger.info("start_polar_align")
        return await self.method_sync("start_polar_align")

    async def get_pa_error(self) -> dict:
        logger.info("get_pa_error")
        return await self.action("get_pa_error", {})

    async def adjust_mag_declination(
        self, adjust: bool = True, fudge_angle: float = 0.0
    ) -> dict:
        logger.info("adjust_mag_declination adjust=%s fudge_angle=%s", adjust, fudge_angle)
        return await self.action(
            "adjust_mag_declination",
            {"adjust_mag_dec": adjust, "fudge_angle": fudge_angle},
        )

    async def is_goto(self) -> dict:
        logger.info("is_goto")
        return await self.action("is_goto", {})

    async def is_goto_completed_ok(self) -> dict:
        logger.info("is_goto_completed_ok")
        return await self.action("is_goto_completed_ok", {})

    async def stop_goto_target(self) -> dict:
        logger.info("stop_goto_target")
        return await self.action("stop_goto_target", {})

    async def set_below_horizon_dec_offset(self, offset: float = 0.0) -> dict:
        logger.info("set_below_horizon_dec_offset offset=%s", offset)
        return await self.action("set_below_horizon_dec_offset", {"offset": offset})

    async def set_dither(self, pix: int, interval: int, enable: bool = True) -> dict:
        logger.info("set_dither pix=%s interval=%s enable=%s", pix, interval, enable)
        return await self.method_sync(
            "set_setting",
            {"stack_dither": {"pix": pix, "interval": interval, "enable": enable}},
        )

    async def set_3ppa_calibration(self, enabled: bool = True) -> dict:
        logger.info("set_3ppa_calibration enabled=%s", enabled)
        return await self.method_sync("set_setting", {"auto_3ppa_calib": enabled})

    async def set_stack_setting(self, **kwargs) -> dict:
        logger.info("set_stack_setting kwargs=%s", kwargs)
        return await self.method_sync("set_stack_setting", kwargs)
