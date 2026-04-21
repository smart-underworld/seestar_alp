# Auto-Level Control Loop — Triaged TODO

Tracking the remaining work on the Seestar closed-loop velocity controller
(`device/velocity_controller.py`) and its surrounding tools
(`scripts/auto_level.py`, `scripts/tune_vc.py`, front-end tuning page at
`/auto_level_tuning`). Ordered by value-over-effort.

See `scripts/auto_level_tuning.md` for the per-run tuning log that
produced the current defaults.

---

## 🔥 Active / high-value (do next)

### 1. Validate the feedforward predictor
The predictor is default (`VC_USE_PREDICTOR = True`, `VC_TAU_S = 0.8`) but
we never ran the A/B comparison on the new `tune_vc.py` harness. One
3-min run each should confirm iterations/residual improve vs pure PD.

```
uv run python scripts/tune_vc.py \
    --setpoints=-170,+30,-60,+90,-30,+170 --tol 0.3 --alt 10 --no-predictor
uv run python scripts/tune_vc.py \
    --setpoints=-170,+30,-60,+90,-30,+170 --tol 0.3 --alt 10 --use-predictor
```

Compare mean iterations, |residual|, sign flips, wall time. Record in
`scripts/auto_level_tuning.md` as Run 6.

### 2. angle=0 first-burst anomaly
In the diagonal-calibration run, the first burst (angle=0, from a fresh
iscope recenter) moved **0.32× expected** — every other angle hit
0.97–1.01×. Likely cause: iscope→speed_move handoff leaves firmware in
a state that suppresses the first +az command. Isolate with a targeted
probe: recenter, then two identical angle=0 bursts, compare.

Suggested probe: extend `tune_vc.py` with a `--mode handoff` that does
  iscope → burst1(angle=0) → burst2(angle=0) → burst3(angle=180) →
  burst4(angle=180) and reports each burst's |v|_ratio.

### 3. Nav link to `/{telescope_id}/velocity_controller`
The route is live after `root_app.py` reload but not in the menu. One
line in `front/templates/base.html` (or its nav partial). Nice to have
so we don't have to remember the URL.

---

## ⚙️ Architecture cleanup

### 4. Module cutover
`device/velocity_controller.py` now holds the canonical
`move_azimuth_to_velocity`, but `scripts/auto_level.py` still has the
old inline copy (~285 lines) kept only to satisfy fallback-goto
plumbing. Replace with a thin `_fallback_goto_iscope` wrapper and a
direct `vc.move_azimuth_to_velocity(…, fallback_goto_fn=…)` call at the
one call site.

Related: the `_wrap_pm180` / `_speed_move` / etc. shim aliases at the
top of `scripts/auto_level.py` can go away once callers (tune_vc.py,
tests) are switched to import directly from `device.velocity_controller`.

### 5. Speed-dependent τ in predictor
Current controller uses a fixed `VC_TAU_S = 0.8`. Step-response data
shows τ ≈ 0.6 s at low speeds, ~1.2 s at mid, higher (unreliably fit)
at high speeds. A `_speed_to_tau(last_commanded_speed)` helper (piecewise
linear or table lookup) lets the predictor adapt per command.

Proposed initial table (from `auto_level_logs/step_response_wide.jsonl`):

| speed band | τ (s) |
|---|---|
| < 100    | 0.60 |
| 100–500  | 0.80 |
| 500–900  | 1.10 |
| ≥ 900    | 1.40 |  (cap — higher fits unreliable)

---

## 🧪 Controller quality (defer until cleanup above)

### 6. High-speed τ characterization
The 1000 / 1440 step-response fits were window artifacts (8 s <
steady-state). Need a multi-burst chained experiment in `tune_vc.py
--mode step_response` that issues two 10 s bursts back-to-back without
decel in between. Compute τ from the second burst's initial slope using
the first burst's terminal velocity as the starting condition.

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
