from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.filter_wheel")


class FilterWheelMixin:
    async def get_wheel_position(self) -> dict:
        logger.info("get_wheel_position")
        return await self.method_sync("get_wheel_position")

    async def get_wheel_state(self) -> dict:
        logger.info("get_wheel_state")
        return await self.method_sync("get_wheel_state")

    async def get_wheel_setting(self) -> dict:
        logger.info("get_wheel_setting")
        return await self.method_sync("get_wheel_setting")

    async def set_wheel_position(self, position: int) -> dict:
        """Move the filter wheel to a named position.

        Args:
            position: 1-based filter position index.
        """
        if position < 1:
            raise ValueError(f"Filter position must be >= 1, got {position}")
        logger.info("set_wheel_position position=%s", position)
        return await self.method_sync("set_wheel_position", [position])

    async def set_lp_filter(self, enabled: bool) -> dict:
        """Enable or disable the light-pollution filter (LP/lenhance).

        Args:
            enabled: True to insert the LP filter, False to remove it.
        """
        logger.info("set_lp_filter enabled=%s", enabled)
        return await self.method_sync("set_setting", {"stack_lenhance": enabled})
