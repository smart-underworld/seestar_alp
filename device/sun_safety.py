"""Sun-avoidance safety primitives.

Pure helpers + dataclass used by the `SunSafetyMonitor` (see follow-up
module) and by the pre-flight guards in `live_tracker`,
`rotation_calibration`, and `seestar_device`. Kept dependency-free
beyond `ephem` so tests can run without a mount or Alpaca.

Conventions:
- Az is measured east of north, in degrees, in the range [0, 360).
- Altitude (el) is measured from the horizon, in degrees, in [-90, 90].
- "Pointing" is the (az, el) of the optical axis; "sun" is the (az, alt)
  of the sun's center as seen from the observer at a given instant.

The sun-altitude threshold defaults to -10° (sun must be at least 10°
below the horizon to short-circuit the check). The exclusion cone
defaults to 30° angular separation between the optical axis and the
sun's center.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import ephem


# Defaults match `[sun_avoidance]` in `device/config.toml`. Re-read via
# `Config` at startup; these constants exist so the helpers stay usable
# from contexts without a populated Config (tests, scripts).
DEFAULT_MIN_SEPARATION_DEG = 30.0
DEFAULT_ALT_THRESHOLD_DEG = -10.0


@dataclass(frozen=True)
class SafetyTrip:
    """Snapshot of a sun-safety violation, displayed in the UI banner."""

    when_utc: datetime
    sun_az_deg: float
    sun_alt_deg: float
    mount_az_deg: float
    mount_el_deg: float
    separation_deg: float
    cone_deg: float
    jog_angle_deg: int
    jog_speed: int
    jog_duration_s: int
    message: str = "Sun safety triggered: mount jogged away from sun and tracking aborted."


@dataclass
class _Site:
    lat_deg: float
    lon_deg: float


def _site_from_config_or(lat_deg: Optional[float], lon_deg: Optional[float]) -> _Site:
    """Resolve site lat/lon, falling back to `Config` if not supplied.

    Imported lazily so this module is importable in environments where
    `device.config` cannot be loaded (e.g. minimal test contexts).
    """
    if lat_deg is not None and lon_deg is not None:
        return _Site(float(lat_deg), float(lon_deg))
    from device.config import Config
    return _Site(float(Config.init_lat), float(Config.init_long))


def angular_separation(a_az_deg: float, a_el_deg: float,
                       b_az_deg: float, b_el_deg: float) -> float:
    """Great-circle angular separation between two (az, el) directions.

    Returns degrees in [0, 180]. Pure function — no observer, no time.
    Az is treated as longitude, el as latitude on the celestial sphere.
    """
    a_az = math.radians(a_az_deg)
    a_el = math.radians(a_el_deg)
    b_az = math.radians(b_az_deg)
    b_el = math.radians(b_el_deg)
    # Spherical law of cosines, clamped for numerical safety.
    cos_sep = (
        math.sin(a_el) * math.sin(b_el)
        + math.cos(a_el) * math.cos(b_el) * math.cos(a_az - b_az)
    )
    cos_sep = max(-1.0, min(1.0, cos_sep))
    return math.degrees(math.acos(cos_sep))


def compute_sun_altaz(
    *,
    lat_deg: Optional[float] = None,
    lon_deg: Optional[float] = None,
    when: Optional[datetime] = None,
) -> tuple[float, float]:
    """Sun (az, alt) in degrees as seen from the given site at `when`.

    `when` defaults to UTC now. `lat_deg` / `lon_deg` default to the
    Config-configured observer site. Uses the `ephem` library, which
    is already a project dependency (see `front/app.py`).
    """
    site = _site_from_config_or(lat_deg, lon_deg)
    obs = ephem.Observer()
    obs.lat = str(site.lat_deg)
    obs.lon = str(site.lon_deg)
    if when is None:
        when = datetime.now(tz=timezone.utc)
    elif when.tzinfo is None:
        # Treat naive datetimes as UTC for predictability.
        when = when.replace(tzinfo=timezone.utc)
    # ephem expects naive UTC; strip tzinfo after converting.
    obs.date = when.astimezone(timezone.utc).replace(tzinfo=None)
    sun = ephem.Sun()
    sun.compute(obs)
    return math.degrees(float(sun.az)), math.degrees(float(sun.alt))


def is_sun_safe(
    target_az_deg: float,
    target_el_deg: float,
    *,
    lat_deg: Optional[float] = None,
    lon_deg: Optional[float] = None,
    when: Optional[datetime] = None,
    min_separation_deg: float = DEFAULT_MIN_SEPARATION_DEG,
    alt_threshold_deg: float = DEFAULT_ALT_THRESHOLD_DEG,
) -> tuple[bool, str]:
    """Return ``(safe, reason)`` for pointing the optical axis at ``(az, el)``.

    Always safe when the sun is below ``alt_threshold_deg`` (default
    -10°). Otherwise returns False if the angular separation between
    the pointing and the sun is below ``min_separation_deg``.

    The ``reason`` string is empty when safe and includes the numbers
    (separation, cone, sun alt) when unsafe so callers can log it.
    """
    sun_az, sun_alt = compute_sun_altaz(
        lat_deg=lat_deg, lon_deg=lon_deg, when=when,
    )
    if sun_alt < alt_threshold_deg:
        return True, ""
    sep = angular_separation(target_az_deg, target_el_deg, sun_az, sun_alt)
    if sep < min_separation_deg:
        return False, (
            f"sun_avoidance: separation {sep:.1f}° < cone {min_separation_deg:.1f}° "
            f"(sun alt {sun_alt:.1f}°, sun az {sun_az:.1f}°)"
        )
    return True, ""


__all__ = [
    "DEFAULT_ALT_THRESHOLD_DEG",
    "DEFAULT_MIN_SEPARATION_DEG",
    "SafetyTrip",
    "angular_separation",
    "compute_sun_altaz",
    "is_sun_safe",
]
