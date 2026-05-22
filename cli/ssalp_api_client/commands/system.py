from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.system")


class SystemMixin:
    async def startup_sequence(self, lat: float, lon: float) -> dict:
        logger.info("startup_sequence lat=%s lon=%s", lat, lon)
        return await self.action("action_start_up_sequence", {"lat": lat, "lon": lon})

    async def pi_reboot(self) -> dict:
        logger.info("pi_reboot")
        return await self.method_sync("pi_reboot")

    async def pi_shutdown(self) -> dict:
        logger.info("pi_shutdown")
        return await self.method_sync("pi_shutdown")

    async def pi_is_verified(self) -> dict:
        logger.info("pi_is_verified")
        return await self.method_sync("pi_is_verified")

    async def play_sound(self, sound_id: int) -> dict:
        logger.info("play_sound id=%s", sound_id)
        return await self.action("play_sound", {"id": sound_id})

    async def set_heater(self, state: bool, value: int = 90) -> dict:
        """Control the dew heater.

        Args:
            state: True to enable heater, False to disable.
            value: Heater power level (0-100).
        """
        if not 0 <= value <= 100:
            raise ValueError(f"Heater value must be 0-100, got {value}")
        logger.info("set_heater state=%s value=%s", state, value)
        return await self.method_sync(
            "pi_output_set2", {"heater": {"state": state, "value": value}}
        )
