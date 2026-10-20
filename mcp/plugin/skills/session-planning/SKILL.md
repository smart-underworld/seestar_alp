---
name: session-planning
description: Use when the user asks to image or observe a target (e.g. "image M31 tonight") with the Seestar - turns the request into readiness checks, goto, plate solve, and stacking tool calls.
---

# Session planning

Turn "image <target>" into concrete `seestar` MCP tool calls. Every tool takes `telescope_id` (default 1); pass it for multi-scope setups.

## Steps
1. **Readiness.** Call `get_device_state` and `get_view_state`. Confirm the scope is connected, not already stacking/slewing, and not in an error state. If a view is active and the user wants a new target, call `stop_view` first.
   - *Optional alignment:* if the user wants to polar align first (or the scope is freshly set up in `equ_mode`), call `polar_align` (3PPA), then poll `get_pa_error` until it returns real values (9999.9 means not yet measured). `set_3ppa_calibration(enabled)` toggles auto-calibration. See the `safety` skill — this moves the mount.
2. **Resolve coordinates.** You need RA/Dec for the target. If the user gave only a name, supply known J2000 coordinates and say so; ask if unsure. Never guess for obscure objects.
3. **Sun check.** Do not slew toward the Sun (see the `safety` skill).
4. **Slew.** `goto_target(target_name, ra, dec, is_j2000=true)`. Poll `is_goto_completed_ok` until true. Use `stop_goto_target` to abort.
5. **Verify pointing.** `start_solve`, then `get_solve_result`. If the solve fails, re-check the sky is clear/dark and retry once before reporting.
6. **Stack.** `start_stack(gain, restart=true)` (typical gain 80; use `set_gain` / `set_exposure` beforehand to adjust).
7. **Monitor.** Use `get_view_state` periodically and `get_last_image` to preview. End with `stop_view`.

For multi-target or timed nights use the `building-schedules` skill instead.
