"""Best-effort compass calibration for the Seestar mount.

The mount's firmware exposes `compass_sensor.direction` — the physical heading
of the telescope body. `cali=0` in the sensor output means the compass is
raw/uncalibrated, but the value still rotates with the mount, so we can fit
a single offset that maps encoder-frame azimuth to true topocentric az:

    true_az ≈ encoder_az + yaw_offset_deg

Procedure:
  1. Park at a few encoder-az positions (at el=0 for simplicity).
  2. At each, settle, then read `compass_sensor.direction` several times.
  3. Fit `yaw_offset_deg = mean(true_az − encoder_az)` where
     `true_az = compass_direction − magnetic_declination_deg`.
  4. Save to `device/mount_calibration.json`.

`magnetic_declination_deg` defaults to +11.5° (LA, ~2026 epoch). Override
via --declination if needed. Compass readings are wrapped cleanly through
the modular fit. Single unambiguous yaw result; no pitch/roll today.

Also captures balance_sensor tilt at each station for diagnostic purposes.

Usage:

    uv run python -m scripts.trajectory.calibrate_compass
    uv run python -m scripts.trajectory.calibrate_compass --points 6 --span-deg 180
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from astropy.coordinates import EarthLocation

from device.alpaca_client import AlpacaClient
from device.plant_limits import AzimuthLimits, CumulativeAzTracker
from device.velocity_controller import (
    ensure_scenery_mode, measure_altaz_timed, move_to_ff, set_tracking,
)


_CAL_PATH = Path(__file__).resolve().parents[2] / "device" / "mount_calibration.json"


@dataclass
class CalibrationStation:
    encoder_az_deg: float
    encoder_el_deg: float
    compass_direction_deg: float
    compass_x: float
    compass_y: float
    compass_z: float
    balance_x: float
    balance_y: float
    balance_z: float
    balance_angle_deg: float


@dataclass
class MountCalibration:
    yaw_offset_deg: float
    magnetic_declination_deg: float
    residual_rms_deg: float
    n_stations: int
    compass_cali_flag: int
    balance_tilt_mean_deg: float
    calibrated_at: str
    stations: list[CalibrationStation]

    def save(self, path: Path = _CAL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)


def _wrap_pm180(deg: float) -> float:
    return ((deg + 180.0) % 360.0) - 180.0


def _read_compass_averaged(cli: AlpacaClient, samples: int = 5) -> dict:
    """Average `samples` compass readings over ~1 s for noise reduction."""
    compass_dirs: list[float] = []
    compass_xyz: list[tuple[float, float, float]] = []
    balance_xyz: list[tuple[float, float, float]] = []
    balance_angles: list[float] = []
    last_cali = 0
    for _ in range(samples):
        resp = cli.method_sync(
            "get_device_state",
            {"keys": ["compass_sensor", "balance_sensor"]},
        )
        result = resp["result"]
        c = result["compass_sensor"]["data"]
        b = result["balance_sensor"]["data"]
        compass_dirs.append(float(c["direction"]))
        compass_xyz.append((float(c["x"]), float(c["y"]), float(c["z"])))
        balance_xyz.append((float(b["x"]), float(b["y"]), float(b["z"])))
        balance_angles.append(float(b["angle"]))
        last_cali = int(c.get("cali", 0))
        time.sleep(0.2)
    # Average with modular wrap for compass_dir.
    mean_sin = np.mean([np.sin(np.radians(d)) for d in compass_dirs])
    mean_cos = np.mean([np.cos(np.radians(d)) for d in compass_dirs])
    mean_dir = float(np.degrees(np.arctan2(mean_sin, mean_cos)) % 360.0)
    c_mean = np.mean(compass_xyz, axis=0)
    b_mean = np.mean(balance_xyz, axis=0)
    return {
        "compass_direction_deg": mean_dir,
        "compass_x": float(c_mean[0]),
        "compass_y": float(c_mean[1]),
        "compass_z": float(c_mean[2]),
        "balance_x": float(b_mean[0]),
        "balance_y": float(b_mean[1]),
        "balance_z": float(b_mean[2]),
        "balance_angle_deg": float(np.mean(balance_angles)),
        "compass_cali": last_cali,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--device", type=int, default=1)
    parser.add_argument("--points", type=int, default=5,
                        help="Number of encoder-az stations")
    parser.add_argument("--span-deg", type=float, default=180.0,
                        help="Total span of encoder az sweep (deg)")
    parser.add_argument("--center-az-deg", type=float, default=0.0,
                        help="Center of the encoder az sweep (deg)")
    parser.add_argument("--el-deg", type=float, default=0.0,
                        help="Elevation to use at each station")
    parser.add_argument("--declination", type=float, default=11.5,
                        help="Magnetic declination (°E positive). "
                             "LA ≈ +11.5° in 2026.")
    parser.add_argument("--settle-s", type=float, default=1.5,
                        help="Extra dwell after arrival before reading compass")
    parser.add_argument("--out", type=Path, default=_CAL_PATH)
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute & print only — don't move mount or save")
    args = parser.parse_args(argv)

    cli = AlpacaClient(args.host, args.port, args.device)
    loc = EarthLocation.from_geodetic(0, 0, 0)
    az_limits = AzimuthLimits.load()

    # Build target list centered at center_az_deg.
    half = args.span_deg / 2.0
    targets = np.linspace(args.center_az_deg - half,
                          args.center_az_deg + half,
                          args.points)

    ensure_scenery_mode(cli)
    set_tracking(cli, False)
    time.sleep(0.3)
    alt_now, az_now, _ = measure_altaz_timed(cli, loc)
    print(f"[calibrate] current: az={az_now:+.3f}°  el={alt_now:+.3f}°",
          file=sys.stderr)

    tracker = CumulativeAzTracker.load_or_fresh(current_wrapped_az_deg=az_now)

    stations: list[CalibrationStation] = []
    cur_az = az_now
    cur_el = alt_now

    for i, tgt_az in enumerate(targets):
        print(f"\n[calibrate] station {i+1}/{len(targets)}: "
              f"moving to az={tgt_az:+.2f}°, el={args.el_deg:+.2f}°",
              file=sys.stderr)

        if not args.dry_run:
            t0 = time.monotonic()
            cur_el, cur_az, _ = move_to_ff(
                cli, target_az_deg=float(tgt_az), target_el_deg=args.el_deg,
                cur_az_deg=cur_az, cur_el_deg=cur_el, loc=loc,
                az_limits=az_limits, az_tracker=tracker,
            )
            print(f"  arrived in {time.monotonic()-t0:.1f}s: "
                  f"az={cur_az:+.3f}° el={cur_el:+.3f}°", file=sys.stderr)
            time.sleep(args.settle_s)

        avg = _read_compass_averaged(cli)
        station = CalibrationStation(
            encoder_az_deg=cur_az,
            encoder_el_deg=cur_el,
            compass_direction_deg=avg["compass_direction_deg"],
            compass_x=avg["compass_x"],
            compass_y=avg["compass_y"],
            compass_z=avg["compass_z"],
            balance_x=avg["balance_x"],
            balance_y=avg["balance_y"],
            balance_z=avg["balance_z"],
            balance_angle_deg=avg["balance_angle_deg"],
        )
        stations.append(station)
        print(f"  compass_dir={avg['compass_direction_deg']:.2f}°  "
              f"tilt={avg['balance_angle_deg']:.3f}°  "
              f"cali={avg['compass_cali']}", file=sys.stderr)

    if not args.dry_run:
        tracker.save()

    # Fit yaw_offset = true_az - encoder_az, where
    # true_az = compass_direction - magnetic_declination.
    # Use circular mean to handle wrap.
    offsets_deg = np.array([
        s.compass_direction_deg - args.declination - s.encoder_az_deg
        for s in stations
    ])
    sin_mean = np.mean(np.sin(np.radians(offsets_deg)))
    cos_mean = np.mean(np.cos(np.radians(offsets_deg)))
    yaw_offset = float(np.degrees(np.arctan2(sin_mean, cos_mean)))
    # Residuals wrapped.
    residuals = np.array([_wrap_pm180(o - yaw_offset) for o in offsets_deg])
    rms = float(np.sqrt(np.mean(residuals ** 2)))
    balance_mean = float(np.mean([s.balance_angle_deg for s in stations]))

    cal = MountCalibration(
        yaw_offset_deg=yaw_offset,
        magnetic_declination_deg=args.declination,
        residual_rms_deg=rms,
        n_stations=len(stations),
        compass_cali_flag=avg["compass_cali"],
        balance_tilt_mean_deg=balance_mean,
        calibrated_at=time.strftime("%Y-%m-%dT%H-%M-%S%z"),
        stations=stations,
    )
    print(f"\n[calibrate] fit results:", file=sys.stderr)
    print(f"  yaw_offset_deg = {yaw_offset:+.3f}°  "
          f"(mount az=0 points at true az={yaw_offset:+.2f}°)",
          file=sys.stderr)
    print(f"  residual RMS   = {rms:.3f}°   "
          f"(lower = compass is consistent)", file=sys.stderr)
    print(f"  magnetic declination = {args.declination:+.2f}°", file=sys.stderr)
    print(f"  tilt (mean)    = {balance_mean:.3f}°", file=sys.stderr)
    print(f"  stations       = {len(stations)}", file=sys.stderr)

    if not args.dry_run:
        cal.save(args.out)
        print(f"\n[calibrate] saved to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
