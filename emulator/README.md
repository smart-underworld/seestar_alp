# Seestar Firmware Emulator

Runs `zwoair_imager` (armhf, Rockchip RV1126) inside an `arm32v7/Debian Buster`
container on an x86 Mac via QEMU, with all hardware dependencies stubbed out, so
the TCP:4700 JSON-RPC protocol can be exercised dynamically against the real binary.

`zwoair_imager` is one shared binary across the whole SeeStar lineup — it picks
its model at runtime from `/proc/device-tree/model` (confirmed via `strings`
on the binary: `"ZWO SeeStar Board"`, `"...S50v2 Board"`, `"...S50P Board"`,
`"...S30 Board"`, `"...S30P Board"`). The emulator can fake any of these via
`SEESTAR_MODEL`, so it can simulate an S50, S50 v2, S50 Pro, S30, or S30 Pro
from the *same* image/binary — no per-model rebuild needed.

This is the in-repo emulator used by `tests/system/` (see
`../tests/system/README.md`) and by CI (`.github/workflows/emulator-smoke.yml`,
`.github/workflows/emulator-full.yml`).

> **Note:** the standalone `*_test.py` poke-scripts referenced in a few
> command examples below (`auth_test.py`, `dark_frame_test.py`,
> `autofocus_test.py`, `solve_test.py`, `live_frame_test.py`) are manual
> protocol-poking tools from the original `seestar-api-research/sandbox`
> checkout — they were *not* migrated into `emulator/` (out of scope for the
> relocation). They're kept here as illustrative examples of what each
> command exchange looks like; for automated verification against this
> in-repo emulator, use `tests/system` (`../tests/system/README.md`) or a
> quick manual JSON-RPC round-trip (see [Authentication](#authentication-firmware-718)
> below for a `docker exec`/`/dev/tcp` example).

## Prerequisites

- Docker with multi-arch (QEMU) support — Docker Desktop on Mac/Windows, or
  `docker` + `qemu-user-static` / `binfmt-support` on Linux
- Firmware extracted to `~/dev/firmware/unpacked/v3.1.2/` (see `run.sh` for the
  expected path; pass `--firmware-dir`/a version argument to override) — see
  [Firmware extraction](#firmware-extraction) below
- RSA private key PEM for the firmware 7.18+ challenge-response auth handshake
- Optional, only for plate solving / 3PPA / Goto Target: astrometry.net index
  files downloaded via `./astrometry/download_index.sh`, and a rebuilt star
  catalog — see
  [Plate solving, polar alignment, and Goto Target](#plate-solving-3-point-polar-alignment-and-goto-target-synthetic-sky)
  below

## Quick start

```bash
./run.sh                        # builds image, starts container as an S50, forwards ports 4700/4701, 4800/4801, 8080, 4720/udp
SEESTAR_MODEL=S30P ./run.sh     # same, but the binary identifies as an S30 Pro
```

`SEESTAR_MODEL` accepts `S50` (default), `S50V2`, `S50P`, `S30`, `S30P`.

In a second terminal, once the binary is up:

```bash
python3 auth_test.py --pem ~/dev/seestar_private_key.pem
```

Or against the real device:

```bash
python3 auth_test.py --pem ~/dev/seestar_private_key.pem --host seestar.local
```

## Firmware extraction

Extract the `iscope` assets from a Seestar app APK/XAPK, then unpack the
resulting `.deb` packages. `extract_iscope`'s output directory is the
*version* directory — it appends `iscope/` itself, so don't include that
segment yourself:

```bash
python3 -m emulator.firmware.extract_iscope --apk ~/Downloads/Seestar_v*.xapk ~/dev/firmware/unpacked/v3.1.2
for deb in ~/dev/firmware/unpacked/v3.1.2/iscope/deb/*.deb; do
  dpkg -x "$deb" ~/dev/firmware/unpacked/v3.1.2/iscope/deb/out
done
```

For the fully-automated version (downloads a pinned release by version
string, extracts, and unpacks in one step — what CI uses), see
`emulator/firmware/provision.py`. It resolves the version against
`api.pureapk.com` (APKPure's Android-app-facing backend API) rather than
the consumer website, which is fronted by a Cloudflare bot challenge that
blocks GitHub Actions runners:

```bash
python3 -m emulator.firmware.provision \
  --version 3.1.2 \
  --work-dir ~/dev/firmware/unpacked
```

Pinned versions used by CI live in `emulator/firmware/versions.yaml`.

## What works

- License verification (`pi_is_verified`)
- Camera (`get_controls`, `iscope_start_view`, frame streaming on port 4800) — fully emulated V4L2 pipeline; see [Camera emulation](#camera-emulation) below
- Scope/mount commands (`scope_*`) via the port 4400 mount-controller stub
- Focuser (`get_focuser_position`, `get_connected_focuser`, etc.) — emulated
  GPIO EAF device
- Filter wheel (EFW: dark/IRCUT/LP slots, `WheelMove` events) — emulated
  GPIO/PWM device; feeds a near-black synthetic frame when parked on the dark
  slot so `CreateMasterDarkFrame`'s brightness check passes — see
  [Filter wheel & dark frames](#filter-wheel--dark-frames) below
- AutoFocus — spoofed to `complete` (the real convergence algorithm can't run
  in the emulator); see [AutoFocus](#autofocus-spoofed) below
- Plate solving (`start_solve`/`PlateSolve`), 3-point polar alignment
  (`start_polar_align`, `eq_3p`), and Goto Target (`scope_goto`/`AutoGoto`) —
  all complete end-to-end against a synthetic rendered sky; see
  [Plate solving, polar alignment, and Goto Target](#plate-solving-3-point-polar-alignment-and-goto-target-synthetic-sky)
  below
- Local storage (`storage.connected_storage` reports `emmc` mounted)
- Station WiFi (`pi_station_state`, `station` in `get_device_state`)
- AP WiFi (`pi_get_ap`, `pi_get_ap_channel`, `ap` in `get_device_state`)
- `firmware_ver_string` / `get_device_state` device info
- Model identity (`SEESTAR_MODEL=S50|S50V2|S50P|S30|S30P`) — see below

## Multi-model support (`SEESTAR_MODEL`)

Verified empirically by booting the real binary as each model and diffing
`get_device_state`/logs against the S50 baseline:

| Model | `product_model` / `user_product_model` | Schema deltas seen |
|---|---|---|
| S50 (default) | `Seestar S50` | — (baseline) |
| S30 | `Seestar S30` | adds `setting.second_camera` sub-object (wide-field cam config) |
| S30 Pro | `Seestar S30P` | adds `setting.second_camera`; `device.can_star_mode_sel_cam`/`can_wide_cam_roi`/`can_wide_cam_af` flip to `true`; `second_focuser` appears in `get_device_state` |

These are real, model-conditional fields in the binary's own JSON schema, not
cosmetic — confirmed by booting each model and diffing the live response.
`SEESTAR_MODEL` only changes `/proc/device-tree/model`; the seed XML's
hardcoded `Seestar S50`/`Seestar_S50` strings (`ASIAIR_imager.xml`,
`ASIAIR_guider.xml`, leftover from a real S50 export) do **not** leak into
`product_model`/`user_product_model` — those come from the device-tree match,
confirmed correct for S30/S30P in testing.

**Caveat — `second_focuser` is structural, not hardware-driven.** On a real
S30 Pro, `second_focuser` is a VCM lens actuator (`dw9800-vcm`) on a separate
I2C device (`/sys/bus/i2c/devices/5-000c/{name,position,powerctl,ismoveing}`,
confirmed via `strings`). In the emulator it reports a static
`{"state":"idle","max_step":2600,"step":2600}` with **no VCM device ever
opened** (verified — no `5-000c`/`dw9800` paths touched in logs, even when
explicitly calling `open_focuser {"name":"second_focuser"}`). The field is
populated from model capability flags, not a live probe, so it's good enough
for protocol/schema testing but won't reflect real lens-position behavior.
The primary focuser (`focuser`, `eaf0`) *is* hardware-path-driven on all
models including S30 Pro — confirmed by `[Open]open focuser eaf0 ok` in logs
— it's the same GPIO EAF stepper as S50/S30, not the VCM.

## Known limitation: compass/balance sensor (S30 magnetometer+IMU)

Real S30 hardware has a magnetometer (`ak09915`) and IMU (`mpu6500`) that S50
and S30 Pro lack (confirmed via kernel module manifests in firmware update
summaries). On real S30 hardware these should make
`compass_sensor`/`balance_sensor` in `get_device_state` report `code:0` with
real readings. In the emulator, on **every** model (including S30),
`compass_sensor`/`balance_sensor` report `code:1` with zeroed data — a
graceful "sensor not found" degradation, not a crash, same as `code:1` is
authentically correct for S50/S30 Pro.

Confirmed via `strings` + a logging-only diagnostic build that the binary
gates this behind `opendir("/sys/bus/iio/devices/")`: it enumerates the
Linux IIO sysfs tree looking for `ak09915`/`mpu6500` devices, finds none
(empty/nonexistent dir in the container), and falls back to `code:1` without
ever touching a per-device file (no `scan_elements`, `buffer`, or
`/dev/iio:deviceN` open observed). That's the same complexity class as the
camera's `/sys/class/video4linux/*/name` directory-enumeration gate above —
faking it properly needs `opendir`/`readdir` emulation of fake `iio:deviceN`
entries plus the buffered-read IIO character-device protocol
(`scan_elements/in_{accel,anglvel,magn}_*_en`, `buffer/enable`,
`/dev/iio:deviceN`), which only has `_en`/`_enable`/`_rate`/`_scale` control
files and no `_raw` polling files in the binary's strings — i.e. real sample
data comes from parsing a binary scan buffer, not a simple text file. Decided
not to build that (multi-day, uncertain byte-layout risk) for one sensor on
one of five models — same call as the camera. `log_if_sensor_probe()` and the
`opendir` diagnostic hook are left in `stubs/stub_hwid.c` (compiled in, but
non-faking) for whoever picks this back up.

## Camera emulation

The camera pipeline is fully stubbed — `get_controls` returns sensor data,
`iscope_start_view` starts streaming, and port 4800 sends live frame data.

### How to trigger streaming

After authenticating on port 4700, send:

```json
{"method":"iscope_start_view","params":{"mode":"star"},"id":1}
```

The binary then starts the ISP/V4L2 pipeline and streams frames on port 4800.
Other modes (`moon`, `solar`, etc.) return `code:204` ("out of limit") in the
emulator because the binary requires a star-mode lock before viewing.

### Port 4800 binary protocol

Each frame arrives as two back-to-back chunks over the TCP connection:

1. **80-byte header** — fixed magic bytes `03 c3 00 02 00 50` at offset 0;
   image height (uint16 LE) at offset 16; image width (uint16 LE) at offset 18;
   remaining bytes are zeroed in the emulator.

2. **Raw 16-bit frame** — `width × height × 2` bytes of little-endian uint16
   pixel values (Y-plane upscaled, not JPEG). For the S50/S30 at 1920×1080 this
   is 4,147,200 bytes; for S50P/S30P at 3856×2180 it is 16,816,640 bytes.

Note: MPP (Rockchip video codec) is **not** used for the port 4800 stream — the
binary sends raw 16-bit data directly, not JPEG or H.264. MPP encoding paths
exist in the binary but are not exercised during normal streaming.

### V4L2 emulation details (stub_hwid.c)

The stub intercepts the full chain that `ASICAM_Scan`/`ASICAM_Open`/`ASICAM_GetImage` use:

| Hook | What it does |
|---|---|
| `popen()` | Intercepts the `grep … video4linux … imx[0-9]+` scan; returns a fake sysfs line with the model-correct sensor name (`imx462` for S50/S50V2, `imx585` for S50P/S30P, `imx662` for S30) |
| `access()` | Returns success for `/dev/video*`, `/dev/v4l*`, `/dev/media0`, `/dev/media1`; returns ENOENT for `/dev/media2+` to stop the binary's enumeration loop cleanly |
| `open()/open64()/openat()` | Redirects `/dev/video*`, `/dev/media*`, `/dev/v4l-subdev*` to `/dev/null`; tracks the resulting fds by type (RAW=video0, YUV=video4) |
| `ioctl()` | Handles all V4L2 ioctls on tracked fds (see below) |
| `mmap()/mmap64()` | Returns a shared synthetic gray test-pattern frame buffer for any camera fd |
| `poll()/ppoll()` | Forces `POLLIN` for camera fds (real poll on `/dev/null` would return `POLLHUP`) |

**Handled V4L2 ioctls:**

| ioctl | Behavior |
|---|---|
| `VIDIOC_QUERYCAP` | Reports `V4L2_CAP_VIDEO_CAPTURE_MPLANE \| V4L2_CAP_STREAMING`; card string = sensor name |
| `VIDIOC_S_FMT / G_FMT / TRY_FMT` | Returns model-correct sensor resolution; RAW10 Bayer for video0, NV12 for video4 |
| `VIDIOC_G_SELECTION / S_SELECTION` | Returns full-sensor active area (0, 0, width, height) |
| `VIDIOC_G_CROP / S_CROP` | Returns full-sensor crop |
| `VIDIOC_REQBUFS` | Passes count through unchanged; count=0 (buffer-free teardown) is not overridden — fixing this was the root cause of `ASICAM_StopCapture` SIGSEGV |
| `VIDIOC_QUERYBUF` | Fills plane struct with frame size and offset=0 |
| `VIDIOC_QBUF / DQBUF` | DQBUF throttles to ~30 fps via `nanosleep(33ms)`, fills buffer with monotonic timestamp and cycle through 3 buffer indices |
| `VIDIOC_STREAMON / STREAMOFF` | Sets/clears internal `_streaming` flag |

### Sensor resolution by model

| Model | Sensor | Resolution |
|---|---|---|
| S50 | IMX462 | 1920 × 1080 |
| S50V2 | IMX662 | 1920 × 1080 (binary maps S50v2 Board → S50N iqfiles → imx662) |
| S50P, S30P | IMX585 | 3856 × 2180 |
| S30 | IMX662 | 1920 × 1080 (confirmed empirically — S30 uses native 1080p crop) |

Stride formulas match what the binary's `ASICAM_GetImage` validates:
- RAW10: `((width × 10/8 + 255) >> 8) × 256` bytes/line
- NV12:  `((width × 3/2  + 255) >> 8) × 256` bytes/line

## Filter wheel & dark frames

The electronic filter wheel (EFW: dark/IRCUT/LP slots) is driven through a
GPIO/PWM device (`/dev/pwm-gpio-misc`); `stub_hwid.c` intercepts it at the
`ioctl` level with two custom ioctls observed via `strace` on a real device:
`EFW_SET` (0x40084307, an 8-byte state blob) and `EFW_GET` (0x80084301, echoes
the last-set state back). The binary only checks that GET returns whatever it
last SET, not any particular payload semantics, so a simple echo is enough for
`open_wheel`/`move_wheel`/`get_wheel_position` to succeed.

`CreateMasterDarkFrame` additionally requires the captured frame to actually
look dark: it moves the wheel to the dark slot (position 0), takes an
exposure, and checks the average pixel value against a low threshold (~700
observed on a real device). A flat mid-gray test frame fails that check
unconditionally. To make this pass, `stub_hwid.c` watches the firmware's own
outgoing `"Event":"WheelMove","state":"complete","position":N` notification
(read-only — nothing is rewritten) and fills the synthetic camera frame
near-black when `N==0`, flat gray otherwise. Verify with:

```bash
python3 dark_frame_test.py --pem ~/dev/seestar_private_key.pem
```

## AutoFocus (spoofed)

The real `AutoFocusFunc` algorithm can't converge in the emulator — it needs
genuine focuser position feedback and an RKNN star-detector output tensor
whose format isn't reverse-engineered. Rather than emulate the algorithm,
`stub_hwid.c` rewrites the outgoing `"Event":"AutoFocus"` notification's
`"state"` field from `fail`/`cancel` to `complete` on the wire before it
reaches the client. Callers that only wait on this event (e.g. seestar_alp's
`wait_end_op`) see success, but no real focus position is found — this is a
protocol-completion stub, not a focus simulation. Verify the rewrite with:

```bash
python3 autofocus_test.py --pem ~/dev/seestar_private_key.pem
```

## Plate solving, 3-point polar alignment, and Goto Target (synthetic sky)

Lets a client drive plate solve / 3PPA / Goto against the emulator with no
real telescope or sky, by injecting a synthetically-rendered star field into
the firmware's own astrometry.net solve pipeline.

### How the firmware solves (discovered from the real device)

`zwoair_imager` plate-solves via **astrometry.net**: it writes the camera
frame to `/tmp/zwo/solvetmp.fit` (a FITS file), then execs `solve-field
--use-sextractor` (SExtractor for source extraction + `astrometry-engine`
against index files `index-4107..4112-Vt.fits`, ~350MB). Solve FITS format:
portrait 1080×1920, uint16, Bayer GRBG, ~2.37 arcsec/px (S50).

### The injection

`solve_redirect()` in `stub_hwid.c` redirects **read-only** opens (and
`fopen`/`fopen64`, since cfitsio uses buffered stdio) of
`/tmp/zwo/solvetmp.fit` → `/run/seestar-sim/solve.fits` (our render), scoped
to `!is_imager_process()` so the imager's own read-mode existence check isn't
hijacked — only `solve-field` and its children get redirected. Writes pass
through unchanged.

### The renderer (host-side Python, `sim/`)

A star catalog (real positions extracted directly from the astrometry index
via libastrometry's `startree` API — see
[Setup / how to run it](#setup--how-to-run-it) below) is gnomonically
projected around a target RA/Dec, given a PSF, and written as a uint16 FITS.
`sim/renderd.py` runs **on the host** (not in the container) and watches
`sim/shared/pointing.json` (bumped `seq` field) for the current telescope
pointing, re-rendering `sim/shared/solve.fits` whenever it changes. The
container's `/run/seestar-sim` is a bind mount of `sim/shared` (`run.sh`
wires this up automatically). `stub_mount.c` reads/writes the same
`pointing.json` so `scope_get_equ_coord`/`scope_get_ra_dec` stay consistent
with whatever the render currently shows.

**Goto/3PPA are closed-loop, not open-loop** — the firmware doesn't just trust
the mount saying "arrived." Each iteration it takes a real exposure, plate-
solves it, and compares the *solved* position against the target; only a
solve landing within tolerance completes the operation. This means the
mount stub pushing a completion event is necessary but not sufficient — the
render must actually depict the commanded position for the solve to agree.

`stub_mount.c` implements the motion handshakes the firmware needs to drive
this loop itself:
- `scope_goto [ra, dec]` — writes the target into `pointing.json` (so the next
  render/solve reflects it), then pushes `{"Event":"ScopeGoto","state":
  "complete",...}`.
- `scope_move_left_by_angle` / `scope_move_right_by_angle` — steps
  `pointing.json` along RA and pushes `{"Event":"MoveByAngle","state":
  "complete",...}`. This is what lets 3-point polar alignment (`eq_3p`)
  actually complete its 3 measurement points instead of timing out waiting
  for a `MoveByAngle` event that never arrives.
- `scope_get_cap` — must return a response *containing the substring*
  `"goto"` (the firmware does a raw `strstr`, not a bitmask parse — RE'd at
  binary VA `0xd7a4c`); `scope_get_ra_dec` returns a 3-element
  `[ra_hours, dec_deg, 0]` array (a scalar makes the firmware's RA-flip check
  fail with "operation fail").

### Known limitation: `autogoto_threshold` raised to 0.5°

The emulator's simulated 3PPA measures a small but non-zero polar-alignment
error (its move-by-angle kinematics are a simplified pure-RA step, not a real
mount's), so the firmware's post-3PPA calibration transform ends up
non-identity and shifts every subsequent plate-solve readout by roughly
0.14–0.35° (varies with target Dec/HA). The real firmware's default
`IsCentered` tolerance is 0.1°, which this offset reliably exceeds. The seed
`ASIAIR_imager.xml` sets `<imager><test><autogoto_threshold type="7">0.5`,
loosening the tolerance so goto genuinely converges (the scope really is
centered on the rendered target — the render/solve round-trip itself is
accurate to <2 arcsec, verified independently). This is an emulator tuning
knob, not a firmware bug; the real 0.1° behavior would need the sim's 3PPA
kinematics corrected to measure ~zero polar error.

### Setup / how to run it

1. `./astrometry/download_index.sh` — one-time, downloads the public
   astrometry.net 4100-series index files (~350MB, gitignored, from
   `data.astrometry.net`) into `astrometry/index/`. Plate-solving support is
   built from public sources — no real device or SSH access needed.
2. Rebuild the renderer's star catalog (gitignored `sim/data/stars.npy`,
   ~23MB) from the downloaded index — see `sim/build_catalog.py`'s module
   docstring for the exact command; it must run **inside the container**
   (needs the ARM `libastrometry.so.0` installed via apt, see `Dockerfile`),
   e.g.:
   ```bash
   docker run --rm --platform linux/arm/v7 \
     -v "$PWD/sim:/sim" \
     -v "$PWD/astrometry/index:/usr/local/astrometry/data:ro" \
     --entrypoint python3 seestar-emulator \
     /sim/build_catalog.py /usr/local/astrometry/data/index-4107.fits /sim/data/stars.npy
   ```
3. Start the emulator: `./run.sh`.
4. Start the renderer **on the host**:
   ```bash
   python3 -m sim.renderd --shared sim/shared --model S50 --catalog sim/data/stars.npy
   ```
5. Drive it:
   ```bash
   python3 solve_test.py --pem ~/dev/seestar_private_key.pem   # plate solve only
   ```
   or drive 3PPA / Goto Target via seestar_alp (see `../tests/system/README.md`),
   or a scratch client that sends `start_polar_align`/`scope_goto`. **3PPA
   and Goto are bound to the client's control socket — the firmware drops
   idle connections after ~16s ([checkConnection]), so any test client must
   send a heartbeat (e.g. `pi_is_verified` every few seconds) for the
   duration of the operation.**

## Live view (synthetic starfield)

The port-4800 live-preview stream (`iscope_start_view {"mode":"star"}` +
`begin_streaming`) shows the same synthetic starfield `sim/renderd.py` already
renders for plate solving, instead of a flat mid-gray fill.

### Why this needed a different technique than the FITS injection

The obvious approach — render into the raw camera buffer the firmware DQBUFs
from (`_cam_frame_buf` in `stub_hwid.c`) — doesn't work: the firmware's
internal reshape/debayer/stride transform from that buffer to the wire bytes
is unknown, and any structured pattern gets stride-aliased into banding
(this is why that buffer stays a flat fill). Instead, `stub_hwid.c`
intercepts the `write()` calls carrying the frame to the client directly,
after the firmware has already assembled its own packet — sidestepping the
unknown transform entirely, the same way `solve_redirect()` sidesteps it for
plate solving.

### The mechanism

Confirmed by directly instrumenting the running container: each preview
frame is sent as one 80-byte header `write()` (magic `03 c3 00 02 00 50`)
followed by several payload `write()` calls on the *same* fd, whose sizes are
an internal firmware buffer-size detail (observed: seven 524,288-byte chunks
+ one 477,184-byte remainder = 4,147,200 bytes, matching the portrait
1080×1920 frame — the same shape `solve.fits` uses). `stub_hwid.c` recognizes
the header by its magic bytes (fd numbers aren't stable across connections,
so content, not fd, is the signal), then substitutes each subsequent payload
`write()` on that fd with the corresponding byte range of
`sim/shared/live.raw`, tracked via a per-fd cumulative offset.

`sim/renderd.py` writes `live.raw` (raw native-endian `uint16` bytes, no FITS
wrapper) alongside `solve.fits` on every `pointing.json` update, from the
*same* rendered image — so live view and solve stay pixel-consistent.

### Verify it

```bash
python3 -m sim.renderd --shared sim/shared --model S50 --catalog sim/data/stars.npy &
python3 live_frame_test.py --pem ~/dev/seestar_private_key.pem
```

## How it works

### QEMU multi-arch

Docker Desktop's Linux VM ships with `binfmt_misc` support for armhf via
`tonistiigi/binfmt`. `run.sh` registers the handler on first run (idempotent).
The container runs `arm32v7/debian:buster`; the firmware binary executes under
`/usr/bin/qemu-arm`.

### Rockchip hardware stubs (`stubs/`)

`zwoair_imager` links against several Rockchip-proprietary shared libraries that
don't exist outside of RV1126 hardware. Stub `.so` files provide working
implementations that let the binary proceed past startup gates:

| Stub | Library | Purpose |
|---|---|---|
| `stub_mpp.c` | `librockchip_mpp.so.1` | Media Process Platform (video codec). Provides 32 `RK_MPI_*` symbols and 22 `mpp_*` symbols. `mpp_create` returns a real 64-byte `FakeMppApi` vtable (14 function pointers) so calls through `mpi->encode_put_frame`/`encode_get_packet` don't null-deref. `encode_get_packet` always sets `*packet=NULL`, causing the binary to log "mpp encode get packet failed" and skip the frame gracefully. MPP is not used for the port 4800 raw stream — only for an alternative JPEG-encode path not triggered in normal operation. |
| `stub_rkaiq.c` | `librkaiq.so` | ISP/AE/AWB pipeline. `rk_aiq_uapi_sysctl_init` returns a non-NULL handle (required); ISP lifecycle calls (prepare/start/stop/deinit) are logged no-ops. |
| `stub_rknn.c` | `librknn_api.so` | Neural network inference — symbol-resolution only, never called in emulator flows. |
| `stub_easymedia.c` | `libeasymedia.so.1` | RK media abstraction layer. Frame-delivery API functions (`SYS_Bind`, `RegisterOutCb/Ex/Event`, `StartGetMediaBuffer`, `VI_SetChnAttr`, `VI_Enable/Disable/Start/StopChn`, `VI_StartStream`) are logged no-ops. |
| `stub_media_ctl.c` | `libmedia-ctl.so` | V4L2 media controller — symbol-resolution only. |

### Mount/motor controller stub (`stubs/stub_mount.c`)

`zwoair_imager` connects *out* to `127.0.0.1:4400` as a client and sends
newline-delimited JSON-RPC to the mount/motor controller daemon. Without
something listening there, every `scope_*` command proxied through the binary
returns `code:103` (method not found). `mount_stub` is a small forking TCP
server (built as an executable, not a shared lib) launched from
`entrypoint.sh` that answers `test_connection`, `scope_get_mode`,
`scope_is_moving`, `scope_get_axle_coord`, `scope_get_equ_coord`,
`scope_get_track_state`, `scope_get_cap`, `scope_get_ra_dec`, and
`scope_send_cmd` with response formats verified against a real device. It
also implements `scope_goto` and `scope_move_left/right_by_angle`, which push
`ScopeGoto`/`MoveByAngle` completion events and keep `sim/shared/pointing.json`
in sync so the synthetic-sky renderer solves at the commanded position — see
[Plate solving, polar alignment, and Goto Target](#plate-solving-3-point-polar-alignment-and-goto-target-synthetic-sky)
above for the full closed-loop picture.

### LD_PRELOAD sysfs/proc/device intercept (`stubs/stub_hwid.c`)

Loaded via `LD_PRELOAD`, intercepts `open`/`open64`/`openat`/`fopen`/`fopen64`/`ioctl`/`mmap`/`mmap64`/`poll`/`ppoll`/`popen`/`access`/`stat`/`opendir`
for hardware paths that don't exist on x86.

**Proc/sysfs file fakes:**

| Path | Fake value |
|---|---|
| `/proc/device-tree/model` | Selected by `SEESTAR_MODEL` at container start (see [Multi-model support](#multi-model-support-seestar_model)); default `ZWO SeeStar Board V0.1 (Rockchip-RV1126-Linux)` (S50) |
| `/proc/cpuinfo` | `Serial: <CPUINFO_SERIAL>` (set to your device's value, see Auth below) |
| `/proc/net/wireless` | fake wlan0 entry, signal level -71 (feeds `station.sig_lev`) |
| `/sys/class/thermal/thermal_zone0/temp` | `45000` (45 °C in millidegrees) |
| `/sys/class/power_supply/bq25890-charger/status` | `Not charging` |
| `/sys/class/power_supply/bq25890-charger/online` | `1` |
| `/sys/class/power_supply/bq25890-charger/temp` | `25` (whole °C) |
| `/sys/class/power_supply/battery/capacity` | `100` |
| `/sys/class/power_supply/battery/voltage_now` | `4000000` (µV) |
| `/sys/class/power_supply/battery/current_now` | `0` (µA) |
| `/dev/eaf-misc` | redirected to `/dev/null`; all `ioctl()` calls on that fd return `0` |

**Camera device intercepts** — see [Camera emulation](#camera-emulation) above for full detail. In brief: `popen` fakes the sensor-scan grep; `access`/`open` redirect `/dev/video*`/`/dev/media*`/`/dev/v4l*` to `/dev/null` with tracked fds; `ioctl` handles all V4L2 operations; `mmap` returns a synthetic gray frame buffer; `poll`/`ppoll` force `POLLIN`.

The `ioctl` intercept is what makes the focuser work: the S50's focuser motor
is GPIO-driven through `/dev/eaf-misc` (not USB — "ZWO GPIO EAF" in the
binary), using custom ioctls of type `'E'`. The binary only checks the
ioctl() return value, not buffer contents, so faking every call to return `0`
is enough for `eaf_open()` to succeed and `get_device_state.focuser` to
report a stable `{"state":"idle","step":1563,"max_step":2600}` instead of
erroring. (Caveat: actual position tracking — `move_focuser` changing the
*reported* position — isn't implemented; that needs the `_IOR('E',1,...)`
struct layout reverse-engineered.)

There's also a `log_if_sensor_probe()` helper that flags any `open()` on
`/sys/bus/iio`, `/dev/iio`, and the S30 Pro VCM's I2C path (`5-000c`,
`dw9800`); an `opendir()` intercept additionally logs (but doesn't fake)
enumeration of `/sys/bus/iio/devices/` — scaffolding for resuming the
compass/IMU investigation (see Known limitation above).

### Shell command stubs (`scripts/`, copied to `/usr/local/bin/`)

`zwoair_imager` never talks to `wpa_supplicant`/`hostapd`/V4L2 tools
directly — it shells out via `popen()` to `network.sh` (from the firmware,
calling `iw`/`iwconfig`/`wpa_cli`/`ifconfig`/`ip`) and regex-parses the text
output. These scripts (plus a few defined inline in the `Dockerfile`) make
that parsing succeed:

| Script | Purpose |
|---|---|
| `scripts/iw` | `iw dev` lists `wlan0` (managed) + `uap0` (AP); `iw wlan0 info` / `iw uap0 info` report mode-appropriate details (`type managed` vs `type AP`, `ssid`, `channel`) |
| `scripts/iwconfig` | `iwconfig wlan0` reports `Signal level=-71 dBm` |
| `scripts/wpa_supplicant` | fake daemon (infinite sleep loop); launched by `entrypoint.sh` with `-c /home/pi/wpa_supplicant.conf` so `ps -ef \| grep wpa_supplicant \| grep .conf` (the firmware's `is_wpa_run()` check) succeeds |
| `wpa_cli` (Dockerfile) | fakes `wlan0` connected to `sandbox-net`, 5 GHz, `wpa_state=COMPLETED` |
| `ifconfig` (Dockerfile) | wraps the real binary; reports a fake `wlan0` with IP `192.168.1.100` |
| `ip` (Dockerfile) | wraps the real binary; `ip route` appends a fake default gateway via `wlan0` |
| `lsblk` (Dockerfile) | reports `/dev/mmcblk0p8` (nested under parent `mmcblk0`, matching real `lsblk -J` structure) mounted at `/boot/Image`, 59699M — `storage.connected_storage` needs the *nested children* JSON shape, a flat structure fails the binary's `MatchBlkCol` traversal |
| `systemctl` (Dockerfile) | no-op; binary calls `systemctl restart hostapd.service` once a minute |
| `sudo` (Dockerfile) | pass-through (we're already root) |

These satisfy two independent regex-parsed code paths in `network.sh`:

- **Station** (`pi_station_state`): `network.sh state` → `is_wpa_run()`
  requires a live `wpa_supplicant` process (see `scripts/wpa_supplicant`
  above) plus `/var/log/wpa_supplicant.log` to exist (triggers the
  `wpa_run_once` line). Then `get_state()` runs `iw wlan0 info` (needs `type
  managed`), `wpa_cli -i wlan0 status`, `ifconfig wlan0 | grep netmask`, `ip
  route | grep default`, `iwconfig wlan0 | grep 'Signal level'`.
- **AP** (`pi_get_ap`, `pi_get_ap_channel`): `network.sh ap_state` →
  `get_ap_state()` runs `iw dev` to enumerate interfaces, then `iw <iface>
  info` per interface looking for `type AP` (must be `uap0`, distinct from
  `wlan0`'s `type managed`). The binary's regexes need `ssid +(.*)` and
  `channel +[0-9]+ +\(([0-9]+) MHz` from that output, plus `key=` (from
  `wlan0.conf`'s `wpa_passphrase=`) and `key_mgmt=` (from `wpa_key_mgmt=`).
  Missing any of these makes the binary's `regex_search` fail →
  `{"error":"fail to find words","code":221}`.

### seed/

Config and database files copied from a real device, mounted writable at
`/home/pi/.ZWO/`. SQLite requires write access to create journal files alongside
the database, so `run.sh` copies `seed/` to a temp directory at launch rather
than mounting it read-only.

`zwoair_license` does **not** need to come from a real device. `entrypoint.sh`
generates it fresh on every container start: it reads the CPU serial from
`/proc/cpuinfo` (the `CPUINFO_SERIAL` value faked by `stub_hwid.c`), derives
the license `sn` with the same XOR-fold formula the binary itself uses to
verify, and computes a matching HMAC digest. Since both sides of the check
(the binary's verification and the entrypoint's generation) start from the
same serial and the same formula, the license is self-consistent by
construction — `pi_is_verified` returns `true` with the placeholder
`CPUINFO_SERIAL` ("0000000000000000") out of the box, no real device
required. There's nothing to copy from a real device here.

### Authentication (firmware 7.18+)

Connections from non-localhost IPs must complete a 3-step RSA challenge-response
handshake before commands are accepted:

1. `get_verify_str` → firmware returns a random challenge string
2. `verify_client` → client signs the challenge (RSA-PKCS1v15-SHA1, base64) and
   sends `{"sign": "...", "data": "..."}`. The firmware derives the expected
   public key from its embedded private key, writes it to `/tmp/zwo/app_publickey.pem`,
   and verifies the signature via `openssl dgst`.
3. `pi_is_verified` → confirms the socket is now in verified state

Connections from `127.0.0.1` inside the container bypass auth entirely
(`localhost=1`). Use `docker exec` with `/dev/tcp` for quick one-off commands:

```bash
docker exec -i seestar-emulator bash << 'EOF'
exec 3<>/dev/tcp/127.0.0.1/4700
echo '{"id":1,"method":"get_device_state","params":{}}' >&3
sleep 2; cat <&3
exec 3>&-
EOF
```

## Ports

Only `zwoair_imager` (and the `zwoair_file_server` it spawns) run in this
emulator. Ports for other binaries are listed for reference but are not active.

| Port | Proto | Active | Service |
|---|---|---|---|
| 4700 | TCP | yes | `zwoair_imager` main JSON-RPC control |
| 4701 | TCP | yes | `zwoair_imager` secondary listener (control) |
| 4800 | TCP | yes | `zwoair_imager` imaging — binary frame stream (80-byte header + raw 16-bit pixels); triggered by `iscope_start_view mode=star` on 4700 |
| 4801 | TCP | yes | `zwoair_imager` secondary listener (imaging) |
| 4720 | UDP | yes | `zwoair_imager` UDP channel |
| 80   | TCP | yes | `zwoair_file_server` (spawned automatically by imager) |
| 4400 | TCP | yes (internal only) | `mount_stub` — `zwoair_imager` connects out to this as a client; not forwarded to the host |
| 6333 | TCP | no  | `zwoair_updater` (not running) |
| 4500 | TCP | no | `zwoair_guider` (not running) |
