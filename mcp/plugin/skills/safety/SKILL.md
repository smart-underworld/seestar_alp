---
name: safety
description: Use before any physical or system action on the Seestar (park, move to horizon, reboot, shutdown) or any slew - rules for confirmation and avoiding the Sun.
---

# Safety

## Confirmation gate
`scope_park`, `scope_move_to_horizon`, `reboot`, and `shutdown` refuse unless `confirm=true`.
- First call WITHOUT confirm (or just describe the action) and ask the user to approve it explicitly.
- Pass `confirm=true` ONLY after the user has said yes in this conversation. Never set it on your own initiative or on a standing assumption.
- These move hardware or interrupt a session; say what will happen (e.g. "this will stop the current stack").

## Sun
Never slew (`goto_target`, `scope_goto`, mosaics, schedules) toward or near the Sun, and never start imaging in daylight without a solar filter the user has confirmed. If the target's position is near the Sun, refuse and explain.

## Shutdown order
1. `stop_view` / `stop_scheduler` if active.
2. `scope_park` (with confirmation) and wait for completion via `get_device_state`.
3. Only then `reboot` or `shutdown` (with confirmation).
Never shut down an un-parked scope unless the user explicitly insists.
