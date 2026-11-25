"""Run a schedule automatically at seestar_alp startup.

This module backs the ``--schedule`` launch option (GitHub issue #816): once
the web servers are up, wait for the telescope to be connected and
controllable, then import the given schedule file and start the scheduler.

The core routine is duck-typed on the device object (it only uses public
``is_connected`` / ``is_client_master`` / ``import_schedule`` /
``start_scheduler``) so it can be unit-tested without the full device stack,
and it never raises: a failure to auto-start a schedule must never take down
the running server.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path


def _failed(result) -> bool:
    """True when a device action returned a non-zero result ``code``."""
    return isinstance(result, dict) and result.get("code", 0) != 0


def run_startup_schedule(
    device,
    filepath,
    *,
    retain_state: bool = False,
    connect_timeout: float = 120.0,
    poll_interval: float = 1.0,
    logger: logging.Logger | None = None,
) -> bool:
    """Wait for the device to be ready, then import and start ``filepath``.

    Returns True only if the scheduler was started. Returns False (never
    raises) on a missing device, a connect/master timeout, an import or start
    failure, or any unexpected exception.
    """
    log = logger or logging.getLogger(__name__)

    if device is None:
        log.error("Startup schedule: no device available; skipping.")
        return False

    abspath = str(Path(filepath).expanduser().resolve())

    deadline = time.monotonic() + connect_timeout
    while True:
        if device.is_connected and device.is_client_master():
            break
        if time.monotonic() >= deadline:
            log.error(
                "Startup schedule: device not connected and master within %ss; "
                "not starting %s.",
                connect_timeout,
                abspath,
            )
            return False
        time.sleep(poll_interval)

    try:
        import_result = device.import_schedule(
            {"filepath": abspath, "is_retain_state": retain_state}
        )
        if _failed(import_result):
            log.error("Startup schedule: import of %s failed: %s", abspath, import_result)
            return False

        start_result = device.start_scheduler({})
        if _failed(start_result):
            log.error("Startup schedule: start_scheduler refused: %s", start_result)
            return False
    except Exception:
        log.exception("Startup schedule: failed to import/start %s.", abspath)
        return False

    log.info("Startup schedule: imported and started %s.", abspath)
    return True
