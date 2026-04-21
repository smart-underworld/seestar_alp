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

---

## Run 5 — step-response characterization

Added `scripts/tune_vc.py --mode step_response`. Commands
`scope_speed_move(speed, angle, dur=8 s)` from rest, samples position
every 0.5 s, fits `rate(t) = r_ss · (1 − exp(−t/τ))` using the position
integral model. Also added `InstrumentedAlpacaClient` that records
per-method round-trip HTTP latency.

**Run logs:** `auto_level_logs/step_response_wide.jsonl`, `/tmp/step_wide.log`.

**Findings:**

1. **Average-rate calibration verified at ±1 %** for speeds 80..1440:
   `total_motion / 8 s ≈ speed / 237` across the tested band. The
   module constant `_SPEED_PER_DEG_PER_SEC = 237` is sound.

2. **Stiction floor is around speed=80.** Below that the motor barely
   moves:

   | speed | 8 s motion | expected | ratio |
   |------:|-----------:|---------:|------:|
   |    20 |    0.13°   |    0.63° |  21 % |
   |    50 |    0.03°   |    1.58° |   2 % |
   |    80 |    2.68°   |    2.53° | 106 % |
   |   100 |    3.35°   |    3.16° | 106 % |

   Action: raised `_VC_MIN_SPEED` from 50 → 100 and `_VC_FINE_MIN_SPEED`
   from 20 → 80. This explains the 0.2–0.5° residual "tails" in earlier
   runs: the fine nudge at speed=50 wasn't producing meaningful motion.

3. **Time constant τ grows with speed.** Fit values (8 s bursts):

   | speed | τ (s) | note |
   |------:|------:|---|
   |    80 | 0.59 | clean |
   |   100 | 0.69 | clean |
   |   300 | 0.70 | clean |
   |   500 | 1.00 | clean |
   |   700 | 1.22 | clean |
   |  1000 | 4.82 | **unreliable** — ramp didn't complete in 8 s |
   |  1200 | 1.39 | clean |
   |  1440 | 2.62 | **partial** — borderline |

   At high speeds the mount doesn't reach steady-state within the 8 s
   firmware cap, so τ is ambiguous (a "high r_ss + long τ" fit and a
   "low r_ss + short τ" fit both match the integrated motion over 8 s).
   A cleaner high-speed τ would need multi-burst experiments.

4. **HTTP latency unchanged** after the Wi-Fi relocation:

   | method | p50 ms | p90 ms | p99 ms |
   |---|---:|---:|---:|
   | scope_get_equ_coord   | 508 | 1011 | 1473 |
   | scope_speed_move      | 509 |  510 | 1515 |
   | get_device_state      | 509 | 1014 | 1512 |

   The bottleneck is the Alpaca action endpoint's fixed overhead, not
   network RTT.

**Implications for future tuning:**

- Residuals below ~0.4° will be dominated by one-tick-of-min-speed
  motion (100/237 × loop_dt ≈ 0.85° at a 2 s tick, 0.42° at 1 s).
  For tighter targets we need either a shorter loop dt (requires
  solving the HTTP latency), or an open-loop "nudge-then-hold" pulse
  that's too short to build velocity.
- Feedforward predictor worth adding:
  `projected_az = measured_az + measured_rate · dt + (commanded_rate
  − measured_rate) · max(0, dt − τ)`
  using τ ≈ 0.7 s for mid-range speeds. Clamp τ at ~1.2 s for
  speeds ≥ 1000 (the 2.6/4.8 fits are window artifacts).
- The 45°-vector calibration question is still open — I've only
  measured cardinal angles. Adding a diagonal probe to `tune_vc.py`
  would tell us whether the firmware decomposes properly.

**This is the stable config going forward.** Next direction for tuning
could target loop-dt reduction (still 2 s) or further damping of the
2–3° oscillation near target before final convergence.

---
