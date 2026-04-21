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

## Phase 1 system identification (2026-04-20, scripts/sysid.py)

Dedicated sysid harness `scripts/sysid.py` with modes `step_response`,
`deadband`, `latency`, `chirp`. Data under `auto_level_logs/sysid/`.
Fitted via `device/plant_models.py`, reported by
`scripts/sysid_report.py`.

### Step response — fitted plant model (az axis)

Training: 10 bursts across speeds 80/200/400/700/900/1000/1200/1440
(single-burst + chain=2 at 900/1200/1440), all az-only.

Best fit: **first-order lag, tau = 0.335 s, k_dc = 0.996**.

| model                  | train_pos_rmse | train_rate_rmse | chirp_pos_rmse |
|---|---:|---:|---:|
| zero_order             |  0.902°        |  0.725 °/s      |  0.732°        |
| first_order            |  0.650°        |  0.689 °/s      |  0.717°        |
| first_order_ratelim    |  0.650°        |  0.689 °/s      |  0.717°        |
| asym_first_order       |  0.650°        |  0.689 °/s      |  0.894°        |

Notes:
- Rate-limited model converged with `a_max = 10 deg/s²` (bound
  unreached at any commanded speed in the training set) — the plant
  is effectively first-order in the explored region.
- Asymmetric accel/decel overfits: better train fit, worse chirp
  holdout.
- `tau = 0.335 s` is significantly shorter than the current
  `VC_TAU_S = 0.8 s` in `device/velocity_controller.py`. The 0.8 s
  default came from per-burst fits that hadn't trimmed the
  tracking-reengagement tail. The new fit trims samples to
  `motor_active == 1` plus one sample after, and fits on the
  aggregate position trajectory across all bursts.

### Deadband / stiction floor

Ramped commanded speed from 20 to 200 at 6 s dwells per step, both
directions. Result: the mount moves at ~100% of the linear model
(`rate ≈ speed / 237`) at every speed tested, including speed=20:

| speed | expected °/s | measured °/s (+az) | measured °/s (-az) |
|---|---:|---:|---:|
| 20  | 0.084 | +0.085 | -0.085 |
| 40  | 0.169 | +0.169 | -0.169 |
| 70  | 0.295 | +0.293 | -0.296 |
| 80  | 0.338 | +0.339 | -0.339 |
| 100 | 0.422 | +0.421 | -0.423 |
| 150 | 0.633 | +0.633 | -0.632 |
| 200 | 0.844 | +0.853 | -0.847 |

(one outlier at speed=60 angle=0: measured 0.004 °/s — likely a
post-burst readout glitch; the reverse direction moved correctly at
speed=60 -0.252 °/s matching expected -0.253 °/s.)

**Implication:** `VC_MIN_SPEED=100` / `VC_FINE_MIN_SPEED=80` are much
too conservative. The controller can use speed=20 or lower and still
get predictable motion. The true stiction floor is below 20 and was
not found in this probe.

### Latency (scope_speed_move RPC)

12 trials, speed=500, motion threshold 0.05°, polling 0.1 s:

- RPC ACK: mean 508 ms, p50 509, p90 510, max 510. **Extremely tight.**
- Motion-onset post-ACK: mean 700 ms, p50 618, p90 1117, max 1117.
  The 1117 ms samples are likely one extra 100 ms poll cycle — the
  mount actually started moving earlier but the rate accumulated to
  0.05° one sample later.
- Total motion-onset from t_send: ~1.1-1.6 s.

This is the dead time any controller must compensate for. A Smith
predictor with a `L = 0.6 s` delay estimate and first-order plant
(tau=0.335) is the natural baseline.

### Chirp holdout

60 s linear chirp `v_cmd(t) = 2.0 * sin(2π f(t) t)`, f0 = 0.05 Hz,
f1 = 0.3 Hz, tick 0.5 s. Held out from the fit; scored with each
fitted model. Results above. First-order model generalizes cleanly
(train 0.65°, chirp 0.72°).

### Summary for controller redesign

1. Drop `VC_TAU_S` to 0.335 s. Per-speed tau table (TODO #5) was
   probably not actually needed — the single-tau model is within
   0.7° RMSE on the chirp.
2. Drop the min-speed floors toward 20. Safety margin: use 40-60
   until this is re-verified with elevation.
3. Motion-onset dead time 0.6-0.7 s dominates. A Smith predictor
   or MPC with explicit delay is the right next controller.

### Skipped this pass

- Turnaround response (reversal dynamics / backlash)
- Speed-to-speed transitions
- Elevation axis (hard limits need extra guards)

These are follow-ups; the fitted plant model is already good enough
to start Phase 2 controller design.

---

## Phase 1 re-run with firmware timestamps (2026-04-20 evening)

Re-ran latency + step_response (single + chain=2) + chirp with
`scripts/sysid.py` now recording firmware Timestamp on every sample.

**Refreshed plant fit (training now 20 segments, old + new):**

- `first_order`: **tau = 0.348 s** (from 0.335), k_dc = 0.996. Train
  pos RMSE 0.696° (from 0.650°, slight widening from including the
  two independent runs). Rate-limited and asymmetric variants still
  offer no improvement.

**Motion-onset (firmware-timestamped, p50 over 11 successful trials):**

- RPC ACK (host): mean 759 ms, p50 509 ms, p90 1514 ms, max 1515 ms.
  Session was more RPC-noisy than the first run — 3/12 trials had
  ~1.5 s RPC latency (probably ARP cache / network congestion).
- motion-onset (host): mean 952 ms, p50 619 ms, max 2085 ms.
- **motion-onset (firmware): mean 896 ms, p50 620 ms, p90 1361 ms.**
  The firmware-time number tracks the host-time number within
  ±100 ms on clean trials, diverges under RPC congestion — as
  expected (host time counts network jitter; fw time doesn't).

Conclusion on latency: the ~620 ms floor is firmware ramp-up from
rest and cannot be compressed. Network congestion adds 0-1.5 s on
top of that. **Use `dead_time_s = 0.62` as the Smith-predictor
baseline**; expect Step 2's speed_transition experiment to give us
a much smaller number for warm (non-zero-to-nonzero) transitions.

**Chirp holdout noise (verified NOT an analysis bug):** the new
chirp run had `commanded integral = +5.37°` vs actual motion
`= -1.41°`. Confirmed via raw-data inspection — the measured az
stayed in `[-61, -50]` the whole run (no azimuth wrap near ±180),
and `unwrap_az_series` was a no-op. The discrepancy is genuine
plant misbehavior: several 2-3 s RPC gaps mid-run, during which
the mount moved ~50% of the commanded rate despite the active
speed_move TTL. Likely cause: firmware tracking re-engagement
mid-chirp, or a racing 10 s TTL expiring before the next command
arrived during an HTTP latency spike. The OLD chirp (earlier the
same day, different firmware state) still scores 0.72° RMSE with
the refreshed model — matching the training fit.

Takeaway: chirp RMSE has **high run-to-run variance due to firmware
state quirks** — a single chirp run is not a reliable holdout.
Repeatable bound: 0.7-1.0° when the firmware doesn't interfere;
3-4° when it does. The plant model itself is fine; we just need
multiple chirp runs to average out the firmware noise.

**Key insights for Phase 2:**

- Plant parameters tau and k_dc are stable across sessions
  (0.335 → 0.348 with more data; k_dc=0.996 unchanged).
- The firmware ramp dead time is ~0.62 s (cold). Warm expected
  much less.
- Chirp-holdout variance suggests we'll need multiple validation
  runs to distinguish controller improvements from session noise.

---

## Speed-transition dead-time (Checkpoint B)

Tested 8 pairs via `scripts/sysid.py --mode speed_transition`:
hold A for 8 s to reach steady state, command B, poll position at
0.3 s (≥ safe polling interval) and detect when measured rate
diverges from A by > 0.3 °/s. Ran on fast proxy (polling 0.01 s).

Results:

| A → B | angle | ss_rate_A (°/s) | fw rate-change latency |
|---|---|---:|---:|
| 0 → 300    |   0 | +0.002 | 1222 ms |
| 300 → 500  | 180 | +0.002 | 1052 ms |
| 500 → 300  |   0 | +2.100 | 1358 ms |
| 500 → 1000 | 180 | +0.002 | 1540 ms |
| 1000 → 500 |   0 | +4.219 | 1439 ms |
| 1000 → 0   | 180 | -4.197 | 1284 ms |
| 500 → 1440 |   0 | +2.100 | 1132 ms |
| 1440 → 500 | 180 | -6.096 | 1501 ms |

Over all 8: mean 1316 ms, p50 1358 ms, p90 1540 ms.

Three trials (`ss_rate_A ≈ 0.002`) where the first speed_move
after a direction-change or a sequence end didn't produce motion —
the mount was stationary at A, so those are effectively cold-start
(A=0 → B) transitions. Excluding them, the 5 genuinely-warm
transitions (3, 5, 6, 7, 8) average **1343 ms, median 1358 ms**.

**Surprising finding: warm transitions are ~2× slower than cold
(1.35 s vs 0.62 s), not faster.** Most likely explanation: the
firmware decelerates from A to zero and then re-ramps to B, rather
than smoothly transitioning. That's a full decel + ramp cycle for
every command update, regardless of magnitude.

**Implication for Phase 2 Smith predictor:** use `dead_time_s =
1.3 s` for the running controller (almost every command is a warm
transition from a nonzero rate). The 0.62 s cold figure applies
only to the first command after rest. Subtract the ~0.15 s
threshold-detection overhead from the 1.35 s number gives an
effective ramp delay of ~1.2 s.

**Implication for planner (Phase 2.0):** with a 1.3 s dead time, the
trajectory can't really be updated faster than ~0.8 Hz and still
have commands take effect before the next update. This is a much
heavier argument for commanding a feasible trajectory open-loop
(FF / MPC) than chasing feedback. Confirms the Phase 2 priority
ordering.

**Also confirms the Run 7 regression root cause.** The PD loop
issues commands every ~0.85 s post-proxy-fix. With 1.3 s effective
dead time, the controller issues ~1.5 commands per actual plant
response cycle — textbook over-commanding, exactly the oscillation
we saw.

---
