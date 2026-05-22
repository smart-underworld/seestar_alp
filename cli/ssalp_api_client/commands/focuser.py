from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.focuser")


class FocuserMixin:
    async def get_focuser_position(self, ret_obj: bool = False) -> dict:
        """Get the current focuser position.

        Args:
            ret_obj: If True, return a full object instead of a scalar.
        """
        logger.info("get_focuser_position ret_obj=%s", ret_obj)
        params = {"ret_obj": True} if ret_obj else None
        return await self.method_sync("get_focuser_position", params)

    async def adjust_focus(self, steps: int) -> dict:
        """Move the focuser by a relative number of steps.

        Args:
            steps: Positive values move in one direction, negative the other.
        """
        logger.info("adjust_focus steps=%s", steps)
        return await self.action("adjust_focus", {"steps": steps})

    async def start_auto_focus(self) -> dict:
        logger.info("start_auto_focus")
        # Preserved API typo: "focuse" not "focus"
        return await self.method_sync("start_auto_focuse")

    async def stop_auto_focus(self) -> dict:
        logger.info("stop_auto_focus")
        # Preserved API typo: "focuse" not "focus"
        return await self.method_sync("stop_auto_focuse")
