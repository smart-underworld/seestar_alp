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

import datetime
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields


_LIMITS_JSON = os.path.join(os.path.dirname(__file__), "plant_limits.json")
_STATE_JSON = os.path.join(os.path.dirname(__file__), "plant_limits_state.json")


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
            # Tolerate extra keys in the JSON (e.g. elevation-limits fields
            # that are stored alongside but aren't part of this dataclass).
            # Without this, `cls(**data)` raises TypeError on unknown kwargs
            # and the whole file is silently treated as missing.
            known = {f.name for f in fields(cls)}
            filtered = {k: v for k, v in data.items() if k in known}
            return cls(**filtered)
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

    def to_dict(self) -> dict:
        """Serialize tracker state for disk persistence."""
        return {
            "cum_az_deg": self.cum_az_deg,
            "wrapped_az_deg": self._prev_wrapped,
            "initialized": self._initialized,
            "saved_at_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def save(self, path: str = _STATE_JSON) -> None:
        """Write cum-az state to disk so the next session can pick it up."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_or_fresh(
        cls,
        current_wrapped_az_deg: float,
        path: str = _STATE_JSON,
        tol_deg: float = 2.0,
    ) -> "CumulativeAzTracker":
        """Load tracker state from disk, or start fresh on mismatch.

        Returns a tracker. If `path` is missing, corrupt, or the saved
        `wrapped_az_deg` differs from `current_wrapped_az_deg` by more than
        `tol_deg` (indicating a power-cycle / home reset), a fresh
        uninitialized tracker is returned (it will anchor to the next
        `update()` reading). On success the tracker's `_prev_wrapped` is
        re-anchored to the current reading, absorbing sub-tolerance drift
        into `cum_az_deg`.
        """
        tracker = cls()
        if not os.path.isfile(path):
            return tracker
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_cum = float(data["cum_az_deg"])
            saved_wrapped = float(data["wrapped_az_deg"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            sys.stderr.write(
                f"CumulativeAzTracker: failed to load {path}: {exc}; "
                "starting fresh.\n"
            )
            return tracker
        # Import here to avoid a cycle on module import.
        from device.velocity_controller import wrap_pm180

        drift = wrap_pm180(current_wrapped_az_deg - saved_wrapped)
        if abs(drift) > tol_deg:
            sys.stderr.write(
                f"CumulativeAzTracker: saved wrapped_az={saved_wrapped:+.3f}° "
                f"vs current={current_wrapped_az_deg:+.3f}° differ by "
                f"{drift:+.3f}° (> tol={tol_deg}°). Assuming power-cycle/home "
                "reset; starting cum_az at 0 from current position.\n"
            )
            return tracker
        tracker.reset(
            cum_az_deg=saved_cum + drift,
            wrapped_az_deg=current_wrapped_az_deg,
        )
        return tracker


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
