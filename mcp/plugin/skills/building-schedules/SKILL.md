---
name: building-schedules
description: Use when the user wants a multi-target, mosaic, or unattended imaging night on the Seestar - composes a schedule with the schedule tools and starts the scheduler.
---

# Building schedules

1. **Inspect.** `get_schedule` to see what already exists. Do not clobber a schedule the user wants to keep; ask first.
2. **Create.** `create_schedule` starts a new empty schedule.
3. **Add items.**
   - Generic item: `add_schedule_item(action, params)` for actions such as wait/park/start-imaging steps.
   - Mosaic: `schedule_mosaic(target_name, ra, dec, session_time_sec, ra_num, dec_num, panel_overlap_percent=20, gain=80, is_use_lp_filter, is_use_autofocus, is_j2000)`. `ra_num x dec_num` is the panel grid; `session_time_sec` is per item.
   - `start_mosaic` runs a single mosaic directly without a stored schedule.
4. **Review.** Call `get_schedule` again and summarise the order and total time for the user.
5. **Run.** `start_scheduler`; stop with `stop_scheduler`.
6. **Persist.** `export_schedule(filepath)` saves a schedule to a file; `import_schedule(...)` loads one. Offer export after building a good plan.

End long unattended schedules with a park step, and confirm with the user before any physical action (see `safety`).
