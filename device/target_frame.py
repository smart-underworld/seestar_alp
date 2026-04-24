"""Coordinate frame between ECEF target predictions and the mount encoder.

The full chain is:

    ECEF (WGS84)
        │   subtract observer ECEF; rotate by observer lat/lon
        ▼
    Local ENU (east/north/up at the observer)
        │   direction cosines
        ▼
    Topocentric az/el (az = compass bearing from north)
        │   topocentric→mount rotation  ←── the only thing that needs calibration
        ▼
    Mount-frame az/el (what the encoder reports)

`MountFrame` carries the observer-specific ECEF origin + ENU rotation (known
from lat/lon/alt), plus the topocentric→mount rotation (unknown; starts as
identity for uncalibrated operation). Transform methods walk the chain in
one pass.

Time-independence: ECEF is earth-fixed, so the conversion is deterministic
from position alone. Satellite propagators return ECEF at a given time; the
time stamp tags the sample but is not fed back into this transform.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from scripts.trajectory.observer import (
    ObserverSite,
    build_site,
    unwrap_az_series,
)


@dataclass(frozen=True)
class MountFrame:
    site: ObserverSite
    # 3×3 rotation applied in the local ENU frame. Identity = "mount frame
    # coincides with topocentric ENU" (uncalibrated). Non-identity rotations
    # encode tripod tilt + compass offset.
    topo_to_mount: np.ndarray
    # Refinement of the mount origin in ECEF metres, added on top of
    # `site.ecef_xyz`. Lets a future calibration step place the mount's
    # optical centre at sub-metre precision (relevant for near-pass LEO
    # satellites and low-altitude drones; ~0.006°/metre at 10 km slant).
    origin_offset_ecef_m: np.ndarray = field(
        default_factory=lambda: np.zeros(3)
    )

    @classmethod
    def from_identity_enu(cls, site: ObserverSite | None = None) -> "MountFrame":
        """Uncalibrated mount frame: treat topocentric az/el as the mount's.

        Motion and rates are correct; absolute sky direction will be off by
        whatever the real compass + tilt error is. Useful for validating the
        tracking pipeline mechanically without depending on sensor
        calibration.
        """
        if site is None:
            site = build_site()
        return cls(site=site, topo_to_mount=np.eye(3))

    @classmethod
    def from_calibration_json(
        cls,
        path: str | Path,
        site: ObserverSite | None = None,
    ) -> "MountFrame":
        """Build a mount frame from a calibration JSON.

        Reads (all optional, default 0):
        - `yaw_offset_deg` — CCW rotation of mount az=0 from topocentric
          north. Produced by `scripts.trajectory.calibrate_compass`.
        - `pitch_offset_deg`, `roll_offset_deg` — tilt of the mount
          relative to the local horizontal plane. Currently only
          produced by landmark-sighting calibration (magnetometer
          cannot resolve tilt direction cleanly).
        - `origin_offset_ecef_m` — 3-vector ECEF translation of the
          mount origin relative to `ObserverSite.ecef_xyz`. Used when
          a calibration step places the mount's optical centre at
          sub-metre precision (relevant for LEO satellites / low-
          altitude drones at <10 km slant).
        """
        p = Path(path)
        with p.open("r", encoding="utf-8") as f:
            cal = json.load(f)
        yaw_offset = float(cal["yaw_offset_deg"])
        pitch_offset = float(cal.get("pitch_offset_deg", 0.0))
        roll_offset = float(cal.get("roll_offset_deg", 0.0))
        off = cal.get("origin_offset_ecef_m")
        origin_offset = (
            np.asarray(off, dtype=float) if off is not None else np.zeros(3)
        )
        return cls.from_euler_deg(
            yaw_deg=yaw_offset,
            pitch_deg=pitch_offset,
            roll_deg=roll_offset,
            site=site,
            origin_offset_ecef_m=origin_offset,
        )

    @classmethod
    def from_euler_deg(
        cls,
        yaw_deg: float,
        pitch_deg: float,
        roll_deg: float,
        site: ObserverSite | None = None,
        origin_offset_ecef_m: np.ndarray | None = None,
    ) -> "MountFrame":
        """Build a mount frame from Euler angles of the mount in ENU.

        Convention: rotations applied intrinsically in the order yaw
        (about local up, +CCW seen from above), then pitch (about the
        new east axis, +tips up), then roll (about the new north axis,
        +tilts the east side down). Used by later calibration code; for
        now it is exposed mostly so tests can exercise non-identity
        frames.
        """
        if site is None:
            site = build_site()
        cy, sy = np.cos(np.radians(yaw_deg)),   np.sin(np.radians(yaw_deg))
        cp, sp = np.cos(np.radians(pitch_deg)), np.sin(np.radians(pitch_deg))
        cr, sr = np.cos(np.radians(roll_deg)),  np.sin(np.radians(roll_deg))
        r_yaw = np.array([[cy, -sy, 0.0],
                          [sy,  cy, 0.0],
                          [0.0, 0.0, 1.0]])
        r_pitch = np.array([[1.0, 0.0, 0.0],
                            [0.0,  cp, -sp],
                            [0.0,  sp,  cp]])
        r_roll = np.array([[ cr, 0.0, sr],
                           [0.0, 1.0, 0.0],
                           [-sr, 0.0, cr]])
        return cls(
            site=site,
            topo_to_mount=r_roll @ r_pitch @ r_yaw,
            origin_offset_ecef_m=(
                np.zeros(3)
                if origin_offset_ecef_m is None
                else np.asarray(origin_offset_ecef_m, dtype=float)
            ),
        )

    # --------------------------- transforms ---------------------------

    def _ecef_to_enu_mount(self, ecef_xyz: np.ndarray) -> np.ndarray:
        """ECEF (shape (3,) or (N, 3)) → ENU rotated into the mount frame."""
        arr = np.asarray(ecef_xyz, dtype=float)
        origin = self.site.ecef_xyz + self.origin_offset_ecef_m
        if arr.ndim == 1:
            v = arr - origin
            enu = self.site.enu_rotation @ v
            return self.topo_to_mount @ enu
        v = arr - origin
        enu = v @ self.site.enu_rotation.T
        return enu @ self.topo_to_mount.T

    def ecef_to_mount_azel(
        self, ecef_xyz: np.ndarray | tuple[float, float, float],
    ) -> tuple[float, float, float]:
        """Single-point ECEF → (az_deg, el_deg, slant_m) in the mount frame.

        `az_deg` is in [0, 360). Callers that need a cumulative (non-wrapping)
        az series should use `ecef_traj_to_mount` instead.
        """
        enu_m = self._ecef_to_enu_mount(np.asarray(ecef_xyz, dtype=float))
        east, north, up = float(enu_m[0]), float(enu_m[1]), float(enu_m[2])
        slant = float(np.sqrt(east * east + north * north + up * up))
        if slant == 0.0:
            return (0.0, 90.0, 0.0)
        az = (np.degrees(np.arctan2(east, north)) + 360.0) % 360.0
        el = np.degrees(np.arcsin(up / slant))
        return (float(az), float(el), slant)

    def ecef_array_to_mount(
        self, ecef_xyz: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Batched ECEF → (az_deg, el_deg, slant_m). Input shape (N, 3)."""
        arr = np.asarray(ecef_xyz, dtype=float)
        if arr.ndim != 2 or arr.shape[1] != 3:
            raise ValueError(f"expected shape (N, 3), got {arr.shape}")
        enu_m = self._ecef_to_enu_mount(arr)
        east = enu_m[:, 0]
        north = enu_m[:, 1]
        up = enu_m[:, 2]
        slant = np.sqrt(east * east + north * north + up * up)
        az = (np.degrees(np.arctan2(east, north)) + 360.0) % 360.0
        with np.errstate(invalid="ignore", divide="ignore"):
            el = np.degrees(np.arcsin(np.where(slant > 0, up / slant, 0.0)))
        return az, el, slant

    def ecef_traj_to_mount(
        self,
        ecef_xyz: np.ndarray,
        t_unix: np.ndarray,
    ) -> dict[str, np.ndarray]:
        """Batched ECEF + time → (az_cum, el, v_az, v_el, a_az, a_el, slant).

        - `az_cum` is unwrapped (monotonic through ±180° crossings), in degrees.
        - `v_*` are °/s via central differences, smoothed by a 3-sample box
          filter. Same convention replay.py already uses.
        - `a_*` are °/s² via central differences on the smoothed rates +
          the same 3-sample smoothing.
        - `slant` is in metres.

        Returns a dict so callers don't have to juggle tuple order.
        """
        t = np.asarray(t_unix, dtype=float)
        if t.ndim != 1:
            raise ValueError(f"t_unix must be 1-D, got shape {t.shape}")
        if len(t) < 4:
            raise ValueError(f"need ≥4 samples for v/a derivation; got {len(t)}")
        az_wrapped, el, slant = self.ecef_array_to_mount(ecef_xyz)
        az_cum = unwrap_az_series(az_wrapped)
        v_az = _smoothed_derivative(az_cum, t)
        v_el = _smoothed_derivative(el, t)
        a_az = _smoothed_derivative(v_az, t)
        a_el = _smoothed_derivative(v_el, t)
        return {
            "t_unix": t,
            "az_cum_deg": az_cum,
            "el_deg": el,
            "v_az_degs": v_az,
            "v_el_degs": v_el,
            "a_az_degs2": a_az,
            "a_el_degs2": a_el,
            "slant_m": slant,
        }


def _smoothed_derivative(x: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Central differences + 3-sample moving-average smoothing.

    Matches the convention already in use by scripts/trajectory/replay.py so
    the Phase 5 provider produces identical numbers on shared fixtures.
    Non-uniform `t` is handled correctly by `np.gradient`.
    """
    d = np.gradient(x, t)
    if d.size >= 3:
        kernel = np.ones(3) / 3.0
        d = np.convolve(d, kernel, mode="same")
    return d
