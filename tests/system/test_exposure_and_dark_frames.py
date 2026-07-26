"""Emulator-matrix regression coverage for the exposure key-mismatch and
dark-frame-on-every-exposure-set bugs (see docs/superpowers/specs/
2026-07-25-front-v2-bugfix-batch-design.md). Runs against the real firmware
binary via the QEMU emulator, across the pinned version matrix
(emulator/firmware/versions.yaml) in the full/nightly CI lane -- see
tests/system/README.md for --target usage.
"""

import time

import pytest
import requests

pytestmark = pytest.mark.system


@pytest.fixture
def app(running_app):
    return running_app("v2")


@pytest.fixture
def app_base_url(app):
    # NOTE: not named `base_url` -- pytest-playwright's pytest-base-url
    # dependency defines its own session-scoped, autouse `base_url` fixture
    # (`_verify_url`). A function-scoped fixture named `base_url` in this
    # module shadows that name for every test collected here and trips a
    # pytest ScopeMismatch error at setup time (same issue as test_flow.py --
    # see its `app_base_url` fixture comment / task-8-report.md).
    return app.base_url


@pytest.mark.smoke
@pytest.mark.full
def test_live_exposure_change_is_reflected_by_firmware(app_base_url):
    requests.post(f"{app_base_url}/api/v1/devices/1/live/mode", json={"mode": "star"})
    time.sleep(3)  # let iscope_start_view settle before touching settings

    set_resp = requests.post(
        f"{app_base_url}/api/v1/devices/1/live/exposure", json={"exp_ms": 3000}
    )
    assert set_resp.status_code == 200

    get_resp = requests.get(f"{app_base_url}/api/v1/devices/1/live/exposure")
    assert get_resp.status_code == 200
    assert get_resp.json()["exp_ms"] == 3000

    requests.delete(f"{app_base_url}/api/v1/devices/1/live/mode")


def _add_and_run_exposure_item(app_base_url, dark_frames: bool) -> None:
    requests.delete(f"{app_base_url}/api/v1/devices/1/schedule")
    requests.post(
        f"{app_base_url}/api/v1/devices/1/schedule/item",
        json={
            "action": "action_set_exposure",
            "params": {"exp": 1200, "dark_frames": dark_frames},
        },
    )

    # start_scheduler rejects a restart with code -1 ("Scheduler thread is
    # still winding down...") for a short window after the *previous*
    # schedule run's state flips to stopped/complete but before its
    # scheduler_thread actually exits (it tails off with a play_sound() call
    # that includes a 1s sleep -- device/seestar_device.py's
    # scheduler_thread_fn / start_scheduler). Back-to-back schedule runs in
    # this module (module-scoped `app` fixture, tests firing seconds apart)
    # can land in that window, so retry the start until it's accepted rather
    # than trusting a single fire-and-forget POST.
    started = False
    start_deadline = time.time() + 20
    while time.time() < start_deadline:
        resp = requests.post(
            f"{app_base_url}/api/v1/devices/1/schedule/state?state=start"
        ).json()
        # toggle_schedule() returns the raw ASCOM Alpaca envelope (unlike
        # get_schedule(), it doesn't unwrap "Value") -- the scheduler's own
        # result/code lives at resp["Value"]["code"].
        if resp.get("Value", {}).get("code", 0) != -1:
            started = True
            break
        time.sleep(1)
    assert started, "scheduler never accepted start (still winding down)"

    finished = False
    deadline = time.time() + 30
    while time.time() < deadline:
        state = requests.get(f"{app_base_url}/api/v1/devices/1/schedule").json()
        if state.get("state") in ("stopped", "complete"):
            finished = True
            break
        time.sleep(1)
    assert finished, "schedule item never reached stopped/complete"


@pytest.mark.smoke
@pytest.mark.full
def test_dark_frames_not_run_when_not_requested(app, app_base_url):
    offset = len(app.log_file.read_text())
    _add_and_run_exposure_item(app_base_url, dark_frames=False)
    log_text = app.log_file.read_text()[offset:]
    assert "Trying to set exposure to {'exp': 1200, 'dark_frames': False}" in log_text
    assert "action_set_exposure: dark_frames requested" not in log_text


@pytest.mark.smoke
@pytest.mark.full
def test_dark_frames_run_when_requested(app, app_base_url):
    offset = len(app.log_file.read_text())
    _add_and_run_exposure_item(app_base_url, dark_frames=True)
    log_text = app.log_file.read_text()[offset:]
    assert "Trying to set exposure to {'exp': 1200, 'dark_frames': True}" in log_text
    assert "action_set_exposure: dark_frames requested" in log_text
