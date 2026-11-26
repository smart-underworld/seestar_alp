"""Local horizon profile: the altitude of the obstructions around the site.

The profile comes from a N.I.N.A. horizon file (``.hrz``): one
``azimuth altitude`` pair per line, in degrees, azimuth measured from north
through east. N.I.N.A. reads this format, and several tools produce it from a
panorama of the site. Between two points the horizon is interpolated
linearly, wrapping at 360 degrees.

The planner draws the profile in AstroMosaic's day chart, and the scheduler
can skip a target hidden behind it (``horizon_skip_hidden_targets``). The
Horizon page makes one from a 360-degree panorama, in the browser.
"""

import bisect
import datetime
import json
import logging
import math
import os
import threading
from collections.abc import Callable
from zoneinfo import ZoneInfo

from astropy import units as u
from astropy.coordinates import (
    FK5,
    GeocentricTrueEcliptic,
    SkyCoord,
    get_body,
    get_sun,
)
from astropy.time import Time

from device.config import Config, stage_file, write_file_atomic
from device.seestar_util import Util


# The app's master logger (see device/log.py).
logger = logging.getLogger()


class HorizonError(ValueError):
    """Raised when a horizon file cannot be read."""


class HorizonSaveError(Exception):
    """Raised when a valid profile cannot be written; the former one stays in use."""


class SiteLocationUnknown(LookupError):
    """Raised when the site latitude and longitude are not set (both 0)."""


class InvalidTarget(ValueError):
    """Raised when the coordinates of a target to check are missing or invalid."""


class HorizonProfile:
    """Horizon altitude by azimuth, from a list of (azimuth, altitude) points."""

    def __init__(self, points):
        by_azimuth = {}
        for azimuth, altitude in points:
            azimuth = float(azimuth) % 360.0
            # Two points at the same azimuth: keep the higher, the safer one.
            by_azimuth[azimuth] = max(float(altitude), by_azimuth.get(azimuth, -90.0))
        if not by_azimuth:
            raise HorizonError("the horizon profile has no point")
        self.points = sorted(by_azimuth.items())
        self._azimuths = [azimuth for azimuth, _ in self.points]

    @classmethod
    def parse_hrz(cls, text, source="horizon file"):
        """Profile from the text of a ``.hrz`` file.

        Blank lines and ``#`` comments are ignored. The two values may be
        separated by spaces, tabs or a semicolon, and then a comma is a
        decimal comma (``12,5 30``); a comma alone also separates them
        (``12.5,30``). Azimuths are taken modulo 360, so an export from -180
        to 180 degrees reads as well.
        """
        points = []
        for number, line in enumerate(text.splitlines(), start=1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                azimuth, altitude = _hrz_values(line)
            except ValueError:
                raise HorizonError(
                    f"{source}, line {number}: expected 'azimuth altitude', got {line!r}"
                ) from None
            if not (math.isfinite(azimuth) and -90.0 <= altitude <= 90.0):
                raise HorizonError(
                    f"{source}, line {number}: altitude must be within -90-90 "
                    f"degrees, got {line!r}"
                )
            points.append((azimuth % 360.0, altitude))
        if not points:
            raise HorizonError(f"{source}: no 'azimuth altitude' line")
        return cls(points)

    def altitude_at(self, azimuth):
        """Horizon altitude at ``azimuth``, in degrees."""
        if len(self.points) == 1:
            return self.points[0][1]
        azimuth = float(azimuth) % 360.0
        i = bisect.bisect_right(self._azimuths, azimuth)
        if 0 < i < len(self.points):
            (a0, h0), (a1, h1) = self.points[i - 1], self.points[i]
        else:
            # Between the last point and the first one, across north.
            (a0, h0), (a1, h1) = self.points[-1], self.points[0]
            a1 += 360.0
            if azimuth < a0:
                azimuth += 360.0
        return h0 + (h1 - h0) * (azimuth - a0) / (a1 - a0)

    def step_limits(self, step=5.0):
        """Highest horizon altitude in each step of ``step`` degrees.

        Value ``k`` covers azimuths ``k * step +/- step / 2``, the layout of
        AstroMosaic's ``horizonHard``. The profile being piecewise linear, its
        highest point in a step is at a bound or at one of its points.
        """
        limits = []
        for k in range(round(360.0 / step)):
            low, high = k * step - step / 2, k * step + step / 2
            heights = [self.altitude_at(low), self.altitude_at(high)]
            heights += [
                altitude
                for azimuth, altitude in self.points
                if _in_arc(azimuth, low, high)
            ]
            limits.append(round(max(heights), 2))
        return limits


def _hrz_values(line):
    """``(azimuth, altitude)`` of a ``.hrz`` line; ValueError when unreadable."""
    fields = line.replace(";", " ").split()
    if len(fields) == 1 and fields[0].count(",") == 1:
        # "12.5,30": the comma is the separator.
        fields = fields[0].split(",")
    else:
        # "12,5 30" or "12,5;30": the comma is a decimal comma. "12, 30"
        # reads as well, its "12," being 12.
        fields = [field.replace(",", ".") for field in fields]
    if len(fields) != 2:
        raise ValueError(line)
    return float(fields[0]), float(fields[1])


def _in_arc(azimuth, low, high):
    """Whether ``azimuth`` lies between ``low`` and ``high``, across north if need be."""
    return (azimuth - low) % 360.0 <= high - low


_lock = threading.Lock()
_cache = {"key": None, "profile": None, "error": None}


def configured_profile():
    """``(profile, error)`` for the configured ``horizon_file``.

    ``(None, None)`` when no file is configured. The file is parsed again
    only when its path, inode, modification time or size changes, so the
    planner and the scheduler can call this freely: it costs one ``stat``.
    The inode catches a file replaced within one tick of a coarse clock (an
    atomic save gives it a new one); ``forget_cached_profile`` covers the
    rest. An unusable file is logged once, when it is read, not on every call.
    """
    path = (Config.horizon_file or "").strip()
    if not path:
        return None, None
    try:
        stat = os.stat(path)
    except OSError as e:
        error = f"{path}: {e.strerror}"
        _log_once(("missing", path, e.errno), error)
        return None, error
    key = (path, stat.st_ino, stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _cache["key"] != key:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    profile, error = HorizonProfile.parse_hrz(f.read(), path), None
            except (OSError, UnicodeDecodeError, HorizonError) as e:
                profile, error = None, str(e)
                logger.warning(f"Horizon file not used, flat horizon instead: {error}")
            _cache.update(key=key, profile=profile, error=error)
        return _cache["profile"], _cache["error"]


def forget_cached_profile():
    """Make the next ``configured_profile`` call read the file again."""
    with _lock:
        _cache.update(key=None, profile=None, error=None)


_logged = set()


def _log_once(key, message):
    with _lock:
        if key in _logged:
            return
        _logged.add(key)
    logger.warning(f"Horizon file not used, flat horizon instead: {message}")


def site_location():
    """``(latitude, longitude)`` from ``[seestar_initialization]``.

    ``None`` while both are 0, the value that stands for an unknown site.
    """
    if Config.init_lat == 0 and Config.init_long == 0:
        return None
    return float(Config.init_lat), float(Config.init_long)


def altaz(coord: SkyCoord, latitude, longitude, when: Time):
    """Altitude and azimuth of ``coord`` at ``when``, in degrees.

    Hour angle from the mean sidereal time, on coordinates of the date: good
    to a few hundredths of a degree, more than a horizon check needs. It
    avoids astropy's AltAz frame, which needs Earth orientation (IERS) tables
    less than 30 days old and raises on an install that cannot download them.
    Refraction is left out: it lifts a low target by half a degree at most,
    so the check errs on the hidden side.
    """
    of_date = coord.transform_to(FK5(equinox=when))
    days = when.utc.jd - 2451545.0
    sidereal = (280.46061837 + 360.98564736629 * days + longitude) % 360.0
    hour_angle = math.radians(sidereal - of_date.ra.deg)
    dec, lat = of_date.dec.radian, math.radians(latitude)
    altitude = math.asin(
        math.sin(dec) * math.sin(lat)
        + math.cos(dec) * math.cos(lat) * math.cos(hour_angle)
    )
    azimuth = math.atan2(
        -math.cos(dec) * math.sin(hour_angle),
        math.sin(dec) * math.cos(lat)
        - math.cos(dec) * math.sin(lat) * math.cos(hour_angle),
    )
    return math.degrees(altitude), math.degrees(azimuth) % 360.0


def _direction(body: SkyCoord) -> SkyCoord:
    """The body's geocentric direction on the sky, at infinity.

    astropy returns the Sun and Moon as finite-distance GCRS positions;
    transforming those to the barycentric FK5 frame would shift them by the
    Earth's orbital offset (some 19 degrees for the Sun). Dropping the
    distance keeps the direction as seen from the Earth.
    """
    return SkyCoord(ra=body.ra, dec=body.dec, frame="icrs")


def sun_alt_az(when: Time, latitude, longitude):
    """Altitude and azimuth of the Sun at ``when``, in degrees (no IERS tables)."""
    return altaz(_direction(get_sun(when)), latitude, longitude, when)


def moon_alt_az(when: Time, latitude, longitude):
    """Altitude and azimuth of the Moon at ``when``, in degrees (no IERS tables).

    Geocentric position: the Moon's parallax (up to about a degree) is left
    out, fine for deciding when it is up or down.
    """
    return altaz(_direction(get_body("moon", when)), latitude, longitude, when)


def moon_illumination(when: Time) -> float:
    """Illuminated fraction of the Moon's disc at ``when``, from 0 to 1."""
    elongation = get_sun(when).separation(get_body("moon", when)).radian
    return (1.0 - math.cos(elongation)) / 2.0


def moon_is_waxing(when: Time) -> bool:
    """Whether the Moon leads the Sun in ecliptic longitude (new to full)."""
    sun = get_sun(when).transform_to(GeocentricTrueEcliptic(equinox=when))
    moon = get_body("moon", when).transform_to(GeocentricTrueEcliptic(equinox=when))
    return bool((moon.lon.deg - sun.lon.deg) % 360.0 < 180.0)


def moon_phase_name(illumination: float, waxing: bool) -> str:
    """Human name of the phase for an illuminated fraction and direction."""
    if illumination < 0.03:
        return "new moon"
    if illumination > 0.97:
        return "full moon"
    if 0.45 <= illumination <= 0.55:
        return "first quarter" if waxing else "last quarter"
    if illumination < 0.5:
        return "waxing crescent" if waxing else "waning crescent"
    return "waxing gibbous" if waxing else "waning gibbous"


def visibility(coord: SkyCoord, profile, margin=0.0, when=None):
    """Altitude and azimuth of ``coord`` now, against the horizon.

    Without a profile the horizon is flat, at 0 degrees. ``visible`` is true
    when the target is above the horizon plus ``margin``. Returns ``None``
    while the site location is unknown.
    """
    location = site_location()
    if location is None:
        return None
    when = Time.now() if when is None else when
    altitude, azimuth = altaz(coord, *location, when)
    horizon = profile.altitude_at(azimuth) if profile is not None else 0.0
    return {
        "altitude": round(altitude, 2),
        "azimuth": round(azimuth, 2),
        "horizon": round(horizon, 2),
        "margin": margin,
        "visible": altitude > horizon + margin,
    }


# Bracket width, in minutes, at which a crossing found by bisection is reported.
_CROSSING_RESOLUTION_MIN = 1.0


def find_crossings(
    alt_az_fn: Callable[[Time], tuple[float, float]],
    threshold_fn: Callable[[float], float],
    start: Time,
    span_hours: float = 24.0,
    step_min: float = 4.0,
) -> list[tuple[Time, str]]:
    """Times in the window when a target crosses a threshold altitude.

    ``alt_az_fn(when)`` gives ``(altitude, azimuth)`` in degrees;
    ``threshold_fn(azimuth)`` gives the altitude to cross at that azimuth (a
    flat horizon is ``lambda az: 0.0``). The window ``[start, start + span]``
    is sampled every ``step_min`` minutes; each sign change of
    ``altitude - threshold`` is then narrowed by bisection to a minute.
    Returns ``(time, "up" | "down")`` in time order, ``"up"`` when the target
    rises above the threshold. A target that stays on one side gives ``[]``.

    The default 4 minute step is short enough that a target grazing the
    horizon, above it for under an hour, is still bracketed; a window shorter
    than one step is only sampled at its ends.
    """

    def margin(when):
        altitude, azimuth = alt_az_fn(when)
        return altitude - threshold_fn(azimuth)

    step = max(float(step_min), 1e-3)
    count = max(int(math.ceil(span_hours * 60.0 / step)), 1)
    offsets = [min(k * step, span_hours * 60.0) for k in range(count + 1)]
    times = [start + m * u.min for m in offsets]
    margins = [margin(t) for t in times]
    crossings = []
    for i in range(count):
        before, after = margins[i], margins[i + 1]
        if (before > 0) == (after > 0):
            continue
        low, high = offsets[i], offsets[i + 1]
        rising = after > 0
        while high - low > _CROSSING_RESOLUTION_MIN:
            middle = (low + high) / 2.0
            if (margin(start + middle * u.min) > 0) == rising:
                high = middle
            else:
                low = middle
        crossings.append(
            (start + (low + high) / 2.0 * u.min, "up" if rising else "down")
        )
    return crossings


def transit(
    alt_az_fn: Callable[[Time], tuple[float, float]],
    start: Time,
    span_hours: float = 24.0,
    step_min: float = 4.0,
) -> tuple[Time, float]:
    """Time and altitude of the highest point of a target in the window.

    The highest of the samples taken every ``step_min`` minutes, refined to
    about a second between its two neighbours (the altitude curve is smooth
    and has one peak there).
    """
    step = max(float(step_min), 1e-3)
    total = span_hours * 60.0
    count = max(int(math.ceil(total / step)), 1)
    offsets = [min(k * step, total) for k in range(count + 1)]
    altitudes = [alt_az_fn(start + m * u.min)[0] for m in offsets]
    best = max(range(len(offsets)), key=altitudes.__getitem__)
    low = offsets[max(best - 1, 0)]
    high = offsets[min(best + 1, count)]
    while high - low > 1.0 / 60.0:
        a = low + (high - low) / 3.0
        b = high - (high - low) / 3.0
        if alt_az_fn(start + a * u.min)[0] < alt_az_fn(start + b * u.min)[0]:
            low = a
        else:
            high = b
    when = start + (low + high) / 2.0 * u.min
    altitude = alt_az_fn(when)[0]
    if altitude < altitudes[best]:  # the peak is at a window edge
        return start + offsets[best] * u.min, altitudes[best]
    return when, altitude


def describe():
    """The ``get_horizon`` action: settings and profile, as plain data."""
    profile, error = configured_profile()
    return {
        "file": Config.horizon_file,
        "error": error,
        "points": [list(point) for point in profile.points] if profile else [],
        "limits_5deg": profile.step_limits() if profile else None,
        "skip_hidden_targets": Config.horizon_skip_hidden_targets,
        "margin": Config.horizon_margin,
    }


def check_target(params):
    """The ``check_target_visibility`` action.

    ``params``: ``ra`` and ``dec`` (decimal hours and degrees, or
    sexagesimal strings) and ``is_j2000`` (default true). Answers for now,
    against the configured profile plus ``horizon_margin``.

    Raises InvalidTarget when ``ra`` or ``dec`` is missing or unreadable,
    and SiteLocationUnknown while the site location is not set.
    """
    params = params or {}
    missing = [name for name in ("ra", "dec") if params.get(name) in (None, "")]
    if missing:
        raise InvalidTarget(f"missing parameter(s): {', '.join(missing)}")
    try:
        coord = Util.parse_coordinate(
            params.get("is_j2000", True), params["ra"], params["dec"]
        )
    except Exception as e:  # astropy raises several kinds on a bad angle
        raise InvalidTarget(
            f"unreadable coordinates ra={params['ra']!r}, dec={params['dec']!r}: {e}"
        ) from None
    profile, error = configured_profile()
    result = visibility(coord, profile, Config.horizon_margin)
    if result is None:
        raise SiteLocationUnknown("site location not set: latitude and longitude are 0")
    result["horizon_error"] = error
    return result


def local_times(when: Time) -> dict:
    """``when`` as site-local ``{"local": "HH:MM", "iso": <local ISO>}``.

    Uses ``[seestar_initialization] timezone`` (an IANA name); the host's
    local zone when that is empty. ``iso`` carries the date, so the day is
    unambiguous across midnight.
    """
    moment = when.utc.to_datetime(timezone=datetime.timezone.utc)
    name = (Config.init_timezone or "").strip()
    if name:
        moment = moment.astimezone(ZoneInfo(name))
    else:
        moment = moment.astimezone()
    return {"local": moment.strftime("%H:%M"), "iso": moment.isoformat()}


def target_window(params, now: Time | None = None) -> dict:
    """The ``target_visibility_window`` action.

    ``params``: ``ra``, ``dec``, ``is_j2000`` (default true) and
    ``min_altitude`` (degrees, default 0). Looks 24 hours ahead of ``now``
    for when the target is above the higher of the configured horizon
    profile (flat 0 when none) and ``min_altitude``.

    ``state`` is ``rises_and_sets``, ``up_now``, ``circumpolar`` or
    ``never_up``. Raises InvalidTarget and SiteLocationUnknown like
    ``check_target``.
    """
    params = params or {}
    missing = [name for name in ("ra", "dec") if params.get(name) in (None, "")]
    if missing:
        raise InvalidTarget(f"missing parameter(s): {', '.join(missing)}")
    try:
        coord = Util.parse_coordinate(
            params.get("is_j2000", True), params["ra"], params["dec"]
        )
        min_altitude = float(params.get("min_altitude", 0.0) or 0.0)
    except Exception as e:  # astropy raises several kinds on a bad angle
        raise InvalidTarget(
            f"unreadable parameters ra={params['ra']!r}, dec={params['dec']!r}: {e}"
        ) from None
    site = site_location()
    if site is None:
        raise SiteLocationUnknown("site location not set: latitude and longitude are 0")
    lat, lon = site
    now = Time.now() if now is None else now
    profile, _error = configured_profile()

    def alt_az_fn(when):
        return altaz(coord, lat, lon, when)

    def threshold_fn(azimuth):
        floor = profile.altitude_at(azimuth) if profile is not None else 0.0
        return max(floor, min_altitude)

    altitude, azimuth = alt_az_fn(now)
    above = altitude > threshold_fn(azimuth)
    crossings = find_crossings(alt_az_fn, threshold_fn, now, span_hours=24, step_min=4)
    peak_time, peak_altitude = transit(alt_az_fn, now, span_hours=24, step_min=4)

    def stamp(when):
        return local_times(when) if when is not None else None

    rises = sets = next_rises = None
    if not crossings:
        state = "circumpolar" if above else "never_up"
    elif above:
        state = "up_now"
        sets = crossings[0][0]
        next_rises = next((t for t, tag in crossings[1:] if tag == "up"), None)
    else:
        state = "rises_and_sets"
        up_index = next(i for i, (_, tag) in enumerate(crossings) if tag == "up")
        rises = crossings[up_index][0]
        sets = next((t for t, tag in crossings[up_index + 1 :] if tag == "down"), None)

    result = {
        "state": state,
        "rises": stamp(rises),
        "sets": stamp(sets),
        "transit": stamp(peak_time),
        "max_altitude": round(peak_altitude, 1),
        "min_altitude_floor": min_altitude,
        "uses_horizon_profile": profile is not None,
    }
    if state == "up_now":
        result["next_rises"] = stamp(next_rises)
    return result


# Profile made from a panorama on the Horizon page, saved next to config.toml.
PANORAMA_HRZ = "horizon.hrz"
PANORAMA_JSON = "horizon.horizon.json"

# One save at a time. The front's WSGI server is threaded: two overlapping
# POST /horizon would otherwise interleave their replaces and roll-backs.
_save_lock = threading.Lock()


def save_panorama_profile(hrz_text, horizon_json=None):
    """Save a profile made from a panorama, and make it the configured horizon.

    ``hrz_text`` is the ``.hrz`` the page exported; ``horizon_json``, when
    given, the MMhorizon ``.horizon.json`` it came from, kept beside it as a
    record of the photo and of how north was set. Both go next to
    config.toml, and ``horizon_file`` then points to the ``.hrz``; a file
    configured before is left in place. A save without ``horizon_json``
    removes the record an earlier save left, which described another photo.
    The planner and the scheduler use the new profile from their next call.
    Returns ``(path, previous_file, profile)``.

    Saves run one at a time. Both files are written in full, to temporary
    files of their own, before anything is replaced; config.toml is saved
    next, then the record takes its place, and the profile last. Any error on
    the way (folder not writable by the service, disk full, a config.toml
    without its ``[seestar_initialization]`` table) removes the temporary
    files, puts back the former record and ``horizon_file``, and raises
    ``HorizonSaveError``: the former profile stays in use. Removing the record
    of an earlier photo comes once the new profile is in place: when it
    fails, the save stands and a warning is logged.

    Raises ``HorizonError`` on an invalid profile, before anything is written.
    """
    profile = HorizonProfile.parse_hrz(hrz_text, "uploaded profile")
    if horizon_json is not None:
        try:
            record = json.loads(horizon_json)
        except ValueError as e:
            raise HorizonError(f"uploaded .horizon.json: {e}") from None
        if not isinstance(record, dict) or record.get("format") != "horizon":
            raise HorizonError("uploaded .horizon.json: not an MMhorizon file")
    with _save_lock:
        path, previous = _save_panorama_files(hrz_text, horizon_json)
    return path, previous, profile


def _save_panorama_files(hrz_text, horizon_json):
    """The file side of ``save_panorama_profile``, under ``_save_lock``."""
    folder = os.path.dirname(Config.path_to_dat)
    path = os.path.join(folder, PANORAMA_HRZ)
    record_path = os.path.join(folder, PANORAMA_JSON)
    previous = Config.horizon_file
    config_changes = previous != path
    config_set = config_saved = record_replaced = False
    former_record = None
    staged = []
    try:
        hrz_tmp = stage_file(path, hrz_text, "utf-8")
        staged.append(hrz_tmp)
        if horizon_json is not None:
            record_tmp = stage_file(record_path, horizon_json, "utf-8")
            staged.append(record_tmp)
            former_record = _read_if_present(record_path)
        if config_changes:
            Config.set_toml("seestar_initialization", "horizon_file", path)
            config_set = True
            Config.save_toml()
            config_saved = True
        if horizon_json is not None:
            os.replace(record_tmp, record_path)
            record_replaced = True
        # The profile last: until this replace succeeds the former one is in
        # use, and everything done above is undone below.
        os.replace(hrz_tmp, path)
    except Exception as e:
        for tmp in staged:
            _remove_quietly(tmp)
        if record_replaced:
            _put_back_record(record_path, former_record)
        if config_set:
            _put_back_horizon_file(previous, config_saved)
        if isinstance(e, OSError):
            detail = str(e)
        else:
            logger.exception("Unexpected error while saving the horizon profile")
            detail = f"{type(e).__name__}: {e}"
        raise HorizonSaveError(f"horizon profile not saved: {detail}") from e
    finally:
        forget_cached_profile()
    if horizon_json is None:
        _remove_stale_record(record_path)
    if config_changes:
        Config.load_toml()
    return path, previous


def _read_if_present(path):
    """The bytes of ``path``, or None when there is no such file."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _put_back_record(record_path, former):
    """The record as it was before the save: ``former`` bytes, or no file."""
    try:
        if former is None:
            os.remove(record_path)
        else:
            write_file_atomic(record_path, former)
    except OSError as e:
        logger.warning(f"Could not put the former {record_path} back: {e}")


def _remove_stale_record(record_path):
    """Remove the record of an earlier photo, once the new profile is in use.

    A failure leaves the save in place: the profile is the new one, and only
    the record, kept for reference, still describes the former photo.
    """
    try:
        os.remove(record_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(
            f"Horizon profile saved, but {record_path} could not be removed "
            f"and still describes the former photo: {e}"
        )


def _remove_quietly(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"Could not remove {path}: {e}")


def _put_back_horizon_file(previous, saved):
    """``horizon_file`` as it was in memory, and in config.toml if ``saved``."""
    Config.set_toml("seestar_initialization", "horizon_file", previous)
    if not saved:
        return
    try:
        Config.save_toml()
        Config.load_toml()
    except Exception as e:
        logger.warning(f"Could not put horizon_file back to {previous!r}: {e}")
