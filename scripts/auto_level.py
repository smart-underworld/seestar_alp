#!/usr/bin/env python3
"""Quick CLI: drive the connected Seestar through 12 azimuths, fit the tilt,
print leveling guidance.

Prereq: `uv run python root_app.py` is running and the scope is connected.
This script sends commands through the running app's Alpaca action endpoint.

Usage:
    .venv/bin/python scripts/auto_level.py [--samples 12] [--alt 10]
                                           [--host 127.0.0.1] [--port 5555]
                                           [--device 1]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import threading
import time
from pathlib import Path

import requests

_here = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.realpath(os.path.join(_here, "..")))

from astropy import units as u  # noqa: E402
from astropy.coordinates import AltAz, EarthLocation, SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402

from datetime import datetime, timezone  # noqa: E402

from device.auto_level import (  # noqa: E402
    AutoLevelSample,
    apply_sign_flip,
    build_guidance,
    fit_auto_level,
    load_run,
    planned_azimuths,
    positions_to_rows,
    save_run,
)
from device.config import Config  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _run_id() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


class AlpacaClient:
    def __init__(self, host: str, port: int, device: int):
        self.base = f"http://{host}:{port}/api/v1/telescope/{device}"
        self._txn = 1000

    def _txn_next(self) -> int:
        self._txn += 1
        return self._txn

    def action(self, action_name: str, parameters: dict, timeout: float = 30.0):
        data = {
            "Action": action_name,
            "Parameters": json.dumps(parameters),
            "ClientID": 1,
            "ClientTransactionID": self._txn_next(),
        }
        r = requests.put(f"{self.base}/action", data=data, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def method_sync(self, method: str, params=None):
        payload = {"method": method}
        if params is not None:
            payload["params"] = params
        resp = self.action("method_sync", payload)
        # Alpaca wraps the RPC payload under "Value"
        return resp.get("Value")

    def get_event_state(self, event_name: str | None = None):
        params = {"event_name": event_name} if event_name else {}
        return self.action("get_event_state", params).get("Value")


def read_sensors(
    cli: AlpacaClient,
) -> tuple[float, float, float, float | None, float | None]:
    """Return (x, y, z, angle, heading) from balance + compass sensors.

    - x, y, z: balance-sensor IMU vector (g-units; z≈1 at rest)
    - angle: balance_sensor.angle — tilt deviation from level in degrees
    - heading: compass_sensor.direction — magnetic compass heading in degrees
    """
    resp = cli.method_sync(
        "get_device_state",
        {"keys": ["balance_sensor", "compass_sensor"]},
    )
    result = resp["result"]
    b = result["balance_sensor"]["data"]
    angle = b.get("angle")
    heading: float | None = None
    if "compass_sensor" in result:
        c = result["compass_sensor"]["data"]
        d = c.get("direction")
        if d is not None:
            heading = float(d)
    return (
        float(b["x"]),
        float(b["y"]),
        float(b["z"]),
        float(angle) if angle is not None else None,
        heading,
    )


def current_radec(cli: AlpacaClient) -> tuple[float, float]:
    resp = cli.method_sync("scope_get_equ_coord")
    result = resp["result"]
    return float(result["ra"]), float(result["dec"])


def radec_to_altaz(ra_h: float, dec_deg: float, loc: EarthLocation, t: Time) -> tuple[float, float]:
    c = SkyCoord(ra=ra_h * u.hourangle, dec=dec_deg * u.deg)
    altaz = c.transform_to(AltAz(obstime=t, location=loc))
    return float(altaz.alt.deg), float(altaz.az.deg)


def altaz_to_radec(alt_deg: float, az_deg: float, loc: EarthLocation, t: Time) -> tuple[float, float]:
    altaz = SkyCoord(
        alt=alt_deg * u.deg,
        az=az_deg * u.deg,
        frame=AltAz(obstime=t, location=loc),
    )
    icrs = altaz.icrs
    return float(icrs.ra.hour), float(icrs.dec.deg)


def angular_distance_deg(
    ra1_h: float, dec1_d: float, ra2_h: float, dec2_d: float,
) -> float:
    """Great-circle angular distance (degrees) between two RA/Dec points.

    RA in hours, Dec in degrees. Uses the spherical law of cosines, clamped
    to guard against floating-point drift pushing |cos| slightly past 1.
    """
    ra1 = math.radians(ra1_h * 15.0)
    ra2 = math.radians(ra2_h * 15.0)
    d1 = math.radians(dec1_d)
    d2 = math.radians(dec2_d)
    cos_d = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(ra1 - ra2)
    cos_d = max(-1.0, min(1.0, cos_d))
    return math.degrees(math.acos(cos_d))


def wait_until_near_target(
    cli: AlpacaClient,
    target_ra_h: float,
    target_dec_d: float,
    tolerance_deg: float = 0.5,
    timeout: float = 90.0,
    poll: float = 0.3,
    stall_threshold_s: float = 5.0,
    stall_delta_deg: float = 0.05,
    nudge_fn=None,
    nudge_multiplier: float = 10.0,
) -> tuple[bool, float | None, bool]:
    """Poll actual RA/Dec via scope_get_equ_coord; compute distance in Python.

    Returns (ok, last_dist_deg, stalled).

    - `ok` is True if within `tolerance_deg` of target.
    - `stalled` is True if the scope's reported position hasn't changed by
      more than `stall_delta_deg` over the last `stall_threshold_s` seconds
      (but we also aren't close to target yet) — caller should re-issue slew.

    When `nudge_fn` is provided, it's called exactly once — the first time
    the reported distance falls below `nudge_multiplier * tolerance_deg` but
    is still above `tolerance_deg`. Firmware sometimes decelerates and stops
    just outside tolerance; a second slew command at short range nudges it
    the rest of the way. The callback may return a new (ra_h, dec_d) tuple
    (because the fresh altaz→radec conversion uses a later timestamp), in
    which case we switch our distance comparison to that new target.
    """
    deadline = time.time() + timeout
    last_dist: float | None = None
    last_move_t = time.time()
    last_pos: tuple[float, float] | None = None
    nudge_threshold = tolerance_deg * nudge_multiplier
    nudged = False
    tgt_ra, tgt_dec = target_ra_h, target_dec_d
    while time.time() < deadline:
        try:
            ra, dec = current_radec(cli)
        except Exception:
            time.sleep(poll)
            continue
        dist = angular_distance_deg(ra, dec, tgt_ra, tgt_dec)
        last_dist = dist
        if dist <= tolerance_deg:
            return True, dist, False

        if not nudged and dist <= nudge_threshold and nudge_fn is not None:
            nudged = True
            new_target = nudge_fn(dist)
            if new_target is not None:
                tgt_ra, tgt_dec = new_target
            # reset stall clock after the nudge — scope about to accelerate again
            last_move_t = time.time()
            last_pos = None

        if last_pos is not None:
            moved = angular_distance_deg(ra, dec, last_pos[0], last_pos[1])
            if moved >= stall_delta_deg:
                last_move_t = time.time()
        last_pos = (ra, dec)
        if time.time() - last_move_t > stall_threshold_s:
            return False, dist, True

        time.sleep(poll)
    return False, last_dist, False


def ensure_scenery_mode(cli: AlpacaClient) -> None:
    """Enter scenery (terrestrial) view mode (no target)."""
    cli.method_sync("iscope_start_view", {"mode": "scenery"})
    time.sleep(1.5)


class _EMA:
    """Single-channel exponential moving average with a time-constant.

    Uses the continuous-time form α = 1 − exp(−Δt / τ), so the filter
    behavior is independent of the poll rate. Call update(value, dt) with
    elapsed seconds since the last update.
    """

    def __init__(self, tau_s: float):
        self.tau = max(tau_s, 1e-6)
        self.value: float | None = None

    def update(self, new_value: float, dt_s: float) -> float:
        if new_value is None:
            return self.value if self.value is not None else float("nan")
        if self.value is None:
            self.value = new_value
            return self.value
        dt = max(dt_s, 0.0)
        alpha = 1.0 - math.exp(-dt / self.tau)
        self.value = alpha * new_value + (1.0 - alpha) * self.value
        return self.value


def live_monitor(
    cli: AlpacaClient,
    interval: float,
    tolerance_deg: float,
    x_offset: float,
    y_offset: float,
    tau_s: float = 1.0,
) -> None:
    """Interactive live-update loop showing current tilt. Ctrl+C to exit.

    EMA smoothing is applied to the raw IMU inputs (x, y, z, angle, heading)
    with the given time constant (default 1 s). Derived values (fit_tilt,
    trend) are recomputed from the smoothed inputs each tick — no separate
    smoothing stage on derived quantities.

    Shows two tilt readings side-by-side:
      fit_tilt  — our fit-corrected tilt in degrees, computed from smoothed
                  (x − x_offset, y − y_offset, z). Reads 0° when physically
                  level.
      seestar   — the scope's own reported balance_sensor.angle (smoothed).
                  Only reads 0° after you run the app's Level Calibration.

    Trend arrow and LEVEL-threshold follow fit_tilt (computed from smoothed
    inputs, so it's implicitly smooth too).
    """
    ema_x = _EMA(tau_s)
    ema_y = _EMA(tau_s)
    ema_z = _EMA(tau_s)
    ema_angle = _EMA(tau_s)
    ema_heading = _EMA(tau_s)

    # Rolling trend window (seconds). Stores (t, fit_tilt) pairs.
    trend_window_s = max(2.0, 3.0 * tau_s)
    trend_samples: list[tuple[float, float]] = []

    last_t = time.monotonic()
    try:
        while True:
            try:
                x, y, z, angle, heading = read_sensors(cli)
            except Exception as e:
                sys.stdout.write(f"\r[read error: {e}]\033[K")
                sys.stdout.flush()
                time.sleep(interval)
                continue

            now = time.monotonic()
            dt = now - last_t
            last_t = now

            # Smooth the raw IMU channels only.
            sm_x = ema_x.update(x, dt)
            sm_y = ema_y.update(y, dt)
            sm_z = ema_z.update(z, dt) if z is not None else None
            sm_angle = ema_angle.update(angle, dt) if angle is not None else None
            sm_heading = ema_heading.update(heading, dt) if heading is not None else None

            # Derive fit_tilt from the smoothed inputs — NOT separately filtered.
            tx = sm_x - x_offset
            ty = sm_y - y_offset
            z_eff = abs(sm_z) if sm_z else 1.0
            fit_tilt = math.degrees(math.atan2(math.hypot(tx, ty), z_eff))

            # Trend: compare current fit_tilt to the value ~trend_window_s ago.
            trend_samples.append((now, fit_tilt))
            trend_samples = [(t, v) for (t, v) in trend_samples if now - t <= trend_window_s]
            trend = ""
            if len(trend_samples) >= 2:
                oldest_v = trend_samples[0][1]
                delta = fit_tilt - oldest_v
                if abs(delta) < 0.005:
                    trend = "→ flat      "
                elif delta < 0:
                    trend = f"↓ {abs(delta):.3f}° better"
                else:
                    trend = f"↑ {delta:.3f}° worse "

            status = "LEVEL ✓" if fit_tilt < tolerance_deg else "adjust "
            fit_s = f"{fit_tilt:.3f}°"
            see_s = f"{sm_angle:.3f}°" if sm_angle is not None else "n/a"
            heading_s = f"{sm_heading:5.1f}°" if sm_heading is not None else "  n/a"
            z_s = f"{sm_z:+.4f}" if sm_z is not None else "n/a"
            line = (
                f"\r[{status}] fit_tilt={fit_s}  seestar={see_s}  "
                f"heading={heading_s}  x={sm_x:+.4f} y={sm_y:+.4f} z={z_s}  {trend}"
            )
            sys.stdout.write(line + "\033[K")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        sys.stdout.write("\n\n")
        sys.stdout.flush()
        print("Exited live monitor. Now open the Seestar app to calibrate the zero reference.")


def issue_slew(
    cli: AlpacaClient, az_deg: float, alt_deg: float, loc: EarthLocation,
) -> tuple[float, float]:
    """Send iscope_start_view (scenery + target). Returns the commanded RA/Dec
    so the caller can compute distance-to-target in Python.

    Uses dict-params so the app's verify-injection transform doesn't mangle
    the payload (list-params would be wrapped as [[list], 'verify']).
    """
    ra_h, dec_deg = altaz_to_radec(alt_deg, az_deg, loc, Time.now())
    cli.method_sync(
        "iscope_start_view",
        {
            "mode": "scenery",
            "target_ra_dec": [ra_h, dec_deg],
            "target_name": f"autolevel_az{az_deg:.0f}",
            "lp_filter": False,
        },
    )
    return ra_h, dec_deg


# Empirical constants (measured on a Seestar S50 via scope_speed_move probes).
# Both axes scale linearly in rate vs speed up to the firmware clamp at ~1440.
_MAIN_SPEED = 1440            # firmware-clamped max
_MAIN_RATE_DEGS = 6.0         # ~6.09 °/s measured at speed=1440 over 10s bursts
_NUDGE_SPEED = 50             # ~0.21 °/s (extrapolated from speed/237 linear fit)
_NUDGE_RATE_DEGS = 0.21
_DUR_SEC_CAP = 10             # firmware ignores dur_sec > 10
_MIN_DUR_S = 5                # never issue any scope_speed_move shorter than this
_SPEED_PER_DEG_PER_SEC = 237  # linear fit from probe: rate°/s ≈ speed / 237
_MAIN_MIN_SPEED = 100         # below this the mount barely overcomes stiction
_MAIN_CLOSE_ENOUGH_DEG = 2.0  # stop chaining main bursts when residual < this
_MAX_MAIN_BURSTS = 12         # hard cap on main-burst iterations; fall back
                              # to iscope_start_view if not converged by then
_MAIN_STUCK_PROGRESS_DEG = 1.0  # if a main burst moves less than this, the
                              # mount is probably stuck against a limit (e.g.,
                              # ±180° azimuth wrap); fall back to iscope goto
_FALLBACK_GOTO_TOL_DEG = 3.0  # iscope_start_view arrival tolerance for fallback
_FALLBACK_GOTO_TIMEOUT_S = 60
_NUDGE_MIN_DUR_S = _MIN_DUR_S
_NUDGE_MAX_DUR_S = 10         # firmware cap
_MAX_NUDGES = 3               # bail out after this many nudge attempts


def _wrap_pm180(deg: float) -> float:
    return ((deg + 180.0) % 360.0) - 180.0


def _speed_move(cli: AlpacaClient, speed: int, angle: int, dur_sec: int) -> None:
    cli.method_sync(
        "scope_speed_move",
        {"speed": int(speed), "angle": int(angle), "dur_sec": int(dur_sec)},
    )


def _wait_for_mount_idle(
    cli: AlpacaClient, timeout_s: float, poll_s: float = 0.3,
) -> tuple[bool, float]:
    """Poll get_device_state(keys=["mount"]) until move_type == "none".

    Returns (idle, elapsed_s). `idle` is True if the mount reported idle
    before `timeout_s`, False on timeout. Polling mount state does NOT
    cancel an active scope_speed_move (probed on firmware; scope_get_equ_coord
    at <0.3 s cadence does, hence this helper queries only `mount`).
    """
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = cli.method_sync("get_device_state", {"keys": ["mount"]})
            mt = resp["result"]["mount"].get("move_type", "none")
            if mt == "none":
                return True, time.monotonic() - t0
        except Exception:
            pass
        time.sleep(poll_s)
    return False, time.monotonic() - t0


def _measure_altaz(cli: AlpacaClient, loc: EarthLocation) -> tuple[float, float]:
    """Single position read → (alt_deg, az_deg) with az wrapped to [-180, 180).

    Caller must guarantee the mount is not currently running a
    scope_speed_move — otherwise the read cancels it.
    """
    ra_h, dec_deg = current_radec(cli)
    alt_deg, az_raw = radec_to_altaz(ra_h, dec_deg, loc, Time.now())
    return alt_deg, _wrap_pm180(az_raw)


class PositionLogger:
    """Background thread that samples mount position every `poll_interval_s`
    and appends each sample as a JSONL record.

    The main thread annotates state via `set_target(az, alt)` and
    `set_phase(name, step=...)`; those values are copied into each poll
    record. Also exposes `mark_event(name, **extra)` to write one-off
    event records interleaved with the polled samples.

    Alpaca exposes no subscription API for position, so this polls
    `scope_get_equ_coord` and converts to alt/az via astropy. Polling at
    0.5 s is safe — probed at 0.3 s without cancelling scope_speed_move.
    """

    def __init__(
        self,
        cli: AlpacaClient,
        loc: EarthLocation,
        path: str | os.PathLike,
        poll_interval_s: float = 0.5,
    ):
        self.cli = cli
        self.loc = loc
        self.path = Path(path)
        self.poll_interval = poll_interval_s
        self._commanded_az: float | None = None
        self._commanded_alt: float | None = None
        self._phase: str = "init"
        self._step: int | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._file = None
        self._write_lock = threading.Lock()

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", buffering=1)  # line-buffered
        self._write({
            "t": _now_iso(),
            "kind": "header",
            "poll_interval_s": self.poll_interval,
        })
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="PositionLogger", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._file is not None:
            self._write({"t": _now_iso(), "kind": "footer"})
            self._file.close()
            self._file = None

    def set_target(self, az_deg: float | None, alt_deg: float | None) -> None:
        with self._lock:
            self._commanded_az = az_deg
            self._commanded_alt = alt_deg

    def set_phase(self, phase: str, step: int | None = None) -> None:
        with self._lock:
            self._phase = phase
            if step is not None:
                self._step = step

    def mark_event(self, event: str, **extra) -> None:
        if self._file is None:
            return
        with self._lock:
            snapshot = {
                "phase": self._phase,
                "step": self._step,
                "commanded_az_deg": self._commanded_az,
                "commanded_alt_deg": self._commanded_alt,
            }
        rec = {"t": _now_iso(), "kind": "event", "event": event, **snapshot, **extra}
        self._write(rec)

    def _write(self, rec: dict) -> None:
        if self._file is None:
            return
        with self._write_lock:
            try:
                self._file.write(json.dumps(rec) + "\n")
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                rec = self._sample()
                self._write(rec)
            except Exception as e:
                self._write({
                    "t": _now_iso(),
                    "kind": "error",
                    "error": repr(e),
                })
            # Event.wait returns True if set; use it as interruptible sleep.
            if self._stop_event.wait(self.poll_interval):
                break

    def _sample(self) -> dict:
        resp = self.cli.method_sync("scope_get_equ_coord")
        ra = float(resp["result"]["ra"])
        dec = float(resp["result"]["dec"])
        aa = SkyCoord(ra=ra * u.hourangle, dec=dec * u.deg).transform_to(
            AltAz(obstime=Time.now(), location=self.loc)
        )
        alt = float(aa.alt.deg)
        az = _wrap_pm180(float(aa.az.deg))
        with self._lock:
            phase = self._phase
            step = self._step
            cmd_az = self._commanded_az
            cmd_alt = self._commanded_alt
        return {
            "t": _now_iso(),
            "kind": "sample",
            "phase": phase,
            "step": step,
            "ra_h": ra,
            "dec_deg": dec,
            "alt_deg": alt,
            "az_deg": az,
            "commanded_az_deg": cmd_az,
            "commanded_alt_deg": cmd_alt,
        }


def move_azimuth_to(
    cli: AlpacaClient,
    target_az_deg: float,
    cur_az_deg: float,
    loc: EarthLocation,
    target_alt_deg: float,
    tag: str = "",
    arrive_tolerance_deg: float = 0.5,
    position_logger: PositionLogger | None = None,
) -> tuple[float, float, dict]:
    """Drive the azimuth axis to `target_az_deg` via scope_speed_move.

    Strategy: chain main bursts at max speed until |delta| < close-enough,
    then issue up to _MAX_NUDGES slow nudges, re-measuring between each,
    stopping once |delta| <= arrive_tolerance_deg. Raises RuntimeError if
    all nudges are exhausted without arriving. Never polls position during
    an active move (that cancels the move on this firmware).

    If a main burst makes less than _MAIN_STUCK_PROGRESS_DEG of progress,
    or we hit _MAX_MAIN_BURSTS without converging, fall back to iscope
    goto (which the firmware routes around the ±180° azimuth wrap) and
    then continue with the nudge loop.
    """
    stats = {
        "main_move_commands": 0,
        "main_move_total_dur_s": 0,
        "fallback_goto_used": False,
        "nudge_attempts": 0,
        "nudge_total_dur_s": 0,
        "final_residual_deg": None,
    }

    delta = _wrap_pm180(target_az_deg - cur_az_deg)

    # Main-move loop: chain bursts until we're within close_enough, or
    # bail to fallback if we detect no-progress / run out of tries.
    # `speed_cap` is a per-step rolling ceiling that gets halved whenever
    # the firmware silently refuses a burst (observed near the ±180° azimuth
    # boundary: high-speed bursts produce ~0.4° motion while nudge-speed
    # bursts cross the boundary fine). This adaptive retry is the main
    # robustness mechanism.
    fallback_reason: str | None = None
    speed_cap = _MAIN_SPEED
    while abs(delta) > _MAIN_CLOSE_ENOUGH_DEG:
        if stats["main_move_commands"] >= _MAX_MAIN_BURSTS:
            fallback_reason = (
                f"main loop reached {_MAX_MAIN_BURSTS} bursts without converging "
                f"(residual={delta:+.2f}°)"
            )
            break

        # Choose (speed, dur) so one burst covers |delta| without
        # overshooting. Strategy: always use min-dur 5s; scale speed
        # proportional to |delta| and clamp to [_MAIN_MIN_SPEED, speed_cap];
        # for deltas larger than a 5s burst at speed_cap can cover,
        # scale dur up instead, capped at _DUR_SEC_CAP.
        cap_rate = speed_cap / _SPEED_PER_DEG_PER_SEC
        max_dist_per_min_burst = cap_rate * _MIN_DUR_S
        if abs(delta) <= max_dist_per_min_burst:
            dur = _MIN_DUR_S
            needed_rate = abs(delta) / _MIN_DUR_S
            speed = max(
                _MAIN_MIN_SPEED,
                min(speed_cap, int(round(needed_rate * _SPEED_PER_DEG_PER_SEC))),
            )
        else:
            speed = speed_cap
            dur = min(
                _DUR_SEC_CAP,
                max(_MIN_DUR_S, math.ceil(abs(delta) / cap_rate)),
            )
        angle = 0 if delta > 0 else 180
        print(f"{tag} main: issuing speed={speed} angle={angle} dur={dur}s "
              f"(delta={delta:+.2f}°)", flush=True)
        if position_logger is not None:
            position_logger.set_phase("main_move")
            position_logger.mark_event(
                "main_issue",
                speed=speed, angle=angle, dur_sec=dur, delta_deg=delta,
            )
        pre_az = cur_az_deg
        _speed_move(cli, speed, angle, dur)
        # Wait for the firmware to report move_type == "none". The motor
        # stops itself when dur_sec elapses — no explicit stop needed.
        idle, elapsed = _wait_for_mount_idle(cli, timeout_s=dur + 3.0)
        if idle:
            print(f"{tag} main: mount idle after {elapsed:.2f}s", flush=True)
        else:
            print(f"{tag} WARNING: main burst did not report idle within "
                  f"{dur + 3.0}s", flush=True)
        stats["main_move_commands"] += 1
        stats["main_move_total_dur_s"] += dur
        if position_logger is not None:
            position_logger.set_phase("main_idle")
            position_logger.mark_event(
                "main_idle", idle=idle, wait_s=round(elapsed, 3),
            )

        # Re-measure to drive the next iteration (or fall through to nudge).
        _, cur_az_deg = _measure_altaz(cli, loc)
        moved = abs(_wrap_pm180(cur_az_deg - pre_az))
        delta = _wrap_pm180(target_az_deg - cur_az_deg)
        expected = dur * (speed / _SPEED_PER_DEG_PER_SEC)
        print(f"{tag} main: measured_az={cur_az_deg:+.3f}° "
              f"(moved {moved:.2f}°, expected ~{expected:.1f}°, "
              f"new delta={delta:+.3f}°)", flush=True)

        # Stuck detection: mount barely moved relative to what we asked for.
        # Use 20% of expected with an absolute floor of 1° so tiny commanded
        # bursts don't trigger spurious fallbacks.
        stuck_threshold = max(_MAIN_STUCK_PROGRESS_DEG, 0.2 * expected)
        if moved < stuck_threshold:
            # First try halving the speed ceiling (firmware soft-throttles
            # high-speed bursts near the ±180° boundary; slower bursts pass
            # through). Only fall back if we've already tried at the floor.
            if speed_cap > _MAIN_MIN_SPEED:
                new_cap = max(_MAIN_MIN_SPEED, speed_cap // 2)
                print(f"{tag} main: stuck ({moved:.2f}° < {stuck_threshold:.2f}°); "
                      f"halving speed cap {speed_cap} → {new_cap} and retrying",
                      flush=True)
                if position_logger is not None:
                    position_logger.mark_event(
                        "main_speed_cap_reduced",
                        old_cap=speed_cap, new_cap=new_cap,
                        moved_deg=moved, expected_deg=expected,
                    )
                speed_cap = new_cap
                continue
            fallback_reason = (
                f"main burst moved only {moved:.2f}° "
                f"(expected ~{expected:.1f}°, threshold {stuck_threshold:.2f}°) "
                f"even at floor speed {_MAIN_MIN_SPEED} — mount refusing motion"
            )
            break

    if fallback_reason is not None:
        print(f"{tag} FALLBACK: {fallback_reason}. Using iscope_start_view to "
              f"route around the limit (target az={target_az_deg:+.2f}°, "
              f"alt={target_alt_deg:.2f}°).", flush=True)
        stats["fallback_goto_used"] = True
        if position_logger is not None:
            position_logger.set_phase("fallback_goto")
            position_logger.mark_event("fallback_issue", reason=fallback_reason)
        tgt_ra, tgt_dec = issue_slew(cli, target_az_deg, target_alt_deg, loc)
        ok, dist, _ = wait_until_near_target(
            cli,
            target_ra_h=tgt_ra,
            target_dec_d=tgt_dec,
            tolerance_deg=_FALLBACK_GOTO_TOL_DEG,
            timeout=_FALLBACK_GOTO_TIMEOUT_S,
            stall_threshold_s=5.0,
        )
        if ok:
            print(f"{tag} fallback: iscope arrived (dist={dist:.3f}°)",
                  flush=True)
        else:
            print(f"{tag} WARNING: fallback iscope goto did not arrive within "
                  f"{_FALLBACK_GOTO_TOL_DEG}°; continuing to nudge anyway "
                  f"(last dist={dist})", flush=True)
        _, cur_az_deg = _measure_altaz(cli, loc)
        delta = _wrap_pm180(target_az_deg - cur_az_deg)
        print(f"{tag} fallback: measured_az={cur_az_deg:+.3f}° "
              f"(new delta={delta:+.3f}°)", flush=True)

    # Nudge loop: at least one nudge always fires (consistent arrival
    # profile); subsequent nudges only fire while we're still outside the
    # arrive tolerance. Each nudge is min 5 s so the slow-approach ramp is
    # fully engaged before deceleration.
    for attempt in range(1, _MAX_NUDGES + 1):
        # ×3 on the raw time estimate: at speed=50 the acceleration ramp
        # dominates a short burst, so give the steady-state phase room.
        raw_dur = math.ceil(abs(delta) / _NUDGE_RATE_DEGS) * 3
        nudge_dur = max(_NUDGE_MIN_DUR_S, min(_NUDGE_MAX_DUR_S, raw_dur))
        nudge_angle = 0 if delta >= 0 else 180
        print(f"{tag} nudge {attempt}/{_MAX_NUDGES}: issuing speed={_NUDGE_SPEED} "
              f"angle={nudge_angle} dur={nudge_dur}s (delta={delta:+.3f}°)",
              flush=True)
        if position_logger is not None:
            position_logger.set_phase(f"nudge_{attempt}")
            position_logger.mark_event(
                "nudge_issue",
                attempt=attempt, speed=_NUDGE_SPEED, angle=nudge_angle,
                dur_sec=nudge_dur, delta_deg=delta,
            )
        _speed_move(cli, _NUDGE_SPEED, nudge_angle, nudge_dur)
        idle, elapsed = _wait_for_mount_idle(cli, timeout_s=nudge_dur + 3.0)
        if idle:
            print(f"{tag} nudge {attempt}: mount idle after {elapsed:.2f}s",
                  flush=True)
        else:
            print(f"{tag} WARNING: nudge {attempt} did not report idle within "
                  f"{nudge_dur + 3.0}s", flush=True)
        stats["nudge_attempts"] += 1
        stats["nudge_total_dur_s"] += nudge_dur
        if position_logger is not None:
            position_logger.set_phase(f"nudge_{attempt}_idle")
            position_logger.mark_event(
                "nudge_idle",
                attempt=attempt, idle=idle, wait_s=round(elapsed, 3),
            )

        measured_alt, cur_az_deg = _measure_altaz(cli, loc)
        delta = _wrap_pm180(target_az_deg - cur_az_deg)
        within = abs(delta) <= arrive_tolerance_deg
        print(f"{tag} nudge {attempt}: measured_az={cur_az_deg:+.3f}° "
              f"residual={delta:+.3f}° "
              f"({'WITHIN' if within else 'OUTSIDE'} "
              f"tol ±{arrive_tolerance_deg}°)", flush=True)
        if within:
            break
    else:
        # Exhausted all nudges without arriving.
        stats["final_residual_deg"] = delta
        raise RuntimeError(
            f"{tag} could not arrive within {arrive_tolerance_deg}° after "
            f"{_MAX_NUDGES} nudges (residual={delta:+.2f}°)"
        )

    stats["final_residual_deg"] = delta
    return measured_alt, cur_az_deg, stats


def main() -> int:
    p = argparse.ArgumentParser(description="Auto-level a Seestar by multi-azimuth tilt fit.")
    p.add_argument("--samples", type=int, default=12,
                   help="Number of distinct azimuth positions to visit.")
    p.add_argument("--reads-per-position", type=int, default=5,
                   help="Sensor reads to average at each azimuth (reduces noise).")
    p.add_argument("--read-interval", type=float, default=0.1,
                   help="Delay between reads at a single position (seconds).")
    p.add_argument("--alt", type=float, default=None,
                   help="Altitude (deg) to hold during rotation. Default: current altitude, clamped to [5, 30].")
    p.add_argument("--settle", type=float, default=1.5,
                   help="Seconds to wait (after arrival) before starting to sample.")
    p.add_argument("--arrive-tolerance", type=float, default=0.5,
                   help="Start the settle timer once mount is within this many degrees of target.")
    p.add_argument("--slew-timeout", type=float, default=90.0,
                   help="Max seconds to wait for slew to reach arrive-tolerance.")
    p.add_argument("--max-slew-attempts", type=int, default=3,
                   help="Re-issue the slew command up to this many times if the scope stalls.")
    p.add_argument("--stall-threshold", type=float, default=5.0,
                   help="Seconds without position change that counts as a stall.")
    p.add_argument("--nudge-multiplier", type=float, default=30.0,
                   help="When distance first falls below nudge-multiplier × arrive-tolerance, "
                        "re-issue the slew command once to nudge the scope the rest of the way.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--device", type=int, default=1)
    p.add_argument("--tolerance-deg", type=float, default=0.1)
    p.add_argument("--no-live", action="store_true",
                   help="Skip the live tilt monitor at the end.")
    p.add_argument("--live-interval", type=float, default=0.5,
                   help="Poll interval (seconds) for the live tilt monitor.")
    p.add_argument("--live-tau", type=float, default=1.0,
                   help="EMA time constant (seconds) for smoothing live readouts.")
    p.add_argument("--log-file", default=None,
                   help="Path to write the run log (JSON). Default: auto_level_logs/{run_id}.json")
    p.add_argument("--no-log", action="store_true",
                   help="Disable writing the run log.")
    p.add_argument("--position-log-file", default=None,
                   help="Path to write the position JSONL trace. Default: "
                        "auto_level_logs/{run_id}.positions.jsonl")
    p.add_argument("--no-position-log", action="store_true",
                   help="Disable the background position logger.")
    p.add_argument("--position-log-interval", type=float, default=0.5,
                   help="Poll interval (seconds) for the background position logger.")
    p.add_argument("--replay", default=None,
                   help="Path to a previously-saved run log. Skips hardware; reruns math only.")
    p.add_argument("--reanchor", action="store_true",
                   help="Force the sign-anchor prompt even if a sign is already stored in config.")
    args = p.parse_args()

    # Replay path — no hardware setup needed.
    if args.replay:
        return run_replay(args)

    # Load scope location from config (used by astropy altaz<->radec transform).
    Config.load_toml()
    if not Config.init_lat or not Config.init_long:
        print("ERROR: seestar_initialization.lat / long not set in device/config.toml.",
              file=sys.stderr)
        print("Set them to your site coordinates and retry.", file=sys.stderr)
        return 2
    loc = EarthLocation(lat=Config.init_lat * u.deg, lon=Config.init_long * u.deg, height=0 * u.m)

    cli = AlpacaClient(args.host, args.port, args.device)

    # Determine the log path (unless disabled).
    log_path = None
    if not args.no_log:
        log_path = args.log_file or os.path.join(
            _here, "..", "auto_level_logs", f"{_run_id()}.json"
        )
        log_path = os.path.abspath(log_path)
        print(f"Logging run to: {log_path}")

    # Start the background position logger (JSONL trace) unless disabled.
    position_logger: PositionLogger | None = None
    if not args.no_position_log:
        position_log_path = args.position_log_file or os.path.join(
            _here, "..", "auto_level_logs", f"{_run_id()}.positions.jsonl"
        )
        position_log_path = os.path.abspath(position_log_path)
        print(f"Logging positions (JSONL) to: {position_log_path}")
        position_logger = PositionLogger(
            cli, loc, position_log_path,
            poll_interval_s=args.position_log_interval,
        )
        position_logger.start()

    try:
        return _main_body(args, cli, loc, log_path, position_logger)
    finally:
        if position_logger is not None:
            position_logger.set_phase("shutdown")
            position_logger.stop()


def _main_body(args, cli, loc, log_path, position_logger):
    # Put the scope into scenery (terrestrial) view mode so scope_goto moves
    # the mount without triggering the AutoGoto plate-solve routine.
    print("Entering scenery view mode...")
    if position_logger is not None:
        position_logger.set_phase("scenery_mode")
    ensure_scenery_mode(cli)

    # Decide the altitude we'll hold during rotation.
    if args.alt is None:
        ra_h, dec_deg = current_radec(cli)
        cur_alt, cur_az = radec_to_altaz(ra_h, dec_deg, loc, Time.now())
        target_alt = max(5.0, min(cur_alt, 30.0))
        print(f"Current scope altitude {cur_alt:.1f}°; holding at {target_alt:.1f}° during rotation.")
    else:
        target_alt = args.alt
        print(f"Holding altitude {target_alt:.1f}° during rotation.")

    reads = args.reads_per_position
    azimuths = planned_azimuths(args.samples, start_deg=-180.0)
    print(f"Collecting {args.samples} positions × {reads} reads each "
          f"(settle {args.settle}s after each scope_speed_move arrival)")

    # Log metadata
    run_meta = {
        "run_id": _run_id(),
        "started_at": _now_iso(),
        "config": {
            "samples": args.samples,
            "alt_deg": target_alt,
            "reads_per_position": reads,
            "read_interval_s": args.read_interval,
            "settle_s": args.settle,
            "main_speed": _MAIN_SPEED,
            "main_rate_degs": _MAIN_RATE_DEGS,
            "nudge_speed": _NUDGE_SPEED,
            "nudge_rate_degs": _NUDGE_RATE_DEGS,
            "lat": Config.init_lat,
            "long": Config.init_long,
        },
    }
    log_positions: list[dict] = []

    # Initial positioning: use iscope_start_view once to land at the starting
    # altitude, then drive pure-azimuth scope_speed_move from there. The
    # firmware goto typically settles ~0.5° shy, so use a coarse tolerance
    # here — step 1's move_azimuth_to will refine az to --arrive-tolerance.
    _INITIAL_GOTO_TOL_DEG = 3.0
    print(f"Initial goto: az={azimuths[0]:+.1f}° alt={target_alt:.1f}° "
          f"(coarse tol {_INITIAL_GOTO_TOL_DEG}°; step 1 will refine)")
    if position_logger is not None:
        position_logger.set_target(azimuths[0], target_alt)
        position_logger.set_phase("initial_goto", step=0)
        position_logger.mark_event("initial_goto_issue",
                                   target_az=azimuths[0], target_alt=target_alt)
    init_ra_h, init_dec_d = issue_slew(cli, azimuths[0], target_alt, loc)
    ok, init_dist, _ = wait_until_near_target(
        cli,
        target_ra_h=init_ra_h,
        target_dec_d=init_dec_d,
        tolerance_deg=_INITIAL_GOTO_TOL_DEG,
        timeout=args.slew_timeout,
        stall_threshold_s=args.stall_threshold,
    )
    if not ok:
        raise RuntimeError(
            f"Initial goto did not arrive within {_INITIAL_GOTO_TOL_DEG}° "
            f"(last dist={init_dist})"
        )
    print(f"Initial goto arrived (dist={init_dist:.3f}°); settling "
          f"{args.settle}s...", flush=True)
    if position_logger is not None:
        position_logger.set_phase("initial_settling", step=0)
        position_logger.mark_event("initial_goto_arrived",
                                   arrived_dist_deg=init_dist)
    time.sleep(args.settle)
    # Seed cur_az from a measurement so the first step's delta is tiny (main
    # loop likely skipped; only the mandatory nudge fires).
    _, cur_az_deg = _measure_altaz(cli, loc)
    print(f"Initial arrived: measured_az={cur_az_deg:+.3f}°  "
          f"(first target={azimuths[0]:+.2f}°)", flush=True)

    samples: list[AutoLevelSample] = []
    t_run_start = time.monotonic()
    for i, az in enumerate(azimuths, start=1):
        tag = f"[{i}/{args.samples}] az={az:+7.2f}°"
        t_step_start = time.monotonic()
        print(f"{tag} START  (cur={cur_az_deg:+.3f}°, "
              f"delta={_wrap_pm180(az - cur_az_deg):+.3f}°, "
              f"elapsed={t_step_start - t_run_start:.1f}s)",
              flush=True)
        if position_logger is not None:
            position_logger.set_target(az, target_alt)
            position_logger.set_phase("step_start", step=i)
            position_logger.mark_event("step_start",
                                       target_az=az, target_alt=target_alt,
                                       cur_az=cur_az_deg)
        measured_alt_deg, measured_az, move_stats = move_azimuth_to(
            cli, target_az_deg=az, cur_az_deg=cur_az_deg, loc=loc,
            target_alt_deg=target_alt, tag=tag,
            arrive_tolerance_deg=args.arrive_tolerance,
            position_logger=position_logger,
        )
        cur_az_deg = measured_az
        print(f"{tag} MOVE DONE  step_time={time.monotonic() - t_step_start:.1f}s  "
              f"main_bursts={move_stats['main_move_commands']}  "
              f"nudges={move_stats['nudge_attempts']}  "
              f"residual={move_stats['final_residual_deg']:+.3f}°",
              flush=True)
        if position_logger is not None:
            position_logger.set_phase("settling", step=i)
            position_logger.mark_event("move_done", **{
                k: v for k, v in move_stats.items() if k != "final_residual_deg"
            }, residual_deg=move_stats["final_residual_deg"])
        print(f"{tag} SETTLING  {args.settle}s before sampling...", flush=True)
        time.sleep(args.settle)

        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        angles: list[float] = []
        headings: list[float] = []
        raw_reads: list[dict] = []
        sample_start_t = time.monotonic()
        if position_logger is not None:
            position_logger.set_phase("sampling", step=i)
        print(f"{tag} SAMPLING  {reads} reads @ {args.read_interval}s interval:",
              end="", flush=True)
        for r in range(reads):
            if r > 0:
                time.sleep(args.read_interval)
            x, y, z, a, h = read_sensors(cli)
            t_offset = time.monotonic() - sample_start_t
            raw_reads.append({
                "t_offset_s": round(t_offset, 4),
                "x": x, "y": y, "z": z,
                "angle": a, "heading": h,
            })
            xs.append(x)
            ys.append(y)
            zs.append(z)
            if a is not None:
                angles.append(a)
            if h is not None:
                headings.append(h)
            print(f" {r+1}", end="", flush=True)
        print()

        def _stats(label: str, values: list[float], fmt: str = "+.5f") -> None:
            if not values:
                return
            m = statistics.mean(values)
            if len(values) >= 2:
                sd = statistics.stdev(values)
                print(f"       {label}: mean={m:{fmt}}  stdev={sd:.5f}  (n={len(values)})")
            else:
                print(f"       {label}: mean={m:{fmt}}  (n=1, stdev requires ≥2)")

        _stats("x      ", xs)
        _stats("y      ", ys)
        _stats("z      ", zs)
        _stats("angle  ", angles)
        _stats("heading", headings)

        avg_x = statistics.mean(xs)
        avg_y = statistics.mean(ys)
        avg_z = statistics.mean(zs) if zs else None
        avg_angle = statistics.mean(angles) if angles else None
        avg_heading = statistics.mean(headings) if headings else None

        # Per-position summary: balance offset (mean angle = tilt from level) and heading.
        offset_s = f"{avg_angle:.3f}°" if avg_angle is not None else "n/a"
        heading_s = f"{avg_heading:.1f}°" if avg_heading is not None else "n/a"
        print(f"       summary: balance_offset={offset_s}  heading={heading_s}")

        samples.append(AutoLevelSample(
            azimuth_deg=measured_az, sensor_x=avg_x, sensor_y=avg_y,
            sensor_z=avg_z, angle=avg_angle,
        ))
        log_positions.append({
            "index": i - 1,
            "azimuth_deg": measured_az,
            "commanded_azimuth_deg": az,
            "target_alt_deg": target_alt,
            "measured_alt_deg": measured_alt_deg,
            "residual_deg": _wrap_pm180(measured_az - az),
            "main_move_commands": move_stats["main_move_commands"],
            "main_move_total_dur_s": move_stats["main_move_total_dur_s"],
            "fallback_goto_used": move_stats["fallback_goto_used"],
            "nudge_attempts": move_stats["nudge_attempts"],
            "nudge_total_dur_s": move_stats["nudge_total_dur_s"],
            "final_residual_deg": move_stats["final_residual_deg"],
            "reads": raw_reads,
        })
        if log_path:
            try:
                save_run(log_path, run_meta, log_positions)
            except Exception as e:
                print(f"  (warning: failed to write log: {e})", file=sys.stderr)

    fit = fit_auto_level(samples)

    # Apply stored sign if configured; otherwise fit stays mount-frame only.
    stored_flip = _read_sign_flip()
    if stored_flip is not None and not args.reanchor:
        fit = apply_sign_flip(fit, stored_flip)

    _print_fit_block(fit)

    # Sign-anchor step: prompt the user if we haven't anchored yet, or if
    # --reanchor was passed, AND the measured tilt is meaningful (≥ 0.3°).
    need_anchor = (stored_flip is None) or args.reanchor
    if need_anchor and fit.tilt_deg >= 0.3:
        flip = _sign_anchor_prompt(cli, loc, fit, target_alt)
        if flip is not None:
            _write_sign_flip(flip)
            fit = apply_sign_flip(fit, flip)
            print()
            print("Re-applying sign to fit:")
            _print_fit_block(fit)

    guidance = build_guidance(fit, tolerance_deg=args.tolerance_deg)
    print()
    print(f">>> {guidance.message}")
    print()

    if args.no_live:
        return 0

    print()
    print("=== Live tilt monitor (Ctrl+C to exit) ===")
    print("Adjust the tripod slowly. The scope stays put; sensor axes are now fixed")
    print(f"in body frame. Polling every {args.live_interval:.1f}s.")
    print()
    live_monitor(
        cli,
        interval=args.live_interval,
        tolerance_deg=args.tolerance_deg,
        x_offset=fit.x_offset,
        y_offset=fit.y_offset,
        tau_s=args.live_tau,
    )
    return 0


def _print_fit_block(fit) -> None:
    print()
    print("=== Auto-Level Fit ===")
    print(f"  samples:          {fit.n_samples}")
    print(f"  tilt magnitude:   {fit.amplitude:.4f} sensor units  ({fit.tilt_deg:.2f}°)")
    print(f"  mount-az of tilt: {fit.tilt_mount_az_deg:.1f}°")
    if fit.uphill_world_az_deg is not None:
        from device.auto_level import azimuth_to_compass
        print(f"  uphill (world):   {fit.uphill_world_az_deg:.1f}°  "
              f"({azimuth_to_compass(fit.uphill_world_az_deg)})")
    else:
        print("  uphill (world):   <not yet anchored — slew-and-look step pending>")
    print(f"  sensor offsets:   x0={fit.x_offset:+.5f}  y0={fit.y_offset:+.5f}")
    print(f"  mean z:           {fit.mean_z:.5f}")
    print(f"  fit rms residual: {fit.rms_residual:.6f}")


def _read_sign_flip() -> bool | None:
    """Return cached sign-flip from config.toml, or None if unset."""
    val = Config.get_toml("seestar_initialization", "balance_sign_flip", None)
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _write_sign_flip(flip: bool) -> None:
    """Persist the sign-flip to config.toml under [seestar_initialization]."""
    try:
        Config.set_toml("seestar_initialization", "balance_sign_flip", flip)
        Config.save_toml()
        print(f"Saved balance_sign_flip={flip} to device/config.toml.")
    except Exception as e:
        print(f"(warning: failed to persist balance_sign_flip: {e})", file=sys.stderr)


def _sign_anchor_prompt(cli, loc, fit, target_alt: float) -> bool | None:
    """Slew scope to tilt_mount_az_deg and ask user if that side is high/low.

    Returns the sign-flip to apply (True = mount-az points to LOW side,
    so uphill is the opposite; False = mount-az already points uphill),
    or None if the user skipped.
    """
    print()
    print("=== Sign anchor ===")
    print("I'll slew the scope to the azimuth where the sensor sees maximum tilt")
    print(f"projection (mount-az {fit.tilt_mount_az_deg:.1f}°).")
    print("Once it arrives, physically look at your tripod: is the side the scope")
    print("is facing the HIGH side of the tripod, or the LOW side?")
    print()

    try:
        input("Press Enter to slew, or Ctrl+C to skip...")
    except (KeyboardInterrupt, EOFError):
        print("\n(skipped)")
        return None

    try:
        target_ra_h, target_dec_d = issue_slew(cli, fit.tilt_mount_az_deg, target_alt, loc)
        ok, dist, _ = wait_until_near_target(
            cli,
            target_ra_h=target_ra_h,
            target_dec_d=target_dec_d,
            tolerance_deg=0.5,
            timeout=60.0,
        )
        if not ok:
            print("(slew didn't complete; skipping anchor)")
            return None
    except Exception as e:
        print(f"(anchor slew failed: {e}; skipping)")
        return None

    print()
    while True:
        try:
            ans = input("Is that side HIGH (h), LOW (l), or skip (s)? ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return None
        if ans in ("h", "high"):
            # Scope is facing the HIGH side, so tilt_mount_az IS uphill. No flip.
            return False
        if ans in ("l", "low"):
            # Scope is facing the LOW side, so uphill is 180° away. Flip.
            return True
        if ans in ("s", "skip", ""):
            return None
        print("Please answer h, l, or s.")


def run_replay(args) -> int:
    """Skip hardware; load a saved run log and rerun the math."""
    path = args.replay
    if not os.path.exists(path):
        print(f"ERROR: replay file not found: {path}", file=sys.stderr)
        return 2

    Config.load_toml()
    meta, positions, samples = load_run(path)
    print(f"Replaying run {meta.get('run_id')} (from {path})")
    cfg = meta.get("config", {})
    print(f"  started_at: {meta.get('started_at')}")
    print(f"  finished_at: {meta.get('finished_at')}")
    print(f"  config: samples={cfg.get('samples')}, alt={cfg.get('alt_deg')}°, "
          f"reads_per_position={cfg.get('reads_per_position')}")
    print()

    # Per-position table
    rows = positions_to_rows(positions)
    print("Per-position samples:")
    print(f"  {'az':>6}  {'n':>2}  {'x_mean':>10}  {'x_std':>9}  "
          f"{'y_mean':>10}  {'y_std':>9}  {'z_mean':>9}  {'angle':>7}  {'heading':>7}")
    for row in rows:
        def fmt(v, w, prec):
            return "n/a".rjust(w) if v is None else f"{v:>{w}.{prec}f}"
        print(f"  {row['az']:>6.1f}  {row['n']:>2}  "
              f"{fmt(row['x_mean'], 10, 5)}  {fmt(row['x_std'], 9, 5)}  "
              f"{fmt(row['y_mean'], 10, 5)}  {fmt(row['y_std'], 9, 5)}  "
              f"{fmt(row['z_mean'], 9, 5)}  "
              f"{fmt(row['angle_mean'], 7, 3)}  {fmt(row['heading_mean'], 7, 1)}")

    if len(samples) < 4:
        print(f"\nNeed at least 4 positions to fit; only {len(samples)} in log.",
              file=sys.stderr)
        return 2

    fit = fit_auto_level(samples)
    stored_flip = _read_sign_flip()
    if stored_flip is not None:
        fit = apply_sign_flip(fit, stored_flip)

    _print_fit_block(fit)
    guidance = build_guidance(fit, tolerance_deg=args.tolerance_deg)
    print()
    print(f">>> {guidance.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
