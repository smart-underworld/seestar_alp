from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.camera")


class CameraMixin:
    async def start_exposure(self, exp_type: str = "light", stack: bool = False) -> dict:
        """Begin an exposure.

        Args:
            exp_type: Exposure type (e.g. ``"light"``).
            stack: Whether to stack the frame.
        """
        if exp_type not in {"light", "dark", "flat", "bias"}:
            raise ValueError(f"exp_type must be light/dark/flat/bias, got {exp_type!r}")
        logger.info("start_exposure type=%s stack=%s", exp_type, stack)
        return await self.method_sync("start_exposure", [exp_type, stack])

    async def stop_exposure(self) -> dict:
        logger.info("stop_exposure")
        return await self.method_sync("stop_exposure")

    async def start_stack(self, gain: int, restart: bool = True) -> dict:
        """Start live-stacking.

        Args:
            gain: Sensor gain value.
            restart: Whether to discard and restart any existing stack.
        """
        if gain < 0:
            raise ValueError(f"gain must be non-negative, got {gain}")
        logger.info("start_stack gain=%s restart=%s", gain, restart)
        return await self.action("start_stack", {"gain": gain, "restart": restart})

    async def stop_view(self, stage: str | None = None) -> dict:
        """Stop the current live view / stacking session.

        Args:
            stage: Optional stage name (e.g. ``"DarkLibrary"``, ``"AutoGoto"``).
        """
        logger.info("stop_view stage=%s", stage)
        params: dict | None = {"stage": stage} if stage is not None else None
        return await self.method_sync("iscope_stop_view", params)

    async def set_gain(self, gain: int) -> dict:
        if gain < 0:
            raise ValueError(f"gain must be non-negative, got {gain}")
        logger.info("set_gain gain=%s", gain)
        return await self.method_sync("set_control_value", ["gain", gain])

    async def set_exposure(self, stack_l_ms: int, continuous_ms: int) -> dict:
        """Set exposure times for stacking and continuous modes.

        Args:
            stack_l_ms: Stacking exposure in milliseconds.
            continuous_ms: Continuous/live view exposure in milliseconds.
        """
        if stack_l_ms <= 0 or continuous_ms <= 0:
            raise ValueError("Exposure times must be positive")
        logger.info("set_exposure stack_l_ms=%s continuous_ms=%s", stack_l_ms, continuous_ms)
        return await self.method_sync(
            "set_setting", {"exp_ms": {"stack_l": stack_l_ms, "continuous": continuous_ms}}
        )

    async def set_brightness(self, percent: int) -> dict:
        """Set auto-exposure brightness target.

        Args:
            percent: Target brightness (0-100).
        """
        if not 0 <= percent <= 100:
            raise ValueError(f"percent must be 0-100, got {percent}")
        logger.info("set_brightness percent=%s", percent)
        return await self.method_sync("set_setting", {"ae_bri_percent": percent})

    async def start_create_dark(self) -> dict:
        logger.info("start_create_dark")
        return await self.method_sync("start_create_dark")
