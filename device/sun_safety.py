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

import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import ephem


logger = logging.getLogger(__name__)


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


class SunSafetyLocked(RuntimeError):
    """Raised by the speed_move wrapper while the emergency jog is in progress.

    Tracking / calibration loops should catch this, log it, and exit
    cleanly — do NOT keep retrying. The monitor owns the mount while the
    lockout event is set.
    """


# Firmware speed→rate constant (mirrors device.velocity_controller).
# Duplicated here so the monitor module has no import-time dependency on
# the velocity controller (which pulls in astropy and other heavy deps).
_SPEED_PER_DEG_PER_SEC = 237.0


def _wrap_pm180(x: float) -> float:
    """Wrap x (degrees) to the range (-180, 180]."""
    return ((x + 180.0) % 360.0) - 180.0


def compute_jog_angle(
    mount_az_deg: float, mount_el_deg: float,
    sun_az_deg: float, sun_alt_deg: float,
    *,
    jog_speed: int = 1440,
    jog_duration_s: float = 3.0,
    require_gain_deg: float = 5.0,
) -> int:
    """Pick the `speed_move` angle that drives the mount AWAY from the sun.

    Angle convention (matches firmware + `streaming_controller.track`):
    - 0°   = pure +azimuth motion
    - 90°  = pure +elevation motion
    - 180° = pure -azimuth motion
    - 270° = pure -elevation motion

    Algorithm (small-angle approximation, valid inside the 30° cone):
    Take the direction-to-sun in local (daz, del) space and reverse it.
    Then forward-simulate the 3 s jog at firmware speed 1440 (~6°/s per
    axis) and require the predicted separation to exceed the current
    separation by at least ``require_gain_deg``. If the check fails
    (e.g. mount at zenith, sun right at mount), fall back to angle=90°
    (+el) which is safe whenever the sun is below zenith; if the mount
    itself sits high (el > 60°) we fall back to angle=270° (−el) to
    avoid crossing zenith.

    Returns an integer angle in [0, 360).
    """
    daz_diff = _wrap_pm180(sun_az_deg - mount_az_deg)
    del_diff = sun_alt_deg - mount_el_deg
    norm = math.hypot(daz_diff, del_diff)

    sep_now = angular_separation(mount_az_deg, mount_el_deg, sun_az_deg, sun_alt_deg)
    rate = jog_speed / _SPEED_PER_DEG_PER_SEC  # deg/s
    step = rate * jog_duration_s  # total motion in degrees

    def _verify(angle_deg: int) -> bool:
        """Forward-sim this angle; True if separation improves enough."""
        rad = math.radians(angle_deg)
        new_az = (mount_az_deg + step * math.cos(rad)) % 360.0
        new_el = max(-90.0, min(90.0, mount_el_deg + step * math.sin(rad)))
        new_sep = angular_separation(new_az, new_el, sun_az_deg, sun_alt_deg)
        return new_sep >= sep_now + require_gain_deg

    # Primary: reverse of direction-to-sun in (daz, del).
    if norm > 1e-6:
        candidate = int(round(
            (math.degrees(math.atan2(-del_diff, -daz_diff)) + 360.0) % 360.0
        ))
        if _verify(candidate):
            return candidate

    # Fallback 1: pure +el (up) — safe unless sun is at zenith above mount.
    if _verify(90):
        return 90
    # Fallback 2: pure -el (down) — mount is high enough that going up would
    # overshoot zenith and re-approach sun on the other side.
    if _verify(270):
        return 270
    # Fallback 3: pure +az or -az — choose whichever increases separation more.
    new_sep_plus_az = angular_separation(
        (mount_az_deg + step) % 360.0, mount_el_deg, sun_az_deg, sun_alt_deg,
    )
    new_sep_minus_az = angular_separation(
        (mount_az_deg - step) % 360.0, mount_el_deg, sun_az_deg, sun_alt_deg,
    )
    return 0 if new_sep_plus_az >= new_sep_minus_az else 180


# ---------- SunSafetyMonitor ---------------------------------------------


# Signature of a "raw mount altaz reader". Returns sky (az_deg, alt_deg) or
# None if the reading is unavailable / untrustworthy this tick (e.g. mount
# disconnected, not plate-solved). Factoring this out keeps the monitor
# independent of AlpacaClient/astropy at import time and testable with a
# fake.
AltazReader = Callable[[], Optional[tuple[float, float]]]

# Signature of a "raw jog commander". Receives (speed, angle, dur_sec)
# and commands the firmware to execute one `scope_speed_move` burst.
# Intentionally bypasses any lockout-aware wrapper — the monitor is the
# one source authorized to move during the emergency window.
RawJogCommand = Callable[[int, int, int], None]


class SunSafetyMonitor:
    """Always-on daemon that trips when the mount points inside the sun cone.

    Started once per process (see `device/live_tracker_service.py`). Two
    cadences: while the sun is below `alt_threshold_deg` it polls slowly
    (default 60 s); when the sun rises above the threshold it polls at
    the active cadence (default 2 s) and compares the mount's sky
    pointing against the sun.

    On a violation it:
      1. Sets the emergency lockout event (blocks the wrapped speed_move).
      2. Calls `abort_active()` to stop in-flight tracking/calibration.
      3. Runs one jog at `jog_speed` / `jog_duration_s` in the direction
         picked by `compute_jog_angle`.
      4. Sleeps for jog_duration_s + margin, then clears the lockout
         so the user can drive the mount again.
      5. Leaves `last_trip` populated until the UI POSTs dismiss.
    """

    def __init__(
        self,
        *,
        altaz_reader: AltazReader,
        jog_command: RawJogCommand,
        abort_active: Optional[Callable[[], None]] = None,
        lat_deg: Optional[float] = None,
        lon_deg: Optional[float] = None,
        min_separation_deg: float = DEFAULT_MIN_SEPARATION_DEG,
        alt_threshold_deg: float = DEFAULT_ALT_THRESHOLD_DEG,
        jog_speed: int = 1440,
        jog_duration_s: int = 3,
        tick_interval_active_s: float = 2.0,
        tick_interval_dormant_s: float = 60.0,
        enabled: bool = True,
    ) -> None:
        self._altaz_reader = altaz_reader
        self._jog_command = jog_command
        self._abort_active = abort_active
        self._lat_deg = lat_deg
        self._lon_deg = lon_deg

        self._min_separation_deg = float(min_separation_deg)
        self._alt_threshold_deg = float(alt_threshold_deg)
        self._jog_speed = int(jog_speed)
        self._jog_duration_s = int(jog_duration_s)
        self._tick_active = float(tick_interval_active_s)
        self._tick_dormant = float(tick_interval_dormant_s)
        self._enabled = bool(enabled)

        self._stop_evt = threading.Event()
        self._emergency_lockout = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_trip: Optional[SafetyTrip] = None
        self._trip_dismissed: bool = False
        self._lock = threading.Lock()

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, name="SunSafetyMonitor", daemon=True,
        )
        self._thread.start()
        logger.info(
            "SunSafetyMonitor started: cone=%.1f° alt_thr=%.1f° "
            "jog=speed=%d dur=%ds",
            self._min_separation_deg, self._alt_threshold_deg,
            self._jog_speed, self._jog_duration_s,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def reload(
        self,
        *,
        min_separation_deg: Optional[float] = None,
        alt_threshold_deg: Optional[float] = None,
        jog_speed: Optional[int] = None,
        jog_duration_s: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        """Update thresholds in place without stopping the monitor thread."""
        with self._lock:
            if min_separation_deg is not None:
                self._min_separation_deg = float(min_separation_deg)
            if alt_threshold_deg is not None:
                self._alt_threshold_deg = float(alt_threshold_deg)
            if jog_speed is not None:
                self._jog_speed = int(jog_speed)
            if jog_duration_s is not None:
                self._jog_duration_s = int(jog_duration_s)
            if enabled is not None:
                self._enabled = bool(enabled)

    # ---------- public state ----------

    def is_locked_out(self) -> bool:
        return self._emergency_lockout.is_set()

    def last_trip(self) -> Optional[SafetyTrip]:
        with self._lock:
            if self._trip_dismissed:
                return None
            return self._last_trip

    def dismiss_last_trip(self) -> None:
        with self._lock:
            self._trip_dismissed = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def min_separation_deg(self) -> float:
        return self._min_separation_deg

    # ---------- loop ----------

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("SunSafetyMonitor tick raised")
            # Sleep interval depends on whether sun is above the
            # activation threshold at the end of the tick. Cheap to
            # recompute.
            try:
                _, sun_alt = compute_sun_altaz(
                    lat_deg=self._lat_deg, lon_deg=self._lon_deg,
                )
                wait = (
                    self._tick_active
                    if sun_alt >= self._alt_threshold_deg
                    else self._tick_dormant
                )
            except Exception:
                wait = self._tick_active
            self._stop_evt.wait(timeout=wait)

    def _tick(self) -> None:
        if not self._enabled or self._emergency_lockout.is_set():
            return
        sun_az, sun_alt = compute_sun_altaz(
            lat_deg=self._lat_deg, lon_deg=self._lon_deg,
        )
        if sun_alt < self._alt_threshold_deg:
            return
        try:
            altaz = self._altaz_reader()
        except Exception:
            logger.warning("altaz_reader failed this tick", exc_info=True)
            return
        if altaz is None:
            return
        mount_az, mount_el = altaz
        sep = angular_separation(mount_az, mount_el, sun_az, sun_alt)
        if sep >= self._min_separation_deg:
            return
        self._trigger_emergency(mount_az, mount_el, sun_az, sun_alt, sep)

    def _trigger_emergency(
        self,
        mount_az: float, mount_el: float,
        sun_az: float, sun_alt: float, sep: float,
    ) -> None:
        jog_angle = compute_jog_angle(
            mount_az, mount_el, sun_az, sun_alt,
            jog_speed=self._jog_speed,
            jog_duration_s=float(self._jog_duration_s),
        )
        trip = SafetyTrip(
            when_utc=datetime.now(timezone.utc),
            sun_az_deg=sun_az, sun_alt_deg=sun_alt,
            mount_az_deg=mount_az, mount_el_deg=mount_el,
            separation_deg=sep, cone_deg=self._min_separation_deg,
            jog_angle_deg=jog_angle,
            jog_speed=self._jog_speed,
            jog_duration_s=self._jog_duration_s,
        )
        logger.error(
            "SUN SAFETY TRIP: sep=%.1f° < cone=%.1f° "
            "(mount az=%.1f° el=%.1f°, sun az=%.1f° alt=%.1f°) — "
            "jogging at speed=%d angle=%d° for %ds",
            sep, self._min_separation_deg,
            mount_az, mount_el, sun_az, sun_alt,
            self._jog_speed, jog_angle, self._jog_duration_s,
        )
        with self._lock:
            self._last_trip = trip
            self._trip_dismissed = False

        # 1. Lock out lockout-aware speed_move calls from tracker/calibration.
        self._emergency_lockout.set()
        try:
            # 2. Ask any active session to stop. Runs whatever caller provided.
            if self._abort_active is not None:
                try:
                    self._abort_active()
                except Exception:
                    logger.exception("abort_active callback failed")
            # 3. Issue the jog (raw path — bypasses the wrapper).
            try:
                self._jog_command(
                    self._jog_speed, jog_angle, self._jog_duration_s,
                )
            except Exception:
                logger.exception("jog_command raised — NOT retrying")
            # 4. Wait for the jog to complete, plus a small margin so any
            #    caller that races back in can see us already done.
            time.sleep(self._jog_duration_s + 0.5)
        finally:
            # 5. Release the lockout so the user can drive the mount.
            self._emergency_lockout.clear()
        logger.info("SUN SAFETY jog complete — user has control")


_MONITOR: Optional[SunSafetyMonitor] = None
_MONITOR_LOCK = threading.Lock()


def get_sun_monitor() -> Optional[SunSafetyMonitor]:
    """Return the process-singleton monitor, or None if not set up yet.

    The live_tracker_service wires this up at process startup. Callers
    that hit this path before startup (or in tests) get None and should
    treat "no monitor" as "no lockout active".
    """
    with _MONITOR_LOCK:
        return _MONITOR


def set_sun_monitor(monitor: Optional[SunSafetyMonitor]) -> None:
    """Install (or clear) the process-singleton monitor."""
    global _MONITOR
    with _MONITOR_LOCK:
        _MONITOR = monitor


def sun_safety_is_locked_out() -> bool:
    """Cheap convenience for the speed_move wrapper.

    Returns False when no monitor is installed (test mode, CLI tools,
    etc.). Never raises.
    """
    m = get_sun_monitor()
    return bool(m is not None and m.is_locked_out())


__all__ = [
    "DEFAULT_ALT_THRESHOLD_DEG",
    "DEFAULT_MIN_SEPARATION_DEG",
    "AltazReader",
    "RawJogCommand",
    "SafetyTrip",
    "SunSafetyLocked",
    "SunSafetyMonitor",
    "angular_separation",
    "compute_jog_angle",
    "compute_sun_altaz",
    "get_sun_monitor",
    "is_sun_safe",
    "set_sun_monitor",
    "sun_safety_is_locked_out",
]
