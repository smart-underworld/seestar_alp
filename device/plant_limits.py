"""Azimuth cable-wrap limits for the Seestar S50.

The mount has a finite-rotation cable wrap, NOT infinite azimuth travel.
Measured via `sysid.py --mode limits` (with dithered commands + retry on
stall): ~900° total travel between hard stops, roughly symmetric about
the power-on home position.

All values in this module are in the mount's **cumulative** encoder-frame
azimuth (unwrapped; starts at 0 at power-on). That lets us distinguish
"currently wound 200° CW past home" from "at home" even though both
wrap to the same [-180, +180°) range. Wrapped az is still useful for
display; cumulative is what the planner must respect.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


_LIMITS_JSON = os.path.join(os.path.dirname(__file__), "plant_limits.json")


@dataclass
class AzimuthLimits:
    """Cable-wrap bounds for the mount's azimuth.

    Convention:
    - `ccw_hard_stop_cum` is negative (cumulative az at the CCW hard stop).
    - `cw_hard_stop_cum` is positive (cumulative az at the CW hard stop).
    - Usable range is `[ccw_hard_stop_cum + padding_deg, cw_hard_stop_cum - padding_deg]`.
    - Startup (cumulative 0) is the power-on position, expected to be
      near the midpoint of the hard stops.
    """

    ccw_hard_stop_cum_deg: float
    cw_hard_stop_cum_deg: float
    padding_deg: float = 15.0
    # Wrapped azimuths at each stop — informational only, session-specific.
    ccw_hard_stop_wrapped_deg: float = 0.0
    cw_hard_stop_wrapped_deg: float = 0.0
    # Provenance.
    measurement_source: str = ""
    measurement_date: str = ""

    @property
    def usable_ccw_cum_deg(self) -> float:
        """Minimum (most-CCW) cumulative az the controller may command."""
        return self.ccw_hard_stop_cum_deg + self.padding_deg

    @property
    def usable_cw_cum_deg(self) -> float:
        """Maximum (most-CW) cumulative az the controller may command."""
        return self.cw_hard_stop_cum_deg - self.padding_deg

    @property
    def total_travel_deg(self) -> float:
        return self.cw_hard_stop_cum_deg - self.ccw_hard_stop_cum_deg

    def contains_cum(self, cum_az: float) -> bool:
        """True if `cum_az` is within the usable (padded) range."""
        return self.usable_ccw_cum_deg <= cum_az <= self.usable_cw_cum_deg

    def save(self, path: str = _LIMITS_JSON) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: str = _LIMITS_JSON) -> "AzimuthLimits | None":
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None


@dataclass
class CumulativeAzTracker:
    """Tracks cumulative (unwrapped) azimuth across a controller session.

    Feed wrapped encoder readings via `update`. The cumulative output
    integrates per-sample `wrap_pm180` deltas so it survives the ±180°
    boundary. At session start, `cum_az_deg = initial_wrapped_az` — i.e.
    cumulative is anchored to the first reading, which corresponds to the
    power-on home position when fed with `scope_get_horiz_coord` data.
    """

    cum_az_deg: float = 0.0
    _initialized: bool = field(default=False, init=False, repr=False)
    _prev_wrapped: float = field(default=0.0, init=False, repr=False)

    def update(self, wrapped_az_deg: float) -> float:
        """Integrate the next wrapped reading into cumulative az. Returns
        the updated `cum_az_deg`."""
        from device.velocity_controller import wrap_pm180  # avoid cycle at import

        if not self._initialized:
            self.cum_az_deg = float(wrapped_az_deg)
            self._prev_wrapped = float(wrapped_az_deg)
            self._initialized = True
            return self.cum_az_deg
        delta = wrap_pm180(wrapped_az_deg - self._prev_wrapped)
        self.cum_az_deg += delta
        self._prev_wrapped = float(wrapped_az_deg)
        return self.cum_az_deg

    def reset(self, cum_az_deg: float = 0.0, wrapped_az_deg: float = 0.0) -> None:
        self.cum_az_deg = float(cum_az_deg)
        self._prev_wrapped = float(wrapped_az_deg)
        self._initialized = True


def pick_cum_target(
    cum_cur_deg: float,
    wrapped_cur_deg: float,
    wrapped_target_deg: float,
    limits: "AzimuthLimits | None",
) -> float:
    """Pick the cumulative azimuth target for a move to the given wrapped
    target, choosing the short or long path so cumulative stays within
    the mount's usable (padded) cable range.

    Returns a cumulative azimuth such that `wrap_pm180(returned - cum_cur_deg)
    + cum_cur_deg` reaches the desired wrapped target.

    If `limits` is None, always returns the short path (equivalent to
    existing single-turn behavior). If both paths are valid, the short
    one is preferred. If neither is valid, a ValueError is raised — the
    target cannot be reached from the current cable-wrap state without
    physically unwinding first.
    """
    from device.velocity_controller import wrap_pm180  # avoid cycle

    short_delta = wrap_pm180(wrapped_target_deg - wrapped_cur_deg)
    short_cum = cum_cur_deg + short_delta
    if limits is None:
        return short_cum

    long_delta = short_delta - 360.0 if short_delta >= 0 else short_delta + 360.0
    long_cum = cum_cur_deg + long_delta

    short_ok = limits.contains_cum(short_cum)
    long_ok = limits.contains_cum(long_cum)

    if short_ok and long_ok:
        # Prefer short path.
        return short_cum if abs(short_delta) <= abs(long_delta) else long_cum
    if short_ok:
        return short_cum
    if long_ok:
        return long_cum
    raise ValueError(
        f"target wrapped={wrapped_target_deg:.3f}° unreachable from "
        f"cum_cur={cum_cur_deg:.3f}° within cable limits "
        f"[{limits.usable_ccw_cum_deg:.1f}, {limits.usable_cw_cum_deg:.1f}]. "
        "Call `unwind_azimuth` first to restore cable headroom."
    )
