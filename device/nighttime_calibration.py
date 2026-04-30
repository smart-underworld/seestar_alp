"""Nighttime calibration session — plate-solve a series of sky frames
to fit the same 3-DOF mount rotation the daytime FAA-landmark workflow
fits.

Each sighting cycle:

1. Operator commands a slew to ``(commanded_az, commanded_el)`` (a
   pre-set sky position; the operator then nudges via the live-tracker
   continuous-control loop from PR #15 if needed).
2. Mount settles (motion session reports ``is_settled``).
3. Caller invokes :meth:`NighttimeCalibrationSession.capture_sighting`.
   With the default :class:`SeestarPlateSolver` no image path is
   needed — the scope's onboard solver inspects whatever it is
   currently looking at. With the ``solve-field`` fallback the caller
   passes the captured image path explicitly.
4. The session runs the plate solver in a background thread, converts
   the solved (RA, Dec) to topocentric (az, el) for the site + capture
   time, and stores the resulting ``(encoder_az_el, true_az_el)`` pair.
5. With ≥3 accepted sightings the session refits the rotation matrix
   via :func:`device.rotation_calibration.solve_rotation_from_pairs`.

If a plate solve fails (no solution / wildly-wrong FOV / timeout), the
caller can :meth:`skip_pending` to discard the latest cycle without
losing prior accepted sightings, then jog (PR #15 arrow keys / click-to-
go) to a clearer-sky neighbour and retry.

The session writes the same ``mount_calibration.json`` schema as the
daytime path, with ``calibration_method: "rotation_platesolve"`` so
downstream consumers (``MountFrame.from_calibration_json``, the live
tracker) pick it up unchanged.

Mutex: refuses to start while ``LiveTrackSession`` is alive on this
telescope. Allowed alongside ``CalibrateMotionSession``.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from device._atomic_json import write_atomic_json
from device.plate_solver import (
    PlateSolver,
    PlateSolverFailed,
    PlateSolverNotAvailable,
    S50_FOV_MAX_DEG,
    S50_FOV_MIN_DEG,
    SolveResult,
    get_default_plate_solver,
)
from device.rotation_calibration import (
    RotationSolution,
    solve_rotation_from_pairs,
)
from scripts.trajectory.observer import ObserverSite


# Minimum altitude (degrees) the mount may be asked to sight at. Below
# this, plate-solving the ground (or trees) is a waste; refuse the
# capture so the operator jogs to a clearer position.
MIN_SIGHTING_ALTITUDE_DEG = 10.0
# Maximum altitude. The az frame is degenerate near the pole, so we
# keep sightings out of the last few degrees.
MAX_SIGHTING_ALTITUDE_DEG = 80.0
# Need this many accepted sightings before ``apply()`` will write the
# calibration. The 3-DOF fit is ill-conditioned with fewer than 3 points
# spanning meaningful sky.
MIN_SIGHTINGS_FOR_APPLY = 3


# ---------- data model ------------------------------------------------


@dataclass(frozen=True)
class NighttimeSighting:
    """One plate-solved (commanded → true) sighting."""

    encoder_az_deg: float
    encoder_el_deg: float
    true_ra_deg: float
    true_dec_deg: float
    true_az_deg: float
    true_el_deg: float
    fov_x_deg: float
    fov_y_deg: float
    position_angle_deg: float
    image_path: str
    t_unix: float
    stars_used: int = 0


@dataclass
class PendingCapture:
    """A single capture currently being plate-solved. Polling the
    ``state`` endpoint shows ``status='solving'`` while this is active;
    success appends to ``sightings``, failure surfaces an error."""

    image_path: str
    encoder_az_deg: float
    encoder_el_deg: float
    t_started_unix: float
    status: str = "queued"  # "queued" | "solving" | "ok" | "fail" | "skipped"
    error: str | None = None


@dataclass
class NighttimeStatus:
    """JSON-serialisable session snapshot."""

    active: bool
    phase: str
    n_accepted: int
    min_required: int
    pending: dict | None
    last_failed: dict | None
    fit: dict | None
    sightings: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------- coordinate conversion ------------------------------------


def radec_to_topocentric_azel(
    ra_deg: float,
    dec_deg: float,
    t_unix: float,
    site: ObserverSite,
) -> tuple[float, float]:
    """Convert ICRS (RA, Dec) → topocentric (az, el) for the site at the
    given UTC time. Uses astropy's AltAz transform — handles precession,
    nutation, atmospheric refraction (default sea-level NIST conditions),
    and aberration.

    Wrapped here so tests can monkey-patch this single function rather
    than mocking astropy's machinery.
    """
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord
    from astropy.time import Time

    loc = EarthLocation.from_geodetic(
        lon=site.lon_deg * u.deg,
        lat=site.lat_deg * u.deg,
        height=site.alt_m * u.m,
    )
    sky = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    altaz = sky.transform_to(AltAz(obstime=Time(t_unix, format="unix"), location=loc))
    return float(altaz.az.deg), float(altaz.alt.deg)


# ---------- session ---------------------------------------------------


class NighttimeCalibrationSession:
    """Stateful holder for one nighttime calibration run.

    Single-flight: one capture in flight at a time. The background
    solve thread is daemonic, joined on ``stop()``.
    """

    def __init__(
        self,
        telescope_id: int,
        site: ObserverSite,
        out_path: Path,
        *,
        plate_solver: PlateSolver | None = None,
        min_sightings: int = MIN_SIGHTINGS_FOR_APPLY,
    ):
        self.telescope_id = int(telescope_id)
        self.site = site
        self.out_path = Path(out_path)
        self.plate_solver = plate_solver or get_default_plate_solver()
        self.min_sightings = int(min_sightings)

        self._lock = threading.Lock()
        self._sightings: list[NighttimeSighting] = []
        self._solution: RotationSolution | None = None
        self._pending: PendingCapture | None = None
        self._last_failed: PendingCapture | None = None
        self._errors: list[str] = []
        self._phase = "idle"
        # Set when ``stop()`` is called; cancels any in-flight solve.
        self._stop_evt = threading.Event()
        self._solve_thread: threading.Thread | None = None
        self._active = True

    # ---------- lifecycle ----------

    def stop(self) -> None:
        with self._lock:
            self._active = False
            self._phase = "stopped"
        self._stop_evt.set()
        # Don't join here; the daemon thread will exit on its own when
        # the solve completes (and we cancel further work via the event
        # check). Caller should not invoke any further methods after stop.

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    # ---------- snapshot ----------

    def status(self) -> NighttimeStatus:
        with self._lock:
            sol_dict = None
            if self._solution is not None:
                sol_dict = {
                    "yaw_deg": self._solution.yaw_deg,
                    "pitch_deg": self._solution.pitch_deg,
                    "roll_deg": self._solution.roll_deg,
                    "residual_rms_deg": self._solution.residual_rms_deg,
                    "per_record": list(self._solution.per_landmark),
                }
            pending_dict = None
            if self._pending is not None:
                pending_dict = {
                    "image_path": self._pending.image_path,
                    "encoder_az_deg": self._pending.encoder_az_deg,
                    "encoder_el_deg": self._pending.encoder_el_deg,
                    "t_started_unix": self._pending.t_started_unix,
                    "elapsed_s": time.time() - self._pending.t_started_unix,
                    "status": self._pending.status,
                    "error": self._pending.error,
                }
            last_failed_dict = None
            if self._last_failed is not None:
                last_failed_dict = {
                    "image_path": self._last_failed.image_path,
                    "encoder_az_deg": self._last_failed.encoder_az_deg,
                    "encoder_el_deg": self._last_failed.encoder_el_deg,
                    "status": self._last_failed.status,
                    "error": self._last_failed.error,
                }
            sightings_list = [
                {
                    "encoder_az_deg": s.encoder_az_deg,
                    "encoder_el_deg": s.encoder_el_deg,
                    "true_ra_deg": s.true_ra_deg,
                    "true_dec_deg": s.true_dec_deg,
                    "true_az_deg": s.true_az_deg,
                    "true_el_deg": s.true_el_deg,
                    "fov_x_deg": s.fov_x_deg,
                    "fov_y_deg": s.fov_y_deg,
                    "position_angle_deg": s.position_angle_deg,
                    "image_path": s.image_path,
                    "t_unix": s.t_unix,
                    "stars_used": s.stars_used,
                }
                for s in self._sightings
            ]
            return NighttimeStatus(
                active=self._active,
                phase=self._phase,
                n_accepted=len(self._sightings),
                min_required=self.min_sightings,
                pending=pending_dict,
                last_failed=last_failed_dict,
                fit=sol_dict,
                sightings=sightings_list,
                errors=list(self._errors),
            )

    # ---------- capture ----------

    def capture_sighting(
        self,
        image_path: Path | str | None = None,
        encoder_az_deg: float | None = None,
        encoder_el_deg: float | None = None,
    ) -> None:
        """Queue a plate solve for the given encoder position.
        Background-threaded; caller polls :meth:`status` for
        completion.

        ``image_path`` is optional: the default
        :class:`SeestarPlateSolver` ignores it because the firmware
        plate-solves the live view. Pass a path only when using the
        ``solve-field`` fallback against a captured FITS image.

        ``encoder_az_deg`` and ``encoder_el_deg`` are required — they
        are sentinel-defaulted to ``None`` only so ``image_path`` can
        remain optional in keyword calls. Forgetting them raises a
        clear ``ValueError`` rather than silently treating the encoder
        as pointing at the horizon (which would fail later with the
        confusing altitude-floor error).

        Raises if a previous solve is still in flight (single-flight) or
        if the encoder position is outside the altitude window.
        """
        if encoder_az_deg is None or encoder_el_deg is None:
            raise ValueError("encoder_az_deg and encoder_el_deg are required")
        if encoder_el_deg < MIN_SIGHTING_ALTITUDE_DEG:
            raise ValueError(
                f"encoder el {encoder_el_deg:.2f}° below "
                f"{MIN_SIGHTING_ALTITUDE_DEG:.0f}° altitude floor"
            )
        if encoder_el_deg > MAX_SIGHTING_ALTITUDE_DEG:
            raise ValueError(
                f"encoder el {encoder_el_deg:.2f}° above "
                f"{MAX_SIGHTING_ALTITUDE_DEG:.0f}° (az ill-conditioned at zenith)"
            )
        with self._lock:
            if self._pending is not None and self._pending.status in (
                "queued",
                "solving",
            ):
                raise RuntimeError("a plate-solve is already in flight; wait")
            self._pending = PendingCapture(
                image_path="" if image_path is None else str(image_path),
                encoder_az_deg=float(encoder_az_deg),
                encoder_el_deg=float(encoder_el_deg),
                t_started_unix=time.time(),
                status="queued",
            )
            self._phase = "solving"
        self._solve_thread = threading.Thread(
            target=self._solve_worker,
            name=f"NighttimePlateSolve({self.telescope_id})",
            daemon=True,
        )
        self._solve_thread.start()

    def skip_pending(self) -> None:
        """Discard a pending or recently-failed capture. The accepted
        sighting list is unchanged."""
        with self._lock:
            if self._pending is not None and self._pending.status in (
                "fail",
                "ok",
            ):
                # Keep last_failed in place so the UI can still show the
                # diagnostic; just clear the pending slot.
                if self._pending.status == "fail":
                    self._last_failed = self._pending
                self._pending = None
            elif self._pending is not None:
                # In-flight solve: mark cancelled. The worker will see
                # _stop_evt is set (or detect _pending=None on exit).
                self._pending.status = "skipped"
                self._last_failed = self._pending
                self._pending = None
            self._phase = "idle"

    def remove_sighting(self, idx: int) -> None:
        """Remove an accepted sighting and refit. Used when the operator
        spots a bad fit row and wants to drop it rather than re-shoot."""
        with self._lock:
            if not (0 <= idx < len(self._sightings)):
                raise IndexError(f"sighting idx {idx} out of range")
            del self._sightings[idx]
        self._refit_locked()

    def apply(self) -> None:
        """Persist the current fit to the calibration JSON. Refuses if
        we don't have ``min_sightings`` accepted records."""
        with self._lock:
            if len(self._sightings) < self.min_sightings:
                raise ValueError(
                    f"need ≥{self.min_sightings} sightings; have {len(self._sightings)}"
                )
            if self._solution is None:
                raise ValueError("no solution yet; capture more sightings")
            sol = self._solution
            sightings_snapshot = list(self._sightings)
        payload = self._build_payload(sol, sightings_snapshot)
        write_atomic_json(self.out_path, payload, indent=2)
        with self._lock:
            self._phase = "committed"

    # ---------- internals ----------

    def _solve_worker(self) -> None:
        with self._lock:
            pending = self._pending
            if pending is None:
                return
            pending.status = "solving"

        # Run the (possibly slow) solver outside the lock so other
        # methods like status() stay responsive. Pass None when the
        # session wasn't given a captured image — the Seestar onboard
        # solver doesn't use it; ``solve-field`` will surface a clear
        # error in that case.
        solver_arg = Path(pending.image_path) if pending.image_path else None
        try:
            solve_result = self.plate_solver.solve(solver_arg)
        except PlateSolverNotAvailable as exc:
            self._record_failure(pending, str(exc))
            return
        except PlateSolverFailed as exc:
            self._record_failure(pending, str(exc))
            return
        except FileNotFoundError as exc:
            self._record_failure(pending, str(exc))
            return
        except Exception as exc:
            self._record_failure(pending, f"unexpected solver error: {exc}")
            return

        # FOV sanity check.
        fx = solve_result.fov_x_deg
        fy = solve_result.fov_y_deg
        if not (
            S50_FOV_MIN_DEG <= fx <= S50_FOV_MAX_DEG
            and S50_FOV_MIN_DEG <= fy <= S50_FOV_MAX_DEG
        ):
            self._record_failure(
                pending,
                f"solver returned FOV {fx:.2f}×{fy:.2f}° outside "
                f"[{S50_FOV_MIN_DEG}, {S50_FOV_MAX_DEG}]°",
            )
            return

        # Convert (RA, Dec) → topocentric (az, el).
        try:
            true_az, true_el = radec_to_topocentric_azel(
                solve_result.ra_deg,
                solve_result.dec_deg,
                pending.t_started_unix,
                self.site,
            )
        except Exception as exc:
            self._record_failure(pending, f"radec→azel failed: {exc}")
            return

        sighting = NighttimeSighting(
            encoder_az_deg=pending.encoder_az_deg,
            encoder_el_deg=pending.encoder_el_deg,
            true_ra_deg=solve_result.ra_deg,
            true_dec_deg=solve_result.dec_deg,
            true_az_deg=true_az,
            true_el_deg=true_el,
            fov_x_deg=fx,
            fov_y_deg=fy,
            position_angle_deg=solve_result.position_angle_deg,
            image_path=pending.image_path,
            t_unix=pending.t_started_unix,
            stars_used=solve_result.stars_used,
        )
        with self._lock:
            self._sightings.append(sighting)
            pending.status = "ok"
            self._pending = None
            self._phase = "fit_pending"
        self._refit_locked()

    def _record_failure(self, pending: PendingCapture, reason: str) -> None:
        with self._lock:
            pending.status = "fail"
            pending.error = reason
            self._last_failed = pending
            self._pending = None
            self._phase = "fail_pending"
            self._errors.append(reason)

    def _refit_locked(self) -> None:
        # Snapshot under lock, fit outside.
        with self._lock:
            sightings = list(self._sightings)
        if len(sightings) < 1:
            with self._lock:
                self._solution = None
                self._phase = "idle"
            return
        try:
            sol = solve_rotation_from_pairs(
                [
                    (
                        s.encoder_az_deg,
                        s.encoder_el_deg,
                        s.true_az_deg,
                        s.true_el_deg,
                    )
                    for s in sightings
                ],
            )
        except Exception as exc:
            with self._lock:
                self._errors.append(f"refit failed: {exc}")
            return
        with self._lock:
            self._solution = sol
            self._phase = (
                "ready_to_apply"
                if len(self._sightings) >= self.min_sightings
                else "fit_pending"
            )

    def _build_payload(
        self,
        sol: RotationSolution,
        sightings: list[NighttimeSighting],
    ) -> dict:
        """Build the same JSON schema the daytime path writes, with
        ``calibration_method`` flipped to ``rotation_platesolve`` and
        the per-record list extended with platesolve-specific fields."""
        return {
            "calibration_method": "rotation_platesolve",
            "calibrated_at": time.strftime("%Y-%m-%dT%H-%M-%S%z"),
            "yaw_offset_deg": sol.yaw_deg,
            "pitch_offset_deg": sol.pitch_deg,
            "roll_offset_deg": sol.roll_deg,
            "origin_offset_ecef_m": [0.0, 0.0, 0.0],
            "residual_rms_deg": sol.residual_rms_deg,
            "n_sightings": len(sightings),
            "observer": {
                "lat_deg": self.site.lat_deg,
                "lon_deg": self.site.lon_deg,
                "alt_m": self.site.alt_m,
                "source": "telescope_get_device_state",
            },
            # Per-sighting records carry both the solver output and the
            # fit residuals (solver's per-record list already has
            # encoder, true, predicted, residual).
            "sightings": [
                {
                    "encoder_az_deg": s.encoder_az_deg,
                    "encoder_el_deg": s.encoder_el_deg,
                    "true_ra_deg": s.true_ra_deg,
                    "true_dec_deg": s.true_dec_deg,
                    "true_az_deg": s.true_az_deg,
                    "true_el_deg": s.true_el_deg,
                    "fov_x_deg": s.fov_x_deg,
                    "fov_y_deg": s.fov_y_deg,
                    "position_angle_deg": s.position_angle_deg,
                    "image_path": s.image_path,
                    "t_unix": s.t_unix,
                    "stars_used": s.stars_used,
                }
                for s in sightings
            ],
            "fit_per_record": list(sol.per_landmark),
        }


# ---------- manager ---------------------------------------------------


class NighttimeCalibrationManager:
    """Singleton-per-process registry, telescope-keyed. Mirrors
    ``CalibrationManager`` and ``CalibrateMotionManager``."""

    def __init__(self) -> None:
        self._sessions: dict[int, NighttimeCalibrationSession] = {}
        self._lock = threading.Lock()

    def get(self, telescope_id: int) -> NighttimeCalibrationSession | None:
        with self._lock:
            return self._sessions.get(int(telescope_id))

    def is_running(self, telescope_id: int) -> bool:
        s = self.get(telescope_id)
        return s is not None and s.is_active()

    def start(
        self, session: NighttimeCalibrationSession
    ) -> NighttimeCalibrationSession:
        tid = int(session.telescope_id)
        # Refuse if the live tracker is driving the same mount.
        try:
            from device.live_tracker import get_manager as _get_tracker_mgr

            tracker = _get_tracker_mgr().get(tid)
            if tracker is not None and tracker.is_alive():
                raise RuntimeError(
                    f"telescope {tid} is live-tracking; stop the tracker first"
                )
        except ImportError:
            pass
        with self._lock:
            existing = self._sessions.get(tid)
            if existing is not None and existing.is_active():
                raise RuntimeError(
                    f"telescope {tid} is already in nighttime calibration mode"
                )
            self._sessions[tid] = session
        return session

    def stop(self, telescope_id: int) -> NighttimeStatus | None:
        s = self.get(telescope_id)
        if s is None:
            return None
        s.stop()
        return s.status()

    def status(self, telescope_id: int) -> NighttimeStatus | None:
        s = self.get(telescope_id)
        return s.status() if s is not None else None


_MANAGER: NighttimeCalibrationManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_nighttime_manager() -> NighttimeCalibrationManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = NighttimeCalibrationManager()
        return _MANAGER


# ---------- auto-calibration -----------------------------------------
#
# Hands-free flow: pick a handful of bright sky targets in a sweet-spot
# altitude window (60–80°), drive the mount to each one, plate-solve,
# count successes, and stop once we've collected enough sightings for
# the rotation fit. The operator clicks one button instead of slewing
# manually for each capture.
#
# Altitude window rationale: above 80° the azimuth axis is geometrically
# ill-conditioned (a small angular error projects to a huge az delta);
# below 60° atmospheric refraction starts to dominate and trees / roof
# lines obstruct typical backyard sites. 60–80° is the band where the
# rotation fit converges cleanly with few sightings.


_AUTO_LOG = logging.getLogger(__name__)


# Default altitude window the picker filters into.
AUTO_MIN_ALT_DEG = 60.0
AUTO_MAX_ALT_DEG = 80.0
# Number of candidates to surface; the runner stops as soon as it has
# enough successes, so a generous pool just buys retries against
# clouds / trees in any one direction.
AUTO_DEFAULT_POOL_SIZE = 8
# How long to wait after a slew completes before reading the encoder
# and triggering the plate-solve. Three things have to settle in this
# window:
#
#   1. Optical tube damps oscillations after the motors stop.
#   2. Sidereal tracking re-engages (firmware emits ScopeTrack=on).
#   3. The live-view pipeline produces a *fresh* exposure at the new
#      pointing. In star mode the seestar reports fps ≈ 0.041 (a frame
#      every ~24 s) — solving an old cached frame from the previous
#      pointing is the dominant failure mode otherwise.
#
# 8 s is chosen as a compromise: well past mechanical settling, well
# past tracking re-engage, and gives the firmware enough of a fresh
# exposure window that the solver sees the new sky region rather than
# the previous one.
AUTO_SETTLE_AFTER_SLEW_S = 8.0
# Per-target plate-solve budget; the firmware's solver typically
# finishes in 5–15 s, so 90 s is generous.
AUTO_PER_TARGET_SOLVE_TIMEOUT_S = 90.0
# Live-view exposure set once at run start. ``start_solve`` plate-solves
# whatever frame the live view most recently produced, so the operator's
# previous ``exp_ms.continuous`` setting (could be 100 ms from a daytime
# preview) directly affects how many stars are detectable. 2000 ms is
# the seestar's documented sweet spot for star-mode plate-solving.
AUTO_PLATE_SOLVE_EXPOSURE_MS = 2000


@dataclass(frozen=True)
class AutoCandidate:
    """One auto-calibration waypoint: a celestial target + its predicted
    (az, el) at session start. The runner uses ``az_deg``/``el_deg`` as
    the slew destination; the actual sighting recorded against the fit
    comes from the firmware plate-solver, not from this prediction."""

    label: str
    az_deg: float
    el_deg: float
    vmag: float | None = None
    kind: str = "star"  # "star" | "planet" | "double"


@dataclass
class AutoCandidateState:
    """Per-candidate progress, mutated as the runner iterates."""

    candidate: AutoCandidate
    status: str = "queued"  # queued|slewing|settling|solving|ok|fail|skipped
    error: str | None = None
    encoder_az_deg: float | None = None
    encoder_el_deg: float | None = None
    t_started_unix: float | None = None
    t_finished_unix: float | None = None


@dataclass
class AutoRunStatus:
    """JSON-serialisable snapshot of an :class:`NighttimeAutoRunner`."""

    active: bool
    phase: str  # "idle" | "running" | "done" | "cancelled" | "failed"
    n_success: int
    n_fail: int
    n_success_target: int
    current_idx: int | None
    candidates: list[dict] = field(default_factory=list)
    error: str | None = None


def _angular_distance_deg(
    az1_deg: float, el1_deg: float, az2_deg: float, el2_deg: float
) -> float:
    """Local copy of the celestial-targets helper so this module stays
    importable in tests that don't pull in ephem."""
    a_az = math.radians(az1_deg)
    a_el = math.radians(el1_deg)
    b_az = math.radians(az2_deg)
    b_el = math.radians(el2_deg)
    cos_sep = math.sin(a_el) * math.sin(b_el) + math.cos(a_el) * math.cos(
        b_el
    ) * math.cos(a_az - b_az)
    cos_sep = max(-1.0, min(1.0, cos_sep))
    return math.degrees(math.acos(cos_sep))


def _az_in_window(
    az_deg: float, az_min_deg: float | None, az_max_deg: float | None
) -> bool:
    """True iff ``az_deg`` (degrees, [0, 360)) lies in the azimuth window.

    ``None`` for either bound means unrestricted on that side. Supports
    wrap-around windows (``az_min_deg`` > ``az_max_deg`` means
    e.g. 350° → 30° passing through 0°). Both bounds being ``None``
    accepts everything, which keeps the existing tests / no-window
    callers unchanged.
    """
    if az_min_deg is None and az_max_deg is None:
        return True
    az = float(az_deg) % 360.0
    lo = float(az_min_deg) % 360.0 if az_min_deg is not None else 0.0
    hi = float(az_max_deg) % 360.0 if az_max_deg is not None else 360.0
    if lo <= hi:
        return lo <= az <= hi
    # Wrap-around window: az is in window if it's >= lo OR <= hi.
    return az >= lo or az <= hi


def pick_synthetic_waypoints(
    *,
    min_el_deg: float = AUTO_MIN_ALT_DEG,
    max_el_deg: float = AUTO_MAX_ALT_DEG,
    az_min_deg: float | None = None,
    az_max_deg: float | None = None,
    pool_size: int = AUTO_DEFAULT_POOL_SIZE,
) -> list[AutoCandidate]:
    """Emit ``pool_size`` synthetic (az, el) waypoints inside the
    requested altitude/azimuth window.

    Used when the hand-curated bright-star catalog has no entries in
    the operator's visible-sky cone (e.g. a yard with obstructions to
    the north). The seestar's onboard plate-solver doesn't need a
    named target to solve — it just needs the camera pointed at any
    star-rich patch. Waypoints are spaced evenly in az at the midpoint
    elevation so the rotation fit gets the wide az diversity it
    likes; a single elevation simplifies the geometry without harming
    conditioning at this band.
    """
    n = max(1, int(pool_size))
    el = (float(min_el_deg) + float(max_el_deg)) / 2.0
    if az_min_deg is None and az_max_deg is None:
        az_lo, az_hi = 0.0, 360.0
        wrap = False
    else:
        az_lo = float(az_min_deg if az_min_deg is not None else 0.0) % 360.0
        az_hi = float(az_max_deg if az_max_deg is not None else 360.0) % 360.0
        wrap = az_lo > az_hi
    span = (az_hi - az_lo) % 360.0 if wrap else (az_hi - az_lo)
    if span <= 0.0:
        span = 360.0
    out: list[AutoCandidate] = []
    for i in range(n):
        # Place waypoints with margin from the window edges so we don't
        # ride right against an obstruction the operator declared.
        frac = (i + 0.5) / n
        az = (az_lo + frac * span) % 360.0
        out.append(
            AutoCandidate(
                label=f"sky az {az:.0f}° el {el:.0f}°",
                az_deg=float(az),
                el_deg=float(el),
                vmag=None,
                kind="sky",
            )
        )
    return out


def pick_auto_calibration_targets(
    site: ObserverSite,
    when_utc: datetime | None = None,
    *,
    min_el_deg: float = AUTO_MIN_ALT_DEG,
    max_el_deg: float = AUTO_MAX_ALT_DEG,
    max_mag: float = 3.5,
    pool_size: int = AUTO_DEFAULT_POOL_SIZE,
    az_min_deg: float | None = None,
    az_max_deg: float | None = None,
) -> list[AutoCandidate]:
    """Return up to ``pool_size`` calibration-grade celestial targets in
    the ``[min_el_deg, max_el_deg]`` altitude window, ordered for
    maximum angular spread.

    First entry is the highest-elevation target; each subsequent entry
    is the candidate with the largest minimum great-circle distance to
    the already-picked set (greedy farthest-point sampling). This
    produces a sequence the rotation solver likes — wide az/el spread
    at every prefix, so even a partial run (e.g. 3 of 8) is
    well-conditioned.

    ``az_min_deg`` / ``az_max_deg`` constrain the azimuth window when
    the operator's site has obstructions in some directions
    (e.g. trees, roof line). Both ``None`` means no constraint. Wrap-
    around windows are supported (``min`` > ``max`` reads as a band
    crossing 0°).

    Falls back to an empty list when the catalog is fully obscured by
    altitude/sun/moon constraints — caller should surface a clear
    message rather than start a doomed run.
    """
    from scripts.trajectory.celestial_targets import (
        all_targets,
        filter_visible,
    )

    if when_utc is None:
        when_utc = datetime.now(timezone.utc)
    pool = all_targets(when_utc, site)
    visible = filter_visible(
        pool,
        site,
        when_utc,
        min_el_deg=min_el_deg,
        max_mag=max_mag,
    )
    # filter_visible has no max-altitude knob; clamp post-hoc.
    visible = [(t, az, el) for (t, az, el) in visible if el <= max_el_deg]
    # Apply optional azimuth window for obstructed-horizon sites.
    visible = [
        (t, az, el)
        for (t, az, el) in visible
        if _az_in_window(az, az_min_deg, az_max_deg)
    ]
    # Catalog is hand-curated (~30 entries) and biased northern. When
    # the operator's visible-sky cone is to the south, the cataloged
    # pool is often empty even though the patch of sky is full of
    # stars. Fall back to synthetic az/el waypoints so the auto-run
    # still has something to slew to — the plate-solver works fine
    # without a "named target."
    if not visible:
        return pick_synthetic_waypoints(
            min_el_deg=min_el_deg,
            max_el_deg=max_el_deg,
            az_min_deg=az_min_deg,
            az_max_deg=az_max_deg,
            pool_size=pool_size,
        )
    # Greedy farthest-point sampling. Start with the highest-elevation
    # entry — gives the best plate-solve odds at the first sighting,
    # which boosts confidence before the operator commits to the run.
    visible.sort(key=lambda r: -r[2])
    picked: list[tuple] = [visible[0]]
    remaining = list(visible[1:])
    while remaining and len(picked) < pool_size:
        best_idx = 0
        best_score = -1.0
        for i, (_, az, el) in enumerate(remaining):
            min_dist = min(
                _angular_distance_deg(az, el, paz, pel)
                for (_, paz, pel) in picked
            )
            if min_dist > best_score:
                best_score = min_dist
                best_idx = i
        picked.append(remaining.pop(best_idx))
    return [
        AutoCandidate(
            label=t.name,
            az_deg=float(az),
            el_deg=float(el),
            vmag=float(t.vmag) if t.vmag is not None else None,
            kind=t.kind,
        )
        for (t, az, el) in picked
    ]


SlewFunc = Callable[[float, float], bool]
EncoderFunc = Callable[[], "tuple[float, float]"]
PrepareFunc = Callable[[], None]


class NighttimeAutoRunner:
    """Drive a :class:`NighttimeCalibrationSession` through a list of
    :class:`AutoCandidate` waypoints until ``n_success_target``
    sightings land.

    Single-flight: refuses to start while another auto-run is alive on
    the same telescope. The daemon thread can be cancelled mid-run via
    :meth:`stop` — the in-flight slew/solve completes (we never
    interrupt the firmware), but no further candidates are visited.

    Tracking policy: the seestar firmware re-engages sidereal tracking
    automatically after each ``scope_goto``. We deliberately leave it
    on. Even pre-calibration the GPS + level sensor + compass priors
    keep the alt-az tracking accurate enough that stars stay points
    over the 2 s exposure (the residual drift is well below the
    plate-scale of one pixel). With tracking off, stars would streak
    across the frame during the exposure, hurting solve odds at the
    altitudes (60–80°) where azimuth slews fastest.
    """

    def __init__(
        self,
        session: NighttimeCalibrationSession,
        candidates: list[AutoCandidate],
        slew_func: SlewFunc,
        encoder_func: EncoderFunc,
        *,
        prepare_func: PrepareFunc | None = None,
        n_success_target: int = MIN_SIGHTINGS_FOR_APPLY,
        per_target_solve_timeout_s: float = AUTO_PER_TARGET_SOLVE_TIMEOUT_S,
        settle_after_slew_s: float = AUTO_SETTLE_AFTER_SLEW_S,
        poll_interval_s: float = 0.5,
    ) -> None:
        self.session = session
        self.candidates = list(candidates)
        self.slew_func = slew_func
        self.encoder_func = encoder_func
        self.prepare_func = prepare_func
        self.n_success_target = int(n_success_target)
        self.per_target_solve_timeout_s = float(per_target_solve_timeout_s)
        self.settle_after_slew_s = float(settle_after_slew_s)
        self.poll_interval_s = float(poll_interval_s)

        self._lock = threading.Lock()
        self._states: list[AutoCandidateState] = [
            AutoCandidateState(candidate=c) for c in self.candidates
        ]
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._phase = "idle"
        self._error: str | None = None
        self._current_idx: int | None = None

    # ---------- lifecycle ----------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("auto-run already in flight")
            self._stop_evt.clear()
            self._phase = "running"
            self._error = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"NighttimeAutoRunner({self.session.telescope_id})",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        # Don't join: caller may be on the same event loop / poll
        # thread, and the daemon will exit on its own.

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---------- snapshot ----------

    def status(self) -> AutoRunStatus:
        with self._lock:
            n_success = sum(1 for s in self._states if s.status == "ok")
            n_fail = sum(1 for s in self._states if s.status in ("fail", "skipped"))
            return AutoRunStatus(
                active=self.is_alive(),
                phase=self._phase,
                n_success=n_success,
                n_fail=n_fail,
                n_success_target=self.n_success_target,
                current_idx=self._current_idx,
                candidates=[
                    {
                        "label": s.candidate.label,
                        "az_deg": s.candidate.az_deg,
                        "el_deg": s.candidate.el_deg,
                        "vmag": s.candidate.vmag,
                        "kind": s.candidate.kind,
                        "status": s.status,
                        "error": s.error,
                        "encoder_az_deg": s.encoder_az_deg,
                        "encoder_el_deg": s.encoder_el_deg,
                    }
                    for s in self._states
                ],
                error=self._error,
            )

    # ---------- main loop ----------

    def _run(self) -> None:
        try:
            if self.prepare_func is not None:
                try:
                    self.prepare_func()
                except Exception as exc:  # noqa: BLE001
                    # Prep failure is non-fatal — the previous live-view
                    # exposure may still be usable for plate-solve. Log
                    # it for the operator but proceed.
                    _AUTO_LOG.warning(
                        "auto-calibrate: prepare_func failed (continuing): %s", exc
                    )
            for idx, state in enumerate(self._states):
                if self._stop_evt.is_set():
                    break
                if self._count_successes() >= self.n_success_target:
                    break
                with self._lock:
                    self._current_idx = idx
                    state.status = "slewing"
                    state.t_started_unix = time.time()
                cand = state.candidate
                _AUTO_LOG.info(
                    "auto-calibrate: slewing to %s (az=%.2f° el=%.2f°)",
                    cand.label,
                    cand.az_deg,
                    cand.el_deg,
                )
                try:
                    ok = self.slew_func(cand.az_deg, cand.el_deg)
                except Exception as exc:  # noqa: BLE001
                    self._mark_state(state, "fail", f"slew error: {exc}")
                    continue
                if not ok:
                    self._mark_state(state, "skipped", "slew refused")
                    continue
                # Brief settle so the optical tube damps after motors stop.
                _wait_with_stop(self._stop_evt, self.settle_after_slew_s)
                if self._stop_evt.is_set():
                    self._mark_state(state, "skipped", "cancelled")
                    break
                with self._lock:
                    state.status = "solving"
                try:
                    enc_az, enc_el = self.encoder_func()
                except Exception as exc:  # noqa: BLE001
                    self._mark_state(state, "fail", f"encoder read failed: {exc}")
                    continue
                with self._lock:
                    state.encoder_az_deg = float(enc_az)
                    state.encoder_el_deg = float(enc_el)
                # Fire the plate-solve. The session enforces the altitude
                # window; if we slewed to a candidate now obscured / drifted
                # below the floor (rare), record a clean fail and move on.
                # Snapshot the sightings count first so the post-poll check
                # can tell ok from fail by seeing whether the list grew —
                # comparing timestamps in last_failed is racy when two
                # consecutive candidates resolve within the same second.
                n_before = len(self.session.status().sightings)
                try:
                    self.session.capture_sighting(
                        image_path=None,
                        encoder_az_deg=float(enc_az),
                        encoder_el_deg=float(enc_el),
                    )
                except (ValueError, RuntimeError) as exc:
                    self._mark_state(state, "fail", f"capture rejected: {exc}")
                    continue
                outcome, reason = self._await_solve(n_before)
                if outcome == "ok":
                    self._mark_state(state, "ok", None)
                else:
                    self._mark_state(state, "fail", reason)
            with self._lock:
                if self._stop_evt.is_set():
                    self._phase = "cancelled"
                elif self._count_successes() >= self.n_success_target:
                    self._phase = "done"
                else:
                    self._phase = "failed"
                    if self._error is None:
                        self._error = (
                            f"only {self._count_successes()} successful sighting(s) "
                            f"after {len(self._states)} candidates"
                        )
                self._current_idx = None
        except Exception as exc:  # noqa: BLE001
            _AUTO_LOG.exception("auto-calibrate run crashed")
            with self._lock:
                self._phase = "failed"
                self._error = f"unexpected error: {exc}"
                self._current_idx = None

    def _await_solve(self, n_sightings_before: int) -> tuple[str, str | None]:
        """Poll ``session.status()`` until the pending solve resolves.

        Returns ``("ok", None)`` if the sightings list grew (the plate
        solve produced a new accepted record), otherwise
        ``("fail", reason)``. ``n_sightings_before`` is the snapshot
        taken right before ``capture_sighting`` was invoked; comparing
        against the current count is the only race-free way to decide
        between ok and fail since the session's ``last_failed`` field
        is sticky across candidates.
        """
        deadline = time.time() + self.per_target_solve_timeout_s
        while not self._stop_evt.is_set() and time.time() < deadline:
            st = self.session.status()
            if st.pending is None:
                if len(st.sightings) > n_sightings_before:
                    return "ok", None
                last_failed = st.last_failed
                reason = "fail"
                if last_failed is not None:
                    reason = str(
                        last_failed.get("error")
                        or last_failed.get("status")
                        or "fail"
                    )
                return "fail", reason
            time.sleep(self.poll_interval_s)
        if self._stop_evt.is_set():
            return "fail", "cancelled"
        # Timeout: discard the in-flight pending so the next cycle starts clean.
        try:
            self.session.skip_pending()
        except Exception:  # noqa: BLE001
            pass
        return "fail", "solve timed out"

    # ---------- helpers ----------

    def _count_successes(self) -> int:
        with self._lock:
            return sum(1 for s in self._states if s.status == "ok")

    def _mark_state(
        self, state: AutoCandidateState, status: str, error: str | None
    ) -> None:
        with self._lock:
            state.status = status
            state.error = error
            state.t_finished_unix = time.time()


def _wait_with_stop(stop_evt: threading.Event, total_s: float) -> None:
    """Sleep up to ``total_s`` seconds, returning early if ``stop_evt``
    fires. Avoids ``time.sleep`` blocking cancellation."""
    if total_s <= 0:
        return
    stop_evt.wait(timeout=float(total_s))


# ---------- auto-runner manager --------------------------------------


class NighttimeAutoManager:
    """Process-singleton registry mirroring
    :class:`NighttimeCalibrationManager`. One auto-runner per
    telescope; refusing concurrent runs keeps the mount under a single
    owner."""

    def __init__(self) -> None:
        self._runners: dict[int, NighttimeAutoRunner] = {}
        self._lock = threading.Lock()

    def get(self, telescope_id: int) -> NighttimeAutoRunner | None:
        with self._lock:
            return self._runners.get(int(telescope_id))

    def start(
        self, telescope_id: int, runner: NighttimeAutoRunner
    ) -> NighttimeAutoRunner:
        tid = int(telescope_id)
        with self._lock:
            existing = self._runners.get(tid)
            if existing is not None and existing.is_alive():
                raise RuntimeError(
                    f"telescope {tid} already has an auto-run in flight"
                )
            self._runners[tid] = runner
        runner.start()
        return runner

    def stop(self, telescope_id: int) -> AutoRunStatus | None:
        runner = self.get(telescope_id)
        if runner is None:
            return None
        runner.stop()
        return runner.status()

    def status(self, telescope_id: int) -> AutoRunStatus | None:
        runner = self.get(telescope_id)
        return runner.status() if runner is not None else None


_AUTO_MANAGER: NighttimeAutoManager | None = None
_AUTO_MANAGER_LOCK = threading.Lock()


def get_nighttime_auto_manager() -> NighttimeAutoManager:
    global _AUTO_MANAGER
    with _AUTO_MANAGER_LOCK:
        if _AUTO_MANAGER is None:
            _AUTO_MANAGER = NighttimeAutoManager()
        return _AUTO_MANAGER


# Silence unused-import warnings.
_ = (math, SolveResult)
