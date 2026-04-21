"""Unit tests for device.trajectory — trapezoidal + S-curve velocity profiles.

Numerical tolerances:
- 1e-6 on endpoint position/velocity
- 1e-3 on constraint violation (accounts for tick-sample granularity)
"""


from device.trajectory import (
    scurve_profile,
    trapezoidal_profile,
)


V_MAX = 6.0       # °/s (firmware clamp)
A_MAX = 10.0      # °/s² (Phase 1 rate-limit bound unused; within envelope)
J_MAX = 40.0      # °/s³ (default from research plan)
TICK = 0.05       # fine tick so samples bracket phase boundaries tightly


def _max_abs(xs):
    return max(abs(x) for x in xs) if xs else 0.0


def test_trapezoid_reaches_target():
    traj = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=60.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    end = traj.points[-1]
    assert abs(end.pos - 60.0) < 1e-6, f"end pos = {end.pos}"
    assert abs(end.vel) < 1e-6, f"end vel = {end.vel}"
    assert traj.total_duration > 0


def test_trapezoid_respects_v_max():
    traj = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=60.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    assert _max_abs([p.vel for p in traj.points]) <= V_MAX + 1e-3


def test_trapezoid_respects_a_max():
    traj = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=60.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    assert _max_abs([p.acc for p in traj.points]) <= A_MAX + 1e-3


def test_triangular_profile_short_move():
    # 2° at v_max=6 a_max=10: time-to-v_max from rest = 0.6s covers
    # d=1.8°. So 2° is too short for full trapezoid; should be
    # triangular (accel + decel with no cruise).
    traj = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=2.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    peak_v = _max_abs([p.vel for p in traj.points])
    assert peak_v < V_MAX - 0.01, f"peak_v {peak_v} shouldn't reach v_max {V_MAX}"
    end = traj.points[-1]
    assert abs(end.pos - 2.0) < 1e-6
    assert abs(end.vel) < 1e-6


def test_zero_delta_returns_single_point():
    traj = trapezoidal_profile(
        p0=45.0, v0=0.0, p_target=45.005,  # < 0.01° threshold
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    assert traj.total_duration == 0.0
    assert len(traj.points) == 1


def test_v0_handoff_to_target_forward():
    # Already moving at 3°/s toward target 30° from 0°; planner should
    # continue forward, not re-accelerate from rest.
    traj = trapezoidal_profile(
        p0=0.0, v0=3.0, p_target=30.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    assert abs(traj.points[0].vel - 3.0) < 1e-9  # starting vel preserved
    end = traj.points[-1]
    assert abs(end.pos - 30.0) < 1e-6, f"end pos = {end.pos}"
    assert abs(end.vel) < 1e-6
    # Max vel should reach cruise (v_max) since 30° is plenty for that
    assert _max_abs([p.vel for p in traj.points]) <= V_MAX + 1e-3


def test_wrap_around_path_short_way():
    # From +170 to -170 — short path is +20° across the wrap boundary,
    # long path is -340°. Planner should pick short.
    traj = trapezoidal_profile(
        p0=170.0, v0=0.0, p_target=-170.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    # The planner's end.pos is the raw integrated position; it may exceed
    # ±180 since trapezoidal_profile doesn't wrap its own output.
    # But the TIME should correspond to 20° of motion (a few seconds),
    # not 340° (much longer).
    # For 20° with triangular trapezoid v_max=6 a_max=10:
    # v_peak = sqrt(10 * 20) = 14.14°/s  → clamped to v_max=6
    # So it's actually trapezoidal. t_accel = 0.6, t_decel = 0.6,
    # d_accel + d_decel = 3.6°, d_cruise = 16.4°, t_cruise = 2.73s
    # Total ~3.9s. Long path would be ~60s.
    assert traj.total_duration < 6.0, (
        f"total_duration={traj.total_duration} suggests long path "
        "was chosen"
    )
    # End position is p0 + signed short delta = 170 + 20 = 190
    # (exceeds +180; caller wraps when comparing).
    end = traj.points[-1]
    # Confirm it's a "forward-through-wrap" path: end > start numerically.
    assert end.pos > 170.0, f"end pos {end.pos} should be > p0 for short wrap path"


def test_sample_interpolates():
    traj = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=30.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=0.1,
    )
    # Midpoint of trajectory should have pos somewhere between 0 and 30
    t_mid = traj.total_duration / 2.0
    mid = traj.sample(t_mid)
    assert 0 < mid.pos < 30.0


def test_scurve_continuous_accel():
    # A long move so the full 7-segment profile is used.
    traj = scurve_profile(
        p0=0.0, v0=0.0, p_target=60.0,
        v_max=V_MAX, a_max=A_MAX, j_max=J_MAX, tick_dt=TICK,
    )
    assert traj.total_duration > 0
    end = traj.points[-1]
    assert abs(end.pos - 60.0) < 1e-3
    assert abs(end.vel) < 1e-3
    # Consecutive-point |Δacc| ≤ j_max * (t_i+1 - t_i) + generous slop.
    # The 1.01 multiplier allows for numerical rounding at segment
    # boundaries.
    max_jerk_violation = 0.0
    for a, b in zip(traj.points[:-1], traj.points[1:]):
        dt = b.t - a.t
        if dt > 0:
            jerk = abs(b.acc - a.acc) / dt
            max_jerk_violation = max(max_jerk_violation, jerk - J_MAX)
    # Allow 10% headroom (segment-boundary sampling can show apparent
    # jerk exceeding cap by the fraction of the tick spent at each
    # segment's cap value).
    assert max_jerk_violation < J_MAX * 0.1, (
        f"observed jerk exceeds cap by {max_jerk_violation:.1f} > "
        f"{J_MAX * 0.1:.1f} (10%)"
    )
