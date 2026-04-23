# Auto-Level Control Loop — Triaged TODO

Tracking the remaining work on the Seestar closed-loop velocity controller
(`device/velocity_controller.py`) and its surrounding tools
(`scripts/auto_level.py`, `scripts/tune_vc.py`, front-end tuning page at
`/auto_level_tuning`). Ordered by value-over-effort.

See `scripts/auto_level_tuning.md` for the per-run tuning log that
produced the current defaults.

---

## 🔥 Active / high-value (do next)

### 1. ~~Validate the feedforward predictor~~ superseded by Phase 1
Phase 1 sysid (`plans/velocity_controller_research_plan.md`) fit the
plant directly and showed τ is **0.335 s, not 0.8 s**. The Run 6 A/B
was partially completed (Run A captured) but the finding above
supersedes it — update `VC_TAU_S` and re-measure once.

### 2. angle=0 first-burst anomaly
In the diagonal-calibration run, the first burst (angle=0, from a fresh
iscope recenter) moved **0.32× expected** — every other angle hit
0.97–1.01×. Likely cause: iscope→speed_move handoff leaves firmware in
a state that suppresses the first +az command. Isolate with a targeted
probe: recenter, then two identical angle=0 bursts, compare.

Suggested probe: extend `tune_vc.py` with a `--mode handoff` that does
  iscope → burst1(angle=0) → burst2(angle=0) → burst3(angle=180) →
  burst4(angle=180) and reports each burst's |v|_ratio.

### 3. ~~Nav link to `/{telescope_id}/velocity_controller`~~ ✅ done (commit cf1c570)

---

## ⚙️ Architecture cleanup

### 4. ~~Module cutover~~ ✅ done (commit 9ab4994)
Inline duplicate of `move_azimuth_to_velocity` deleted from
`scripts/auto_level.py`; shim aliases removed; both scripts import
from `device/` only. `AlpacaClient` moved to
`device/alpaca_client.py`; `PositionLogger`, `ensure_scenery_mode`,
`issue_slew`, `wait_until_near_target`, `iscope_fallback_goto`,
`altaz_to_radec`, `radec_to_altaz`, `angular_distance_deg` moved to
`device/velocity_controller.py`. Unit tests unchanged.

### 5. ~~Speed-dependent τ in predictor~~ not needed per Phase 1
Phase 1 fit shows a single `tau = 0.335 s` with chirp-holdout RMSE
0.72°. Asymmetric / rate-limited variants offered no improvement.
The earlier per-speed τ spread (0.6–1.4 s) was an artifact of
per-burst fits contaminated by post-burst deceleration /
tracking-reengagement — the Phase 1 fitter trims to `motor_active=1`
and fits on aggregate position.

Action: drop `VC_TAU_S` from 0.8 to 0.335 in
`device/velocity_controller.py`, drop `VC_MIN_SPEED`/`VC_FINE_MIN_SPEED`
from 100/80 to safer low values (40/20), and re-measure on hardware.

---

## 🧪 Controller quality (defer until cleanup above)

### 6. ~~High-speed τ characterization~~ done via chain=2 in Phase 1
`scripts/sysid.py --mode step_response --chain 2` issues back-to-back
10 s bursts; data at speeds 900/1200/1440 fed into the fit. Result:
single-τ model still best. No per-speed table needed.

### 7. Integral term
Small steady residuals (~0.1–0.2°) might close with a capped `kI`.
Only worth doing if a user actually wants an arrive-tolerance below
what #5 (speed-dependent τ) already gives us. Add anti-windup
(clamp integral when at rate ceiling).

### 8. Step-response panel in tuning page
`/auto_level_tuning` currently shows only the live position log.
Adding a second tab with `step_response_*.jsonl` samples and their
fitted curves would make it easy to spot calibration drift between
sessions.

---

## 🔌 Integration / UX (bigger chunks)

### 9. Auto-level from the web UI
Currently CLI-only. Can be wrapped as a front-app action that calls
`velocity_controller` directly via the in-process `seestar_device`
(skipping the AlpacaClient HTTP hop — faster loop dt, no serialization
contention with the PositionLogger). Bigger lift but the natural end
state.

### 10. Remove legacy feedforward mover
Once velocity-mode is locked in as the only controller, delete
`move_azimuth_to` in `scripts/auto_level.py` plus its feedforward
constants (`_MAIN_MIN_SPEED`, `_MAIN_CLOSE_ENOUGH_DEG`,
`_MAX_MAIN_BURSTS`, `_MAIN_STUCK_PROGRESS_DEG`, `_NUDGE_*`) and the
`--control-mode` CLI flag.

---

## Notes for the next session

- Unit tests in `tests/test_auto_level.py` stay green across all of
  this — the math module (`device/auto_level.py`) is untouched.
- `dev_autoreload.sh` at the repo root restarts `root_app.py` on
  front/ and device/ edits (1 s debounce). Use while iterating on the
  tuning page or any device-side integration.
- `auto_level_logs/` is gitignored; both raw logs and the tuning
  markdown live under `scripts/` (e.g., `scripts/auto_level_tuning.md`).
