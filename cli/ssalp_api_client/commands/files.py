from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.files")


class FilesMixin:
    async def get_albums(self) -> dict:
        logger.info("get_albums")
        return await self.method_sync("get_albums")

    async def get_img_name_field(self) -> dict:
        logger.info("get_img_name_field")
        return await self.method_sync("get_img_name_field")

    async def set_img_name_field(
        self,
        bin: bool = True,
        date_time: bool = True,
        temp: bool = True,
        gain: bool = True,
        camera_name: bool = False,
    ) -> dict:
        logger.info(
            "set_img_name_field bin=%s date_time=%s temp=%s gain=%s camera_name=%s",
            bin,
            date_time,
            temp,
            gain,
            camera_name,
        )
        return await self.method_sync(
            "set_img_name_field",
            {
                "bin": bin,
                "date_time": date_time,
                "temp": temp,
                "gain": gain,
                "camera_name": camera_name,
            },
        )

    async def get_last_image(
        self, is_subframe: bool = True, is_thumb: bool = False
    ) -> dict:
        """Get metadata for the last captured image.

        Args:
            is_subframe: Return subframe crop coordinates.
            is_thumb: Return a thumbnail instead of full image info.
        """
        logger.info("get_last_image subframe=%s thumb=%s", is_subframe, is_thumb)
        return await self.action(
            "get_last_image", {"is_subframe": is_subframe, "is_thumb": is_thumb}
        )

    async def set_sequence_group_name(self, group_name: str) -> dict:
        logger.info("set_sequence_group_name name=%s", group_name)
        return await self.method_sync("set_sequence_setting", [{"group_name": group_name}])

    async def download_image(self, url: str) -> bytes:
        """Download a raw image from the device by URL.

        Args:
            url: Full URL to the image file on the device.

        Returns:
            Raw image bytes.
        """
        logger.info("download_image url=%s", url)
        return await self.get_bytes(url)
