# auto_level velocity-controller tuning log

Tracking experiments on the closed-loop azimuth controller in
`scripts/auto_level.py::move_azimuth_to_velocity`.

Test command (unless otherwise noted):
```
uv run python scripts/auto_level.py --samples 12 --settle 2.0 \
    --alt 10.0 --reads-per-position 3 --arrive-tolerance 1.0 --no-live
```

Metric we care about:
- Total sweep wall time
- Per-step mean iterations
- Per-step mean |residual|
- Oscillations near target (approximated by number of direction flips)
- Boundary crossing reliability (step 2)

---

## Run 0 — baseline (commit 2f9d3fb)

**Params:** kP=0.6, loop_dt=0.5s (target), max_rate=6°/s, reissue only when
angle flips, |Δspeed|>max(20, 10%), or every 4 iters.

**Run log:** `auto_level_logs/2026-04-20T17-57-16.*`

**Observations:**
- Real loop dt ≈ **1.03–1.54s** (p50 1.03, p90 1.54, max 2.55). HTTP overhead
  dominates over the 0.5s sleep.
- Reissue gaps up to **6.6s** when speed changed little (iter 1→5 at step 7).
  Mount kept running at 6°/s for those 6s.
- Per-step median iterations ≈ **21**.
- Step 7 printed swing sequence (errors °): +30.8 → +4.7 → −10.0 → −1.1 →
  +6.2 → +2.5 → −3.6 → −4.0 → +3.7 → +2.1 → −2.1 → −1.1 → +1.1 → +1.3
  (14 sign flips before convergence to −0.55°).
- Total sweep wall time: **~7 min** for 12 samples.
- Fit: tilt 0.06°, rms 0.012. ✓ CONVERGED.

**Key findings:**
1. Loop period is 2.4× target (0.5→1.2s). HTTP latency dominates.
2. Background `PositionLogger` thread polls the same endpoint, likely adds
   serialization cost at the Alpaca action endpoint.
3. "Reissue only on big change" lets the mount cruise at old rate too long.
4. kP=0.6 with a 1.2s dead time produces classic overshoot ringing.

---

## Run 1 — PD controller + reissue every tick

**Changes vs baseline:**
- `kP=0.3` (was 0.6) — damp the overshoot caused by the ~1.2 s HTTP dead time.
- `kD=0.4` new — PD command is `kP·error − kD·measured_rate`. D term
  predicts upcoming arrival using current velocity.
- Reissue `scope_speed_move` every tick (was: only on speed/angle change).
  Bounds "runaway at old commanded rate" to one loop dt.
- Record real `dt` per tick, print it in every vc-issue log line.

**Run log:** `auto_level_logs/2026-04-20T18-11-25.*`

**Results:**
- Step 1: 2 iter, residual +0.106°.
- **Step 2 (boundary): 9 iter, 1 sign flip, residual −0.461°**
  (was 33 iter, 14 flips — a 3–4× reduction).
- Steps 4–12: all 7–10 iterations, 0–1 sign flips per step, residuals ≤ 0.92°.
- **Step 3 was pathological: 27 iter, 2 halvings, residual +0.626°.**
  Cause discovered below.
- Loop dt mean ≈ **2.0 s** (up from 1.2 s baseline, because always-reissue
  adds one HTTP command per tick on top of the measurement call).
- Total wall time ~4.5 min (was ~7 min). Fit: tilt 0.01°, rms 0.012.

**Step 3 investigation — tracking drift bug:**
After step 2 arrival, the position logger shows az going from −152° to
−172° over the next 5 s (at **≈ −5.6 °/s backward**). We issued `vc_stop`
at the end of step 2 correctly, but firmware-level tracking re-engaged
when the motor went idle and drove the mount toward some stale goto
target at near-max slew speed. That placed step 3 at az ≈ −178° when
the control loop started, forcing a boundary crossing that triggered
the stuck-halving code.

Fix: disable tracking up front with `scope_set_track_state(false)` once
in `main()` right after entering scenery mode.

---

## Run 2 — Run 1 tuning + tracking disabled

**Change:** call `scope_set_track_state(false)` after `ensure_scenery_mode`.
No other tuning changed.

**Run log:** `auto_level_logs/2026-04-20T18-22-08.*`

**Results:**
- Step 3: **10 iter, 0 halvings, residual +0.288°** (was 27/2/+0.626°).
- All steps 8–10 iterations (median 9); one step had 1 sign flip, rest 0.
- Position logger shows ≈ 0.003 °/s drift between samples (was 5 °/s).
- Total wall time ~4.5 min.
- Fit: tilt **0.01°**, rms **0.0117**. ✓

**This is the stable config going forward.** Next direction for tuning
could target loop-dt reduction (still 2 s) or further damping of the
2–3° oscillation near target before final convergence.

---
