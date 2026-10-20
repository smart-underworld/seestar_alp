---
name: building-schedules
description: Use when the user wants a multi-target, mosaic, or unattended imaging night on the Seestar - composes a schedule with the schedule tools and starts the scheduler.
---

# Building schedules

1. **Inspect.** `get_schedule` to see what already exists. Do not clobber a schedule the user wants to keep; ask first.
2. **Create.** `create_schedule` starts a new empty schedule.
3. **Add items.**
   - Generic item: `add_schedule_item(action, params)` for actions such as wait/park/start-imaging steps. Physical actions (`scope_park`, `scope_move_to_horizon`, `reboot`, `shutdown`) are refused unless `confirm=true`; pass it only after the user explicitly confirms that item.
   - Mosaic: `schedule_mosaic(target_name, ra, dec, session_time_sec, ra_num, dec_num, panel_overlap_percent=20, gain=80, is_use_lp_filter, is_use_autofocus, is_j2000)`. `ra_num x dec_num` is the panel grid; `session_time_sec` is the total across the grid (the tool converts it to per-panel `panel_time_sec`).
   - Timing: `add_schedule_item("wait_until", {"local_time": "HH:MM"})` holds until a clock time; `add_schedule_item("wait_for", {"timer_sec": N})` waits a duration. Use a `wait_until` as the first item so an early start waits for darkness.
   - `start_mosaic` runs a single mosaic directly without a stored schedule.
   - **Field gotcha:** if you ever build a `start_mosaic` item by hand via `add_schedule_item`, put the per-panel time in **`panel_time_sec`**, not `session_time_sec` — the device tolerates the legacy `session_time_sec`, but the web schedule page only reads `panel_time_sec` and will error without it. Prefer `schedule_mosaic`, which handles this for you.
4. **Review.** Call `get_schedule` again and summarise the order and total time for the user.
5. **Run.** `start_scheduler` launches an unattended run and requires `confirm=true`; pass it only after the user confirms the reviewed plan. Stop with `stop_scheduler`.
6. **Persist.** `export_schedule(filepath)` saves a schedule to a file; `import_schedule(filepath)` loads one. Offer export after building a good plan.

## Planning a whole night
When the user wants "tonight"/"tomorrow night" across many targets: work out the dark window (astronomical dusk→dawn) and the moon (phase, and when it rises/sets) for the device's location — `get_device_state` reports `location_lon_lat`. Schedule moon-tolerant targets (open/globular clusters, bright galaxy cores, and emission nebulae with `is_use_lp_filter=true`) while the moon is up, and save faint broadband/reflection targets for after moonset. Order targets near their culmination, and anchor the start (and the moonset handover) with `wait_until` items.

For a large timed plan, building item-by-item is many calls and risks out-of-order appends; it is cleaner to assemble the full schedule JSON (a `{"list": [ {action, params, schedule_item_id}, … ]}` dict — mosaic items use `panel_time_sec`) and load it in one `import_schedule(filepath)` call, then `get_schedule` to review.

End long unattended schedules with a park step, and confirm with the user before any physical action (see `safety`).
