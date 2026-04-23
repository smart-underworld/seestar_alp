"""Streaming reference provider — feeds (az, el, v, a) to the controller.

The Phase 5 StreamingFFController treats the reference as a callable: it
asks for a sample at (t_now + latency) every tick and drives the plant
toward it. This module defines the protocol and a concrete provider backed
by pre-recorded ECEF JSONL (the same schema produced by
scripts/trajectory/fetch_{aircraft,satellites}.py).

Later providers will live-feed predictions from skyfield or from an
ADS-B stream, but all must expose the same minimal interface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from scipy.interpolate import CubicSpline

from device.target_frame import MountFrame


# Match the absolute-time extrapolation budget in the research plan §5.2.2.
DEFAULT_EXTRAPOLATION_S = 1.0


@dataclass(frozen=True)
class ReferenceSample:
    """What the controller wants from the provider at each tick.

    `az_cum_deg` is a cumulative (unwrapped) azimuth — callers that need
    cable-wrap checks compare this directly to AzimuthLimits.contains_cum.
    """

    t_unix: float
    az_cum_deg: float
    el_deg: float
    v_az_degs: float
    v_el_degs: float
    a_az_degs2: float
    a_el_degs2: float
    stale: bool = False
    extrapolated: bool = False


@runtime_checkable
class ReferenceProvider(Protocol):
    """Duck-typed interface. Anything that exposes `sample` and `valid_range` works."""

    def sample(self, t_unix: float) -> ReferenceSample:
        """Return a sample at the requested time.

        Implementations should:
        - Interpolate within the buffered range.
        - Extrapolate up to a small horizon past the tail using the last v, a
          (mark `extrapolated=True`).
        - Return a sample with `stale=True` if the requested time is past the
          tail + extrapolation budget. The controller uses the stale flag as
          an exit condition after N consecutive stale samples.
        - Before the head time, raise or clamp — policy per provider.
        """
        ...

    def valid_range(self) -> tuple[float, float]:
        """Return (t_start_unix, t_end_unix) covered by the provider."""
        ...


class JsonlECEFProvider:
    """Provider backed by a pre-recorded ECEF JSONL file.

    Behavior:
    - Load the JSONL once at construction (or accept pre-parsed arrays).
    - Convert ECEF samples to mount-frame arrays (az_cum, el, v, a) using
      the supplied MountFrame.
    - Build cubic splines on az_cum and el; derive v and a by differentiating
      the same splines (guarantees consistency between position and
      rate at query time).
    - Extrapolate up to `extrapolation_s` past the tail with the last
      spline-derived v, a. Beyond that → stale.

    Queries before the head time raise `ValueError` — the caller must wait
    for the start of the track. We don't extrapolate backwards; the
    controller has a dedicated "waiting for AOS" state that keeps the mount
    static before the first tick.
    """

    def __init__(
        self,
        path: str | Path,
        mount_frame: MountFrame,
        extrapolation_s: float = DEFAULT_EXTRAPOLATION_S,
    ) -> None:
        self.path = Path(path)
        self.mount_frame = mount_frame
        self.extrapolation_s = float(extrapolation_s)
        header, t, ecef = _load_jsonl(self.path)
        self._init_from_arrays(header, t, ecef)

    @classmethod
    def from_samples(
        cls,
        header: dict,
        t_unix: np.ndarray,
        ecef_xyz: np.ndarray,
        mount_frame: MountFrame,
        extrapolation_s: float = DEFAULT_EXTRAPOLATION_S,
    ) -> "JsonlECEFProvider":
        """Build a provider without touching disk — for in-process callers
        like the offline replay harness."""
        obj = cls.__new__(cls)
        obj.path = Path("<in-memory>")
        obj.mount_frame = mount_frame
        obj.extrapolation_s = float(extrapolation_s)
        obj._init_from_arrays(header, np.asarray(t_unix, dtype=float),
                              np.asarray(ecef_xyz, dtype=float))
        return obj

    # ---------- internal: build splines from arrays ----------

    def _init_from_arrays(
        self, header: dict, t: np.ndarray, ecef: np.ndarray,
    ) -> None:
        if len(t) < 4:
            raise ValueError(
                f"{self.path}: need ≥4 samples for cubic spline, got {len(t)}"
            )
        self.header = header
        traj = self.mount_frame.ecef_traj_to_mount(ecef, t)
        self._t = t
        self._az_cum = traj["az_cum_deg"]
        self._el = traj["el_deg"]
        # Splines for position. Velocity + acceleration come from spline
        # derivatives so pos/vel/acc at any query time are mathematically
        # consistent (the smoothed-finite-diff arrays in `traj` are only
        # used at sample times; anything between samples uses the spline
        # derivative, which handles the slight irregular-dt case cleanly).
        self._spline_az = CubicSpline(t, self._az_cum, extrapolate=False)
        self._spline_el = CubicSpline(t, self._el, extrapolate=False)
        # For extrapolation past the tail: cache last spline derivatives.
        self._tail_v_az = float(self._spline_az(t[-1], 1))
        self._tail_v_el = float(self._spline_el(t[-1], 1))
        self._tail_a_az = float(self._spline_az(t[-1], 2))
        self._tail_a_el = float(self._spline_el(t[-1], 2))

    # ---------- API ----------

    def valid_range(self) -> tuple[float, float]:
        return float(self._t[0]), float(self._t[-1])

    def sample(self, t_unix: float) -> ReferenceSample:
        t0, t1 = float(self._t[0]), float(self._t[-1])
        t_query = float(t_unix)

        if t_query < t0:
            raise ValueError(
                f"query t={t_query:.3f} is before buffer head {t0:.3f}"
            )

        if t_query <= t1:
            # Interpolate in-buffer.
            az = float(self._spline_az(t_query))
            el = float(self._spline_el(t_query))
            v_az = float(self._spline_az(t_query, 1))
            v_el = float(self._spline_el(t_query, 1))
            a_az = float(self._spline_az(t_query, 2))
            a_el = float(self._spline_el(t_query, 2))
            return ReferenceSample(
                t_unix=t_query, az_cum_deg=az, el_deg=el,
                v_az_degs=v_az, v_el_degs=v_el,
                a_az_degs2=a_az, a_el_degs2=a_el,
                stale=False, extrapolated=False,
            )

        # Past the tail. Extrapolate linearly with tail v, a up to the horizon.
        dt = t_query - t1
        stale = dt > self.extrapolation_s
        # Keep extrapolating even past the horizon — but mark stale so the
        # controller can make a clean exit. The position keeps moving at
        # the tail's last rate so if the controller ignores `stale` briefly
        # the mount doesn't snap.
        az_tail = float(self._spline_az(t1))
        el_tail = float(self._spline_el(t1))
        az = az_tail + self._tail_v_az * dt + 0.5 * self._tail_a_az * dt * dt
        el = el_tail + self._tail_v_el * dt + 0.5 * self._tail_a_el * dt * dt
        v_az = self._tail_v_az + self._tail_a_az * dt
        v_el = self._tail_v_el + self._tail_a_el * dt
        return ReferenceSample(
            t_unix=t_query, az_cum_deg=az, el_deg=el,
            v_az_degs=v_az, v_el_degs=v_el,
            a_az_degs2=self._tail_a_az, a_el_degs2=self._tail_a_el,
            stale=stale, extrapolated=True,
        )

    # ---------- convenience for pre-check ----------

    def iter_ticks(
        self, tick_dt: float, start_t: float | None = None,
    ) -> list[ReferenceSample]:
        """Sample the provider at a uniform tick grid over its valid range.

        Used by StreamingFFController's cable-wrap pre-check to walk the
        whole planned trajectory before commanding anything.
        """
        t0, t1 = self.valid_range()
        s = t0 if start_t is None else max(t0, float(start_t))
        n = int(np.floor((t1 - s) / tick_dt)) + 1
        return [self.sample(s + i * tick_dt) for i in range(n)]


def _load_jsonl(path: Path) -> tuple[dict, np.ndarray, np.ndarray]:
    """Parse an ECEF JSONL file → (header, t_array, ecef_array(N,3))."""
    header: dict | None = None
    ecef_rows: list[tuple[float, float, float]] = []
    t_rows: list[float] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("kind") == "header":
                header = rec
            elif rec.get("kind") == "sample":
                ecef_rows.append((
                    float(rec["ecef_x"]),
                    float(rec["ecef_y"]),
                    float(rec["ecef_z"]),
                ))
                t_rows.append(float(rec["t_unix"]))
    if header is None:
        raise ValueError(f"{path}: no header record")
    return (
        header,
        np.asarray(t_rows, dtype=float),
        np.asarray(ecef_rows, dtype=float),
    )
