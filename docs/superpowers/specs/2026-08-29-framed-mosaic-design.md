# Framed Mosaic — Design

Status: Approved
Date: 2026-08-29
Author: Ben Guthro (with Claude)

## 1. Background

The request that started this: port "the ability to add seestar style mosaics, where you
choose the framing size and angle" from `bguthro/front_v2` into the old (`front/`) UI.

Investigation found the premise didn't hold as stated:

- No such feature exists in `bguthro/front_v2` or anywhere in `seestar_alp`'s history. The
  actual reference implementation is `MosaicFramingEditor.tsx` in a separate, unrelated repo
  (`~/dev/esc`, the "esc" Tauri/React app). There, `scale`/`angle` are stored on a schedule
  target purely as a display label (`"2.0× / 15°"`) — never converted into device commands.
  `starMapAngle` is explicitly commented "always 0.0," unused. A literal port would be an
  inert widget.
- However, the real ZWO Seestar Android app has a genuine, firmware-level version of this:
  a `PlanMosaic` / `SetMosaicCmd` structure (`scale`, `angle`, `star_map_angle`) sent via
  `set_setting`/`set_view_plan`, documented in
  `seestar-api-research/docs/firmware/v3.1.2_7.32/apk_plan_analysis.md` (§2.4, §10) from
  static analysis of the app's decompiled sources.
- This was verified against the decompiled firmware binary itself
  (`~/Development/firmware/unpacked/v3.1.2/iscope_decompiled/zwoair_imager`), not just the
  app: the `set_setting`/`get_setting` handlers have a dedicated `"mosaic"` key branch
  (`scale`, `angle`, `star_map_angle`, plus firmware-computed `estimated_hours` and
  `star_map_ratio`), and in the capture-dispatch path, a `wide_mosaic_angle` setting is read
  and passed directly into the low-level capture-initiation call at the moment a capture
  starts. This confirms the setting is live and threaded into the imaging pipeline, not
  merely echoed UI state — the failure mode that makes `esc`'s version inert.
- One confirmed open question: the traced firmware code path is for **wide-camera mode**.
  The Android app's UI guards the angle *control* to **telephoto** mode and reads what
  appears to be a differently-named setting there, which wasn't fully traced through the
  binary. Which camera mode(s)/models this works on in practice is not settled by static
  analysis alone — see §9 (Risks).

`seestar_alp`'s existing "Mosaic" feature (`start_mosaic` action, `mosaic_thread_fn`) is
architecturally unrelated: it's a Python-orchestrated grid of discrete panels, each visited
by a separate `goto_target` call, with panel spacing computed axis-aligned in RA/Dec
(`Util.mosaic_next_center_spacing`). It has no rotation concept and none is being added to
it. The feature described here is a distinct single-frame capture mode where the *device
firmware* handles the enlarged/rotated framing internally — conceptually much closer to the
existing single-target "Image" flow (which is itself `start_mosaic` with `ra_num=1,
dec_num=1`) than to the grid Mosaic.

## 2. Goals

- Let a user pick a target, a scale (1.0×–2.0×) and a rotation angle (−90°..+90°) for a
  single enlarged/rotated capture, and either run it immediately or schedule it — matching
  the real Seestar app's own framing control ranges and semantics.
- Support this from both an immediate-action page and the Schedule page, and from the
  Planning page as a visual framing tool that can hand off to either.
- Support federation (`duplicate` and `by_time` modes) consistent with how other
  single-target actions are federated today.

## 3. Non-goals

- No changes to the existing grid-panel Mosaic (`start_mosaic`) math, UI, or schema.
- No `by_panels` federation mode for this feature — there are no discrete panels.
- No support for the device-native `set_view_plan`/`get_view_plan` overnight-plan protocol.
  This feature is implemented entirely through `seestar_alp`'s existing Python scheduler
  (`scheduler_thread_fn`), issuing a single `goto` + a `set_setting` framing update + a
  normal stack session — it does not hand scheduling over to the firmware.
- No resolution of the telephoto-vs-wide-camera nuance in §9 within this change — it ships
  as a normal (non-gated) feature, with hardware/emulator verification tracked as a
  follow-up per §9 and §11, not as a precondition for landing.

## 4. Naming

| Concept | Name |
|---|---|
| Scheduler action | `start_framed_mosaic` |
| Item type (event/schedule display) | `framed_mosaic` |
| Nav / page title | "Framed Mosaic" |
| Planning card | "Framed Mosaic" (`card_name: "framed_mosaic"`) |

Chosen to read clearly as distinct from the existing grid "Mosaic," while still signaling
it's a mosaic-family capture mode.

## 5. Device layer (`device/seestar_device.py`)

### 5.1 New params (schedule item `params` dict)

| Field | Type | Notes |
|---|---|---|
| `target_name` | str | same as Image/Mosaic |
| `ra`, `dec`, `is_j2000` | as existing | resolved via `Util.parse_coordinate`, same as `start_mosaic_item` |
| `mosaic_scale` | float, 1.0–2.0 | maps to firmware `mosaic.scale`; default 1.0 |
| `mosaic_angle` | float, −90..90 | maps to firmware `mosaic.angle`; default 0.0 |
| `panel_time_sec` | int | reused name for consistency with Image/Mosaic forms — total single-session imaging duration |
| `gain`, `is_use_lp_filter`, `is_use_autofocus`, `num_tries`, `retry_wait_s`, `stack_type` | as existing | same semantics as Image/Mosaic |
| `federation_mode`, `max_devices` | optional | only meaningful when targeting the federation device (`device_num == 0`) |

Validation: reject if `mosaic_scale` outside `[1.0, 2.0]` or `mosaic_angle` outside
`[-90, 90]`, mirroring the existing `nRA < 1 or nDec < 0` guard style in
`start_mosaic_item`. Reject (log + skip) rather than raise, consistent with existing
mosaic item error handling.

### 5.2 New methods

- **`start_framed_mosaic(params)`** — mirrors `start_mosaic`/`start_spectra`: guards on
  `self.schedule["state"]`, calls `create_schedule`, `add_schedule_item({"action":
  "start_framed_mosaic", "params": params})`, `start_scheduler(params)`. This alone gives
  immediate-run behavior for free by reusing the existing one-item-schedule pattern — no
  separate "immediate" code path needed.
- **`start_framed_mosaic_item(params)`** — validates schedule state and params (as above),
  resolves RA/Dec, spawns `framed_mosaic_thread_fn` on a new thread
  (`FramedMosaicThread:{device_name}`), sets `is_cur_scheduler_item_working = True`.
- **`framed_mosaic_thread_fn(...)`** — single-session execution:
  1. Update scheduler state (`item_state` dict, `type: "framed_mosaic"`), same shape as
     `mosaic_thread_fn`'s state updates.
  2. Goto + retry loop: reuse the same structure as `mosaic_goto_inner_worker`
     (`goto_target`, `wait_end_op`, `is_use_lp_filter` via `set_setting
     stack_lenhance`, optional `try_auto_focus`), looped up to `num_tries` with
     `retry_wait_s` between attempts — matching existing mosaic retry semantics exactly
     rather than inventing new retry logic.
  3. On successful goto: send
     `set_setting {"mosaic": {"scale": mosaic_scale, "angle": mosaic_angle,
     "star_map_angle": 0.0}}`.
  4. Start the stack/session for `panel_time_sec`, reusing whatever single-panel
     stack-start/wait logic `mosaic_thread_fn` already uses for one panel (same
     `stack_type`, `gain` handling).
  5. **`finally`: reset the device's mosaic setting back to
     `{"scale": 1.0, "angle": 0.0, "star_map_angle": 0.0}`.** This is a *persistent*
     device setting (the real app saves it via `PreferenceBaseHelper` across sessions) —
     leaving it non-trivial would silently affect unrelated later captures (plain Image,
     grid Mosaic, live view). This reset must run on both success and failure/exception
     paths, and on skip/stop requests.
  6. Respect `self.schedule["is_skip_requested"]` and `self.schedule["state"] !=
     "working"` checks at the same points `mosaic_thread_fn` does, so skip/stop scheduler
     controls work identically.

### 5.3 Scheduler dispatch

New `elif` branch in `scheduler_thread_fn`, alongside the existing `start_mosaic` /
`start_spectra` cases:

```python
elif action == "start_framed_mosaic":
    self.start_framed_mosaic_item(cur_schedule_item["params"])
    while self.is_cur_scheduler_item_working:
        update_time()
        time.sleep(2)
```

## 6. Federation layer (`device/seestar_federation.py`)

- **`construct_schedule_item`**: extend the existing `if item["action"] == "start_mosaic"`
  condition to also match `"start_framed_mosaic"`, so the same RA/Dec trimming/rounding and
  the `ra < 0` rejection apply. Today that block is mosaic-specific by name; a federated
  framed-mosaic item would otherwise silently skip this validation.
- **`start_scheduler`**: new branch for `schedule_item["action"] == "start_framed_mosaic"`,
  parallel to the existing `start_mosaic` branch:
  - Default `federation_mode` to `"duplicate"` when unset or `num_devices == 1` (identical
    to existing logic).
  - `"by_time"`: divide `panel_time_sec` by `num_devices`, identical in spirit to the
    existing `start_mosaic` by-time branch.
  - No `"by_panels"` handling — there is nothing to split by panel. If a caller passes
    `federation_mode: "by_panels"` for this action, treat it as an invalid combination
    (log a warning, fall back to `"duplicate"`) rather than silently misbehaving.

## 7. Front-end — immediate/schedule create page (`front/`)

- New template `front/templates/framed_mosaic_create.html`, structured like
  `mosaic_create.html`: target search/catalog widget (reuse existing shared search JS),
  RA/Dec fields, a scale slider (1.0×–2.0×, step 0.1) and an angle slider (−90°..+90°,
  step 5°) — matching the real app's control ranges/step sizes exactly — plus the standard
  exposure/gain/retry/stack-type fields shared with Image/Mosaic, and (for the federation
  device) `federation_mode`/`max_devices` fields matching the existing Mosaic form.
- New routes: `/{telescope_id}/framed_mosaic` (immediate) and
  `/{telescope_id}/schedule/framed_mosaic` (append/insert to schedule), following the same
  `do_create_image`/`do_create_mosaic`-style handler pattern already used in `front/app.py`
  (parse form → build `values` dict → `do_action_device("start_framed_mosaic", ...)` or
  `do_insert_schedule_item("start_framed_mosaic", ...)`).
- Nav entry ("Framed Mosaic") added to `nav.html`, alongside the existing Image/Mosaic
  entries.
- `front/templates/partials/schedule_list.html` gets a render case for
  `action == "start_framed_mosaic"` items, showing a summary line like
  `"Framed Mosaic: M31 @ 1.5× / 45°"`, parallel to the existing Mosaic item summary.

## 8. Front-end — Planning page card

- New card, added as a **separate** Planning card (not merged into the existing
  "AstroMosaic" card), per explicit direction — this is a different workflow from grid
  mosaic planning, and keeps the existing grid planner and the vendored
  `AstroMosaicEngine.js` completely untouched.
- New partial `front/templates/partials/framed_mosaic.html` + new card entry appended to
  `front/planning.json.example`:
  ```json
  {
      "card_name": "framed_mosaic",
      "card_friendly_name": "Framed Mosaic",
      "template": "partials/framed_mosaic.html",
      "planning_page_enable": true,
      "planning_page_collapsed": false
  }
  ```
- The card has its own Aladin Lite instance (loaded the same way `astro_mosaic.html`
  loads it — shared CDN scripts, already cached from other pages per the front_v2 PR's
  prefetch work) and its own target search box.
- Visual preview: a rectangle overlay drawn directly via Aladin's own overlay/graphic API
  (not `AstroMosaicEngine.js`), sized by `mosaic_scale` relative to the device's base FOV
  and rotated by `mosaic_angle`, centered on the searched target. A small new JS file
  (e.g. `front/public/framed_mosaic.js`) owns this — no fork of the vendored engine file.
- Scale and angle sliders (same ranges/steps as §7) drive the overlay live.
- "Send to Schedule" button opens a modal (same interaction pattern as the existing
  AstroMosaic card's modal) pre-filled with the current target/scale/angle, posting to
  `/{telescope_id}/schedule/framed_mosaic`.

### 8.1 Card-list upgrade path

`get_planning_cards()` currently seeds `planning.json` from `planning.json.example` only
when the file doesn't exist yet (first run) — it never merges afterward. Any card added to
`.example` in the future is invisible to existing installations. Fix as part of this work:

- After loading the user's `planning.json`, compute the set of `card_name`s present in
  `planning.json.example` but missing from the loaded list, and append those entries
  (as-is from `.example`, i.e. default enabled/expanded) to the in-memory result before
  returning it, then persist the merged list back to `planning.json`.
- Cards the user already has are left untouched (their `planning_page_enable` /
  `planning_page_collapsed` choices are preserved) — this only *adds* missing cards, never
  modifies existing ones.
- This is a general fix (benefits any future card addition), not scoped narrowly to
  `framed_mosaic`.

## 9. Risks / open questions

- **Camera-mode scope (not yet verified on hardware):** firmware evidence traced confirms
  `wide_mosaic_angle` is read at capture time for camera mode 2 ("wide"). The Android app's
  own UI gates the angle *control* to telephoto mode and reads a separately-named setting
  there, not fully traced. Until verified, `mosaic_angle`/`mosaic_scale` should be treated
  as possibly-camera-mode-dependent. No code in this design should assume telephoto-only or
  wide-only; the setting is just sent for whatever the device's current active camera mode
  is. Because this ships without an experimental gate, treat the bruno-collection
  verification pass in §10 as a near-term priority rather than a someday follow-up.
- **Firmware version coverage:** verification was done against v3.1.2 firmware. Confirm
  the `mosaic` `set_setting` key and behavior are unchanged (or note differences) on
  whatever firmware version(s) CI's emulator matrix covers (currently 3.3.0/3.2.0/2.6.4 per
  `emulator-full.yml`).
- **Persistent-setting reset ordering:** the `finally`-block reset (§5.2 step 5) must not
  race with a subsequent schedule item starting immediately after (e.g., a plain Image item
  right after a framed mosaic in the same schedule) — the reset must complete and be
  acknowledged (`set_setting` response) before `is_cur_scheduler_item_working` is cleared,
  so the scheduler doesn't advance to the next item with a stale mosaic setting still in
  flight.
- **Estimated capture duration:** firmware's `get_setting` response for `mosaic` includes
  an `estimated_hours` field. This design does not surface it in the UI (out of scope for
  v1) but it's worth a follow-up: reading it back after setting scale/angle could improve
  the accuracy of "Panel Acquisition Time" guidance shown to the user.

## 10. Testing

Per `AGENTS.md`'s testing expectations:

- **Device unit tests** (new, alongside existing mosaic tests in the device test suite):
  - `start_framed_mosaic`/`start_framed_mosaic_item` reject out-of-range `mosaic_scale`/
    `mosaic_angle`.
  - `framed_mosaic_thread_fn` sends the expected `set_setting {"mosaic": {...}}` payload
    after a successful goto, and sends the reset payload in a `finally` on both the
    success path and when goto/stack raises.
  - Retry loop (`num_tries`/`retry_wait_s`) behaves identically to the existing mosaic
    goto retry logic (can likely share a parametrized test helper with the existing
    `mosaic_goto_inner_worker` tests).
  - Scheduler dispatch: `scheduler_thread_fn` correctly routes `action ==
    "start_framed_mosaic"` items.
  - Federation: `construct_schedule_item` validates/trims RA/Dec for
    `start_framed_mosaic` items; `start_scheduler` correctly fans out `duplicate` and
    `by_time` modes and rejects/falls back on `by_panels`.
- **`tests/test_front_app_state.py`**: render-contract tests for the new
  `framed_mosaic_create.html` route (form fields present, correct defaults/ranges), the
  new Planning card, the nav entry, and the `schedule_list.html` render case for
  `start_framed_mosaic` items.
- **`tests/integration/test_simulator_e2e.py`**: full round trip — submit a framed mosaic
  via the immediate-action route and verify the simulator receives the expected
  `set_setting` mosaic payload followed by goto/stack commands; submit via the schedule
  route and verify execution order and the post-completion reset; a federated `by_time`
  case verifying `panel_time_sec` division and per-device dispatch.
- **Bruno collection**: add `action-start_framed_mosaic.bru` and
  `action-add_schedule_item_framed_mosaic.bru` (plus insert/replace variants matching the
  existing Mosaic set) under `bruno/Seestar Alpaca API/Schedule - Mosaic/`, documenting
  request/response shape for manual verification against real hardware — this is also the
  natural place to eventually confirm the camera-mode question in §9.

## 11. Rollout

- Ships as a normal, default-available feature (no `Config.experimental` gate) — the nav
  entry, create page, Planning card, and API action are all live for every user once this
  lands.
- Given the reverse-engineered protocol basis, prioritize the bruno-collection
  verification pass and the emulator/CI regression suite
  (`emulator-smoke.yml`/`emulator-full.yml`) exercising this action against real
  firmware/hardware soon after landing, per §9.
