"""Observer-site constants and coordinate utilities.

The velocity_controller stack operates in the mount's topocentric az/el.
Trajectory sources (ADS-B, TLEs) give us ECEF or lat/lon/alt. This module
is the single place that converts between the two, referenced to a fixed
observing site.

Default site: 33°57'38.1"N, 118°27'36.5"W, ~30 m elevation (El Segundo, CA).
Override via env vars OBSERVER_LAT_DEG / OBSERVER_LON_DEG / OBSERVER_ALT_M.

All ECEF values are WGS84 / ITRS — earth-fixed. Converting ECEF to
topocentric is time-independent because the ENU rotation only depends on
the observer's geodetic lat/lon.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from astropy import units as u
from astropy.coordinates import EarthLocation


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


OBSERVER_LAT_DEG = _env_float("OBSERVER_LAT_DEG", 33.960583)
OBSERVER_LON_DEG = _env_float("OBSERVER_LON_DEG", -118.460139)
OBSERVER_ALT_M = _env_float("OBSERVER_ALT_M", 30.0)


@dataclass(frozen=True)
class ObserverSite:
    lat_deg: float
    lon_deg: float
    alt_m: float
    ecef_x: float
    ecef_y: float
    ecef_z: float
    enu_rotation: np.ndarray  # shape (3, 3): rows are E, N, U in ECEF

    @property
    def ecef_xyz(self) -> np.ndarray:
        return np.array([self.ecef_x, self.ecef_y, self.ecef_z])


def _enu_rotation(lat_deg: float, lon_deg: float) -> np.ndarray:
    phi = np.radians(lat_deg)
    lam = np.radians(lon_deg)
    sp, cp = np.sin(phi), np.cos(phi)
    sl, cl = np.sin(lam), np.cos(lam)
    return np.array([
        [-sl,      cl,      0.0],
        [-sp * cl, -sp * sl, cp],
        [ cp * cl,  cp * sl, sp],
    ])


def build_site(
    lat_deg: float = OBSERVER_LAT_DEG,
    lon_deg: float = OBSERVER_LON_DEG,
    alt_m: float = OBSERVER_ALT_M,
) -> ObserverSite:
    loc = EarthLocation.from_geodetic(
        lon=lon_deg * u.deg, lat=lat_deg * u.deg, height=alt_m * u.m,
    )
    # `geocentric` returns an astropy Quantity triple in metres (ITRS/ECEF).
    x = float(loc.geocentric[0].to(u.m).value)
    y = float(loc.geocentric[1].to(u.m).value)
    z = float(loc.geocentric[2].to(u.m).value)
    return ObserverSite(
        lat_deg=lat_deg, lon_deg=lon_deg, alt_m=alt_m,
        ecef_x=x, ecef_y=y, ecef_z=z,
        enu_rotation=_enu_rotation(lat_deg, lon_deg),
    )


_DEFAULT_SITE: ObserverSite | None = None


def default_site() -> ObserverSite:
    global _DEFAULT_SITE
    if _DEFAULT_SITE is None:
        _DEFAULT_SITE = build_site()
    return _DEFAULT_SITE


def fetch_telescope_lonlat(cli) -> tuple[float, float]:
    """Return ``(lat_deg, lon_deg)`` from the telescope's stored GPS.

    The Seestar firmware exposes its configured geodetic origin via
    ``get_device_state`` with key ``location_lon_lat`` — a two-element
    list in ``[lon, lat]`` order (see device/seestar_device.py:1038).
    Altitude isn't stored by the firmware, so callers resolve that
    separately (manual entry, prior calibration, or elevation lookup).
    """
    resp = cli.method_sync(
        "get_device_state", {"keys": ["location_lon_lat"]},
    )
    if not isinstance(resp, dict):
        raise RuntimeError(
            "telescope did not return a valid response to "
            "get_device_state (is the mount powered on and connected?)"
        )
    result = resp.get("result")
    if not isinstance(result, dict) or "location_lon_lat" not in result:
        raise RuntimeError(
            f"telescope response missing 'location_lon_lat': {resp!r}"
        )
    lon_lat = result["location_lon_lat"]
    if not (isinstance(lon_lat, (list, tuple)) and len(lon_lat) >= 2):
        raise RuntimeError(
            f"telescope 'location_lon_lat' malformed: {lon_lat!r}"
        )
    return float(lon_lat[1]), float(lon_lat[0])


def build_site_from_telescope(cli, alt_m: float) -> ObserverSite:
    """Fetch the observer's lat/lon from the telescope's stored state
    and build an ObserverSite at the given altitude.

    Thin wrapper over :func:`fetch_telescope_lonlat` for callers that
    don't need the intermediate lat/lon.
    """
    lat_deg, lon_deg = fetch_telescope_lonlat(cli)
    return build_site(lat_deg=lat_deg, lon_deg=lon_deg, alt_m=float(alt_m))


def lla_to_ecef(
    lat_deg: float, lon_deg: float, alt_m: float,
) -> tuple[float, float, float]:
    """WGS84 lat/lon/alt → ECEF (metres). Time-independent."""
    loc = EarthLocation.from_geodetic(
        lon=lon_deg * u.deg, lat=lat_deg * u.deg, height=alt_m * u.m,
    )
    return (
        float(loc.geocentric[0].to(u.m).value),
        float(loc.geocentric[1].to(u.m).value),
        float(loc.geocentric[2].to(u.m).value),
    )


def ecef_to_topocentric(
    ecef_xyz: np.ndarray | tuple[float, float, float],
    site: ObserverSite | None = None,
) -> tuple[float, float, float]:
    """ECEF (m) → (az_deg, el_deg, slant_m) at the observer site.

    az is in [0, 360) with 0° = north, 90° = east (standard compass).
    el is in [-90, 90]. Accepts a single 3-vector; see `ecef_array_to_topo`
    for batched input.
    """
    if site is None:
        site = default_site()
    v = np.asarray(ecef_xyz, dtype=float) - site.ecef_xyz
    enu = site.enu_rotation @ v
    east, north, up = enu[0], enu[1], enu[2]
    slant = float(np.sqrt(east * east + north * north + up * up))
    if slant == 0.0:
        return (0.0, 90.0, 0.0)
    az = (np.degrees(np.arctan2(east, north)) + 360.0) % 360.0
    el = np.degrees(np.arcsin(up / slant))
    return (float(az), float(el), slant)


def ecef_array_to_topo(
    ecef_xyz: np.ndarray,
    site: ObserverSite | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Batched ECEF → (az_deg, el_deg, slant_m). Input shape (N, 3)."""
    if site is None:
        site = default_site()
    arr = np.asarray(ecef_xyz, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"expected shape (N, 3), got {arr.shape}")
    v = arr - site.ecef_xyz
    enu = v @ site.enu_rotation.T
    east = enu[:, 0]
    north = enu[:, 1]
    up = enu[:, 2]
    slant = np.sqrt(east * east + north * north + up * up)
    az = (np.degrees(np.arctan2(east, north)) + 360.0) % 360.0
    with np.errstate(invalid="ignore", divide="ignore"):
        el = np.degrees(np.arcsin(np.where(slant > 0, up / slant, 0.0)))
    return az, el, slant


def wrap_pm180(deg: float) -> float:
    d = (deg + 180.0) % 360.0 - 180.0
    if d == -180.0:
        return 180.0
    return d


def haversine_m(
    lat1_deg: float, lon1_deg: float,
    lat2_deg: float, lon2_deg: float,
) -> float:
    """Great-circle distance in metres between two WGS84 points.

    Used by the calibration tool's staleness check and anywhere else
    we need a quick 'has the observer moved?' test. Accuracy is ≲0.5%
    — plenty for our ~10 m thresholds. Uses the standard Earth radius
    6,371,000 m; we don't need WGS84 ellipsoidal precision here.
    """
    earth_r_m = 6_371_000.0
    phi1 = np.radians(lat1_deg)
    phi2 = np.radians(lat2_deg)
    dphi = np.radians(lat2_deg - lat1_deg)
    dlam = np.radians(lon2_deg - lon1_deg)
    a = (
        np.sin(dphi / 2.0) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    )
    c = 2.0 * np.arcsin(np.sqrt(min(1.0, float(a))))
    return float(earth_r_m * c)


def lookup_elevation(
    lat_deg: float, lon_deg: float, *, timeout_s: float = 4.0,
) -> float:
    """Return the ground elevation in metres AMSL at the given
    lat/lon, via the Open-Meteo free elevation API.

    Raises ``RuntimeError`` on any HTTP, timeout, parse, or
    schema-mismatch failure so callers can fall back without swallowing
    the cause. The endpoint is unauthenticated and rate-limited to a
    very generous cap — a single call per CLI invocation is safe.
    """
    import requests

    url = "https://api.open-meteo.com/v1/elevation"
    params = {"latitude": f"{lat_deg:.6f}", "longitude": f"{lon_deg:.6f}"}
    try:
        resp = requests.get(url, params=params, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"elevation lookup failed: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"elevation response not JSON: {exc}") from exc
    elev = data.get("elevation") if isinstance(data, dict) else None
    if not isinstance(elev, list) or not elev:
        raise RuntimeError(f"elevation response malformed: {data!r}")
    try:
        return float(elev[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"elevation value not numeric: {elev!r}") from exc


def unwrap_az_series(wrapped_deg: np.ndarray) -> np.ndarray:
    """Unwrap a wrapped az sequence (any convention) into a monotone-ish
    cumulative series. Used by replay to feed the plant-model loop with
    positions that don't jump at the ±180° boundary."""
    arr = np.asarray(wrapped_deg, dtype=float)
    if arr.size == 0:
        return arr.copy()
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, arr.size):
        delta = wrap_pm180(arr[i] - arr[i - 1])
        out[i] = out[i - 1] + delta
    return out
