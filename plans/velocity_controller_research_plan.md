# Velocity controller — system ID and control algorithm roadmap

Research-and-engineering plan for evaluating and improving the Seestar S50
azimuth (and eventually elevation) velocity controller in
`device/velocity_controller.py`. Starts with rigorous system identification,
uses the identified plant to evaluate candidate control algorithms, and
ends with a validated controller that can handle the ~0.3-0.7 s variable
RPC latency.

---

## Executive summary — what to do next (for a fresh Claude Code session)

**Where we are (2026-04-21 end-of-session):** The 2-axis closed-loop
velocity controller is working end-to-end. Az, el, and 2D diagonal
moves all converge to ≤ 0.25° residual. Everything is committed.

| Component | Status | Commits |
|---|---|---|
| Closed-loop FF+FB (az) | **done** — Run 11 met Phase-2 exit (0.14° mean) | `eb64a1d` |
| Raw encoder readout (`scope_get_horiz_coord`) | **done** — replaces stale `scope_get_equ_coord` | `eb64a1d` |
| Cable-wrap limits (±435° usable) | **done** — probed, saved, planner-integrated | `eb64a1d` |
| Closed-loop FF+FB (el) | **done** — limits ±70.8° usable, 3 moves ≤ 0.13° | `ba8a679` |
| 2D combined `move_to_ff(az, el)` | **done** — 4 diagonals ≤ 0.22° | `68f21f1` |
| Diagonal speed fix (per-axis clamp) | **done** — firmware clamps per-axis at 1440, not total | `868490d` |
| Velocity controller page fixes | **done** — PositionLogger→horiz_coord, event field fix, el overlay | `2040be6` |

**Firmware speed model (verified 2026-04-21):**
- Per-axis max: speed=1440 → 6.054°/s. Ratio = 237.8 speed/°/s.
- Speed > 1440 is per-axis clamped (not rejected). Diagonal at
  speed=2036 (1440×√2) angle=45° gives each axis full 6°/s.
- `PLAN_MAX_RATE_DEGS = 6.0` is the per-axis cap; the 2D controller
  clamps per-axis (not magnitude), so diagonals don't sacrifice rate.
- `SPEED_PER_DEG_PER_SEC = 237` confirmed correct with mid-50%
  cruise-rate measurement at multiple speed settings.

**What to do next (priority order):**

1. **Velocity controller page: show live data without setpoints.**
   Currently the page only shows data when `PositionLogger` is running
   (launched by `tune_vc.py`). Need a standalone "live position" mode
   that reads `scope_get_horiz_coord` directly (even during manual
   jogs or idle state) and feeds the chart.

2. **Streaming trajectory consumer** for dynamic targets (plane chase,
   sidereal tracking). Builds on `move_to_ff`. Needs:
   - External source feeding `(t, az, el)` reference stream.
   - `unwind_azimuth` called before each tracking session if cable is
     wound past threshold.
   - Time-varying reference injection into the 2D controller loop
     (currently the loop runs a pre-computed fixed trajectory).

3. **Run a clean 6-setpoint az sweep with cumulative limits** to
   confirm the full pipeline end-to-end. Run 15 step 1 was clean
   (+0.12°); step 2 hit a network disconnect (not controller-related).

4. **Cable-wrap cumulative state across restarts.** Currently the
   `CumulativeAzTracker` resets each time `tune_vc.py` runs. For
   multi-session tracking, persist the cumulative state to a file or
   track it via the firmware's startup-home assumption (cum=0 after
   every power cycle).

**Session-restart cheat-sheet:**
```bash
# Unit tests (38 should pass):
uv run python -m pytest tests/test_auto_level.py tests/test_trajectory.py -q

# Hardware az setpoint sweep (loads plant_limits.json automatically):
uv run python scripts/tune_vc.py --control feedforward \
  --setpoints=-170,+30,-60,+90,-30,+170 --tol 0.3 --alt 10

# Quick 2D diagonal test (both axes):
uv run python -c "
import os, sys; sys.path.insert(0, '.')
from astropy import units as u
from astropy.coordinates import EarthLocation
from device.alpaca_client import AlpacaClient
from device.config import Config
from device.velocity_controller import (
    move_to_ff, measure_altaz_timed, ensure_scenery_mode, set_tracking,
    wait_for_mount_idle,
)
Config.load_toml()
loc = EarthLocation(lat=Config.init_lat*u.deg, lon=Config.init_long*u.deg, height=0*u.m)
cli = AlpacaClient('127.0.0.1', 5555, 1)
ensure_scenery_mode(cli)
set_tracking(cli, False)
wait_for_mount_idle(cli, timeout_s=5.0)
alt, az, _ = measure_altaz_timed(cli, loc)
move_to_ff(cli, target_az_deg=30, target_el_deg=20,
           cur_az_deg=az, cur_el_deg=alt, loc=loc,
           el_min_deg=-70.9, el_max_deg=70.8)
"

# Read current encoder position:
uv run python -c "
import sys; sys.path.insert(0, '.')
from device.alpaca_client import AlpacaClient
from device.velocity_controller import measure_altaz_timed
from device.config import Config
from astropy import units as u; from astropy.coordinates import EarthLocation
Config.load_toml()
cli = AlpacaClient('127.0.0.1',5555,1)
loc = EarthLocation(lat=Config.init_lat*u.deg,lon=Config.init_long*u.deg,height=0*u.m)
alt,az,_=measure_altaz_timed(cli,loc)
print(f'az={az:+.3f}°  el={alt:+.3f}°')
"
```

**Key file paths:**
| File | What |
|---|---|
| `device/velocity_controller.py` | `move_azimuth_to_ff`, `move_elevation_to_ff`, `move_to_ff`, `unwind_azimuth`, `measure_altaz_timed`, `PositionLogger` |
| `device/trajectory.py` | `trapezoidal_profile`, `scurve_profile` (both accept `wrap_target`, `az_forbidden_deg`) |
| `device/plant_limits.py` | `AzimuthLimits`, `CumulativeAzTracker`, `pick_cum_target` |
| `device/plant_limits.json` | Measured cable-wrap + el limits (gitignored — per-device) |
| `scripts/tune_vc.py` | `--control feedforward` setpoint sweep harness |
| `scripts/sysid.py` | `--mode limits` (dithered probe), `--mode trajectory_track` |
| `front/templates/velocity_controller.html` | Chart page (trajectory ref from ff_tick/2d_ff_tick events) |
| `front/app.py` | `VelocityControllerLogResource` (JSONL → JSON) |

**Controller defaults (all in `velocity_controller.py`):**
- `profile = "scurve"`, `kp_pos = 0.5 /s`, `v_corr_max = 2.0 °/s`
- `v_max = PLAN_MAX_RATE_DEGS = 6.0 °/s` (per-axis; firmware clamps at speed=1440)
- `SPEED_PER_DEG_PER_SEC = 237` (linear, verified)
- `arrive_tolerance_deg = 0.3°`, `settle_max_s = 5.0 s`, `converged_ticks_required = 2`
- `cold_start_lag_s = 0.0` (closed-loop feedback absorbs cold-start)

**Plant limits (in `plant_limits.json`):**
- Az cable wrap: ±450° hard stops, ±435° usable (15° padding). Symmetric around power-on home.
- El: hard stops ±85.8°, usable ±70.8° (15° padding).

> Jump to [Phase 3](#phase-3-closed-loop-ffFB--cable-wrap-calibration-2026-04-21)
> for full session context, or [Phase 4](#phase-4-elevation-control--2-axis-motion-done)
> for the elevation/2D results.

---

Position sensor: raw motor encoder via **`scope_get_horiz_coord`** (as of
2026-04-21). Older sections still reference `scope_get_equ_coord`; that
path is unreliable when the scope hasn't plate-solve-aligned in the
current power session. See Phase 3 for details.

**Azimuth wrap (CORRECTED 2026-04-21):** the S50 does NOT spin infinitely
in azimuth — it has a finite cable wrap of **~900° (~2.5 turns)** total
travel, symmetric about the power-on home position. Both hard stops are
mechanical, detectable via stall when commanded speed stops producing
motion. Measured limits and cumulative-az tracking live in
`device/plant_limits.py` (`AzimuthLimits`, `CumulativeAzTracker`,
`pick_cum_target`) with persisted calibration in
`device/plant_limits.json`. `wrap_pm180` still applies per-sample (true
delta stays < 180°); the planner can now operate in cumulative
(unwrapped) coordinates for multi-turn safety via `wrap_target=False`.

**Elevation limits (2026-04-21):** hard stops at ±85.8° encoder-deg,
usable ±70.8° with 15° padding. No wrap (el is a bounded joint < 180°
range). Simple min/max clamp in `move_elevation_to_ff`.

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

---

## Phase 2 progress (2026-04-20 / 2026-04-21)

### Checkpoint A (timestamps + constants) — DONE

- **Commit 3a297a1** plumbed firmware timestamps through
  `measure_altaz_timed`, `PositionLogger`, `sysid.py`, `plant_models.py`,
  `tune_vc.py`. All `scope_get_equ_coord` responses now carry a
  monotonic firmware `Timestamp` (sub-µs precision). Old JSONL
  still loads via fallback to host-t.
- **Commit 61540fa** captured re-run latency / step_response / chirp
  with firmware timestamps. Refit: `tau = 0.348 s` (from 0.335),
  `k_dc = 0.996`. Training pos-RMSE 0.696°, chirp holdout 0.72° on
  the earlier cleaner session (the new chirp had firmware-state
  anomaly; single-run chirp is not a reliable holdout).
- **Commit ddbf66e** three related changes: VC_TAU_S 0.8→0.348,
  VC_MIN_SPEED 100→40, VC_FINE_MIN_SPEED 80→20, VC_CMD_DUR_S 10→5,
  loop-tick sleep made deadline-based. Plus the proxy polling fix:
  `device/seestar_device.py:666` `sleep(0.5)` → `sleep(0.01)`.
  Back-to-back RPC RTT dropped from ~500 ms to ~230 ms (remaining
  floor is Falcon / network / TCP processing, not the proxy poll).
- **Run 7 regression** at fast proxy + new constants: total wall
  380 s, mean residual 11°, step 3 residual 61°, 4 fallbacks. The
  faster tick rate doubled controller command rate, but PD gains
  (kp=0.3, kd=0.4) tuned at ~1.5 s tick became unstable at ~0.85 s
  tick. Not a plant issue; just gain mismatch.

### Checkpoint B (speed_transition / warm dead time) — DONE

- **Commit 36a0e53 + 411a20d.** New `--mode speed_transition` in
  `scripts/sysid.py`; full-trace raw-data analysis corrected an
  earlier premature conclusion.
- **Finding: warm transitions have ≈ 0 pure dead time.** All 5
  tested warm transitions match pure first-order τ=0.348 s by the
  first observable sample (~1.5 s). No sign of decel-through-zero.
- **Cold-start is 0.5 s pure delay + 0.13 s to position threshold**
  (firmware ramp from rest takes longer than ramp between
  non-zero rates).
- **Implication: Smith predictor (D2) provides minimal value** over
  pure FF for this plant. Smith compensates dynamic delay; we have
  none during running.

### Checkpoint C (trajectory planner) — DONE

- **Commit 28d3737.** New `device/trajectory.py` with
  `trapezoidal_profile` and `scurve_profile`. 9 unit tests
  (`tests/test_trajectory.py`) pass — endpoint correctness,
  v_max/a_max constraints, triangular fallback, zero-delta,
  v0 handoff, ±180 wrap path selection, sample interpolation,
  S-curve jerk-cap. Defaults: `v_max=6.0 °/s, a_max=10.0 °/s²,
  j_max=40.0 °/s³`.

### Checkpoint D1 (FF controller + correction wrapper) — IN PROGRESS

**Architecture decision** (user-directed): keep `move_azimuth_to_ff`
as pure open-loop, add a separate `move_azimuth_to_with_correction`
wrapper that calls FF then runs a bounded slow-nudge correction
loop. Rationale: the inner FF stays ready for future streaming
trajectory control (dynamic-target tracking), while the outer
correction layer handles slow-drift / plant-gain / cold-start
residuals. Both in `device/velocity_controller.py`.

`scripts/tune_vc.py` `--control` options:
- `velocity` (default) — existing PD+predictor
- `feedforward` — FF + correction wrapper (the realistic controller)
- `ff_pure` — pure FF, no correction (for evaluating raw FF)

**Run 8** (FF + correction, 6 setpoints):

| step | target | residual | iter | wall | flags |
|---|---|---|---|---|---|
| 1 | -170 | -0.022° |  2 |  7.7s | |
| 2 |  +30 | -0.935° | 35 | 65.9s | |
| 3 |  -60 | +0.025° | 22 | 41.9s | |
| 4 |  +90 | +0.326° | 33 | 70.8s | FB (iscope) |
| 5 |  -30 | +0.025° | 25 | 46.4s | |
| 6 | +170 | +0.569° | 33 | 66.3s | |

Total wall 302 s (vs Run A 229 s); |residual| mean 0.317° (vs Run A
0.075°); mean iterations 25.0 (vs 24.7); **0 oscillations** (flips
= 0 across every step, vs Run A avg 0.7). One fallback — step 4's
post-FF residual was 6.7°, and the three-nudge correction at
speed=20 (0.085 °/s × 10 s = 0.84° per nudge) only closed 2.5° of
that before running out of attempts.

**Observations for next session:**

1. **FF + correction is stable (zero oscillation) but slower than
   Run A's PD.** The added ~73 s wall time is post-FF settling
   (1.5 s × 6 steps = 9 s) and the slow-speed nudges (up to 30 s
   per step when 3 corrections fire).
2. **FF open-loop error on large moves (>100°) is 3-7°** — larger
   than predicted from k_dc + cold-start. Worth investigating
   whether the extra error is accumulated latency (proxy polling
   introduces a small command-issue drift during motion), speed
   saturation (1440 hitting slightly below 6 °/s), or a plant
   quirk we haven't modeled.
3. **Correction loop at speed=20 is undersized for residuals > ~2.5°.**
   Options: faster nudge (speed=100 covers ~4.2° per 10 s), or
   retry-FF for residuals above a threshold, or increase
   max_corrections.

### Pending — Checkpoint D2 reassessment

Smith predictor was preemptively planned as D2. **Checkpoint B's
finding that warm dead time ≈ 0 argues Smith has nothing to
compensate for.** Run 8's residuals are static/gain/cold-start,
not dynamic delay. Recommendation: **skip D2**; instead refine the
correction layer (faster nudge speed, retry-FF) which directly
attacks the observed error source.

### Open items (resume here tomorrow)

Post-Run-8 analysis: the plant cruises at 5.93-6.00 °/s (roughly
matching commanded 6.0 °/s) but the trajectory accumulates ~6.7° of
position deficit on a 150° move. Decomposition:
- **~3°** from cold-start 0.5 s delay (mount doesn't start moving
  until ~0.5 s after trajectory t=0).
- **~1.2°** from slight cruise rate deficit over 17 s of cruise.
- **~2.5°** unexplained — likely decel-phase imperfection or a
  second-order effect.

Correction loop with 3 × 0.84° nudges at speed=20 only closes 2.5°,
so a 6.7° post-FF residual triggers fallback.

1. **Add cold-start compensation to the trajectory planner or FF
   controller.** Cleanest: `trapezoidal_profile(..., t_offset=L)`
   where trajectory samples are shifted by L seconds, so the FF
   controller commands the trajectory's t=0 point at wall time -L.
   Default L=0.5 (cold-start); pass via `move_azimuth_to_ff` as a
   new arg. Alternative: FF pre-rolls v_peak for L seconds before
   the real trajectory. Option A is cleaner.
2. **Add planner-isolation validation test** (new
   `scripts/sysid.py --mode trajectory_track` or hardware-probe
   script). Issue a known trapezoidal trajectory, poll position at
   sample_dt, compute RMSE of `meas_az(t)` vs `ref_pos(t - L)`.
   This cleanly separates planner correctness from FF execution
   behavior.
3. **Tune the correction layer to close larger residuals**: either
   faster nudge (speed=100 → 0.42 °/s, 4° per 10 s) for residuals
   > 2°, or retry-FF for residuals > 1°. With cold-start compensation
   (item 1), post-FF residual should drop to ~2° so the correction
   layer's existing 2.5° capacity is adequate.
4. **Investigate the unexplained ~2.5° deficit**. Options: (a)
   cruise rate saturation is actually < 6.0 °/s at high speed;
   replicate step_response at speed 1440 and fit. (b) decel-phase
   runs faster than model predicts.
5. **Overlay trajectory reference on the /velocity_controller page.**
   `ff_tick` events contain `ref_pos`, `ref_vel`, `cmd_speed`,
   `cmd_angle` at every tick. The page currently only plots samples
   + coarse commanded setpoint from `set_target()`. Adding a
   trajectory-reference line makes FF tracking errors visually
   obvious (today we have to post-process JSONL manually for
   analysis). Changes: `front/app.py` log parser emits the `ff_tick`
   event stream; `front/templates/velocity_controller.html` adds
   a reference overlay on the azimuth axis plot.
6. **Skip Smith (D2)** unless above fails.
7. **Tier-2 2-axis extension** (elevation sysid, 2D trajectory
   planner, `move_to_ff(target_az, target_el)`) — queued for after
   D1 wraps.

### Session restart cheat-sheet

Quick resume from a fresh Claude session:

- **Current controller under test:** `move_azimuth_to_ff` +
  `move_azimuth_to_with_correction` in
  `device/velocity_controller.py`.
- **Trajectory planner:** `device/trajectory.py` with
  `trapezoidal_profile` and `scurve_profile`.
- **Test harness:** `scripts/tune_vc.py --control feedforward`
  (FF + nudge correction), `--control ff_pure` (open-loop only),
  `--control velocity` (legacy PD+predictor).
- **Hardware verification command:**
  ```
  uv run python scripts/tune_vc.py --control feedforward \
    --setpoints=-170,+30,-60,+90,-30,+170 --tol 0.3 --alt 10 \
    --loop-dt 0.5 --max-rate 6.0 --a-max 10.0
  ```
- **Unit tests:** `uv run python -m pytest tests/test_auto_level.py
  tests/test_trajectory.py -q` — 30 tests should pass.
- **Run-log dir** (gitignored): `auto_level_logs/` (JSON summaries,
  JSONL position traces, sysid traces under `sysid/`).
- **Plant constants after Phase 1:** `VC_TAU_S=0.348`,
  `VC_MIN_SPEED=40`, `VC_FINE_MIN_SPEED=20`, `VC_CMD_DUR_S=5`
  (`device/velocity_controller.py`).
- **Proxy latency floor:** ~230 ms RPC (post `device/seestar_device.py:666`
  sleep=0.01 fix). Two RPCs per tick = ~500 ms real tick.
- **Key findings carried over:**
  - Plant is first-order with τ=0.348 s, k_dc=0.996.
  - Stiction floor is below speed=20, not 80 as previously set.
  - Warm motion-onset dead time ≈ 0 s; cold-start is ~0.5 s pure
    delay (Smith predictor has nothing to compensate during
    running).
  - FF + correction is stable (0 oscillations) but slower and
    residual-noisier than PD (0.317° vs 0.075°). Step 4's 6.7°
    post-FF residual is the main failure mode to fix next.

### Commit handles

| Checkpoint | Commit | One-liner |
|---|---|---|
| A1 timestamps + doc | `3a297a1` | firmware Timestamp plumbing |
| A2 re-run sysid | `61540fa` | tau refit to 0.348 |
| A3 constants + proxy | `ddbf66e` | proxy poll 500ms→10ms; VC constants |
| B speed_transition | `36a0e53` | + correction `411a20d` |
| C trajectory planner | `28d3737` | trapezoid + S-curve + 9 tests |
| D1 FF + correction | `15199b3` | Run 8 captured |

`git log --oneline | head -10` for the full tail.

Phase 2 exits when:

- At least one controller (2.1-2.5) meets both: mean |residual| < 0.2
  deg across the Run 6 setpoint sweep, and total wall time < 180 s
  (20% faster than Run A's 229 s).
- No step in the sweep requires the iscope fallback.

---

## Tier-2 follow-up: 2-axis control (post-Phase 2)

Current FF (`move_azimuth_to_ff`) and the trajectory planner operate
on a single scalar axis (azimuth). Elevation is not controlled by
these functions — auto-level fixes elevation during its sweep, and
Phase 1 sysid was az-only.

Firmware capability: `scope_speed_move(speed, angle, dur_sec)` takes
a single 2D vector. Phase 1 diagonal probe confirmed the firmware
correctly vector-decomposes `angle=45°` into sqrt(2)/2 velocity on
each axis — native 2-axis diagonal motion via ONE command per tick.

Extension path, in order:

1. **Elevation sysid.** Replicate `scripts/sysid.py --mode step_response`
   and `--mode deadband` on elevation (angle=90 / 270) across several
   safe altitudes. Confirm τ, k_dc, stiction floor match az values —
   expected because same stepper / gearing, but gravity load may
   shift el's τ slightly. Fold into `plant_models.py` as per-axis
   params.

2. **2D trajectory planner** (`device/trajectory_2d.py`). Plans in
   (az, el) space with scalar `v_max`, `a_max` on motion magnitude
   `|v_vec|`, NOT per-axis. Naturally produces diagonal trajectories
   when both axes change.

3. **`move_to_ff(target_az, target_el)` generalization** of
   `move_azimuth_to_ff`. Uses 2D planner; per-tick converts
   `(v_az, v_el)` to firmware `(speed, angle)` via
   `speed = |v_vec| · 237`, `angle = atan2(v_el, v_az)`. Single
   firmware command per tick commands both axes simultaneously.

4. **Streaming trajectory consumer** for dynamic-target tracking.
   `move_to_ff` becomes a loop that continuously consumes new 2D
   trajectory references (sidereal tracking, moving-object chase).
   A low-bandwidth bias estimator (per-axis, or joint pointing EKF)
   trims the reference as slow drift accumulates. This is the
   natural extension of the FF + correction wrapper pattern in
   `move_azimuth_to_with_correction`: same separation of concerns,
   different time scale for the correction loop.

Benefit of Tier 2 over Tier-1 sequential single-axis moves: for a
(30°, 30°) point-to-point, Tier 1 takes ~14 s (7 s az + 7 s el).
Tier 2 takes ~7 s (single sqrt(2) diagonal at the magnitude limit).
Bigger benefit for tracking: Tier 2 is natural; Tier 1 doesn't apply
because both axes move continuously.

---

## Phase 3: closed-loop FF+FB + cable-wrap calibration (2026-04-21)

### Summary of session

This session re-architected the controller (removing post-hoc nudge
loops in favor of in-motion position feedback) and discovered / measured
the mount's finite cable-wrap limits.

### Key discoveries

1. **Mount has finite cable wrap (~900° = 2.5 turns)**, NOT infinite
   azimuth rotation. Hard stops are symmetric about the power-on home
   position (±450° each side). Measured via `sysid.py --mode limits`
   with dithered command re-issue + retry-on-stall detection. The
   firmware silently drops repeated identical `scope_speed_move`
   commands at ~80s intervals, producing spurious "stalls" (detected
   and bypassed by the retry mechanism). Saved to
   `device/plant_limits.json`; usable range set to **±435°** (15°
   padding on each side).

2. **`scope_get_equ_coord` (RA/Dec) does NOT track encoder motion live
   unless plate-solve-aligned.** Without alignment (e.g. after a cold
   power-up), RA/Dec is stale and the astropy-converted az is useless.
   Switched `measure_altaz_timed` to `scope_get_horiz_coord` which
   returns **raw motor-encoder [alt, az]** — always live, always
   mount-frame, never compass-influenced. This is the correct data
   source for closed-loop control.

3. **Encoder az is NOT compass-influenced.** Verified by rotating the
   tripod ~120° while powered: encoder az unchanged, compass direction
   changed by the expected amount. Encoder az is a pure mount-internal
   readout, zeroed at each power-on to the home (cable midpoint)
   position. The firmware also exposes `compass_sensor.direction`
   (MEMS magnetometer, `cali=0`) separately — the two are independent.

4. **Startup (power-on) position = cable midpoint.** Verified: mount
   spins ~1.25 turns CW during power-off → parks at midpoint.
   Symmetric: ±450° of cable from there. The center wrapped-az at
   power-on is approximately 0° in the encoder frame (but the
   firmware's internal "home" is at horiz_coord[1] ≈ 0° ± some noise;
   not the same as compass heading or sky azimuth).

### Architectural changes

**Closed-loop FF+FB controller** (`move_azimuth_to_ff`):
- At every tick: `v_cmd = v_ff(t) + clamp(kp_pos · pos_error, ±v_corr_max)`.
- Firmware timestamps (`scope_get_horiz_coord.Timestamp`) align ref
  with measurement RPC-jitter-free.
- After trajectory ends, loop continues at `ref_vel=0 + feedback` until
  `|pos_error| ≤ arrive_tolerance_deg` for `converged_ticks_required`
  consecutive ticks, or `settle_max_s` timeout.
- **No separate nudge / correction phase.** The nudge loop and its
  adaptive-speed logic are deleted.
- Defaults: `kp_pos=0.5 /s`, `v_corr_max=2.0 °/s`, `v_max=5.0 °/s`
  (via `PLAN_MAX_RATE_DEGS`), `profile=scurve`, `cold_start_lag_s=0`.

**S-curve as default profile**: S-curve's jerk-limited accel ramp gives
the firmware smoother first-tick commands, avoiding the "step velocity
change" that trapezoid + cold-start-hold produced (which caused the
Run 9 short-move regression). S-curve is strictly better on the
hardware runs than trapezoid for both long and short moves.

**Cable-wrap-aware planning** (`device/plant_limits.py`):
- `AzimuthLimits` dataclass with `usable_ccw_cum_deg`, `usable_cw_cum_deg`.
- `CumulativeAzTracker`: integrates wrapped encoder deltas into
  unwrapped cumulative az.
- `pick_cum_target(cum_cur, wrapped_cur, wrapped_target, limits)`:
  picks short or long path such that the cumulative target stays
  within the usable cable range.
- `trapezoidal_profile` / `scurve_profile` accept `wrap_target=False`:
  in cumulative mode the planner uses `delta = p_target - p0` verbatim
  (no wrap_pm180, no az_forbidden check). Caller is responsible for
  computing a valid cumulative target beforehand.
- `unwind_azimuth(cli, loc, tracker, limits, ...)`: moves mount back
  to cumulative 0 (cable midpoint) if |cum| > threshold_deg. Called
  before dynamic tracking to restore cable headroom.

**`measure_altaz_timed` switched to `scope_get_horiz_coord`**: returns
raw motor-encoder `[alt, az]`. `loc` parameter kept for backward compat
but unused. This fixes the stale-RA/Dec problem and removes the astropy
conversion overhead + time/location dependency from the measurement path.

**Velocity controller page** (`/velocity_controller`): azimuth chart
dataset 1 now reads `ff_tick.ref_pos` from JSONL events (the trajectory
reference curve), not the flat step-setpoint. Falls back to legacy
`commanded_az_deg` when no `ff_tick` events are in the window.

### Hardware run results

| Run | Config | Wall | \|res\| mean | FBs | Notes |
|---|---|---|---|---|---|
| 8 | trap no-comp (PD+pred) | 229 s | 0.32° | 1 | old baseline |
| 9 | trap + cold_start 0.5 | 338 s | 2.54° | 3 | cold-start hold hurt short moves |
| 10 | scurve no-comp | 359 s | 2.06° | 3 | scurve better FF, but nudges too weak |
| 11 | scurve + adaptive nudge | **183 s** | **0.14°** | **0** | Phase-2 exit met (max |res| 0.225°) |
| 12 | same @ v_max=5 | 284 s | 17.9° | 2 | hardware-state failure steps 3,5 |
| 13 | closed-loop FF+FB (no nudge) | — | — | — | step-2 errored (firmware hiccup) |
| 14v2 | closed-loop FF+FB | 185 s | 16.9° | 2 | controller clean where mount moves; steps 3,5 hit +5° CCW cable-wrap limit |
| 15 (partial, 3 steps) | CL + az_forbidden=7 | — | steps 1-3 ≤ 0.08° | 0 | planner correctly routed step 3 the long way CW |

### Files changed (not yet committed)

```
device/velocity_controller.py   — measure_altaz_timed switched to scope_get_horiz_coord;
                                   closed-loop FF+FB; unwind_azimuth; az_limits/az_tracker plumbing;
                                   PLAN_MAX_RATE_DEGS=5.0; scurve as default profile
device/trajectory.py            — t_offset, az_forbidden_deg, wrap_target params
device/plant_limits.py          — NEW: AzimuthLimits, CumulativeAzTracker, pick_cum_target
device/plant_limits.json        — NEW: measured cable-wrap calibration (±450 hard, ±435 usable)
tests/test_trajectory.py        — 4 t_offset tests, 4 az_forbidden tests (38 total, all pass)
scripts/tune_vc.py              — scurve + closed-loop defaults; --kp-pos, --v-corr-max,
                                   --profile, --az-forbidden, --no-az-limits; loads plant_limits.json
scripts/sysid.py                — --mode limits (dithered, retry-on-stall);
                                   --mode trajectory_track + --profile/--cold-start-lag flags
front/templates/velocity_controller.html — trajectory-ref overlay from ff_tick events
```

### Session-restart cheat-sheet (next session)

- **Current architecture:** closed-loop FF+FB in `move_azimuth_to_ff`.
  `v_cmd = v_ff(t) + kp_pos * pos_err`. No nudge loop, no separate
  correction wrapper. `move_azimuth_to_with_correction` is a thin
  alias.
- **Position readout:** `measure_altaz_timed` → `scope_get_horiz_coord`
  → raw encoder `[alt, az]`. NOT `scope_get_equ_coord` (stale without
  plate-solve alignment).
- **Cable-wrap limits:** ±450° hard, ±435° usable. Loaded from
  `device/plant_limits.json` by `tune_vc.py`. Planner uses cumulative
  coordinates when limits are active (`wrap_target=False`).
- **Defaults:** `profile=scurve`, `kp_pos=0.5`, `v_corr_max=2.0`,
  `v_max=5.0` (via `PLAN_MAX_RATE_DEGS`), `cold_start_lag_s=0.0`.
- **Firmware dither:** the probe (`sysid.py --mode limits`) randomizes
  `dur_sec` on re-issue to avoid firmware command dedup. The closed-loop
  FF controller doesn't need dither because each tick's `v_cmd` varies
  naturally with the trajectory + feedback.
- **Unit tests:** `uv run python -m pytest tests/test_auto_level.py
  tests/test_trajectory.py -q` — 38 tests should pass.
- **Hardware test:** after power-on, the mount homes to cable midpoint
  (encoder az ≈ 0°). Run
  ```
  uv run python scripts/tune_vc.py --control feedforward \
    --setpoints=-170,+30,-60,+90,-30,+170 --tol 0.3 --alt 10
  ```
  (defaults load plant_limits.json, scurve profile, closed-loop FF+FB).

---

## Phase 4: elevation control + 2-axis motion — DONE

### Status

| Step | Status | Details |
|---|---|---|
| 4.1 **El limits probe** | **DONE** | hard stops ±85.8°, usable ±70.8° (15° padding). Saved in plant_limits.json. |
| 4.2 **El sysid** | **skipped** | El converges with az-derived tau — no separate sysid needed. |
| 4.3 **Independent el controller** | **DONE** | `move_elevation_to_ff` — 3 moves ≤ 0.13° (commit `ba8a679`). |
| 4.4 **Combined `move_to_ff(az, el)`** | **DONE** | 2D velocity composition works (commit `68f21f1`). |
| 4.5 **Diagonal speed fix** | **DONE** | Per-axis clamp, not magnitude. 4 diagonals ≤ 0.22° (commit `868490d`). |
| 4.6 **Velocity controller page** | **DONE** | PositionLogger→horiz_coord, event field fix, el+2d overlay (commit `2040be6`). |
| 4.7 **Streaming trajectory consumer** | **pending** | Next priority. |

### Firmware speed model (verified empirically 2026-04-21)

Tested with mid-50% cruise-rate sampling (excluding accel/decel ramps)
at multiple speeds, both axes, and diagonal.

- **Per-axis linear range:** speed ∈ [0, 1440]. Rate = speed / 237 °/s.
  Confirmed at speed=200, 500, 1000, 1440 — ratio is 237.8 ± 0.3.
- **Per-axis saturation:** speed > 1440 gives the same rate as 1440
  (~6.054 °/s). Firmware silently clamps, doesn't reject.
- **Both axes identical:** az and el both saturate at 1440 → 6.058°/s.
- **Diagonal decomposition:** `scope_speed_move(speed, angle, dur)`
  decomposes into per-axis components `speed × cos(angle)` and
  `speed × sin(angle)`, each clamped independently at 1440.
- **Diagonal max:** at angle=45°, speed=2036 (1440×√2) gives each
  axis full 6.05°/s. Total |v| = 8.56°/s.
- **Max useful speed for angle θ:** `1440 / max(|cos θ|, |sin θ|)`.

Implication for the planner: `PLAN_MAX_RATE_DEGS = 6.0` is the
per-axis cap. The 2D controller clamps per-axis (not magnitude), then
converts to firmware `(speed, angle)` via:
`speed = |v_vec| × 237, angle = atan2(v_el, v_az)`.
The firmware's internal per-axis clamp handles any overshoot.

### 4.1 Elevation limits probe

Run `sysid.py --mode limits --direction up` and `--direction down` at
speed=500. Stall detection + retry works the same as az. Expect limits
at roughly `[−90°, 0°]` or `[−90°, +10°]` encoder-frame (the mount
parks at horiz_coord[0] = −89.8°, which is near the physical down
stop; "up" is toward 0° in this frame).

Save to `plant_limits.json` as `el_min_deg`, `el_max_deg`. No cable-
wrap (el is < 180° range), so no cumulative tracking needed — simple
min/max clamp suffices.

### 4.2 Elevation sysid (optional)

If the el axis has a different tau due to gravity loading, a quick step-
response will reveal it. Expected: tau ≈ 0.35 s (same stepper/gearing
as az; gravity at low el angles is mostly axial to the stepper shaft).
Skip if initial el hardware runs converge well with az-derived tau.

### 4.3 Independent elevation controller

- New function `move_elevation_to_ff(cli, target_el_deg, cur_el_deg,
  ...)` in `device/velocity_controller.py`.
- Uses S-curve planner with `v_max`, `a_max`, `j_max` (same defaults
  as az initially). No wrap (`wrap_target=False` since el doesn't wrap).
- Firmware command: `scope_speed_move(speed, 90, dur)` for up,
  `scope_speed_move(speed, 270, dur)` for down.
- Position feedback from `scope_get_horiz_coord[0]`.
- `el_limits` (simple min/max, no cumulative) checked before planning.
- `tune_vc.py --mode setpoints_el` for setpoint sweeps on el.

### 4.4 Combined 2-axis controller

Once both axes are independently proven:
- `move_to_ff(cli, target_az, target_el, ...)` plans both axes
  simultaneously (either independent concurrent trajectories with a
  shared clock, or a single 2D diagonal trajectory).
- Each tick: read both horiz_coord[0] (el) and horiz_coord[1] (az),
  compute v_cmd_az and v_cmd_el, compose into firmware
  `(speed, angle)`.
- The 2D velocity composition:
  `speed = sqrt(v_az² + v_el²) * SPEED_PER_DEG_PER_SEC`
  `angle = atan2(v_el, v_az)` (firmware convention: 0=+az, 90=+el).
- Rate cap: `|v_vec| ≤ v_max` (not per-axis — so diagonal moves are
  faster than sequential single-axis by √2 only when both axes are
  near peak).

### 4.5 Streaming trajectory consumer (future)

For plane tracking or sidereal: an external source feeds `(t, az, el)`
references. The 2D controller tracks them with closed-loop feedback.
`unwind_azimuth` is called before each new tracking session if
cumulative az has drifted > 180° from cable center.

### Alternative approaches to consider

1. **Skip independent el controller; go straight to 2D.** Saves code
   duplication. Risk: debugging is harder if el doesn't respond as
   expected (can't isolate the axis). Recommendation: do 4.3 first for
   one quick hardware validation, then merge into 4.4.

2. **Rate-limit firmware commands during the closed-loop settle phase.**
   Currently the loop issues `speed_move` every tick (~0.5 s) even
   when vel is tiny during settle. If the firmware has a minimum
   commandable rate (stiction floor) we're already clipping below
   `VC_FINE_MIN_SPEED`. Could add a "coast to stop" phase that stops
   commanding entirely and just monitors position error.

3. **Integral term on position feedback.** Currently P-only. If there's
   a DC bias (e.g. mount tilt causing gravity-driven drift on el), a
   small `kI` would close it. Add anti-windup (clamp integral when at
   velocity cap). Only add if empirical el runs show a persistent
   nonzero residual.

### Open items from 2026-04-21 session

- [x] Commit all changes — `eb64a1d`, `ba8a679`, `68f21f1`, `868490d`, `2040be6`.
- [x] Elevation limits + `move_elevation_to_ff` (Phase 4.1–4.3) — `ba8a679`.
- [x] 2D combined controller (Phase 4.4) — `68f21f1`.
- [x] Diagonal speed fix — per-axis clamp — `868490d`.
- [x] Velocity controller page: PositionLogger→horiz_coord, event field
      fix (`e.event` not `e.name`), el trajectory overlay — `2040be6`.
- [x] Firmware speed calibration: per-axis clamp at 1440, ratio=237,
      diagonal at 2036 gives full 6°/s per axis.
- [ ] Full 6-setpoint sweep with cumulative limits (Run 15 step 2 hit
      network disconnect; needs retry).
- [ ] Velocity controller page: live position display when no
      PositionLogger is running (standalone read of horiz_coord).
- [ ] Investigate `scope_get_equ_coord` stale-data behavior — we
      bypass via `scope_get_horiz_coord`, but `issue_slew` / iscope
      gotos still use RA/Dec which may explain why gotos miss by
      30-100°.
- [ ] Cable-wrap cumulative-az state persisted across restarts of
      tune_vc (currently resets each run; fine for sweeps from home,
      risky for multi-session tracking).
- [ ] Streaming trajectory consumer for dynamic-target tracking
      (Phase 4.7).
