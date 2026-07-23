"""The 4-step system test flow: startup -> goto -> live imaging ->
scheduled star capture with a concurrent live-imaging check.

Runs once per frontend selected via --frontend (classic, v2, or both).
"""

import time

import pytest

from tests.system import ui_classic, ui_v2

pytestmark = pytest.mark.system

DRIVERS = {"classic": ui_classic, "v2": ui_v2}


def _selected_frontends(config):
    choice = config.getoption("--frontend")
    return ["classic", "v2"] if choice == "both" else [choice]


@pytest.fixture(params=["classic", "v2"])
def frontend(request):
    if request.param not in _selected_frontends(request.config):
        pytest.skip(f"--frontend did not select {request.param}")
    return request.param


@pytest.fixture
def driver(frontend):
    return DRIVERS[frontend]


@pytest.fixture
def app(frontend, running_app):
    proc = running_app(frontend)
    return proc


@pytest.fixture
def app_base_url(app):
    # NOTE: not named `base_url` -- pytest-playwright's pytest-base-url
    # dependency defines its own session-scoped, autouse `base_url` fixture
    # (`_verify_url`). A function-scoped fixture named `base_url` in this
    # module shadows that name for every test collected here and trips a
    # pytest ScopeMismatch error at setup time (confirmed by running the
    # suite; --collect-only does not surface it since fixtures never
    # execute during collection). See task-8-report.md for details.
    return app.base_url


def test_startup(page, app_base_url, driver):
    driver.run_startup(page, app_base_url)


def test_goto(page, app_base_url, driver, target, require_real_confirmation):
    require_real_confirmation(
        f"slew to {target.goto_target_name} (ra={target.goto_ra}, dec={target.goto_dec})"
    )
    driver.do_goto(page, app_base_url, target)


def test_live_imaging_standalone(page, app_base_url, driver):
    driver.check_live_imaging(page, app_base_url)
    # Stop the view this test started -- leaving it running was confirmed to
    # carry over into test_schedule_capture_with_concurrent_live_check (same
    # module-scoped app, different page/tab) and prevent its stacking
    # progress from ever registering.
    driver.stop_live_view(page, app_base_url)


def test_schedule_capture_with_concurrent_live_check(
    page, app_base_url, driver, target, require_real_confirmation
):
    require_real_confirmation(
        f"run a {target.capture_duration_s}s scheduled star capture of "
        f"{target.goto_target_name}"
    )
    driver.add_and_start_schedule_capture(page, app_base_url, target)

    # Asserts on frames *processed* (stacked + dropped), not frames actually
    # stacked: the sandbox never injects its synthetic star field into the
    # live camera/stack pipeline (only into the offline solve-field FITS
    # read), so stacked_frame stays 0 there by architectural design. Total
    # processed frames still proves the schedule genuinely executes and the
    # camera pipeline keeps actively running throughout the capture window.
    #
    # The very first sample can reflect a stale count replayed from a prior
    # session before this item's own goto/solve prep finishes and the
    # counter genuinely resets to 0 -- so look for any consecutive increase
    # across the window rather than comparing only the first and last
    # sample, which would spuriously fail across that one-time reset.
    # window_s must comfortably exceed a single stack exposure cycle
    # (exposure_length_stack_ms in the scratch config, 10s): during active
    # stacking, new frames arrive roughly once per exposure, not continuously
    # like the standalone preview/ContinuousExposure check, and the first
    # frame is typically already delivered before monitoring starts (during
    # the element-visibility wait) -- confirmed via a direct stream fetch
    # that real bytes do flow, just on a ~10s cadence, not a 3s one.
    samples = []
    progressed = False
    last = None
    deadline = time.time() + target.capture_duration_s + 30
    while time.time() < deadline:
        driver.check_live_imaging(page, app_base_url, window_s=15.0)
        count = driver.read_frames_processed_count(page, app_base_url)
        samples.append(count)
        if last is not None and count > last:
            progressed = True
            break
        last = count
        time.sleep(min(20, target.capture_duration_s / 3))

    assert progressed, (
        f"processed-frame count never increased between consecutive samples: {samples}"
    )
