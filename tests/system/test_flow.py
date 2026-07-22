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


def test_schedule_capture_with_concurrent_live_check(
    page, app_base_url, driver, target, require_real_confirmation
):
    require_real_confirmation(
        f"run a {target.capture_duration_s}s scheduled star capture of "
        f"{target.goto_target_name}"
    )
    driver.add_and_start_schedule_capture(page, app_base_url, target)

    samples = []
    deadline = time.time() + target.capture_duration_s + 30
    while time.time() < deadline and len(samples) < 2:
        driver.check_live_imaging(page, app_base_url, window_s=3.0)
        count = driver.read_stacked_frame_count(page, app_base_url)
        samples.append(count)
        if len(samples) < 2:
            time.sleep(min(20, target.capture_duration_s / 3))

    assert len(samples) >= 2, "did not sample stacked-frame count at least twice"
    assert samples[-1] > samples[0], (
        f"stacked-frame count did not increase during the capture window: {samples}"
    )
