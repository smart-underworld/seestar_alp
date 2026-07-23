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
            r"(AutoFocus|DarkLibrary|PolarAlign)[\s\S]{0,120}?State:\s*(\S+)",
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
        match = re.search(r"AutoGoto[\s\S]{0,120}?State:\s*(\S+)", text)
        if match and match.group(1).strip().lower() == "complete":
            return
        page.wait_for_timeout(2000)
    raise AssertionError(f"Goto did not complete within 120s:\n{status.inner_text()}")


def check_live_imaging(page: Page, base_url: str, window_s: float = 5.0, min_bytes: int = 2048) -> None:
    page.goto(_device_path(base_url, "/live/star"))
    assert_stream_liveness(page, "#liveViewImg", window_s=window_s, min_bytes=min_bytes)


def stop_live_view(page: Page, base_url: str) -> None:
    # Only call this for a standalone check (no schedule running) -- the
    # Stop button's backend route stops the *scheduler* instead of the view
    # if one is currently working, so calling this during the concurrent
    # schedule-capture check would cancel the very capture being tested.
    #
    # .live-quickbar (which holds this button) is "display: none" by default
    # and only "display: flex" under a mobile-width media query -- it's a
    # real, mobile-only control, not a timing issue. Use a narrow viewport
    # so it's actually rendered, matching how a real user would reach it.
    original_size = page.viewport_size
    page.set_viewport_size({"width": 420, "height": 900})
    try:
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator(".live-quickbar button", has_text="Stop").click()
    finally:
        if original_size:
            page.set_viewport_size(original_size)


def add_and_start_schedule_capture(page: Page, base_url: str, target: SystemTestTarget) -> None:
    page.goto(_device_path(base_url, "/schedule/image"))
    page.fill("#targetName", target.goto_target_name)
    page.fill("#ra", target.goto_ra)
    page.fill("#dec", target.goto_dec)
    page.fill("#panelTime", str(target.capture_duration_s))
    page.click("button[type='submit'][value='append']")

    page.wait_for_selector(".row.border-bottom", timeout=10000)

    # Once the schedule is "working", a second "Skip" button also appears
    # alongside the toggle (Start/Stop) button, so "#schedule-state button"
    # alone is an ambiguous locator. Scope to the toggle button specifically
    # via its hx-vals action, which "Skip" doesn't share.
    toggle_button = page.locator("#schedule-state button[hx-vals*='toggle']")
    expect(toggle_button).to_contain_text("Start", timeout=10000)
    toggle_button.click()
    expect(page.locator("#schedule-state button[hx-vals*='toggle']")).to_contain_text(
        "Stop", timeout=15000
    )


def read_frames_processed_count(page: Page, base_url: str) -> int:
    # Counts stacked + dropped frames, not just stacked_frame: the sandbox's
    # synthetic star field is injected only into the offline solve-field FITS
    # read, never into the live camera/stack frame buffer (always a flat gray
    # test pattern by design), so real stacking success (stacked_frame > 0) is
    # architecturally impossible there -- every frame gets dropped with "too
    # few stars". Total frames processed still proves the schedule genuinely
    # executes and the camera pipeline keeps actively running throughout.
    #
    # The schedule page's own accordion body only renders Stacked/Dropped
    # Frames when stacked_frame is truthy (schedule_list.html), which would
    # never show anything here. The Stack event card (event_card.html) has no
    # such gate -- it renders Stacked/Dropped unconditionally once any Stack
    # event has fired -- so read from there instead.
    page.goto(_device_path(base_url, "/eventstatus?action=image"))
    text = page.locator("body").inner_text()
    stacked = re.search(r"Stacked:\s*(\d+)", text)
    dropped = re.search(r"Dropped:\s*(\d+)", text)
    return (int(stacked.group(1)) if stacked else 0) + (
        int(dropped.group(1)) if dropped else 0
    )
