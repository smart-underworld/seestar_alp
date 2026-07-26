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
