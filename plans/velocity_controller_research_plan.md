# Velocity controller — system ID and control algorithm roadmap

Research-and-engineering plan for evaluating and improving the Seestar S50
azimuth (and eventually elevation) velocity controller in
`device/velocity_controller.py`. Starts with rigorous system identification,
uses the identified plant to evaluate candidate control algorithms, and
ends with a validated controller that can handle the ~0.3-0.7 s variable
RPC latency.

Position sensor throughout: encoder-integrated RPC (`scope_get_equ_coord`).
Plate-solve is out of scope for this plan.

**Azimuth wrap:** the S50 spins infinitely in azimuth (no cable-wrap limits).
The existing `wrap_pm180` keeps measured az in [-180, +180) and per-sample
rate is computed from `wrap_pm180(az_new - az_prev)` which is correct as
long as |true delta| < 180. For fitting we need a continuous cumulative
position; add `unwrap_az_series` that integrates wrapped per-sample deltas.
Elevation has physical limits and needs no unwrap.

See `scripts/auto_level_tuning.md` for the per-run tuning log and
`plans/auto_level_control_loop_todo.md` for near-term triaged tasks.

---

## Current state (baseline)

- **Harness:** `scripts/tune_vc.py` has three modes — `setpoints`,
  `step_response`, `diagonal`. Writes per-run JSONL into
  `auto_level_logs/`. HTTP latency summarized on every run via
  `InstrumentedAlpacaClient`.
- **Sysid data on hand:** `auto_level_logs/step_response.jsonl` (4 speeds)
  and `step_response_wide.jsonl` (speeds 80-1200, tau ~0.59-1.39 s).
  Azimuth only. No speed-to-speed, turnaround, deadband, or chirp data.
- **Plant model used by the controller:** first-order lag
  `rate(t) = r_ss * (1 - exp(-t/tau))` with a single global
  `VC_TAU_S = 0.8 s`. Feedforward predictor in
  `device/velocity_controller.py` lines 342-350 uses the deadbeat form
  `v_cmd = (error - v_now*G) / (dt - G)` where `G = tau*(1 - exp(-dt/tau))`.
- **Sensor:** encoder-integrated RPC (`scope_get_equ_coord`) only.
- **Known gap:** speed-1440 tau fits are unreliable (8 s burst never
  reaches steady state at r_ss ~6 deg/s); speed-dependent tau table is a
  pending TODO (item #5).

---

## Plant properties (stepper + anti-skip)

The Seestar uses stepper motors with onboard anti-skip protection.
The firmware ramps the commanded step rate to avoid losing sync.
That makes the plant deterministic in a way generic control-design
frameworks assume it isn't. Five observable consequences and their
controller-design implications:

| Plant property | Why it's true | Implication for controller |
|---|---|---|
| Commanded rate = actual rate (after firmware ramp) | Anti-skip means steps never drop. Motion-per-step is fixed by gearing. | **No velocity observer needed** (Kalman, complementary filter) — we know `v` from the commands. |
| Position = integrated command | Onboard encoder counts pulses and increments position deterministically. | **No position filter needed.** RPC-reported position is noise-free at the encoder resolution. |
| The measured `tau = 0.335 s` is the firmware ramp, not mechanical dynamics | Tau tracks almost perfectly with step-rate ramp-up time; mechanical masses would introduce higher-order modes we don't see. | **FF is extremely powerful** — invert the known ramp and position error is quantization. |
| Stiction floor is a firmware minimum step rate, not physics | Deadband probes show motion at speed=20 matching speed/237 to 1%; below some threshold the firmware sends zero pulses. | **No high-gain feedback needed** to break through stiction — just command above the floor. |
| Rate cap at 1440 is a firmware ceiling, not torque saturation | Speed > 1440 silently produces the same 6 °/s rate. | **Rate limit is a hard constraint** for the trajectory planner, not a soft one. |

Takeaway: the dominant uncertainty in this system is **pure dead
time** (~0.7 s cold, expected 0.3-0.4 s warm). That makes Smith
predictor (2.3) the archetypal architecture for this plant and FF
(2.1) an extremely strong baseline. Generic-plant techniques that
invest in noise rejection / velocity observation / high-gain
feedback are mostly wasted here; they solve problems we don't
have.

### Firmware timestamps

Every firmware RPC response includes a monotonic `Timestamp` field
formatted as a decimal-seconds string with sub-microsecond
precision, e.g. `"9507.244805160"`. Format reference:
`device/seestar_device.py:500`. It represents firmware uptime in
seconds and is the right clock for:

- dt between consecutive position samples (HTTP-latency-free)
- motion-onset latency measured as
  `fw_t_first_motion - fw_t_ack`
- aligning commanded vs. measured trajectories in controllers that
  need sub-tick timing accuracy (Smith's delay queue, MPC's
  horizon)

The device proxy (`device/seestar_device.py`) preserves `Timestamp`
on RPC responses and strips it only in the SSE event stream
(`get_events`, line 2680). `AlpacaClient.method_sync` returns the
entire response dict untouched, so host code has access today —
sysid + controller code switched over in this plan.

Host `time.monotonic()` stays useful for scheduling (sleep to the
next tick, rate limits), just not for measuring plant dynamics.

---

## Phase 1: System identification

Goal: produce a validated per-axis plant model good enough that an
open-loop feedforward command for a known trajectory lands within the
arrival tolerance without closed-loop correction.

### 1.1 Step response tests (extend existing)

Build on the existing `--mode step_response`. Extensions needed:

- **Sweep both axes.** Currently azimuth-only. Add `--axis {az,el}` and
  issue `angle=0/180` vs `angle=90/270`. Capture elevation bursts at
  safe altitudes (15-45 deg to avoid horizon/zenith edge cases).
- **Longer bursts for high-speed fits.** Current 8 s `dur_sec` caps at
  the firmware limit of 10 s. The TODO #6 "multi-burst chained"
  experiment in `plans/auto_level_control_loop_todo.md` is the
  remediation: issue two consecutive 10 s bursts at the same (speed,
  angle), no intervening stop; fit tau on the second burst using the
  first burst's terminal velocity as initial condition.
- **Finer speed grid.** Current: 80, 100, 200, 300, 500, 700, 1000,
  1200, 1440. Add: 40, 60, 70 (below the ~80 stiction floor), 900,
  1100, 1300 (upper linear range).
- **Output:** per-run `auto_level_logs/sysid/step_<axis>_<date>.jsonl`
  with raw (t, alt_deg, az_deg) samples plus fitted
  `(speed, r_ss, tau, fit_rmse)` rows.

### 1.2 Speed-to-speed transitions

New mode `--mode speed_transition`:

- Command speed A for 8 s, then switch to speed B for 8 s without stop.
- Sweep A,B pairs: (100, 500), (500, 100), (500, 1000), (1000, 500),
  (1000, 1440), (1440, 1000). Both axes, both angles.
- Fit tau separately for the A-to-B transient; compare against
  tau-from-rest for the same B.
- **Hypothesis to test:** motor torque (and hence tau) depends on
  current speed, not just commanded speed.

### 1.3 Turnaround response

New mode `--mode turnaround`:

- Command +speed for 8 s, then -speed for 8 s at the same magnitude.
- Sweep speeds (300, 700, 1440) on both axes.
- Measure (a) reversal time (time between commanded sign flip and
  observed zero crossing), (b) overshoot past zero, (c) any backlash
  dead-zone visible in the position trace.
- Log the sign flips already captured by `InstrumentedAlpacaClient`
  latency timing to distinguish RPC latency from mechanical turnaround.

### 1.4 Deadband characterization

New mode `--mode deadband`:

- Ramp commanded speed from 0 upward in unit steps (speed = 20, 30, 40,
  50, 60, 70, 80, 90) with 5 s dwell and 2 s rest between steps.
- Record which commanded speed first produces >0.1 deg/s motion; log the
  stiction floor per direction and per axis.
- Known: existing data shows ~80 is the threshold on az. Quantify
  hysteresis (descending ramp from 200 down to 0).

### 1.5 dur_sec behavior

New mode `--mode dur_sec_probe`:

- Issue identical (speed, angle) commands with `dur_sec` values 1, 2,
  3, 5, 8, 10. Measure motion duration.
- Issue overlapping commands: fire cmd A with `dur_sec=10`, then 2 s
  later fire cmd B with different (speed, angle). Observe whether B
  replaces A immediately (probably yes, per existing notes), queues
  behind A, or is rejected.
- Also test: does `dur_sec=0` act as a stop command? Does it throw?

### 1.6 Latency measurement

Refine `InstrumentedAlpacaClient`:

- Already captures `t_send -> t_response` (full RPC round-trip). Add
  `t_response -> t_first_motion` by polling `scope_get_equ_coord` at the
  max-safe rate (0.3 s) starting immediately after ACK and looking for
  the first sample where |rate| > 0.1 deg/s.
- Produce per-axis histogram of motion-onset latency separately from
  RPC latency. Motion-onset latency is what the controller dead-time
  compensator must handle.

### 1.7 Axis asymmetry

Every experiment above runs on both axes in one sweep, with results
tagged by axis. Compare fitted parameters side by side; flag any
asymmetry > 10%.

### 1.8 Validation via chirp / sinusoid

New mode `--mode chirp`:

- Generate a commanded-velocity profile `v_cmd(t) = A * sin(2*pi*f(t)*t)`
  where `f(t)` ramps linearly from 0.05 Hz to 0.5 Hz over 60 s. Sample
  amplitude A = 2 deg/s (well below r_ss at speed=500).
- Issue `scope_speed_move` once per control-loop tick (0.5 s), updating
  the commanded speed/angle from the chirp.
- **Holdout test:** fit plant model on steps 1.1-1.4 data only, then
  predict the chirp response with the fitted model and compare to
  measured chirp response. RMSE between predicted and measured is the
  headline fidelity metric.

### Candidate model forms to fit

Fit each to the combined sysid dataset and report RMSE + AIC:

1. **Zero-order:** `v_actual = v_cmd * k_dc` (baseline; `k_dc` from
   steady-state slope).
2. **First-order lag:** `tau * dv/dt = v_cmd - v`. Single global tau, and
   per-speed tau lookup.
3. **First-order + rate limit:** first-order model with `|dv/dt|`
   saturated at a fitted `a_max` (accel cap). Most likely to fit the
   speed_transition data.
4. **Asymmetric accel/decel:** separate tau for v_cmd > v vs v_cmd < v.
   Fit only if step-up vs step-down residuals on 1.2 data diverge > 15%.
5. **Piecewise lookup:** per-axis LUT of
   `(current_speed, cmd_speed) -> expected_rate_30ms_later`. Fallback
   when closed forms don't hit the chirp validation target.

Each model exposes the same interface (`predict(state, cmd, dt) ->
next_rate`) so the controller code stays agnostic.

### Phase 1 deliverables

- `scripts/tune_vc.py` modes added: `speed_transition`, `turnaround`,
  `deadband`, `dur_sec_probe`, `chirp`. Existing `step_response`
  extended for both axes and multi-burst chaining.
- `auto_level_logs/sysid/` directory with per-experiment JSONL.
- `device/plant_models.py` (new): each candidate model as a class with
  `fit(data) -> params` and `predict(state, cmd, dt) -> rate`
  (or `next_state`).
- `scripts/sysid_report.py`: loads everything under
  `auto_level_logs/sysid/`, fits all candidate models, prints a
  comparison table (RMSE, AIC, chirp-holdout RMSE per axis and model).
- Results written up in `scripts/auto_level_tuning.md` as Run 7+ entries.

---

## Phase 2: Control algorithm evaluation

Hold controller bake-off until Phase 1 produces a trusted plant model.
Then evaluate these in order.

The "Plant properties" section above reshapes priorities. Because
the plant is deterministic with pure dead time as the only real
uncertainty: **FF (2.1) and Smith (2.3) are the two primary
candidates**, EKF (2.2) is repurposed as a slow bias estimator only
(never a velocity observer), and MPC (2.4)'s robustness value is
reduced (but its constraint-handling value remains). PID (2.6)
stays dismissed.

### 2.0 Feasible trajectory planner (prerequisite)

Every controller below needs a reference trajectory `(pos(t), vel(t))`
that respects the plant limits identified in Phase 1:

- rate cap (currently `MAIN_RATE_DEGS = 6.0` at speed=1440)
- accel cap (from rate-limited first-order model, 1.3)
- stiction floor (deadband from 1.4)
- axis independence / cross-coupling (diagonal 1.7)

Planner output: a sequence of `(t_k, pos_ref_k, vel_ref_k, acc_ref_k)`
feasible under those limits from `(pos_0, vel_0)` to
`(pos_target, 0)`. Simplest implementation is a trapezoidal velocity
profile with accel-limited ramps; the next step up is an S-curve
(bounded jerk) for smoother commands. MPC (2.4) absorbs the planner
implicitly; FF (2.1), FF+EKF (2.2), and Smith (2.3) all consume the
planned trajectory as the reference the controller tracks.

Proposed module: `device/trajectory.py` with a `trapezoidal_profile`
and `scurve_profile` function, both taking
`(p0, v0, p_target, v_max, a_max)` and returning a `PlannedTrajectory`
dataclass iterable over (t, p, v, a). Reuse across az and el axes by
parameterizing the limits.

Evaluated controllers below then track the planner's output:

### 2.1 Pure feedforward (FF) — open-loop

Given the identified plant inverse, generate `v_cmd(t)` directly from a
desired `(az_target, alt_target)` trajectory. No feedback.

- **Test:** run the existing setpoint sweep with feedback disabled,
  compare final residuals. If FF alone gets within ~1 deg of setpoint
  consistently, the plant model is good and most of the controller's
  complexity can be retired.
- **Failure mode:** slowly-accumulating pointing bias (e.g., mount
  not perfectly level, encoder drift). This is what 2.2 fixes.

### 2.2 Feedforward + EKF bias estimator

FF for fast dynamics; a low-bandwidth EKF estimates slow
pointing-model biases (tilt, encoder offset) from intermittent feedback
and trims the FF command.

- **State vector:** (az_bias, alt_bias, optional: tilt_magnitude,
  tilt_phase).
- **Measurement:** RPC az/alt minus commanded.
- **Process noise:** low (biases are slow).
- **Measurement noise:** per-sample, tuned from sysid data.

### 2.3 Smith predictor

Compensates for the ~0.3-0.7 s measurement + command delay by running
feedback against an internal delay-free model; the real (delayed)
measurement is used only to correct model mismatch.

- **Requirement:** delay must be reasonably constant or band-limited.
  Phase 1.6 determines this.
- **Expected benefit:** stable feedback gains 2-3x higher than the
  current PD, without oscillation.

### 2.4 MPC (Model Predictive Control)

Solves a constrained QP over a 2-3 s finite horizon each tick, using
the identified plant model. Constraints: rate limits, speed floor
(stiction), az/alt soft limits, command-rate-of-change
(smoothness).

- **Computational cost:** a small dense QP (~10 horizon steps * 1
  input) is microseconds even in pure Python; the 0.5 s loop dt gives
  huge headroom.
- **Expected benefit:** natively handles rate saturation and the
  stiction floor; produces smoother commands; trivially extensible to
  elevation-axis coupling and field-of-view constraints later.

### 2.5 Dead-beat acquisition + FF tracking

Two-mode controller: for |error| > ~5 deg, compute the
minimum-duration burst that lands at the target given the identified
plant; after arrival, hand off to FF tracking (Phase 2.1 or 2.2).

- **Natural fit for auto_level:** each sweep step is a large-error
  acquisition followed by a sampling window. The current controller
  effectively does this implicitly; formalizing it may simplify
  the state machine.

### 2.6 PID — dismissed

Classical feedback oscillates at useful gains given the measured
0.3-0.7 s variable latency. Existing PD controller lives at the edge
of stability (see tuning log Run 3). Do not invest further without
a step-change reduction in measurement latency.

### Bake-off method

- Same setpoint list as Run 6 A/B (`--setpoints=-170,+30,-60,+90,-30,+170`).
- Metrics per run, per algorithm: total wall time, mean/max |final
  residual|, iterations (commands issued), wall time to first arrival
  within 1 deg, wall time to first arrival within 0.3 deg (arrive
  tolerance), sign flips (oscillation proxy), max measured rate.
- Each controller implemented as an alternative inside the same
  `move_azimuth_to_velocity` shape (takes `cli, target, cur, loc,
  target_alt, ...` and returns `(measured_alt, measured_az, stats)`)
  so the harness wrapping is identical.

---

## Supporting terms (glossary)

- **tau** — first-order time constant of the plant response (seconds).
  Also used loosely for transport delay; Phase 1.6 separates them.
- **r_ss** — steady-state rate (deg/s) reached at a given commanded
  speed.
- **FOV** — Field of View (the angular patch the sensor sees).
- **RPC** — Remote Procedure Call. Here: the JSON-RPC interface to the
  scope (`method_sync` on the Alpaca action endpoint).
- **EKF** — Extended Kalman Filter.
- **MPC** — Model Predictive Control.
- **FF** — feedforward (open-loop command computed from a model
  inverse).

---

## Success criteria

Phase 1 exits when:

- All 8 experiments have been run at least once on both axes, data is
  under `auto_level_logs/sysid/`.
- At least one candidate model fits the step/transition/turnaround
  data with < 5% RMSE in predicted rate.
- The chirp holdout test has < 10% RMSE between predicted and
  measured position over the 60 s run.

---

## Phase 1 results (2026-04-20)

Executed: step_response (10 bursts), deadband (20 speeds), latency (12
trials), chirp (60 s). Deferred: turnaround, speed_transition, elevation
axis — the fitted plant is already good enough to begin Phase 2.

**Plant model:** first-order lag with `tau = 0.335 s`, `k_dc = 0.996`.
Training position RMSE 0.65°, chirp-holdout RMSE 0.72°. Rate-limited
and asymmetric variants offer no improvement (plant is clean first-order
in 0.05-0.3 Hz band).

**Stiction:** floor is below speed=20 firmware units. Motion matches
`speed / 237` within 1% across 20-200. Current controller's
`VC_MIN_SPEED=100` / `VC_FINE_MIN_SPEED=80` are far too conservative.

**Latency:** RPC ACK 508±1 ms, motion-onset post-ACK mean 700 ms
(p90 1117 ms). Total motion-onset from command send ~1.1-1.6 s — the
dead time any Phase 2 controller must compensate.

Full write-up in `scripts/auto_level_tuning.md` under the Phase 1
heading.

Phase 2 exits when:

- At least one controller (2.1-2.5) meets both: mean |residual| < 0.2
  deg across the Run 6 setpoint sweep, and total wall time < 180 s
  (20% faster than Run A's 229 s).
- No step in the sweep requires the iscope fallback.
