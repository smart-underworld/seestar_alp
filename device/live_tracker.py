"""Live tracker session manager.

Wraps `streaming_controller.track()` in a background thread with mutable,
thread-safe offset knobs so a browser UI can start/stop a track and nudge
the reference mid-run without restarting the loop.

Scope:
- `AtomicOffsets`: bounded, lock-protected offset store, consumed each
  tick by `track()` via its `offset_provider` hook.
- `LiveTrackSession`: one active track per telescope; owns its logger,
  stop event, thread, and latest `TickInfo`.
- `LiveTrackManager`: module-level registry keyed by telescope id.
- `TargetCatalog`: cached-file listing + provider factory (v1). Live
  ADS-B polling and `LiveADSBProvider` land in a follow-up.
- `load_session_mount_frame()`: read device/mount_calibration.json once
  per session start, fall back to identity. This is the hook a future
  per-session calibration step will write to.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import requests
from astropy.coordinates import EarthLocation

from device.alpaca_client import AlpacaClient
from device.config import Config
from device.plant_limits import AzimuthLimits, CumulativeAzTracker
from device.reference_provider import (
    DEFAULT_EXTRAPOLATION_S,
    JsonlECEFProvider,
    ReferenceProvider,
    ReferenceSample,
)
from device.streaming_controller import (
    OffsetSnapshot,
    TickInfo,
    track,
)
from device.target_frame import MountFrame
from device.velocity_controller import (
    PositionLogger,
    ensure_scenery_mode,
    measure_altaz_timed,
    move_to_ff,
)
from scripts.trajectory.fetch_aircraft import (
    MAX_ALT_M,
    RawSample,
    extract_sample_adsbfi,
    poll_once_adsbfi,
)
from scripts.trajectory.observer import (
    ObserverSite,
    build_site,
    ecef_array_to_topo,
    lla_to_ecef,
)


# ---------- bounds ----------------------------------------------------

AZ_BIAS_BOUND_DEG = 5.0
EL_BIAS_BOUND_DEG = 5.0
ALONG_BOUND_DEG = 5.0
CROSS_BOUND_DEG = 5.0
TIME_OFFSET_BOUND_S = 30.0


def _clamp(x: float, lo: float, hi: float) -> float:
    # NaN compares false against every bound, so a naive min/max lets it
    # slip through into the snapshot and then into the streaming loop,
    # where it poisons the mount command. Reject explicitly so the
    # endpoint handler can surface a 400 to the caller.
    if math.isnan(x):
        raise ValueError("offset value must be a finite number")
    return lo if x < lo else (hi if x > hi else x)


# ---------- AtomicOffsets --------------------------------------------


@dataclass
class AtomicOffsets:
    """Thread-safe, bounded offset store.

    `get()` returns an immutable `OffsetSnapshot` under a lock so the
    streaming loop always sees a consistent set of fields per tick.
    `set(**kwargs)` accepts any subset of fields, clamps each to its bound,
    and returns the updated snapshot.
    """

    _snapshot: OffsetSnapshot = field(default_factory=OffsetSnapshot)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self) -> OffsetSnapshot:
        with self._lock:
            return self._snapshot

    def set(self, **kwargs) -> OffsetSnapshot:
        with self._lock:
            patch: dict[str, float] = {}
            if "time_offset_s" in kwargs:
                patch["time_offset_s"] = _clamp(
                    float(kwargs["time_offset_s"]),
                    -TIME_OFFSET_BOUND_S, TIME_OFFSET_BOUND_S,
                )
            if "az_bias_deg" in kwargs:
                patch["az_bias_deg"] = _clamp(
                    float(kwargs["az_bias_deg"]),
                    -AZ_BIAS_BOUND_DEG, AZ_BIAS_BOUND_DEG,
                )
            if "el_bias_deg" in kwargs:
                patch["el_bias_deg"] = _clamp(
                    float(kwargs["el_bias_deg"]),
                    -EL_BIAS_BOUND_DEG, EL_BIAS_BOUND_DEG,
                )
            if "along_deg" in kwargs:
                patch["along_deg"] = _clamp(
                    float(kwargs["along_deg"]),
                    -ALONG_BOUND_DEG, ALONG_BOUND_DEG,
                )
            if "cross_deg" in kwargs:
                patch["cross_deg"] = _clamp(
                    float(kwargs["cross_deg"]),
                    -CROSS_BOUND_DEG, CROSS_BOUND_DEG,
                )
            self._snapshot = replace(self._snapshot, **patch)
            return self._snapshot

    def reset_azel(self) -> OffsetSnapshot:
        with self._lock:
            self._snapshot = replace(self._snapshot, az_bias_deg=0.0, el_bias_deg=0.0)
            return self._snapshot

    def reset_alongcross(self) -> OffsetSnapshot:
        with self._lock:
            self._snapshot = replace(self._snapshot, along_deg=0.0, cross_deg=0.0)
            return self._snapshot

    def reset_all(self) -> OffsetSnapshot:
        with self._lock:
            self._snapshot = OffsetSnapshot()
            return self._snapshot


# ---------- calibration loader ---------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CAL_PATH = _REPO_ROOT / "device" / "mount_calibration.json"


def load_session_mount_frame() -> MountFrame:
    """Read device/mount_calibration.json and build a MountFrame.

    Falls back to an identity frame (rotation=I, translation=0) if the
    file is missing or unreadable. Called once per session start — the
    per-session calibration step writes a new JSON and the next track
    picks it up.

    Passes ``site=None`` to `from_calibration_json` so an ``observer``
    block embedded in the calibration (written by
    `calibrate_rotation.py`) wins over the env-var default. When no
    observer is embedded, the method falls back to env-var ``build_site()``
    internally.
    """
    if _CAL_PATH.exists():
        try:
            return MountFrame.from_calibration_json(_CAL_PATH)
        except Exception:
            pass
    return MountFrame.from_identity_enu()


# ---------- TargetCatalog --------------------------------------------


@dataclass
class CachedTarget:
    path: Path
    id: str               # stem of the file, used as the UI id
    display_name: str
    kind: str             # "aircraft" or "satellite" (derived from subdir)
    source: str           # header "source" field if present
    duration_s: float
    peak_el_deg: float
    min_slant_m: float
    n_samples: int


_DEFAULT_TRAJ_DIR = _REPO_ROOT / "data" / "trajectories"


# ---------- LiveADSBProvider -----------------------------------------


@dataclass
class _LiveSample:
    t_unix: float
    ecef: tuple[float, float, float]


class _LiveBuffer:
    """Per-aircraft rolling buffer of ECEF samples keyed by icao24.

    Thread-safe: the catalog's poller appends from the background thread
    while `LiveADSBProvider` reads under the same lock to build its
    spline snapshot.
    """

    def __init__(self, icao24: str, callsign: str, maxlen: int = 1200):
        self.icao24 = icao24
        self.callsign = callsign
        self._samples: deque[_LiveSample] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._gen = 0  # monotonically bumped on each append
        self.last_sample_t: float = 0.0
        # Latest instantaneous geometry (topocentric, from the most recent
        # poll). Used by list_live() for UI ranking and display; not by the
        # spline-based LiveADSBProvider.
        self.current_az_deg: float = 0.0
        self.current_el_deg: float = -90.0
        self.current_slant_m: float = 0.0
        self.current_heading_deg: float = 0.0
        self.current_alt_m: float = 0.0
        self.current_velocity_mps: float = 0.0
        self.current_az_rate_degs: float = 0.0
        self.current_el_rate_degs: float = 0.0
        # Previous sample's topocentric az/el (for finite-diff rates).
        self._prev_topo_t: float = 0.0
        self._prev_az_deg: float = 0.0
        self._prev_el_deg: float = 0.0

    def append(self, t_unix: float, ecef_xyz: tuple[float, float, float]) -> None:
        with self._lock:
            if self._samples and self._samples[-1].t_unix == t_unix:
                return
            self._samples.append(_LiveSample(t_unix=t_unix, ecef=ecef_xyz))
            self._gen += 1
            self.last_sample_t = t_unix

    def snapshot(self) -> tuple[int, np.ndarray, np.ndarray]:
        with self._lock:
            gen = self._gen
            n = len(self._samples)
            t = np.empty(n, dtype=float)
            ecef = np.empty((n, 3), dtype=float)
            for i, s in enumerate(self._samples):
                t[i] = s.t_unix
                ecef[i] = s.ecef
            return gen, t, ecef

    def __len__(self) -> int:
        with self._lock:
            return len(self._samples)


class LiveADSBProvider:
    """ReferenceProvider over a live-updating `_LiveBuffer`.

    Uses **linear interpolation** on mount-frame az/el between ADS-B
    samples (with 3-sample smoothing on velocity), and **constant-velocity
    extrapolation** past the tail using the spline-derived velocity at the
    last sample. Rebuilds on a gated cadence as the buffer grows.

    Why not JsonlECEFProvider's cubic spline? Sparse live samples (~2–5 s
    apart while aircraft move 1–3°/s) plus cubic boundary derivatives
    cause ~10° jumps at each rebuild — the reference trajectory looked
    smooth interpolating, but rebuild shifted the spline's tail
    derivative every time a new sample landed. Linear + tail-velocity
    extrapolation has no derivative-of-derivative to swing around, so
    rebuilds produce sub-degree discontinuities even at low sample rates.
    """

    def __init__(
        self,
        buffer: _LiveBuffer,
        mount_frame: MountFrame,
        rebuild_s: float = 2.0,
        extrapolation_s: float = DEFAULT_EXTRAPOLATION_S,
    ) -> None:
        self._buffer = buffer
        self._mount_frame = mount_frame
        self._rebuild_s = float(rebuild_s)
        # Stored as a plain instance attribute (not a property) so the
        # controller's `provider.__dict__.get("extrapolation_s", ...)` lookup
        # in streaming_controller.track() finds it.
        self.extrapolation_s = float(extrapolation_s)
        self._gen: int = -1
        self._last_build_t: float = 0.0
        self._rebuild_lock = threading.Lock()
        # Interpolation tables; populated by _rebuild().
        self._t_arr: np.ndarray = np.zeros(0)
        self._az_cum: np.ndarray = np.zeros(0)
        self._el: np.ndarray = np.zeros(0)
        self._v_az: np.ndarray = np.zeros(0)
        self._v_el: np.ndarray = np.zeros(0)
        self._a_az: np.ndarray = np.zeros(0)
        self._a_el: np.ndarray = np.zeros(0)
        self._rebuild()

    def _rebuild(self) -> None:
        gen, t, ecef = self._buffer.snapshot()
        if gen == self._gen and self._t_arr.size:
            return
        if len(t) < 2:
            return
        try:
            traj = self._mount_frame.ecef_traj_to_mount(
                ecef, t,
            ) if len(t) >= 4 else None
        except Exception:
            traj = None
        if traj is not None:
            # Use the smoothed per-sample rates from target_frame (central
            # differences + 3-sample box filter — matches replay.py).
            self._t_arr = np.asarray(traj["t_unix"], dtype=float)
            self._az_cum = np.asarray(traj["az_cum_deg"], dtype=float)
            self._el = np.asarray(traj["el_deg"], dtype=float)
            self._v_az = np.asarray(traj["v_az_degs"], dtype=float)
            self._v_el = np.asarray(traj["v_el_degs"], dtype=float)
            self._a_az = np.asarray(traj["a_az_degs2"], dtype=float)
            self._a_el = np.asarray(traj["a_el_degs2"], dtype=float)
        else:
            # Too few samples for rate smoothing; still build a usable
            # linear-interp table with forward-diff velocities.
            az, el, _slant = self._mount_frame.ecef_array_to_mount(ecef)
            from scripts.trajectory.observer import unwrap_az_series
            az_cum = unwrap_az_series(az)
            self._t_arr = np.asarray(t, dtype=float)
            self._az_cum = az_cum
            self._el = el
            n = len(t)
            v_az = np.zeros(n)
            v_el = np.zeros(n)
            if n >= 2:
                v_az[:-1] = np.diff(az_cum) / np.diff(t)
                v_el[:-1] = np.diff(el) / np.diff(t)
                v_az[-1] = v_az[-2]
                v_el[-1] = v_el[-2]
            self._v_az = v_az
            self._v_el = v_el
            self._a_az = np.zeros(n)
            self._a_el = np.zeros(n)
        self._gen = gen
        self._last_build_t = time.time()

    def _ensure_inner(self) -> None:
        with self._rebuild_lock:
            if (
                self._t_arr.size == 0
                or (time.time() - self._last_build_t) >= self._rebuild_s
            ):
                self._rebuild()

    def valid_range(self) -> tuple[float, float]:
        self._ensure_inner()
        if self._t_arr.size == 0:
            now = time.time()
            return (now, now)
        return (float(self._t_arr[0]), float(self._t_arr[-1]))

    def sample(self, t_unix: float) -> ReferenceSample:
        self._ensure_inner()
        if self._t_arr.size < 2:
            return ReferenceSample(
                t_unix=float(t_unix), az_cum_deg=0.0, el_deg=45.0,
                v_az_degs=0.0, v_el_degs=0.0,
                a_az_degs2=0.0, a_el_degs2=0.0,
                stale=True, extrapolated=True,
            )

        t = float(t_unix)
        t_arr = self._t_arr
        t_head, t_tail = float(t_arr[0]), float(t_arr[-1])

        if t < t_head:
            # Before the buffer — extrapolate backward at head velocity.
            dt = t - t_head
            return ReferenceSample(
                t_unix=t,
                az_cum_deg=float(self._az_cum[0] + self._v_az[0] * dt),
                el_deg=float(self._el[0] + self._v_el[0] * dt),
                v_az_degs=float(self._v_az[0]),
                v_el_degs=float(self._v_el[0]),
                a_az_degs2=float(self._a_az[0]),
                a_el_degs2=float(self._a_el[0]),
                stale=(abs(dt) > self.extrapolation_s),
                extrapolated=True,
            )

        if t <= t_tail:
            # Linear interpolation between samples; carry rates from the
            # smoothed per-sample arrays without additional derivative
            # estimation (avoids the cubic-spline boundary artefacts).
            az = float(np.interp(t, t_arr, self._az_cum))
            el = float(np.interp(t, t_arr, self._el))
            v_az = float(np.interp(t, t_arr, self._v_az))
            v_el = float(np.interp(t, t_arr, self._v_el))
            a_az = float(np.interp(t, t_arr, self._a_az))
            a_el = float(np.interp(t, t_arr, self._a_el))
            return ReferenceSample(
                t_unix=t, az_cum_deg=az, el_deg=el,
                v_az_degs=v_az, v_el_degs=v_el,
                a_az_degs2=a_az, a_el_degs2=a_el,
                stale=False, extrapolated=False,
            )

        # Past the tail — constant-velocity extrapolation.
        dt = t - t_tail
        v_az_t = float(self._v_az[-1])
        v_el_t = float(self._v_el[-1])
        return ReferenceSample(
            t_unix=t,
            az_cum_deg=float(self._az_cum[-1] + v_az_t * dt),
            el_deg=float(self._el[-1] + v_el_t * dt),
            v_az_degs=v_az_t,
            v_el_degs=v_el_t,
            a_az_degs2=float(self._a_az[-1]),
            a_el_degs2=float(self._a_el[-1]),
            stale=(dt > self.extrapolation_s),
            extrapolated=True,
        )


class TargetCatalog:
    """Enumerate trajectory targets available to the live tracker.

    - Pre-recorded JSONL files under `data/trajectories/` (cached).
    - Live adsb.fi feed polled in a background daemon thread; each
      aircraft's samples accumulate in a `_LiveBuffer`. `make_provider("live", ...)`
      wraps one in a `LiveADSBProvider`.
    """

    LIVE_POLL_INTERVAL_S = 5.0
    LIVE_MIN_SAMPLES = 4
    LIVE_BUFFER_TTL_S = 300.0
    # Stop polling adsb.fi if `list_live()` hasn't been called for this
    # long — the UI is not watching, so no point hammering the upstream.
    # `list_live()` auto-restarts the poller on the next call.
    LIVE_IDLE_TIMEOUT_S = 600.0
    # Keep aircraft from wheels-up onward (loaded heavy climbs ~6 m/s; at
    # 10 m we catch the rotation within ~2 s of liftoff). The
    # `extract_sample_adsbfi` layer above already drops adsb.fi's "ground"
    # surface-position messages, so we don't need to re-filter taxiing aircraft.
    LIVE_MIN_ALT_M = 10.0
    # Live-provider extrapolation budget. Tail is always at least one poll
    # interval stale, so needs to cover at least that plus controller latency
    # + a safety margin. 30 s works for aircraft at adsb.fi cadence: heading
    # is near-constant over that window so linear extrapolation is accurate.
    LIVE_EXTRAPOLATION_S = 30.0
    LIVE_REBUILD_S = 2.0

    def __init__(
        self, trajectory_root: Path | None = None,
        *, live_enabled: bool = True,
        session: requests.Session | None = None,
    ) -> None:
        self.root = Path(trajectory_root) if trajectory_root else _DEFAULT_TRAJ_DIR
        self._live_enabled = bool(live_enabled)
        self._session = session or requests.Session()
        self._site: ObserverSite | None = None
        self._live_buffers: dict[str, _LiveBuffer] = {}
        self._live_lock = threading.Lock()
        self._live_thread: threading.Thread | None = None
        self._live_stop = threading.Event()
        # Deferred start: the adsb.fi poller does not run until the
        # first `list_live()` call. This keeps the catalog cheap to
        # instantiate at startup (see `device/live_tracker_service.py`).
        # After that, the loop shuts itself down if `list_live()`
        # hasn't been called for `LIVE_IDLE_TIMEOUT_S`.
        self._last_access_t: float = 0.0

    # ---------- cached files ----------

    def list_cached(self) -> list[CachedTarget]:
        if not self.root.exists():
            return []
        out: list[CachedTarget] = []
        for sub in sorted(self.root.iterdir()):
            if not sub.is_dir():
                continue
            kind = sub.name.rstrip("s")  # "aircraft" or "satellite"
            for p in sorted(sub.glob("*.jsonl")):
                meta = _read_header(p)
                if meta is None:
                    continue
                out.append(CachedTarget(
                    path=p,
                    id=p.stem,
                    display_name=(
                        meta.get("name")
                        or meta.get("callsign")
                        or meta.get("id")
                        or p.stem
                    ),
                    kind=kind,
                    source=str(meta.get("source", "")),
                    duration_s=float(meta.get("duration_s", 0.0)),
                    peak_el_deg=float(meta.get("peak_el_deg", 0.0)),
                    min_slant_m=float(meta.get("min_slant_m", 0.0)),
                    n_samples=int(meta.get("n_samples", 0)),
                ))
        return out

    # ---------- live ADS-B ----------

    def _start_live_poller(self) -> None:
        self._live_stop.clear()
        self._live_thread = threading.Thread(
            target=self._live_loop,
            name="TargetCatalog.adsbfi",
            daemon=True,
        )
        self._live_thread.start()

    def _ensure_poller_running(self) -> None:
        """Spin the adsb.fi poller up if it is not already running.

        Called from `list_live()` — the UI hit is the signal that the
        user wants live targets. Idempotent and cheap when the thread
        is alive.
        """
        if not self._live_enabled:
            return
        with self._live_lock:
            alive = self._live_thread is not None and self._live_thread.is_alive()
        if not alive:
            self._start_live_poller()

    def close(self) -> None:
        self._live_stop.set()

    def _site_lazy(self) -> ObserverSite:
        if self._site is None:
            self._site = build_site()
        return self._site

    def _live_loop(self) -> None:
        backoff_s = 0.0
        while not self._live_stop.is_set():
            # Idle shutdown: if the UI hasn't asked for live targets in
            # a while, stop polling to be kind to adsb.fi. The next
            # `list_live()` call will restart us.
            if (
                self._last_access_t > 0.0
                and (time.time() - self._last_access_t) > self.LIVE_IDLE_TIMEOUT_S
            ):
                break
            t0 = time.time()
            ok = False
            try:
                ok = self._poll_once()
            except Exception:
                pass
            if ok:
                backoff_s = 0.0
            else:
                # Exponential backoff on failures (adsb.fi returns 429
                # when polled too aggressively). Caps at 60 s.
                backoff_s = min(60.0, max(backoff_s * 2, self.LIVE_POLL_INTERVAL_S))
            self._prune_stale_buffers()
            wait = max(self.LIVE_POLL_INTERVAL_S, backoff_s) - (time.time() - t0)
            if wait > 0:
                self._live_stop.wait(timeout=wait)

    def _poll_once(self) -> bool:
        """Returns True if data was received, False on failure (for backoff)."""
        site = self._site_lazy()
        # 100 km ≈ 54 nm radius around the observer. adsb.fi's endpoint
        # takes a radius in nautical miles, not km.
        ac_list = poll_once_adsbfi(
            self._session, site.lat_deg, site.lon_deg, dist_nm=54.0,
        )
        if not ac_list:
            return False
        t_now = time.time()
        for ac in ac_list:
            parsed = extract_sample_adsbfi(ac)
            if parsed is None:
                # extract_sample_adsbfi drops ground aircraft (alt_baro
                # == "ground"). For live tracking we want to see them so
                # we can watch for departures. Fall back to a manual
                # extraction with alt_m = field elevation (~30 m for LAX).
                parsed = self._extract_ground_aircraft(ac, t_now)
            if parsed is None:
                continue
            icao24, callsign, s = parsed
            if s.alt_m > MAX_ALT_M:
                continue
            ecef = tuple(float(x) for x in lla_to_ecef(s.lat, s.lon, s.alt_m))
            with self._live_lock:
                buf = self._live_buffers.get(icao24)
                if buf is None:
                    buf = _LiveBuffer(icao24=icao24, callsign=callsign)
                    self._live_buffers[icao24] = buf
                elif callsign and not buf.callsign:
                    buf.callsign = callsign
            buf.append(t_now, ecef)
            # Cache instantaneous geometry for ranking + UI display.
            try:
                arr = np.asarray([ecef], dtype=float)
                az, el, slant = ecef_array_to_topo(arr, site)
                new_az = float(az[0])
                new_el = float(el[0])
                # Finite-diff az/el rates against the previous poll.
                if buf._prev_topo_t > 0:
                    dt = t_now - buf._prev_topo_t
                    if dt > 0:
                        # Unwrap azimuth delta through the ±180° boundary.
                        d_az = ((new_az - buf._prev_az_deg + 540.0) % 360.0) - 180.0
                        d_el = new_el - buf._prev_el_deg
                        buf.current_az_rate_degs = d_az / dt
                        buf.current_el_rate_degs = d_el / dt
                buf._prev_topo_t = t_now
                buf._prev_az_deg = new_az
                buf._prev_el_deg = new_el
                buf.current_az_deg = new_az
                buf.current_el_deg = new_el
                buf.current_slant_m = float(slant[0])
                buf.current_alt_m = float(s.alt_m)
                if s.velocity_mps is not None:
                    buf.current_velocity_mps = float(s.velocity_mps)
                if s.heading_deg is not None:
                    buf.current_heading_deg = float(s.heading_deg)
            except Exception:
                pass

    @staticmethod
    def _extract_ground_aircraft(
        ac: dict, t_now: float,
    ) -> tuple[str, str, RawSample] | None:
        """Parse an adsb.fi dict for a ground aircraft that
        `extract_sample_adsbfi` would have dropped (alt_baro == "ground").
        Uses field elevation (~30 m for LAX area) as the altitude."""
        icao24 = ac.get("hex")
        if not icao24:
            return None
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            return None
        alt_geom = ac.get("alt_geom")
        if alt_geom is not None and alt_geom != "ground":
            try:
                alt_m = float(alt_geom) * 0.3048
            except (TypeError, ValueError):
                alt_m = 30.0
        else:
            alt_m = 30.0
        callsign = (ac.get("flight") or "").strip()
        gs_kts = ac.get("gs")
        velocity_mps = float(gs_kts) * 0.514444 if gs_kts is not None else 0.0
        heading = ac.get("track")
        heading_deg = float(heading) if heading is not None else None
        return icao24, callsign, RawSample(
            t_unix=t_now, lat=float(lat), lon=float(lon), alt_m=alt_m,
            velocity_mps=velocity_mps, heading_deg=heading_deg,
            vertical_rate_mps=0.0,
        )

    def _prune_stale_buffers(self) -> None:
        cutoff = time.time() - self.LIVE_BUFFER_TTL_S
        with self._live_lock:
            for k in list(self._live_buffers.keys()):
                if self._live_buffers[k].last_sample_t < cutoff:
                    del self._live_buffers[k]

    def list_live(self) -> list[dict]:
        # Touch first: mark the UI as interested, so the idle-shutdown
        # branch in `_live_loop` won't hit right after we spin up.
        self._last_access_t = time.time()
        self._ensure_poller_running()
        with self._live_lock:
            bufs = list(self._live_buffers.values())
        bufs = [b for b in bufs if len(b) >= self.LIVE_MIN_SAMPLES]
        # Rank by current elevation (higher first).
        bufs.sort(key=lambda b: b.current_el_deg, reverse=True)
        return [
            {
                "id": b.icao24,
                "icao24": b.icao24,
                "display_name": (b.callsign or b.icao24).strip() or b.icao24,
                "current_az_deg": float(b.current_az_deg),
                "current_el_deg": float(b.current_el_deg),
                "current_slant_m": float(b.current_slant_m),
                "current_heading_deg": float(b.current_heading_deg),
                "current_alt_m": float(b.current_alt_m),
                "current_velocity_mps": float(b.current_velocity_mps),
                "current_az_rate_degs": float(b.current_az_rate_degs),
                "current_el_rate_degs": float(b.current_el_rate_degs),
                "n_samples": len(b),
                "age_s": float(time.time() - b.last_sample_t),
            }
            for b in bufs
        ]

    def make_provider(
        self, kind: str, target_id: str, mount_frame: MountFrame,
    ) -> ReferenceProvider:
        """Build a provider for a target identified by UI (kind, id)."""
        if kind == "file":
            for t in self.list_cached():
                if t.id == target_id:
                    return JsonlECEFProvider(t.path, mount_frame)
            raise KeyError(f"cached target not found: {target_id}")
        if kind == "live":
            with self._live_lock:
                buf = self._live_buffers.get(target_id)
            if buf is None:
                raise KeyError(f"live target not found: {target_id}")
            if len(buf) < self.LIVE_MIN_SAMPLES:
                raise ValueError(
                    f"live target {target_id} has only {len(buf)} sample(s); "
                    f"need ≥ {self.LIVE_MIN_SAMPLES}"
                )
            return LiveADSBProvider(
                buf, mount_frame,
                rebuild_s=self.LIVE_REBUILD_S,
                extrapolation_s=self.LIVE_EXTRAPOLATION_S,
            )
        raise ValueError(f"unknown target kind: {kind}")


def _read_header(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            first = f.readline().strip()
            if not first:
                return None
            rec = json.loads(first)
            if rec.get("kind") != "header":
                return None
            return rec
    except Exception:
        return None


# ---------- LiveTrackSession -----------------------------------------


@dataclass
class SessionStatus:
    active: bool
    target_kind: str | None
    target_id: str | None
    target_display_name: str | None
    phase: str
    elapsed_s: float
    exit_reason: str | None
    # Derived from last tick.
    heading_deg: float | None
    heading_locked: bool
    d_az_deg: float
    d_el_deg: float
    eff_ref_az_cum_deg: float | None
    eff_ref_el_deg: float | None
    cur_cum_az_deg: float | None
    cur_el_deg: float | None
    err_az_deg: float | None
    err_el_deg: float | None
    tick: int
    errors: list[str] = field(default_factory=list)


_LOG_DIR = _REPO_ROOT / "auto_level_logs"


class LiveTrackSession:
    """One live tracking run for a telescope.

    Spawns a daemon thread that calls `streaming_controller.track()`
    with this session's offsets + a tick callback. `status()` reflects
    the most recent tick under a short lock.
    """

    def __init__(
        self,
        telescope_id: int,
        target_kind: str,
        target_id: str,
        target_display_name: str,
        provider: ReferenceProvider,
        offsets: AtomicOffsets,
        *,
        dry_run: bool = False,
        alpaca_host: str = "127.0.0.1",
        alpaca_port: int | None = None,
        log_dir: Path | None = None,
        az_limits: AzimuthLimits | None = None,
        auto_slew: bool = True,
    ) -> None:
        self.telescope_id = int(telescope_id)
        self.target_kind = target_kind
        self.target_id = target_id
        self.target_display_name = target_display_name
        self._provider = provider
        self.offsets = offsets
        self.dry_run = bool(dry_run)
        self._alpaca_host = alpaca_host
        self._alpaca_port = (
            int(alpaca_port) if alpaca_port is not None else int(Config.port)
        )
        self._log_dir = Path(log_dir) if log_dir else _LOG_DIR
        self._az_limits = az_limits
        self._auto_slew_enabled = bool(auto_slew)

        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._t_start = 0.0
        self._last_tick: TickInfo | None = None
        self._phase = "init"
        self._exit_reason: str | None = None
        self._errors: list[str] = []
        self._log_path: Path | None = None
        self._position_logger: PositionLogger | None = None

    # ---------- public ----------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("session already running")
        self._stop_evt.clear()
        self._t_start = time.time()
        self._phase = "starting"
        self._thread = threading.Thread(
            target=self._run, name=f"LiveTrackSession({self.telescope_id})",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> SessionStatus:
        with self._lock:
            tick = self._last_tick
            elapsed = (time.time() - self._t_start) if self._t_start else 0.0
            if tick is None:
                return SessionStatus(
                    active=self.is_alive(),
                    target_kind=self.target_kind,
                    target_id=self.target_id,
                    target_display_name=self.target_display_name,
                    phase=self._phase,
                    elapsed_s=elapsed,
                    exit_reason=self._exit_reason,
                    heading_deg=None,
                    heading_locked=True,
                    d_az_deg=0.0,
                    d_el_deg=0.0,
                    eff_ref_az_cum_deg=None,
                    eff_ref_el_deg=None,
                    cur_cum_az_deg=None,
                    cur_el_deg=None,
                    err_az_deg=None,
                    err_el_deg=None,
                    tick=0,
                    errors=list(self._errors),
                )
            return SessionStatus(
                active=self.is_alive(),
                target_kind=self.target_kind,
                target_id=self.target_id,
                target_display_name=self.target_display_name,
                phase=self._phase,
                elapsed_s=elapsed,
                exit_reason=self._exit_reason,
                heading_deg=None if tick.heading_locked else tick.heading_deg,
                heading_locked=tick.heading_locked,
                d_az_deg=tick.d_az_deg,
                d_el_deg=tick.d_el_deg,
                eff_ref_az_cum_deg=tick.eff_ref_az_cum_deg,
                eff_ref_el_deg=tick.eff_ref_el_deg,
                cur_cum_az_deg=tick.cur_cum_az_deg,
                cur_el_deg=tick.cur_el_deg,
                err_az_deg=tick.err_az_deg,
                err_el_deg=tick.err_el_deg,
                tick=tick.tick,
                errors=list(self._errors),
            )

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    # ---------- thread body ----------

    def _on_tick(self, info: TickInfo) -> None:
        with self._lock:
            self._last_tick = info
            self._phase = "track"

    def _stop_requested_during_preslew(self) -> bool:
        """Return True and record stop state if stop was requested.

        Called at each substep boundary inside `_auto_slew` to bail out
        before committing to the next `move_to_ff`. The `_run` loop also
        rechecks after `_auto_slew` returns, so setting the exit reason
        here is belt-and-suspenders — harmless if set twice.
        """
        if not self._stop_evt.is_set():
            return False
        with self._lock:
            if self._exit_reason is None:
                self._exit_reason = "stop_signal"
            self._phase = "stopped"
        return True

    def _auto_slew(self, cli, loc) -> None:
        """Point the mount at the target's current sky position before
        engaging the streaming loop. Two steps:

        1. If the mount is below el=-30° (stowed/near-floor), raise to
           el=-30° first at the current encoder az. Seestar's goto path
           silently refuses to drive the mount from the el=-90° mechanical
           limit; un-stowing with a direct velocity move bypasses that.

        2. Slew to the plane's current mount-frame (az, el). Same
           pattern as scripts/auto_level.py — `move_to_ff` uses raw
           encoder feedback via scope_get_horiz_coord / speed_move, so no
           plate-solve alignment is required. The provider's `az_cum_deg`
           comes from the session's MountFrame (identity ENU for
           uncalibrated; full SE(3) when calibration.json is loaded), so
           the target az is a mount-encoder target.

        Scenery view mode is entered first so the imager can display the
        live camera while the loop runs. Failures are logged to
        `self._errors` but the streaming loop still runs from wherever
        the mount ended up.

        Stop preemption: `self._stop_evt` is checked at each substep
        boundary. A running `move_to_ff` call cannot itself be
        interrupted (no `stop_signal` parameter), so worst-case latency
        is one in-flight move (~10 s on a big unstow) rather than the
        full pre-slew duration.
        """
        with self._lock:
            self._phase = "pre_slew"

        if self._stop_requested_during_preslew():
            return

        # --- 0. Enter scenery mode so the camera is live the whole time.
        try:
            ensure_scenery_mode(cli)
        except Exception as exc:
            with self._lock:
                self._errors.append(f"ensure_scenery_mode failed: {exc}")

        if self._stop_requested_during_preslew():
            return

        # --- 1. Measure current mount position.
        try:
            cur_el, cur_az_wrapped, _ = measure_altaz_timed(cli, loc)
        except Exception as exc:
            with self._lock:
                self._errors.append(f"pre-slew measure_altaz failed: {exc}")
            return

        # --- 2. Unstow if below -30° elevation (scenery mode cannot reliably
        #       command gotos from the -90° mechanical floor).
        if cur_el < -30.0:
            with self._lock:
                self._phase = "unstow"
            if self._stop_requested_during_preslew():
                return
            if self._position_logger is not None:
                try:
                    self._position_logger.mark_event(
                        "unstow_start",
                        cur_az_deg=cur_az_wrapped,
                        cur_el_deg=cur_el,
                        target_el_deg=-30.0,
                    )
                except Exception:
                    pass
            try:
                new_el, new_az, _stats = move_to_ff(
                    cli,
                    target_az_deg=cur_az_wrapped,
                    target_el_deg=-30.0,
                    cur_az_deg=cur_az_wrapped,
                    cur_el_deg=cur_el,
                    loc=loc,
                    tag="[unstow]",
                    position_logger=self._position_logger,
                    el_min_deg=-85.0,
                    el_max_deg=85.0,
                    arrive_tolerance_deg=1.0,
                )
                cur_el, cur_az_wrapped = new_el, new_az
            except Exception as exc:
                with self._lock:
                    self._errors.append(f"unstow failed: {exc}")
                return
            if self._position_logger is not None:
                try:
                    self._position_logger.mark_event(
                        "unstow_done",
                        cur_az_deg=cur_az_wrapped,
                        cur_el_deg=cur_el,
                    )
                except Exception:
                    pass

        # --- 3. Sample the provider ahead of the expected slew duration,
        #       then move the mount to that (az, el) via move_to_ff.
        with self._lock:
            self._phase = "pre_slew"
        if self._stop_requested_during_preslew():
            return
        try:
            first = self._provider.sample(time.time() + 5.0)
        except Exception as exc:
            with self._lock:
                self._errors.append(f"pre-slew sample failed: {exc}")
            return

        target_az_wrapped = ((first.az_cum_deg + 180.0) % 360.0) - 180.0
        target_el = max(-30.0, min(85.0, first.el_deg))

        # Pre-flight sun-avoidance check. Uses the target mount-frame
        # (az, el) as an approximation of sky (az, el) — accurate after
        # rotation calibration, conservative otherwise since we refuse
        # a wider neighborhood than strictly needed.
        from device.sun_safety import is_sun_safe as _is_sun_safe
        sun_safe, sun_reason = _is_sun_safe(
            target_az_wrapped % 360.0, float(target_el),
        )
        if not sun_safe:
            with self._lock:
                self._errors.append(sun_reason)
                self._exit_reason = "sun_avoidance"
                self._phase = "refused"
            if self._position_logger is not None:
                try:
                    self._position_logger.mark_event(
                        "pre_slew_refused_sun",
                        target_az_deg=target_az_wrapped,
                        target_el_deg=target_el,
                        reason=sun_reason,
                    )
                except Exception:
                    pass
            return

        if self._position_logger is not None:
            try:
                self._position_logger.mark_event(
                    "pre_slew_issued",
                    target_az_deg=target_az_wrapped,
                    target_el_deg=target_el,
                    cur_az_deg=cur_az_wrapped,
                    cur_el_deg=cur_el,
                )
            except Exception:
                pass
        if self._stop_requested_during_preslew():
            return
        try:
            new_el, new_az, stats = move_to_ff(
                cli,
                target_az_deg=target_az_wrapped,
                target_el_deg=target_el,
                cur_az_deg=cur_az_wrapped,
                cur_el_deg=cur_el,
                loc=loc,
                tag="[pre_slew]",
                position_logger=self._position_logger,
                el_min_deg=-30.0,
                el_max_deg=85.0,
                arrive_tolerance_deg=0.8,
            )
        except Exception as exc:
            with self._lock:
                self._errors.append(f"pre-slew move_to_ff failed: {exc}")
            return
        if self._position_logger is not None:
            try:
                self._position_logger.mark_event(
                    "pre_slew_done",
                    new_az_deg=new_az,
                    new_el_deg=new_el,
                    converged=stats.get("converged"),
                )
            except Exception:
                pass
        if not stats.get("converged"):
            with self._lock:
                self._errors.append(
                    f"pre-slew did not converge (final az={new_az:+.2f}° "
                    f"el={new_el:+.2f}°)"
                )

    def _run(self) -> None:
        cli = AlpacaClient(self._alpaca_host, self._alpaca_port, self.telescope_id)
        site = build_site()
        loc = EarthLocation.from_geodetic(
            lon=site.lon_deg, lat=site.lat_deg, height=site.alt_m,
        )
        self._log_dir.mkdir(parents=True, exist_ok=True)
        run_tag = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())
        self._log_path = (
            self._log_dir
            / f"{run_tag}.live_tracker-{self.target_id}.jsonl"
        )
        try:
            self._position_logger = PositionLogger(cli, loc, self._log_path)
            self._position_logger.start()
            self._position_logger.set_phase("live_track_init")
            self._position_logger.mark_event(
                "live_track_start",
                target_kind=self.target_kind,
                target_id=self.target_id,
                target_display_name=self.target_display_name,
                dry_run=self.dry_run,
            )
        except Exception as exc:
            with self._lock:
                self._errors.append(f"PositionLogger start failed: {exc}")
            self._position_logger = None

        try:
            tracker: CumulativeAzTracker | None = None
            try:
                tracker = CumulativeAzTracker.load_or_fresh()
            except Exception:
                tracker = CumulativeAzTracker()

            if self._auto_slew_enabled and not self.dry_run:
                if self._stop_evt.is_set():
                    pass
                else:
                    self._auto_slew(cli, loc)

            # If stop was requested during pre-slew (either detected by a
            # checkpoint inside _auto_slew, or arriving after it returned),
            # skip the tracking loop entirely.
            if self._stop_evt.is_set():
                with self._lock:
                    if self._exit_reason is None:
                        self._exit_reason = "stop_signal"
                    self._phase = "stopped"
                return

            with self._lock:
                self._phase = "track"

            try:
                result = track(
                    cli, self._provider,
                    az_limits=self._az_limits,
                    az_tracker=tracker,
                    position_logger=self._position_logger,
                    stop_signal=self._stop_evt,
                    dry_run=self.dry_run,
                    offset_provider=self.offsets.get,
                    tick_callback=self._on_tick,
                )
            except Exception as exc:
                with self._lock:
                    self._exit_reason = "session_error"
                    self._errors.append(f"track() raised: {exc}")
                    self._phase = "error"
            else:
                with self._lock:
                    self._exit_reason = result.exit_reason
                    if result.errors:
                        self._errors.extend(result.errors)
                    self._phase = "done"
        finally:
            if self._position_logger is not None:
                try:
                    self._position_logger.mark_event(
                        "live_track_end",
                        exit_reason=self._exit_reason,
                    )
                    self._position_logger.stop()
                except Exception:
                    pass


# ---------- LiveTrackManager -----------------------------------------


class LiveTrackManager:
    """Process-singleton registry of live-track sessions, keyed by telescope id."""

    def __init__(self) -> None:
        self._sessions: dict[int, LiveTrackSession] = {}
        self._lock = threading.Lock()

    def get(self, telescope_id: int) -> LiveTrackSession | None:
        with self._lock:
            return self._sessions.get(int(telescope_id))

    def start(self, session: LiveTrackSession) -> LiveTrackSession:
        tid = int(session.telescope_id)
        # Refuse if a calibration session is driving the same mount.
        # Lazy import keeps this module independent of
        # `device.rotation_calibration` at import time.
        try:
            from device.rotation_calibration import get_calibration_manager
            if get_calibration_manager().is_running(tid):
                raise RuntimeError(
                    f"telescope {tid} is calibrating; stop the calibration first"
                )
        except ImportError:
            pass
        with self._lock:
            existing = self._sessions.get(tid)
            if existing is not None and existing.is_alive():
                raise RuntimeError(
                    f"telescope {tid} already tracking; stop first"
                )
            # Start the thread inside the lock so the is_alive() check,
            # thread spawn, and registry write are atomic. Otherwise two
            # concurrent /track POSTs can both pass the check (the first
            # session is registered but its thread hasn't been .start()-ed
            # yet, so is_alive() returns False), and each spawns its own
            # tracking thread. The losing session gets overwritten in the
            # registry but its thread keeps running — orphaned from stop().
            session.start()
            self._sessions[tid] = session
        return session

    def stop(self, telescope_id: int) -> SessionStatus | None:
        with self._lock:
            s = self._sessions.get(int(telescope_id))
        if s is None:
            return None
        s.stop()
        return s.status()

    def status(self, telescope_id: int) -> SessionStatus | None:
        s = self.get(telescope_id)
        return s.status() if s is not None else None

    def set_offsets(
        self, telescope_id: int, **kwargs,
    ) -> OffsetSnapshot | None:
        s = self.get(telescope_id)
        if s is None:
            return None
        return s.offsets.set(**kwargs)

    def reset_offsets(
        self, telescope_id: int, scope: str = "all",
    ) -> OffsetSnapshot | None:
        s = self.get(telescope_id)
        if s is None:
            return None
        if scope == "azel":
            return s.offsets.reset_azel()
        if scope == "alongcross":
            return s.offsets.reset_alongcross()
        return s.offsets.reset_all()


_MANAGER: LiveTrackManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> LiveTrackManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = LiveTrackManager()
        return _MANAGER


_CATALOG: TargetCatalog | None = None
_CATALOG_LOCK = threading.Lock()


def get_catalog() -> TargetCatalog:
    global _CATALOG
    with _CATALOG_LOCK:
        if _CATALOG is None:
            _CATALOG = TargetCatalog()
        return _CATALOG


# Silence "imported but unused" for types only referenced in annotations.
_ = (Callable, Optional)
