"""Top-level LiveTracker / sun-safety service wired into `root_app.py`.

`LiveTrackerMain` is the fourth `AppRunner`-compatible entry point in
the process (alongside `DeviceMain`, `FrontMain`, and the imaging
Flask server). At boot it:

- Instantiates the `LiveTrackManager` singleton (cheap — no threads).
- Instantiates the `TargetCatalog` with `live_enabled=True` (cheap —
  the adsb.fi poller is deferred to the first `list_live()` call).
- Starts a `SunSafetyMonitor` whose altaz_reader talks to the ALP
  device server via AlpacaClient + astropy, and whose jog_command
  bypasses the lockout-aware `speed_move` wrapper by hitting
  `cli.method_sync('scope_speed_move', ...)` directly.

The goal: the tracker infrastructure is always loaded so the
sun-safety guard is authoritative, but it stays quiescent (no
outbound traffic, no mount commands) until the user actually opens
the live-tracker UI or runs a calibration.
"""

from __future__ import annotations

import logging
from typing import Optional

from device import live_tracker as _lt
from device import sun_safety as _ss
from device.config import Config


logger = logging.getLogger(__name__)


class LiveTrackerMain:
    """AppRunner-compatible wrapper for the live-tracker service."""

    def __init__(self) -> None:
        self._monitor: Optional[_ss.SunSafetyMonitor] = None

    # ---------- lifecycle ----------

    def start(self) -> None:
        Config.load_toml()

        # Touch the lazy singletons so their state is ready when the
        # Front hits them. Neither call starts a thread.
        _lt.get_manager()
        _lt.get_catalog()

        if not getattr(Config, "sun_avoidance_enabled", True):
            logger.info("sun_avoidance disabled in config — monitor NOT started")
            return

        self._monitor = _ss.SunSafetyMonitor(
            altaz_reader=_make_altaz_reader(),
            jog_command=_make_jog_command(),
            abort_active=_abort_active_sessions,
            lat_deg=Config.init_lat,
            lon_deg=Config.init_long,
            min_separation_deg=Config.sun_avoidance_min_sep_deg,
            alt_threshold_deg=Config.sun_avoidance_alt_threshold_deg,
            jog_speed=Config.sun_avoidance_jog_speed,
            jog_duration_s=Config.sun_avoidance_jog_duration_s,
            enabled=Config.sun_avoidance_enabled,
        )
        _ss.set_sun_monitor(self._monitor)
        self._monitor.start()

    def reload(self) -> None:
        """Picked up by root_app's config watcher. Pushes the new
        thresholds into the running monitor without restarting."""
        Config.load_toml()
        if self._monitor is None:
            # Config might have re-enabled us; spin up now.
            if getattr(Config, "sun_avoidance_enabled", True):
                self.start()
            return
        self._monitor.reload(
            min_separation_deg=Config.sun_avoidance_min_sep_deg,
            alt_threshold_deg=Config.sun_avoidance_alt_threshold_deg,
            jog_speed=Config.sun_avoidance_jog_speed,
            jog_duration_s=Config.sun_avoidance_jog_duration_s,
            enabled=Config.sun_avoidance_enabled,
        )

    def stop(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
        _ss.set_sun_monitor(None)


# ---------- callbacks / adapters ----------


def _make_altaz_reader() -> _ss.AltazReader:
    """Build a callable that reads the first configured scope's sky
    (az, alt). Returns None on any failure so the monitor skips a
    tick rather than crashing."""

    def _read() -> Optional[tuple[float, float]]:
        try:
            from astropy.coordinates import AltAz, EarthLocation, SkyCoord
            from astropy.time import Time
            import astropy.units as u
            from device.alpaca_client import AlpacaClient

            tid = _primary_telescope_id()
            cli = AlpacaClient("127.0.0.1", int(Config.port), tid)
            resp = cli.method_sync("scope_get_equ_coord")
            if not isinstance(resp, dict) or "result" not in resp:
                return None
            result = resp["result"]
            ra_h = float(result.get("ra", 0.0))
            dec_d = float(result.get("dec", 0.0))
            # Heuristic: firmware reports (0, 0) before plate-solve
            # alignment. A real session that has never been aligned
            # parks at ra=0,dec=0 sometimes — treat that as "don't
            # trust" so we don't spuriously trip the monitor.
            if abs(ra_h) < 1e-6 and abs(dec_d) < 1e-6:
                return None
            loc = EarthLocation.from_geodetic(
                lat=Config.init_lat * u.deg,
                lon=Config.init_long * u.deg,
            )
            altaz = (
                SkyCoord(ra=ra_h * u.hour, dec=dec_d * u.deg, frame="icrs")
                .transform_to(AltAz(obstime=Time.now(), location=loc))
            )
            return float(altaz.az.deg) % 360.0, float(altaz.alt.deg)
        except Exception:
            logger.debug("altaz_reader failed", exc_info=True)
            return None

    return _read


def _make_jog_command() -> _ss.RawJogCommand:
    """Build the privileged jog callable. Uses the raw AlpacaClient
    directly (bypasses device.velocity_controller.speed_move, which
    would short-circuit on the lockout event the monitor just set)."""

    def _jog(speed: int, angle: int, dur_sec: int) -> None:
        from device.alpaca_client import AlpacaClient

        tid = _primary_telescope_id()
        cli = AlpacaClient("127.0.0.1", int(Config.port), tid)
        cli.method_sync(
            "scope_speed_move",
            {"speed": int(speed), "angle": int(angle), "dur_sec": int(dur_sec)},
        )

    return _jog


def _abort_active_sessions() -> None:
    """Stop live-tracker + calibration sessions on every configured
    scope. Runs inside the monitor's trigger sequence; exceptions are
    caught at the monitor level."""
    import device.rotation_calibration as _rc
    mgr = _lt.get_manager()
    for dev in getattr(Config, "seestars", []) or []:
        try:
            mgr.stop(int(dev["device_num"]))
        except Exception:
            logger.debug("mgr.stop raised for %s", dev, exc_info=True)
        try:
            _rc.get_calibration_manager().stop(int(dev["device_num"]))
        except Exception:
            logger.debug("calibration stop raised for %s", dev, exc_info=True)


def _primary_telescope_id() -> int:
    """Return the first configured seestar's device_num, defaulting to 1."""
    seestars = getattr(Config, "seestars", None) or []
    if seestars:
        try:
            return int(seestars[0]["device_num"])
        except (KeyError, TypeError, ValueError):
            pass
    return 1


__all__ = ["LiveTrackerMain"]
