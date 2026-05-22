from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.info")


class InfoMixin:
    async def test_connection(self) -> dict:
        logger.info("test_connection")
        return await self.method_sync("test_connection")

    async def get_device_state(self) -> dict:
        logger.info("get_device_state")
        return await self.method_sync("get_device_state")

    async def get_camera_info(self) -> dict:
        logger.info("get_camera_info")
        return await self.method_sync("get_camera_info")

    async def get_camera_state(self) -> dict:
        logger.info("get_camera_state")
        return await self.method_sync("get_camera_state")

    async def get_camera_exp_and_bin(self) -> dict:
        logger.info("get_camera_exp_and_bin")
        return await self.method_sync("get_camera_exp_and_bin")

    async def get_controls(self) -> dict:
        logger.info("get_controls")
        return await self.method_sync("get_controls")

    async def get_control_value(self, name: str) -> dict:
        logger.info("get_control_value name=%s", name)
        return await self.method_sync("get_control_value", [name])

    async def get_setting(self) -> dict:
        logger.info("get_setting")
        return await self.method_sync("get_setting")

    async def get_stack_info(self) -> dict:
        logger.info("get_stack_info")
        return await self.method_sync("get_stack_info")

    async def get_stack_setting(self) -> dict:
        logger.info("get_stack_setting")
        return await self.method_sync("get_stack_setting")

    async def get_test_setting(self) -> dict:
        logger.info("get_test_setting")
        return await self.method_sync("get_test_setting")

    async def get_disk_volume(self) -> dict:
        logger.info("get_disk_volume")
        return await self.method_sync("get_disk_volume")

    async def get_view_state(self) -> dict:
        logger.info("get_view_state")
        return await self.method_sync("get_view_state")

    async def get_user_location(self) -> dict:
        logger.info("get_user_location")
        return await self.method_sync("get_user_location")

    async def set_user_location(self, lat: float, lon: float, alt: float = 0.0) -> dict:
        logger.info("set_user_location lat=%s lon=%s alt=%s", lat, lon, alt)
        return await self.method_sync("set_user_location", {"lat": lat, "lon": lon, "alt": alt})

    async def get_app_setting(self) -> dict:
        logger.info("get_app_setting")
        return await self.method_sync("get_app_setting")

    async def set_app_setting(self, **kwargs) -> dict:
        logger.info("set_app_setting kwargs=%s", kwargs)
        return await self.method_sync("set_app_setting", [kwargs])

    async def get_sequence_setting(self) -> dict:
        logger.info("get_sequence_setting")
        return await self.method_sync("get_sequence_setting")

    async def set_sequence_setting(self, **kwargs) -> dict:
        logger.info("set_sequence_setting kwargs=%s", kwargs)
        return await self.method_sync("set_sequence_setting", [kwargs])

    async def iscope_get_app_state(self) -> dict:
        logger.info("iscope_get_app_state")
        return await self.method_sync("iscope_get_app_state")

    async def get_event_state(self) -> dict:
        logger.info("get_event_state")
        return await self.action("get_event_state", {})

    async def get_image_save_path(self) -> dict:
        logger.info("get_image_save_path")
        return await self.method_sync("get_image_save_path")

    async def get_annotate_result(self, image_id: int) -> dict:
        logger.info("get_annotate_result image_id=%s", image_id)
        return await self.method_sync("get_annotate_result", {"image_id": image_id})

    async def is_stacked(self) -> dict:
        logger.info("is_stacked")
        return await self.method_sync("is_stacked")

    async def pi_get_ap(self) -> dict:
        logger.info("pi_get_ap")
        return await self.method_sync("pi_get_ap")

    async def pi_get_time(self) -> dict:
        logger.info("pi_get_time")
        return await self.method_sync("pi_get_time")

    async def pi_set_time(self, iso_time: str) -> dict:
        logger.info("pi_set_time time=%s", iso_time)
        return await self.method_sync("pi_set_time", [iso_time])
