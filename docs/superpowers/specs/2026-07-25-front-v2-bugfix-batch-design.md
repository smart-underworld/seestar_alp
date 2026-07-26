# front_v2 tester bug-fix batch (search, live exposure, dark frames, zoom) + lunar/solar goto — design

Date: 2026-07-25
Branch: `bguthro/front_v2`

## Summary

A beta tester (WileECyte, Discord) running seestar_alp against a Seestar S50
on APK 2.6.4 firmware (`firmware_ver_int: 2582`) reported five bugs and one
feature gap while dogfooding `front_v2`. This design covers fixes for all
five bugs plus a small lunar/solar goto feature, in one batch, to land before
the branch merges.

Root cause for each bug was established by reading the relevant `front_v2`/
`device` code alongside the tester's own `alpyca.log` capture (which
contains the real device's `get_setting` response and live push-event
traffic), not by guessing. Two items are called out below as confirmed vs.
open/needs-verification.

## Goals

- Fix catalog search returning the wrong astronomical object for common
  queries (e.g. "M8" → "M82").
- Make the Live View exposure/gain sidebar reflect the telescope's actual
  current exposure/gain, and make edits actually take effect.
- Stop scheduled imaging sessions from running a full dark-frame calibration
  every time, regardless of the user's own dark-frames setting.
- Fix Live View's zoom-below-1× behavior, which currently letterboxes the
  video instead of shrinking the whole viewing box.
- Make the Settings page's Manual Exposure override usable: no more showing
  raw device "auto" sentinel values as an editable starting point, and
  enforce the device's real min/max so out-of-range values can't be
  silently dropped.
- Add one-tap "Goto Moon" / "Goto Sun" buttons to Live View, reusing
  existing search/goto machinery.
- Add emulator-CI (real-firmware, matrix: 2.6.4/3.2.0/3.3.0) regression
  coverage for the two bugs most plausibly firmware-version-dependent
  (exposure key mismatch, dark-frame-on-every-exposure-set).

## Non-goals

- Photo / Timelapse / Video capture modes for Live View (raw or otherwise).
  This needs its own capture-pipeline design; explicitly deferred.
- A general refactor of the search/catalog subsystem beyond fixing the
  ranking bug.
- Confirming the manual-exposure *write* path end-to-end against real
  hardware (see Open Items) — the obvious display/range bugs are fixed now;
  the write path is flagged, not fixed blind.
- Confirming exactly how Live View gain should be read/written before
  verifying against the emulator (see Open Items) — the recommended
  approach is documented, but implementation must verify first.

## Bug 1 — Catalog search returns the wrong object

**Where:** `front_v2/api/router_goto.py::_search_local`

**Root cause (confirmed):** the query is
`SELECT ra, dec, commonNames, identifiers FROM objects WHERE identifiers LIKE '%q%' OR commonNames LIKE '%q%' LIMIT 1`
— no `ORDER BY`, no exact-match priority. Verified directly against
`data/alp.dat` (15,058-row OpenNGC catalog): searching "M8" returns rowid
4195 ("M82" / Cigar Galaxy) before ever reaching an exact "M8" match,
because SQLite returns the first row satisfying the substring match in scan
order, and no row has `identifiers = 'M8'` in this catalog (it may be stored
differently, e.g. with a space, or not present standalone). This
deterministically reproduces "search M8 → Cigar Galaxy."

Planning.svelte does not hit this bug — it resolves targets via Aladin
Lite's own built-in resolver, entirely bypassing this backend endpoint,
which is why "Planning search works, everywhere else doesn't."

**Fix:**
1. Normalize both the incoming query and the stored `identifiers`/
   `commonNames` values the same way before comparing (strip whitespace,
   uppercase) — the NGC6888 report may be explained by a stored/typed
   spacing mismatch (e.g. "NGC 6888" vs. "NGC6888"); confirm during
   implementation.
2. Replace the single unranked query with tiered lookups, returning the
   first hit from the highest-priority tier that matches:
   - exact normalized match
   - prefix match
   - substring match (today's behavior, as last resort)
3. Spot-check `_search_simbad` and the `auto` dispatch
   (`_search_local(q) or _search_simbad(q)`) to confirm a bad local
   substring match never masked a correct Simbad result — this should
   naturally stop happening once local search is fixed to only return
   confident matches, but verify.

**Testing:** unit tests against `_search_local` with known collision cases
(M8 vs M82, and any other catalog rows sharing a prefix). Non-matrix (no
emulator needed — this is pure SQL/string logic against the shipped
`alp.dat`).

## Bug 2 — Live View exposure/gain sidebar

**Where:** `front_v2/api/router_live.py::get_exposure/set_exposure/set_gain`

**Root cause (confirmed for exposure):** the real firmware's `get_setting`
response nests exposure as `exp_ms: {stack_l, continuous}` — confirmed
directly from the tester's log (`'exp_ms': {'stack_l': 20000, 'continuous':
2000}`, while they reported capturing 20s subs). The current code reads
`result.get("exp_ms_continuous")`, a flat key that never exists, so
`get_exposure` always falls through to its hardcoded default (10000ms),
matching the tester's screenshot exactly. `set_exposure` has the same
mismatch on write, so slider changes are silently dropped by the firmware.

**Root cause (confirmed absent for gain, mechanism open):** `gain` does not
appear anywhere in the tester's logged `get_setting` payload. Live gain
instead arrives via push events (`Event: 'Exposure'` carrying `exp_us`,
`Event: 'View'` carrying `gain`, values observed cycling 0→80 during
mode transitions). This means `set_gain`'s current `set_setting {gain: N}`
call is likely a no-op against a field the firmware doesn't expose that
way; other gain writes in `device/seestar_device.py` use
`set_control_value ["gain", value]` instead.

**Fix:**
- `get_exposure`/`set_exposure`: switch to nested `exp_ms.stack_l` /
  `exp_ms.continuous`. Display/edit `stack_l` while `s.stage == "Stack"`,
  `continuous` otherwise (decision confirmed with project owner).
- `set_gain`/gain display: **open item, verify before implementing** (see
  Open Items). Recommended default absent contrary evidence: source
  displayed gain from the same live event stream `deviceStore` already
  consumes (already carries `gain` on `Exposure`/`View` events), and write
  via `set_control_value ["gain", N]` instead of `set_setting`.

**Testing:** emulator-matrix system test (2.6.4/3.2.0/3.3.0) — start a live
mode, change exposure via the API, assert the firmware's `get_setting`
subsequently reports the matching `exp_ms.{stack_l,continuous}` value.
First implementation step: confirm the emulator (which runs the real
firmware binary under stubbed hardware, not a hand-written mock) actually
emits this nested shape identically to the real device log, so the test
isn't validated against a fixture that happens to match the buggy code.

## Bug 3 — Dark-frame calibration runs on every scheduled exposure change

**Where:** `device/seestar_device.py::action_set_exposure` (~line 1771),
invoked by the scheduler via `telescope.py:279` / `seestar_device.py:2793`.

**Root cause (strong lead, not yet hardware-confirmed):**
`action_set_exposure` unconditionally calls `start_create_dark` immediately
after every `set_setting exp_ms.stack_l` write — with no gating on any
dark_frames flag. Since most/all scheduled imaging items set an exposure at
some point, this means a full dark calibration runs on nearly every
scheduled session regardless of the user's own Startup/Schedule
"Dark Frames: Off" choice (those toggles were confirmed working correctly
for the *startup sequence* action specifically, in the tester's own logs —
this is a separate, unguarded code path).

**Decision (confirmed with project owner):** treat as a bug — gate it.

**Fix:** thread a `dark_frames` boolean through into
`action_set_exposure`'s params (sourced from the same schedule-item
`dark_frames` field already collected by Startup.svelte/Schedule.svelte),
defaulting to `false` to match existing UI defaults, and only call
`start_create_dark` when true.

**Testing:** emulator-matrix system test (2.6.4/3.2.0/3.3.0) — run a
scheduled item with `dark_frames: false` and assert `start_create_dark` is
never sent to the firmware; companion case with `dark_frames: true`
asserting it is sent.

## Bug 4 — Live View zoom below 1× letterboxes instead of shrinking

**Where:** `front_v2/ui/src/pages/Live.svelte`

**Root cause (confirmed):** zoom is implemented purely as CSS
`transform: scale()` on the `<img>`, inside a `.feed-wrap` container whose
own layout size never changes. Below 1.0, the image visually shrinks but
the surrounding box (and its background) stays full-size, producing the
border the tester screenshotted. Zoom above 1× (with pan, for viewing
clipped detail) is a separate, already-correct use case.

**Fix:** below 1×, resize `.feed-wrap` itself (e.g. `width: {zoom*100}%`,
centered within its parent) instead of relying solely on the image
transform. At/above 1×, keep today's `transform: scale()` + pan-and-clip
behavior unchanged.

**Testing:** component/visual test (Playwright or Svelte component test)
asserting `.feed-wrap` shrinks below 1× with no residual border. Non-matrix
— pure frontend CSS/layout, no firmware involved.

## Bug 5 — Settings page Manual Exposure override

**Where:** `front_v2/ui/src/pages/Settings.svelte`

**Root cause (confirmed for the sentinel display):** `isp_exp_ms: -999000`
and `isp_gain: -9990` are real device-reported "auto" sentinel values
(confirmed directly in the tester's log), not a display bug — the code
already has a `REQUIRES_MANUAL_EXP` gate acknowledging this. The real
problems: (a) toggling Manual Exposure to "Enable" doesn't reset the
now-editable field away from the sentinel, so the user's starting point
is literally "-999000"; (b) there's a likely units mismatch — the device
reports `isp_range_exp_us: [30, 1000000]` (**microseconds**, ~1 second max)
against a field named/labeled `isp_exp_ms`, with no `CONSTRAINTS` entry at
all today, and `isp_range_gain: [0,400]` vs. the unrelated Live View gain
slider's 0–300 max.

**Decision (confirmed with project owner):** fix the obvious/confirmed part
now; explicitly flag the write-path as unverified rather than guessing
further.

**Fix:**
- When `manual_exp` flips to enabled, seed `isp_exp_ms`/`isp_gain` with a
  real starting value (not the sentinel).
- Add `CONSTRAINTS` entries for `isp_exp_ms` (converted from the device's
  `isp_range_exp_us`, µs→ms) and `isp_gain` (from `isp_range_gain`), so
  out-of-range input is rejected client-side before it can be silently
  dropped by the device.
- Leave the save/write mechanism itself unchanged — the field names already
  match firmware's own flat naming for this feature (unlike Bug 2's
  nested-vs-flat mismatch) — but flag in Open Items that we have not
  confirmed end-to-end against real hardware that a valid, in-range value
  actually takes effect.

**Testing:** Settings.svelte component test asserting the sentinel is never
shown as an editable value once Manual Exposure is enabled, and that
out-of-range input is rejected. Non-matrix.

## Feature — Lunar/Solar Live View goto shortcuts

Scope (confirmed with project owner): goto shortcuts only. Photo/Timelapse/
Video capture modes are out of scope (see Non-goals).

- Add "Goto Moon" and "Goto Sun" buttons to `Live.svelte`.
- Each button calls the existing
  `/api/v1/devices/{dev_num}/search?catalog=planet&q=moon|sun` endpoint
  (already implemented via `_search_planet`, which resolves live ephemeris
  coordinates) and feeds the result directly into the existing `/goto`
  endpoint. No new backend logic — this is wiring two existing pieces
  together.
- Manual exposure/gain tweaking "in the moment" for sun/moon/planet modes
  is already covered by Bug 2's fix once the sidebar reflects real values —
  no separate work needed here.

**Testing:** covered incidentally by existing goto/search tests plus a new
component test that the buttons fire the expected search+goto calls.
Non-matrix.

## Open items (must resolve during implementation, before/while coding)

1. **Gain read/write mechanism for Live View (Bug 2).** Confirm against the
   emulator (and/or real hardware) whether gain is obtainable via
   `get_stack_setting`, or only via the live push-event stream, before
   committing to an implementation. Recommended default if nothing better
   turns up: read from the event stream already flowing into `deviceStore`;
   write via `set_control_value ["gain", N]`.
2. **Manual Exposure write path (Bug 5).** Not confirmed end-to-end against
   real hardware whether a valid, in-range `isp_exp_ms`/`isp_gain` value
   actually takes effect after save. Flagged, not fixed blind — worth a
   quick real-hardware or emulator check early in implementation, since it
   may reveal a second bug beyond the units/default issue.
3. **Emulator fidelity check.** Before writing the two emulator-matrix
   tests (Bugs 2 and 3), confirm the emulator's real firmware binary
   actually emits the nested `exp_ms: {stack_l, continuous}` shape (and the
   push-event gain/exposure shape) seen on real hardware for each matrix
   version — the emulator runs actual firmware code under stubbed hardware
   rather than a hand-written fixture, so this should hold, but must be
   checked rather than assumed.

### Follow-ups noted during implementation (2026-07-25), not fixed in this round

- **Bug 4 (zoom), `min-height: 200px` floor on `.live-feed`.** Below a
  certain zoom-out width, this pre-existing CSS floor could in principle
  reintroduce a small letterbox on a *different* axis than the one this
  round's fix addressed. Low priority: for the tester's actual portrait-
  aspect feed, the natural (aspect-ratio-derived) height only drops below
  200px once the box narrows to roughly ~110px wide — far narrower than
  any realistic "smaller window" use case — so this is unlikely to matter
  in practice. Not fixed; revisit only if a real report surfaces it.
- **Bug 4 (zoom), fullscreen + zoom < 1 interaction.** `.feed-wrap-fs`'s
  `flex: 1` and `.live-feed-fs`'s `height: 100%` derive the image's height
  from the fullscreen container's own flex sizing, independent of the
  zoom-driven `feedWrapStyle` width shrink — so a border could reappear on
  the vertical axis specifically while fullscreen. Not fixed in this round
  (zooming out while already fullscreen is an unusual combination, and this
  is CSS static analysis, not a rendered/visual confirmation). Revisit if a
  real report surfaces it.
- **Lunar/solar goto feature, missing `Value: false` handling.** `Live.svelte`'s
  new `gotoBody()` (Task 6) awaits `api.devices.goto(...)` and treats any
  non-throwing response as success — it never checks `result.Value === false`,
  which is how the device layer signals "a goto is already in progress" (no
  exception, no non-2xx status). `Goto.svelte:66-76` already handles this
  correctly and documents why. Tapping Goto Moon/Sun while a goto is already
  running will silently no-op instead of showing an error. Pre-existing gap
  in this task's own new code, confirmed by the final reviewer, not fixed in
  this round (doesn't block Task 6, since it was never a regression — the
  behavior simply hasn't been built yet).
- **`Goto.svelte`'s existing planet-catalog searches have the same
  double-precession bug Task 6 fixed for Live View.** `Goto.svelte:66`
  calls `api.devices.goto($activeDevNum, ra, dec, targetName)` with no
  `isJ2000` argument, which defaults to `true` — but its catalog dropdown's
  `"planet"` option resolves via the same `_search_planet`, which returns
  JNow coordinates. Confirmed as a real, pre-existing bug (predates this
  entire batch) by the Task 6 final reviewer, not something Task 6
  introduced or is in scope to fix. A user searching Moon/Sun/a planet via
  the Planning/Goto page's catalog dropdown and hitting "GoTo" would hit
  the same pointing error Task 6 just fixed for the two new Live View
  buttons. Worth a small standalone follow-up fix (mirroring Task 6's
  `is_j2000: false` fix, scoped to wherever `Goto.svelte` learned the
  result came from the `"planet"` catalog) — not fixed in this round.

### Verification results (2026-07-26, emulator spike)

- exp_ms nested shape: confirmed on v2.6.4 / v3.2.0 / v3.3.0 (all three
  CI-matrix versions) — `get_setting` returned
  `"exp_ms":{"stack_l":10000,"continuous":500}` on every version, against
  the real `zwoair_imager` binary in the emulator. v2.6.4 also emitted a
  push `"Event":"Setting"` with nested `exp_ms` during boot, independent
  corroboration of the same shape outside the RPC path. (v2.6.4's
  `get_device_state` additionally reported `firmware_ver_int:2582` /
  `firmware_ver_string:"5.82"`, an exact match to the original tester's
  real-device log — confirms this is genuinely the reported version, not
  just a same-numbered rebuild.)
- gain present on View events: confirmed on v2.6.4 / v3.2.0 / v3.3.0 —
  every version's `"Event":"View"` push notification (triggered by
  `iscope_start_view {"mode":"star"}`) carried a `"gain"` field (value `0`
  at view start in this short observation window); `"Event":"Exposure"`
  was not observed in this preview-only window (only a gain-less
  `ContinuousExposure` fired alongside `View`) — not fixed-dependent, since
  `View` alone already carries `gain`. No version's `get_setting` response
  contained a flat `gain` key.
- **Open Item #1 resolved**: `get_stack_setting` was probed directly on
  v2.6.4 — it is a real, implemented method (`code:0`) but its result
  object contains only `save_discrete_frame`/`save_discrete_ok_frame`/
  `light_duration_min`, no `gain` key. Gain is confirmed obtainable *only*
  via the live push-event stream (`View`'s `gain` field), not via
  `get_stack_setting` or any other RPC observed. The recommended
  event-stream approach is the only viable source, not merely the
  fallback default. Full transcripts in `.superpowers/sdd/task-7-report.md`.

### Correction (2026-07-26): `AbstractDevice`/ABC claim in the Task 8 plan

The implementation plan's Task 8 justified implementing `get_last_gain` on
`SeestarDevice`, `SeestarRemote`, and `SeestarFederation` alike by claiming
`AbstractDevice` is a real `ABC` that all three subclass, so skipping any
one would break instantiation. Task 8's reviewer found this is only true
for `SeestarRemote` — `SeestarDevice` (the `Seestar` class) and
`SeestarFederation` (`Seestar_Federation`) don't inherit from
`AbstractDevice` at all. The resulting code is still correct and
consistent (matching the existing `action_set_exposure` pattern in all
three), just built on an inaccurate premise for two of the three classes.
No code change needed; noted here so the premise isn't relied on again in
a future task.

### Follow-up (2026-07-26): federation `dev_num=0` gain type contract — fixed

Task 8's reviewer found `get_exposure` would leak a federation-fan-out
dict (`{"1": 80, ...}`) through as the `gain` field for `dev_num=0`
requests, since the original guard only checked for `None`. Unreachable
via the current Live View UI (which already blocks `dev_num=0` with "Live
view requires a single telescope"), but fixed anyway as API-boundary
hardening: `get_exposure` now rejects any non-`int` gain value (falls back
to 80), verified not to reject a real `gain=0` reading.

### Accepted as-is (2026-07-26): `get_last_gain` doesn't compare event recency

`get_last_gain` statically prefers `View`'s gain over `Exposure`'s
whenever both are present, rather than comparing timestamps to pick
whichever event is genuinely newer (no timestamps are tracked). Accepted:
Task 7's emulator spike never observed a `gain` field on `Exposure` events
at all across any firmware version, only on `View` — so static
View-preference is very likely correct in practice, not merely a
convenient simplification. Revisit only if an `Exposure`-carried `gain` is
ever observed for real.

### Fixed during implementation (2026-07-26): Task 2's `set_exposure` never reached the firmware

While writing Task 9's real end-to-end system test, discovered that
`set_exposure` (`front_v2/api/router_live.py`, from Task 2) called
`do_action("set_setting", dev_num, {...})` directly — but `"set_setting"`
is a firmware *method* name, not a registered Alpaca *action* in
`device/telescope.py`'s dispatcher, so the write silently no-op'd against
real firmware (confirmed via a genuine emulator round-trip: the value
never changed). This is the identical bug pattern already fixed once
before in this repo (commit `ae54037`, "settings saves now reach
firmware", for `save_device_settings`) — reintroduced here, and uncaught
by Task 2's own tests since they mock `do_action` directly rather than
exercising the real dispatcher. Fixed by routing through
`method_sync(..., params=...)`, matching `ae54037`'s exact precedent;
re-verified end-to-end against a real emulator.

**Follow-up, not fixed in this round**: `front_v2/api/router_guestmode.py`
has the identical `do_action("set_setting", ...)` direct-dispatch bug
(two call sites, master_cli true/false) — found while checking for
sibling instances of the `set_exposure` bug, but unrelated to this batch
and out of scope to fix here.
