"""
Planning page data: twilight times, nearest Clear Dark Sky chart, location.
"""

import json
import math
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from device.config import Config  # type: ignore

router = APIRouter(prefix="/api/v1")

# Path to the classic front's CSC sites database (shared asset)
_CSC_SITES_FILE = Path(__file__).parent.parent.parent / "front" / "csc_sites.json"
_csc_cache: dict | None = None


def _load_csc_sites() -> dict:
    global _csc_cache
    if _csc_cache is None and _CSC_SITES_FILE.exists():
        with open(_CSC_SITES_FILE) as f:
            _csc_cache = json.load(f)
    return _csc_cache or {}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_csc(lat: float, lon: float) -> dict:
    data = _load_csc_sites()
    if not data:
        return {}
    nearby = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            lat_k = str(int(lat) + dx)
            lon_k = str(int(lon) + dy)
            if lat_k in data and lon_k in data[lat_k]:
                nearby.extend(data[lat_k][lon_k])
    if not nearby:
        return {}
    best, best_km = None, 1e9
    for site in nearby:
        km = _haversine_km(lat, lon, site["lat"], site["lng"])
        if km < best_km:
            best_km = km
            best = site
    if best and best_km < 1000:
        site_id = best["id"]
        return {
            "name": best.get("name", site_id),
            "dist_km": round(best_km, 1),
            "href": f"https://www.cleardarksky.com/c/{site_id}key.html",
            "img": f"https://www.cleardarksky.com/c/{site_id}csk.gif",
        }
    return {}


def _twilight_times(lat: float, lon: float) -> dict:
    try:
        import ephem  # type: ignore
        import pytz
        import tzlocal

        obs = ephem.Observer()
        obs.date = datetime.utcnow()
        obs.lat = str(lat)
        obs.lon = str(lon)
        sun = ephem.Sun()
        tz = tzlocal.get_localzone()

        def _next_set(horizon="0"):
            obs.horizon = horizon
            try:
                return (
                    pytz.utc.localize(
                        obs.next_setting(sun, use_center=(horizon != "0")).datetime()
                    )
                    .astimezone(tz)
                    .strftime("%H:%M %Z")
                )
            except Exception:
                return "N/A"

        def _next_rise(horizon="0"):
            obs.horizon = horizon
            try:
                return (
                    pytz.utc.localize(
                        obs.next_rising(sun, use_center=(horizon != "0")).datetime()
                    )
                    .astimezone(tz)
                    .strftime("%H:%M %Z")
                )
            except Exception:
                return "N/A"

        obs.horizon = "0"
        return {
            "Sunset": _next_set("0"),
            "Sunrise": _next_rise("0"),
            "Civil End": _next_set("-6"),
            "Civil Begin": _next_rise("-6"),
            "Astronomical Begin": _next_set("-18"),
            "Astronomical End": _next_rise("-18"),
        }
    except ImportError:
        return {}
    except Exception:
        return {}


@router.get("/planning")
def get_planning_data():
    lat = float(getattr(Config, "init_lat", 0.0) or 0.0)
    lon = float(getattr(Config, "init_long", 0.0) or 0.0)

    try:
        import datetime as _dt

        local_offset_h = int(
            (
                _dt.datetime.now(_dt.timezone.utc).astimezone().utcoffset()
                or _dt.timedelta(0)
            ).total_seconds()
            / 3600
        )
    except Exception:
        local_offset_h = 0

    return {
        "lat": lat,
        "lon": lon,
        "utc_offset": local_offset_h,
        "twilight": _twilight_times(lat, lon),
        "clear_dark_sky": _nearest_csc(lat, lon),
    }
