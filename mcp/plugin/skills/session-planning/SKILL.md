---
name: session-planning
description: Use when the user asks to image or observe a target (e.g. "image M31 tonight") with the Seestar - turns the request into readiness checks, goto, plate solve, and stacking tool calls.
---

# Session planning

Turn "image <target>" into concrete `seestar` MCP tool calls. Every tool takes `telescope_id` (default 1); pass it for multi-scope setups.

## Startup (when setting up for the night)
The whole startup sequence is drivable via MCP tools. Run the steps the situation needs, in this order, and only when the user is setting up (they move hardware — see `safety`):
1. **Initialize.** `startup_sequence(lat, lon)` — `lat`/`lon` come from `get_device_state`'s `location_lon_lat` (or ask). Optionally `set_heater(state, value)` for dew control.
2. **Dark frames.** `create_dark` — have the user cap the lens first. Run this *before* `startup_sequence`, or only once startup has fully settled: it needs a free device and will return `function conflict` (code 524) if another operation is still running.
3. **Polar align / 3PPA.** `polar_align`, then poll `get_pa_error` until it returns real values (`9999.9` = not yet measured). `set_3ppa_calibration(enabled)` toggles auto-calibration.
4. **Autofocus.** `start_auto_focus` (stop with `stop_auto_focus`; `adjust_focus(steps)` / `get_focuser_position` for manual control).
5. **Filter.** `set_lp_filter(enabled)` for the duo-band/LP filter, or `set_wheel_position(n)` where a wheel exists (`get_wheel_position` / `get_wheel_state`).

**One step at a time.** The Seestar runs one operation at a time — do not fire these back-to-back. Start a step, then wait for it to finish before the next: poll `get_device_state` (and `get_pa_error` for alignment) until the device is idle / reports a result. Firing the next command while one is still running returns `function conflict` (code 524). A tool call returning `{"ok": true}`/code 0 only means the command was *accepted*, not that the motion or routine has completed.

Then proceed to the per-target steps below.

## Steps
1. **Readiness.** Call `get_device_state` and `get_view_state`. Confirm the scope is connected, not already stacking/slewing, and not in an error state. If a view is active and the user wants a new target, call `stop_view` first.
2. **Resolve coordinates.** You need RA/Dec for the target. If the user gave only a name, supply known J2000 coordinates and say so; ask if unsure. Never guess for obscure objects.
3. **Sun check.** Do not slew toward the Sun (see the `safety` skill).
4. **Slew.** `goto_target(target_name, ra, dec, is_j2000=true)`. Poll `is_goto_completed_ok` until true. Use `stop_goto_target` to abort.
5. **Verify pointing.** `start_solve`, then `get_solve_result`. If the solve fails, re-check the sky is clear/dark and retry once before reporting.
6. **Stack.** `start_stack(gain, restart=true)` (typical gain 80; use `set_gain` / `set_exposure` beforehand to adjust).
7. **Monitor.** Use `get_view_state` periodically and `get_last_image` to preview. End with `stop_view`.

For multi-target or timed nights use the `building-schedules` skill instead.
