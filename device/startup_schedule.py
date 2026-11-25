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

import argparse
import logging
import threading
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


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the root_app.py argument parser (startup-schedule options).

    All options are optional, so parsing an empty argv leaves ``schedule``
    unset and the launcher inert — the no-arg launch behaves exactly as before.
    """
    parser = argparse.ArgumentParser(
        prog="root_app.py",
        description="Start seestar_alp; optionally auto-run a schedule once the scope is ready.",
    )
    parser.add_argument(
        "--schedule",
        default=None,
        metavar="FILE",
        help="Path to a schedule JSON file to import and start automatically at startup.",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=1,
        metavar="N",
        help="Device number to load the startup schedule onto (default: 1).",
    )
    parser.add_argument(
        "--retain-state",
        action="store_true",
        default=False,
        help="Keep the schedule's saved state/ids when importing (default: fresh ids).",
    )
    parser.add_argument(
        "--schedule-connect-timeout",
        type=float,
        default=120.0,
        metavar="SECONDS",
        help="How long to wait for the scope to connect and grant control before giving up (default: 120).",
    )
    return parser


def maybe_launch_startup_schedule(
    args,
    get_device,
    *,
    logger: logging.Logger | None = None,
) -> threading.Thread | None:
    """Spawn a background thread to run the startup schedule, if one was given.

    Returns None (and never calls ``get_device``) when ``args.schedule`` is
    unset. Otherwise starts a daemon thread that resolves the device via
    ``get_device(args.device)`` and hands off to ``run_startup_schedule``,
    and returns that thread. The thread never blocks server startup and
    swallows its own errors.
    """
    log = logger or logging.getLogger(__name__)

    if not args.schedule:
        return None

    def target():
        try:
            device = get_device(args.device)
            run_startup_schedule(
                device,
                args.schedule,
                retain_state=args.retain_state,
                connect_timeout=args.schedule_connect_timeout,
                logger=log,
            )
        except Exception:
            log.exception(
                "Startup schedule: launcher failed for device %s.", args.device
            )

    thread = threading.Thread(target=target, name="StartupScheduleThread", daemon=True)
    thread.start()
    return thread
