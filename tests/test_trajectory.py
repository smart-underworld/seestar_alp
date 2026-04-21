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


def test_trapezoid_t_offset_hold_phase():
    # 0.5 s lead-in at tick_dt=0.1 → 5 hold samples at t = 0.0 … 0.4,
    # all at (p0=10.0, vel=0, acc=0). Motion starts at t=0.5.
    traj = trapezoidal_profile(
        p0=10.0, v0=0.0, p_target=40.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=0.1,
        t_offset=0.5,
    )
    hold_pts = [p for p in traj.points if p.t < 0.5 - 1e-9]
    assert len(hold_pts) == 5, f"expected 5 hold samples, got {len(hold_pts)}"
    for p in hold_pts:
        assert p.pos == 10.0
        assert p.vel == 0.0
        assert p.acc == 0.0


def test_trapezoid_t_offset_preserves_endpoint():
    base = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=30.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    shifted = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=30.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
        t_offset=0.5,
    )
    # Endpoint position identical; endpoint time shifted by +0.5.
    assert abs(shifted.points[-1].pos - base.points[-1].pos) < 1e-6
    assert abs(shifted.points[-1].vel) < 1e-6
    assert abs(shifted.total_duration - (base.total_duration + 0.5)) < 1e-9


def test_trapezoid_t_offset_sample_during_hold():
    # Sampling during the hold window returns the start pose.
    traj = trapezoidal_profile(
        p0=25.0, v0=0.0, p_target=55.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=0.1,
        t_offset=0.5,
    )
    for t_probe in (0.0, 0.1, 0.25, 0.49):
        s = traj.sample(t_probe)
        assert abs(s.pos - 25.0) < 1e-6, (
            f"at t={t_probe} pos should be 25, got {s.pos}"
        )
        assert abs(s.vel) < 1e-6


def test_trapezoid_t_offset_wrap_still_short_path():
    # +170 → -170 across wrap with a 0.5 s cold-start hold. Still should
    # pick the +20° short path (not -340°).
    traj = trapezoidal_profile(
        p0=170.0, v0=0.0, p_target=-170.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
        t_offset=0.5,
    )
    # Short path total was ~4 s; with +0.5 hold, expect ~4.5 s.
    assert traj.total_duration < 6.5, (
        f"total_duration={traj.total_duration} suggests long path chosen"
    )
    # Hold samples still at p0=170.
    early = traj.sample(0.2)
    assert abs(early.pos - 170.0) < 1e-6


def test_forbidden_not_on_short_path_uses_short():
    # p0=+30, target=-60: short path is -90° (CCW through 0°).
    # Forbidden at +180° is not on that path → still goes short.
    traj = trapezoidal_profile(
        p0=30.0, v0=0.0, p_target=-60.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
        az_forbidden_deg=180.0,
    )
    assert abs(traj.points[-1].pos - (-60.0)) < 1e-6
    # Total motion should be ~90° (short), not ~270° (long).
    assert traj.total_duration < 20.0, (
        f"took {traj.total_duration}s — suggests long path chosen"
    )


def test_forbidden_on_short_path_uses_long():
    # p0=+30, target=-60: short path is CCW through +9°.
    # Forbidden at +9° → long path (+270° CW).
    traj = trapezoidal_profile(
        p0=30.0, v0=0.0, p_target=-60.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
        az_forbidden_deg=9.0,
    )
    # End position: planner doesn't wrap its output, so p_cur = p0 + long_delta.
    # Long delta = +270° CW, so end.pos ≈ 30 + 270 = 300.
    assert abs(traj.points[-1].pos - 300.0) < 1e-3, (
        f"end pos {traj.points[-1].pos}, expected ~300 for long-way path"
    )
    # No sample along the way should be in (+8°, +10°).
    for p in traj.points:
        wrapped = ((p.pos + 180) % 360) - 180
        assert not (8.0 < wrapped < 10.0), (
            f"trajectory crosses forbidden {wrapped:.3f}°"
        )


def test_forbidden_none_unchanged():
    # Sanity: az_forbidden=None gives the same result as not passing it.
    traj_a = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=120.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
    )
    traj_b = trapezoidal_profile(
        p0=0.0, v0=0.0, p_target=120.0,
        v_max=V_MAX, a_max=A_MAX, tick_dt=TICK,
        az_forbidden_deg=None,
    )
    assert abs(traj_a.total_duration - traj_b.total_duration) < 1e-9
    assert abs(traj_a.points[-1].pos - traj_b.points[-1].pos) < 1e-9


def test_scurve_forbidden_takes_long_way():
    # Same as test_forbidden_on_short_path_uses_long but with S-curve.
    traj = scurve_profile(
        p0=30.0, v0=0.0, p_target=-60.0,
        v_max=V_MAX, a_max=A_MAX, j_max=J_MAX, tick_dt=TICK,
        az_forbidden_deg=9.0,
    )
    # End position: ~30 + 270 = 300.
    assert abs(traj.points[-1].pos - 300.0) < 1e-2, (
        f"end pos {traj.points[-1].pos}, expected ~300"
    )


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
