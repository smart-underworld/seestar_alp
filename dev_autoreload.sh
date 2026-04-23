#!/usr/bin/env bash
# Dev helper: run root_app.py with auto-restart on front/ and device/ .py changes.
#
# watchmedo (from watchdog) watches the two source directories and SIGINTs
# the running process whenever a .py file changes, then relaunches it.
# A 1 s debounce absorbs editors that write-then-rename on save (otherwise
# a single save triggers two restarts).
#
# Runs until you Ctrl+C it; the signal is forwarded to the child so the
# app exits cleanly.

set -euo pipefail

cd "$(dirname "$0")"

exec uv run watchmedo auto-restart \
    --directory=./front \
    --directory=./device \
    --pattern="*.py" \
    --recursive \
    --signal=SIGINT \
    --debounce-interval=1 \
    -- python root_app.py
