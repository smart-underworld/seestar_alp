"""Playwright driver functions for the classic (Falcon + HTMX) frontend."""

import re
import time

from playwright.sync_api import Page, expect

from tests.system.live_check import assert_stream_liveness
from tests.system.target import SystemTestTarget

DEVICE_ID = 1


def _device_path(base_url: str, suffix: str) -> str:
    return f"{base_url}/{DEVICE_ID}{suffix}"


def run_startup(page: Page, base_url: str) -> None:
    page.goto(_device_path(base_url, "/startup"))
    page.check("#auto_focus")
    page.check("#dark_frames")
    # Leave #polar_align at its default (checked) — full startup sequence.
    page.click("button[type='submit'][value='start']")

    status = page.locator("#eventStatusContent")
    expect(status).to_contain_text("AutoFocus", timeout=5000)

    deadline = time.time() + 180
    while time.time() < deadline:
        text = status.inner_text()
        if "fail" in text.lower():
            raise AssertionError(f"Startup sequence reported a failure:\n{text}")
        # All three enabled events (AutoFocus, DarkLibrary, 3PPA) must show
        # "complete" — Scheduler/WheelMove/PlateSolve cards may stay idle.
        watched = re.findall(
            r"(AutoFocus|DarkLibrary|PolarAlign)[\s\S]{0,120}?State:\s*(\w[\w\s]*)",
            text,
        )
        if len(watched) >= 3 and all(state.strip().lower() == "complete" for _, state in watched):
            return
        page.wait_for_timeout(2000)
    raise AssertionError(f"Startup sequence did not complete within 180s:\n{status.inner_text()}")


def do_goto(page: Page, base_url: str, target: SystemTestTarget) -> None:
    page.goto(_device_path(base_url, "/goto"))
    page.fill("#targetName", target.goto_target_name)
    page.fill("#ra", target.goto_ra)
    page.fill("#dec", target.goto_dec)
    page.click("form button[type='submit']")

    status = page.locator("#eventStatusContent")
    expect(status).to_contain_text("AutoGoto", timeout=5000)

    deadline = time.time() + 120
    while time.time() < deadline:
        text = status.inner_text()
        if "fail" in text.lower():
            raise AssertionError(f"Goto reported a failure:\n{text}")
        match = re.search(r"AutoGoto[\s\S]{0,120}?State:\s*(\w[\w\s]*)", text)
        if match and match.group(1).strip().lower() == "complete":
            return
        page.wait_for_timeout(2000)
    raise AssertionError(f"Goto did not complete within 120s:\n{status.inner_text()}")


def check_live_imaging(page: Page, base_url: str, window_s: float = 5.0, min_bytes: int = 2048) -> None:
    page.goto(_device_path(base_url, "/live/star"))
    assert_stream_liveness(page, "#liveViewImg", window_s=window_s, min_bytes=min_bytes)


def add_and_start_schedule_capture(page: Page, base_url: str, target: SystemTestTarget) -> None:
    page.goto(_device_path(base_url, "/schedule/image"))
    page.fill("#targetName", target.goto_target_name)
    page.fill("#ra", target.goto_ra)
    page.fill("#dec", target.goto_dec)
    page.fill("#panelTime", str(target.capture_duration_s))
    page.click("button[type='submit'][value='append']")

    page.wait_for_selector(".row.border-bottom", timeout=10000)

    start_button = page.locator("#schedule-state button")
    expect(start_button).to_contain_text("Start", timeout=10000)
    start_button.click()
    expect(page.locator("#schedule-state button")).to_contain_text("Stop", timeout=15000)


def read_stacked_frame_count(page: Page, base_url: str) -> int:
    page.goto(_device_path(base_url, "/schedule/image"))
    current_row = page.locator(".row.border-bottom.bg-primary").first
    toggle = current_row.locator("[data-bs-toggle='collapse']")
    if toggle.count() == 0:
        return 0
    toggle.first.click()
    body = current_row.locator(".accordion-body").first
    text = body.inner_text()
    match = re.search(r"Stacked Frames:\s*(\d+)", text)
    return int(match.group(1)) if match else 0
