"""Playwright driver functions for the v2 (FastAPI + Svelte) frontend."""

import re
import time

from playwright.sync_api import Page, expect

from tests.system.live_check import assert_stream_liveness
from tests.system.target import SystemTestTarget


def run_startup(page: Page, base_url: str) -> None:
    # v2 is a client-side-routed SPA (svelte-spa-router, hash mode) with no
    # server-side deep-link fallback -- a bare "/startup" 404s at the FastAPI
    # layer (StaticFiles only serves index.html for "/" itself). The hash
    # fragment never reaches the server, so "/#/startup" loads "/" and the
    # client-side router renders the right page from the hash.
    page.goto(f"{base_url}/#/startup")

    # Auto Focus: On (default true, but set explicitly for determinism)
    page.locator(".option-row", has_text="Auto Focus").get_by_text(
        "On", exact=True
    ).click()
    page.locator(".option-row", has_text="Dark Frames").get_by_text(
        "On", exact=True
    ).click()
    # Polar Align left at its default (true) — full startup sequence.

    page.get_by_role("button", name=re.compile("Run Startup Sequence")).click()

    deadline = time.time() + 180
    while time.time() < deadline:
        tiles_ok = True
        for label in ["Auto Focus", "Dark Frames", "Polar Align"]:
            tile = page.locator(".event-tile", has_text=label)
            if tile.count() == 0:
                tiles_ok = False
                break
            state_text = tile.inner_text()
            if "fail" in state_text.lower():
                raise AssertionError(
                    f"Startup sequence reported a failure for {label}:\n{state_text}"
                )
            if "complete" not in state_text.lower():
                tiles_ok = False
        if tiles_ok:
            return
        page.wait_for_timeout(2000)
    raise AssertionError("Startup sequence did not complete within 180s")


def do_goto(page: Page, base_url: str, target: SystemTestTarget) -> None:
    page.goto(f"{base_url}/#/goto")  # hash route -- see run_startup's comment
    page.fill("#tname", target.goto_target_name)
    page.fill("#ra", target.goto_ra)
    page.fill("#dec", target.goto_dec)
    page.get_by_role("button", name=re.compile("GoTo")).click()

    deadline = time.time() + 120
    while time.time() < deadline:
        card = page.locator(".event-card", has_text="AutoGoto")
        if card.count() > 0:
            text = card.inner_text()
            if "fail" in text.lower():
                raise AssertionError(f"Goto reported a failure:\n{text}")
            if "complete" in text.lower():
                return
        page.wait_for_timeout(2000)
    raise AssertionError("Goto did not complete within 120s")


def check_live_imaging(
    page: Page, base_url: str, window_s: float = 5.0, min_bytes: int = 2048
) -> None:
    page.goto(f"{base_url}/#/live")  # hash route -- see run_startup's comment
    assert_stream_liveness(page, "img", window_s=window_s, min_bytes=min_bytes)


def stop_live_view(page: Page, base_url: str) -> None:
    # Only call this for a standalone check (no schedule running) --
    # setMode("none") shows a confirmation dialog and, per its own comment,
    # interrupts an in-progress stack if one is active, so calling this
    # during the concurrent schedule-capture check would cancel the very
    # capture being tested. No schedule should be active here, so
    # isImagingActive() should be false and no dialog should appear, but
    # accept one defensively if it does.
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_title("Stop live view").click()


def add_and_start_schedule_capture(
    page: Page, base_url: str, target: SystemTestTarget
) -> None:
    page.goto(f"{base_url}/#/schedule")  # hash route -- see run_startup's comment
    page.get_by_role("button", name="Image (1×1)").click()
    page.fill("#field-target_name", target.goto_target_name)
    page.fill("#field-ra", target.goto_ra)
    page.fill("#field-dec", target.goto_dec)
    page.fill("#field-panel_time_sec", str(target.capture_duration_s))

    # Clicking "+ Add to Schedule" is sometimes silently swallowed (confirmed:
    # no network request fires at all, no error alert, not a validation issue
    # -- addItem()'s network path just never runs that time). This reproduces
    # intermittently even with a multi-second gap after the last field fill,
    # so it's a genuine flaky client-side timing race, not something a fixed
    # delay reliably avoids -- not root-caused further. Retry the click,
    # verified against the Start button becoming enabled (addItem() awaits an
    # API call + schedule reload before `items`, and thus
    # disabled={items.length===0}, reflects the new item), instead of
    # trusting a single click after a guessed delay.
    add_button = page.get_by_role("button", name=re.compile(r"\+ Add to Schedule"))
    start_button = page.get_by_role("button", name=re.compile(r"▶ Start"))
    for attempt in range(10):
        add_button.click()
        try:
            expect(start_button).to_be_enabled(timeout=3000)
            break
        except AssertionError:
            if attempt == 9:
                raise
    start_button.click()
    expect(page.locator(".sched-state-badge")).to_contain_text("working", timeout=15000)


def read_frames_processed_count(page: Page, base_url: str) -> int:
    # Counts stacked + dropped frames, not just stacked_frame: the sandbox's
    # synthetic star field is injected only into the offline solve-field FITS
    # read, never into the live camera/stack frame buffer (always a flat gray
    # test pattern by design), so real stacking success (stacked_frame > 0) is
    # architecturally impossible there -- every frame gets dropped with "too
    # few stars". Total frames processed still proves the schedule genuinely
    # executes and the camera pipeline keeps actively running throughout.
    page.goto(f"{base_url}/#/image")  # hash route -- see run_startup's comment
    # EventStatusPanel populates asynchronously (onMount -> load(), a ~2s-
    # interval poll) -- checking card.count() immediately after goto() races
    # that fetch and reads 0 every time, even though the backend's own
    # dropped_frame climbs continuously and steadily the whole time (confirmed
    # via the app log directly). Wait for the card to actually appear.
    card = page.locator(".event-card", has_text="Stack")
    try:
        expect(card).to_have_count(1, timeout=10000)
    except AssertionError:
        return 0
    text = card.first.inner_text()
    stacked = re.search(r"Stacked:\s*(\d+)", text)
    dropped = re.search(r"Dropped:\s*(\d+)", text)
    return (int(stacked.group(1)) if stacked else 0) + (
        int(dropped.group(1)) if dropped else 0
    )
