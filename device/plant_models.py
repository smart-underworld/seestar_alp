"""Candidate plant models for the Seestar velocity plant.

Each model exposes the same interface:

    fit(segments) -> None             # learn params from step-response data
    predict_rate(v_now, v_cmd, dt)    # one-step prediction given state + cmd
    simulate(v_cmds, dts, v0) -> rates    # unroll predictions
    params_dict() -> dict             # for logging

`segments` is a list of `Segment(ts, azs_unwrapped, cmd_speed_signed)`
where `cmd_speed_signed` is positive for angle=0 and negative for
angle=180. All models fit commanded *signed velocity* (deg/s) to
actual *signed velocity* (deg/s) from position derivatives.

SPEED_PER_DEG_PER_SEC (237) is the calibrated constant from prior
probes. Every fit works in deg/s; conversion to the firmware's speed
unit happens at the controller edge, not here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import minimize

from device.velocity_controller import SPEED_PER_DEG_PER_SEC, unwrap_az_series


def cmd_speed_to_degs(cmd_speed: int, angle: int) -> float:
    """Firmware (speed, angle) -> signed deg/s using linear calibration."""
    sign = 1.0 if angle == 0 else (-1.0 if angle == 180 else 0.0)
    return sign * cmd_speed / SPEED_PER_DEG_PER_SEC


@dataclass
class Segment:
    ts: np.ndarray            # shape (N,), host-monotonic relative seconds
                              # (matches cmd_times axis)
    azs_unwrapped: np.ndarray # shape (N,), cumulative position (deg)
    cmd_degs: np.ndarray      # shape (N,), commanded signed velocity deg/s
    motor_active: np.ndarray  # shape (N,), 1.0 while any commanded burst active
    speed: int                # firmware speed (informational)
    angle: int                # firmware angle (informational)
    fw_ts: Optional[np.ndarray] = None  # shape (N,), firmware uptime (s).
                                        # When present, use for dt between
                                        # consecutive samples (jitter-free).


def samples_to_segment(
    samples: list,
    speed: int, angle: int, cmd_times: list[tuple[float, int, int, int]],
) -> Segment:
    """Convert raw position samples into a Segment.

    Accepts both sample layouts:
      3-tuple (host_t, wrapped_az, motor_active)                  — legacy
      4-tuple (host_t, fw_t, wrapped_az, motor_active)            — with fw time

    `ts` is always host-monotonic seconds-from-burst-start (so it aligns
    with `cmd_times`, which is also in host time). When all samples have
    an `fw_t`, the Segment also carries `fw_ts` — an equal-length array
    of firmware uptime seconds used by downstream code (e.g.
    `segment_rates`) for jitter-free dt computation.

    cmd_times is list of (t_rel, speed, angle, dur).
    """
    if not samples:
        ts_list: list[float] = []
        azs_wrapped: list[float] = []
        mact: list[float] = []
        fw_ts_raw: list = []
    elif len(samples[0]) == 4:
        ts_list = [s[0] for s in samples]
        fw_ts_raw = [s[1] for s in samples]
        azs_wrapped = [s[2] for s in samples]
        mact = [s[3] for s in samples]
    else:
        ts_list = [s[0] for s in samples]
        fw_ts_raw = [None] * len(samples)
        azs_wrapped = [s[1] for s in samples]
        mact = [s[2] for s in samples]

    azs_unwrapped = unwrap_az_series(azs_wrapped)

    use_fw = bool(fw_ts_raw) and all(ft is not None for ft in fw_ts_raw)
    fw_ts_arr = (
        np.asarray([float(ft) for ft in fw_ts_raw], dtype=float)
        if use_fw else None
    )

    cmd_degs = np.zeros(len(samples))
    for i, t in enumerate(ts_list):
        # Which cmd (if any) is active at t?
        active_cmd = None
        for (t_c, s, a, d) in cmd_times:
            if t_c <= t <= t_c + d:
                active_cmd = (s, a)
        if active_cmd is not None:
            cmd_degs[i] = cmd_speed_to_degs(active_cmd[0], active_cmd[1])
        else:
            cmd_degs[i] = 0.0

    return Segment(
        ts=np.asarray(ts_list, dtype=float),
        azs_unwrapped=np.asarray(azs_unwrapped, dtype=float),
        cmd_degs=cmd_degs,
        motor_active=np.asarray(mact, dtype=float),
        speed=speed,
        angle=angle,
        fw_ts=fw_ts_arr,
    )


def segment_rates(seg: Segment) -> tuple[np.ndarray, np.ndarray]:
    """Per-sample instantaneous rate via backward difference.

    Returns (midpoint_ts, rates) with length N-1. When `seg.fw_ts` is
    present, uses firmware timestamps for dt (eliminates HTTP-latency
    jitter from the rate derivative); otherwise falls back to host ts.
    `mid_ts` stays on the host clock so it aligns with cmd_times for
    downstream use.
    """
    ts = seg.ts
    az = seg.azs_unwrapped
    dt_axis = seg.fw_ts if seg.fw_ts is not None else ts
    rates = np.diff(az) / np.diff(dt_axis)
    mid_ts = (ts[1:] + ts[:-1]) / 2.0
    return mid_ts, rates


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ZeroOrderModel:
    """v_actual = k_dc * v_cmd. No dynamics."""

    def __init__(self):
        self.k_dc: float = 1.0

    def fit(self, segments: list[Segment]) -> None:
        # Collect (cmd, measured_rate) samples from all segments.
        xs, ys = [], []
        for seg in segments:
            _, rates = segment_rates(seg)
            cmds_mid = (seg.cmd_degs[1:] + seg.cmd_degs[:-1]) / 2.0
            mask = np.abs(cmds_mid) > 0.1  # only fit where cmd is nonzero
            xs.extend(cmds_mid[mask])
            ys.extend(rates[mask])
        xs = np.asarray(xs)
        ys = np.asarray(ys)
        if len(xs) > 0:
            self.k_dc = float(np.sum(xs * ys) / np.sum(xs * xs))
        else:
            self.k_dc = 1.0

    def predict_rate(self, v_now: float, v_cmd: float, dt: float) -> float:
        return self.k_dc * v_cmd

    def simulate(self, v_cmds: np.ndarray, dts: np.ndarray, v0: float) -> np.ndarray:
        return self.k_dc * v_cmds

    def params_dict(self) -> dict:
        return {"kind": "zero_order", "k_dc": self.k_dc}


class FirstOrderLagModel:
    """tau * dv/dt = k_dc * v_cmd - v  (discretized).

    Single global tau, global dc-gain k_dc.
    """

    def __init__(self):
        self.tau: float = 0.8
        self.k_dc: float = 1.0

    def fit(self, segments: list[Segment]) -> None:
        # Fit on each burst's position trajectory.
        # Concatenate all (ts, az_pred, az_meas) residuals.
        def unroll_all(params):
            tau, k_dc = params
            tau = max(tau, 1e-3)
            total_sq = 0.0
            n = 0
            for seg in segments:
                v = 0.0
                pos_pred = [seg.azs_unwrapped[0]]
                for i in range(1, len(seg.ts)):
                    dt = seg.ts[i] - seg.ts[i - 1]
                    v_cmd = seg.cmd_degs[i - 1]
                    # exponential step
                    alpha = 1.0 - math.exp(-dt / tau)
                    v = v + alpha * (k_dc * v_cmd - v)
                    pos_pred.append(pos_pred[-1] + v * dt)
                p = np.asarray(pos_pred)
                m = seg.azs_unwrapped
                # ignore initial alignment; just compute RMSE of deltas from t0
                total_sq += float(np.sum((p - m) ** 2))
                n += len(seg.ts)
            return total_sq / max(n, 1)

        result = minimize(
            unroll_all, x0=[0.8, 1.0],
            bounds=[(0.05, 5.0), (0.5, 1.5)],
            method="L-BFGS-B",
        )
        self.tau, self.k_dc = float(result.x[0]), float(result.x[1])

    def predict_rate(self, v_now: float, v_cmd: float, dt: float) -> float:
        alpha = 1.0 - math.exp(-dt / max(self.tau, 1e-3))
        return v_now + alpha * (self.k_dc * v_cmd - v_now)

    def simulate(self, v_cmds: np.ndarray, dts: np.ndarray, v0: float) -> np.ndarray:
        tau = max(self.tau, 1e-3)
        v = v0
        out = []
        for v_cmd, dt in zip(v_cmds, dts):
            alpha = 1.0 - math.exp(-dt / tau)
            v = v + alpha * (self.k_dc * v_cmd - v)
            out.append(v)
        return np.asarray(out)

    def params_dict(self) -> dict:
        return {"kind": "first_order_lag", "tau_s": self.tau, "k_dc": self.k_dc}


class FirstOrderRateLimitedModel:
    """First-order toward cmd but |dv/dt| saturates at a_max.

    Equivalently: v_next = v + dt * sign(k_dc*v_cmd - v) * min(|error|/tau, a_max)
    """

    def __init__(self):
        self.tau: float = 0.3
        self.k_dc: float = 1.0
        self.a_max: float = 10.0

    def _step(self, v: float, v_cmd: float, dt: float,
              tau: float, k_dc: float, a_max: float) -> float:
        target = k_dc * v_cmd
        err = target - v
        if tau > 1e-3:
            unsat_step = err * (1.0 - math.exp(-dt / tau))
        else:
            unsat_step = err
        # rate-limit: |step| <= a_max * dt
        max_step = a_max * dt
        step = max(-max_step, min(max_step, unsat_step))
        return v + step

    def fit(self, segments: list[Segment]) -> None:
        def unroll_all(params):
            tau, k_dc, a_max = params
            tau = max(tau, 1e-3)
            total_sq = 0.0
            n = 0
            for seg in segments:
                v = 0.0
                pos_pred = [seg.azs_unwrapped[0]]
                for i in range(1, len(seg.ts)):
                    dt = seg.ts[i] - seg.ts[i - 1]
                    v_cmd = seg.cmd_degs[i - 1]
                    v = self._step(v, v_cmd, dt, tau, k_dc, a_max)
                    pos_pred.append(pos_pred[-1] + v * dt)
                p = np.asarray(pos_pred)
                m = seg.azs_unwrapped
                total_sq += float(np.sum((p - m) ** 2))
                n += len(seg.ts)
            return total_sq / max(n, 1)

        result = minimize(
            unroll_all, x0=[0.3, 1.0, 10.0],
            bounds=[(0.05, 5.0), (0.5, 1.5), (1.0, 50.0)],
            method="L-BFGS-B",
        )
        self.tau, self.k_dc, self.a_max = (
            float(result.x[0]), float(result.x[1]), float(result.x[2]),
        )

    def predict_rate(self, v_now: float, v_cmd: float, dt: float) -> float:
        return self._step(v_now, v_cmd, dt, self.tau, self.k_dc, self.a_max)

    def simulate(self, v_cmds: np.ndarray, dts: np.ndarray, v0: float) -> np.ndarray:
        v = v0
        out = []
        for v_cmd, dt in zip(v_cmds, dts):
            v = self._step(v, v_cmd, dt, self.tau, self.k_dc, self.a_max)
            out.append(v)
        return np.asarray(out)

    def params_dict(self) -> dict:
        return {
            "kind": "first_order_rate_limited",
            "tau_s": self.tau, "k_dc": self.k_dc, "a_max_degs2": self.a_max,
        }


class AsymmetricFirstOrderModel:
    """First-order with separate tau for accel (|v_cmd| > |v|) vs decel."""

    def __init__(self):
        self.tau_accel: float = 0.5
        self.tau_decel: float = 0.8
        self.k_dc: float = 1.0

    def _step(self, v, v_cmd, dt, tau_a, tau_d, k_dc):
        target = k_dc * v_cmd
        tau = tau_a if abs(target) > abs(v) else tau_d
        alpha = 1.0 - math.exp(-dt / max(tau, 1e-3))
        return v + alpha * (target - v)

    def fit(self, segments: list[Segment]) -> None:
        def unroll_all(params):
            ta, td, k = params
            total_sq = 0.0
            n = 0
            for seg in segments:
                v = 0.0
                pos_pred = [seg.azs_unwrapped[0]]
                for i in range(1, len(seg.ts)):
                    dt = seg.ts[i] - seg.ts[i - 1]
                    v_cmd = seg.cmd_degs[i - 1]
                    v = self._step(v, v_cmd, dt, ta, td, k)
                    pos_pred.append(pos_pred[-1] + v * dt)
                p = np.asarray(pos_pred)
                total_sq += float(np.sum((p - seg.azs_unwrapped) ** 2))
                n += len(seg.ts)
            return total_sq / max(n, 1)

        result = minimize(
            unroll_all, x0=[0.5, 0.8, 1.0],
            bounds=[(0.05, 5.0), (0.05, 5.0), (0.5, 1.5)],
            method="L-BFGS-B",
        )
        self.tau_accel, self.tau_decel, self.k_dc = (
            float(result.x[0]), float(result.x[1]), float(result.x[2]),
        )

    def predict_rate(self, v_now, v_cmd, dt):
        return self._step(v_now, v_cmd, dt, self.tau_accel, self.tau_decel, self.k_dc)

    def simulate(self, v_cmds, dts, v0):
        v = v0
        out = []
        for v_cmd, dt in zip(v_cmds, dts):
            v = self._step(v, v_cmd, dt, self.tau_accel, self.tau_decel, self.k_dc)
            out.append(v)
        return np.asarray(out)

    def params_dict(self) -> dict:
        return {
            "kind": "asymmetric_first_order",
            "tau_accel_s": self.tau_accel, "tau_decel_s": self.tau_decel,
            "k_dc": self.k_dc,
        }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def score_segments(model, segments: list[Segment]) -> dict:
    """Run model on each segment's cmd trace from rest; report position
    RMSE and rate RMSE across the aggregate."""
    pos_sq, pos_n = 0.0, 0
    rate_sq, rate_n = 0.0, 0
    for seg in segments:
        # Position predicted (integrating predicted rate)
        v = 0.0
        pos_pred = [seg.azs_unwrapped[0]]
        rate_pred = []
        for i in range(1, len(seg.ts)):
            dt = seg.ts[i] - seg.ts[i - 1]
            v_cmd = seg.cmd_degs[i - 1]
            v = model.predict_rate(v, v_cmd, dt)
            rate_pred.append(v)
            pos_pred.append(pos_pred[-1] + v * dt)
        p = np.asarray(pos_pred)
        pos_sq += float(np.sum((p - seg.azs_unwrapped) ** 2))
        pos_n += len(seg.ts)
        # rate comparison
        _, rates_meas = segment_rates(seg)
        rates_pred = np.asarray(rate_pred)
        k = min(len(rates_meas), len(rates_pred))
        if k > 0:
            rate_sq += float(np.sum((rates_pred[:k] - rates_meas[:k]) ** 2))
            rate_n += k
    return {
        "pos_rmse_deg": math.sqrt(pos_sq / max(pos_n, 1)),
        "rate_rmse_degs": math.sqrt(rate_sq / max(rate_n, 1)),
        "n_pos_samples": pos_n,
        "n_rate_samples": rate_n,
    }
