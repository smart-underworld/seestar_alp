from __future__ import annotations

import logging

logger = logging.getLogger("ssalp_api_client.commands.schedule")


class ScheduleMixin:
    # ── scheduler lifecycle ───────────────────────────────────────────────

    async def start_scheduler(self) -> dict:
        logger.info("start_scheduler")
        return await self.action("start_scheduler", {})

    async def stop_scheduler(self) -> dict:
        logger.info("stop_scheduler")
        return await self.action("stop_scheduler", {})

    async def pause_scheduler(self) -> dict:
        logger.info("pause_scheduler")
        return await self.action("pause_scheduler", {})

    async def continue_scheduler(self) -> dict:
        logger.info("continue_scheduler")
        return await self.action("continue_scheduler", {})

    async def reset_scheduler_cur_item(self) -> dict:
        logger.info("reset_scheduler_cur_item")
        return await self.action("reset_scheduler_cur_item", {})

    async def skip_scheduler_cur_item(self) -> dict:
        logger.info("skip_scheduler_cur_item")
        return await self.action("skip_scheduler_cur_item", {})

    # ── schedule CRUD ────────────────────────────────────────────────────

    async def get_schedule(self) -> dict:
        logger.info("get_schedule")
        return await self.action("get_schedule", {})

    async def create_schedule(self) -> dict:
        logger.info("create_schedule")
        return await self.action("create_schedule", {})

    async def add_schedule_item(self, action: str, params: dict | None = None) -> dict:
        logger.info("add_schedule_item action=%s params=%s", action, params)
        payload: dict = {"action": action}
        if params is not None:
            payload["params"] = params
        return await self.action("add_schedule_item", payload)

    async def remove_schedule_item(self, schedule_item_id: str) -> dict:
        logger.info("remove_schedule_item id=%s", schedule_item_id)
        return await self.action(
            "remove_schedule_item", {"schedule_item_id": schedule_item_id}
        )

    async def replace_schedule_item(
        self, item_id: str, action: str, params: dict | None = None
    ) -> dict:
        logger.info("replace_schedule_item id=%s action=%s", item_id, action)
        payload: dict = {"item_id": item_id, "action": action}
        if params is not None:
            payload["params"] = params
        return await self.action("replace_schedule_item", payload)

    async def insert_schedule_item_before(
        self, before_id: str, action: str, params: dict | None = None
    ) -> dict:
        logger.info(
            "insert_schedule_item_before before_id=%s action=%s", before_id, action
        )
        payload: dict = {"before_id": before_id, "action": action}
        if params is not None:
            payload["params"] = params
        return await self.action("insert_schedule_item_before", payload)

    # ── import / export ──────────────────────────────────────────────────

    async def export_schedule(self, filepath: str) -> dict:
        logger.info("export_schedule path=%s", filepath)
        return await self.action("export_schedule", {"filepath": filepath})

    async def import_schedule(self, filepath: str, retain_state: bool = False) -> dict:
        logger.info("import_schedule path=%s retain_state=%s", filepath, retain_state)
        return await self.action(
            "import_schedule", {"filepath": filepath, "is_retain_state": retain_state}
        )

    # ── high-level schedule item helpers ─────────────────────────────────

    async def schedule_mosaic(
        self,
        target_name: str,
        ra: str | float,
        dec: str | float,
        session_time_sec: int,
        ra_num: int = 1,
        dec_num: int = 1,
        panel_overlap_percent: int = 20,
        gain: int = 80,
        is_use_lp_filter: bool = False,
        is_use_autofocus: bool = False,
        is_j2000: bool = False,
    ) -> dict:
        """Add a mosaic imaging item to the schedule."""
        if session_time_sec <= 0:
            raise ValueError("session_time_sec must be positive")
        if gain < 0:
            raise ValueError("gain must be non-negative")
        logger.info("schedule_mosaic target=%s ra=%s dec=%s", target_name, ra, dec)
        return await self.add_schedule_item(
            "start_mosaic",
            {
                "target_name": target_name,
                "ra": ra,
                "dec": dec,
                "is_j2000": is_j2000,
                "is_use_lp_filter": is_use_lp_filter,
                "is_use_autofocus": is_use_autofocus,
                "session_time_sec": session_time_sec,
                "ra_num": ra_num,
                "dec_num": dec_num,
                "panel_overlap_percent": panel_overlap_percent,
                "gain": gain,
            },
        )

    async def schedule_spectra(
        self,
        target_name: str,
        ra: str | float,
        dec: str | float,
        session_time_sec: int,
        gain: int = 120,
        grating_lines: int = 300,
        is_j2000: bool = False,
    ) -> dict:
        """Add a spectrography item to the schedule."""
        if session_time_sec <= 0:
            raise ValueError("session_time_sec must be positive")
        logger.info("schedule_spectra target=%s", target_name)
        return await self.add_schedule_item(
            "start_spectra",
            {
                "target_name": target_name,
                "ra": ra,
                "dec": dec,
                "is_j2000": is_j2000,
                "session_time_sec": session_time_sec,
                "gain": gain,
                "grating_lines": grating_lines,
            },
        )

    async def schedule_wait_until(self, local_time: str) -> dict:
        """Add a wait-until-time item to the schedule.

        Args:
            local_time: Local time in ``HH:MM`` format.
        """
        logger.info("schedule_wait_until time=%s", local_time)
        return await self.add_schedule_item("wait_until", {"local_time": local_time})

    async def schedule_wait_for(self, timer_sec: int) -> dict:
        """Add a wait-for-duration item to the schedule."""
        if timer_sec <= 0:
            raise ValueError("timer_sec must be positive")
        logger.info("schedule_wait_for sec=%s", timer_sec)
        return await self.add_schedule_item("wait_for", {"timer_sec": timer_sec})

    async def schedule_auto_focus(self, try_count: int = 2) -> dict:
        logger.info("schedule_auto_focus tries=%s", try_count)
        return await self.add_schedule_item("auto_focus", {"ry_count": try_count})

    async def schedule_adjust_focus(self, steps: int) -> dict:
        logger.info("schedule_adjust_focus steps=%s", steps)
        return await self.add_schedule_item("adjust_focus", {"steps": steps})

    async def schedule_shutdown(self) -> dict:
        logger.info("schedule_shutdown")
        return await self.add_schedule_item("shutdown")

    async def schedule_set_exposure(self, stack_l_ms: int, continuous_ms: int) -> dict:
        """Add an exposure-settings item to the schedule."""
        if stack_l_ms <= 0 or continuous_ms <= 0:
            raise ValueError("Exposure times must be positive")
        logger.info(
            "schedule_set_exposure stack_l=%s continuous=%s", stack_l_ms, continuous_ms
        )
        return await self.add_schedule_item(
            "set_setting_exposures",
            {"exp_ms": {"stack_l": stack_l_ms, "continuous": continuous_ms}},
        )

    # ── direct mosaic / spectra (outside scheduler) ──────────────────────

    async def start_mosaic(
        self,
        target_name: str,
        ra: str | float,
        dec: str | float,
        session_time_sec: int,
        ra_num: int = 1,
        dec_num: int = 1,
        panel_overlap_percent: int = 20,
        gain: int = 80,
        is_use_lp_filter: bool = False,
        is_use_autofocus: bool = False,
        is_j2000: bool = False,
    ) -> dict:
        """Start a mosaic capture immediately (outside the scheduler)."""
        if session_time_sec <= 0:
            raise ValueError("session_time_sec must be positive")
        if gain < 0:
            raise ValueError("gain must be non-negative")
        logger.info("start_mosaic target=%s ra=%s dec=%s", target_name, ra, dec)
        return await self.action(
            "start_mosaic",
            {
                "target_name": target_name,
                "ra": ra,
                "dec": dec,
                "is_j2000": is_j2000,
                "is_use_lp_filter": is_use_lp_filter,
                "is_use_autofocus": is_use_autofocus,
                "session_time_sec": session_time_sec,
                "ra_num": ra_num,
                "dec_num": dec_num,
                "panel_overlap_percent": panel_overlap_percent,
                "gain": gain,
            },
        )

    async def start_spectra(
        self,
        target_name: str,
        ra: str | float,
        dec: str | float,
        session_time_sec: int,
        gain: int = 120,
        grating_lines: int = 300,
        is_j2000: bool = False,
    ) -> dict:
        """Start a spectrography session immediately (outside the scheduler)."""
        if session_time_sec <= 0:
            raise ValueError("session_time_sec must be positive")
        logger.info("start_spectra target=%s", target_name)
        return await self.action(
            "start_spectra",
            {
                "target_name": target_name,
                "ra": ra,
                "dec": dec,
                "is_j2000": is_j2000,
                "session_time_sec": session_time_sec,
                "gain": gain,
                "grating_lines": grating_lines,
            },
        )
