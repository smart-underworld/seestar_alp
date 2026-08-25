# Emulator-Based Firmware Regression Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate the QEMU-armhf Seestar firmware emulator into `seestar_alp` as `emulator/`, and turn `tests/system` into a two-tier (smoke/full) CI regression suite that runs against a pinned matrix of real firmware versions acquired at CI time — with no firmware bytes ever committed to the repo.

**Architecture:** `emulator/` holds the Docker/QEMU container definition, hardware stubs, synthetic-sky renderer, and firmware-acquisition tooling (moved from `seestar-api-research`). `tests/system` gains `--target emulator` (renamed from `--target sandbox`), `@pytest.mark.smoke`/`@pytest.mark.full` markers, and a `polar_align` toggle on the startup driver so the smoke tier can run without plate-solving. Two GitHub Actions workflows drive it: an always-on smoke lane and a label/nightly-gated full lane.

**Tech Stack:** Python 3.13, pytest, Playwright, Docker (multi-arch/QEMU `linux/arm/v7`), Debian buster (armhf), astrometry.net + SExtractor (apt packages), GitHub Actions.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-23-emulator-firmware-regression-design.md`.
- No firmware bytes (APKs, `.deb`s, extracted binaries, index files) are ever committed to the repo.
- `tests/system`'s existing "never auto-selected without `--target`" skip guard in `conftest.py` must remain intact — CI satisfies it the same way a human does, by passing `--target emulator` explicitly.
- Manual local use of `tests/system` and `emulator/run.sh` (a human pre-launching the container) must keep working unchanged.
- Model coverage is S50-only across both CI lanes. Both lanes use `--frontend both`.
- Ghidra decompilation, the Claude-API markdown-doc generation, and `extract_iscope.py`'s `repack` subcommand are NOT moved — they're irrelevant to running the emulator.
- Test/verification commands (from `AGENTS.md`): `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m "not integration" -q` and `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m ruff check .`. On this machine, use whatever `python`/`pytest` the repo's active venv provides if that interpreter path doesn't exist locally — check with `python3 -m pytest --version` first.
- Branch: `bguthro/emulator-ci` (already created, based off `bguthro/front_v2`). All commits in this plan go on this branch.

## Findings from the astrometry feasibility spike (already run — do not repeat)

This was the single biggest open risk from the design doc, and it's now resolved with empirical evidence gathered live in this session:

1. `arm32v7/debian:buster` (the emulator's exact base image, with the buster→archive.debian.org apt-source patch already used in `Dockerfile`) has both `astrometry.net` (0.76+dfsg-3) and `sextractor` (2.19.5+dfsg-6) available via `apt-cache policy` for `armhf`. Buster does **not** rename `sextractor` to `source-extractor` (that happened in later Debian releases) — the binary name matches what the firmware execs.
2. Installing both packages via `apt-get install -y --no-install-recommends astrometry.net sextractor` pulls in all needed shared libs and the `astrometry.util` Python glue automatically — no manual lib/pylib staging needed, unlike the old device-SSH-staged approach.
3. The production index files (`index-4107..4112-Vt.fits`, staged from a real device) are **not** publicly downloadable under that exact name, but the standard public astrometry.net 4100-series (`index-4107.fits` .. `index-4112.fits`, no `-Vt` suffix, hosted at `http://data.astrometry.net/4100/`) sum to ~350 MB — matching the original footprint exactly — and are real Tycho-2-derived star positions.
4. **End-to-end proof:** using only the apt-installed `solve-field`/`sextractor` plus the downloaded public `index-4107.fits`, the existing committed fixture `sim/astrometry-stage/synth.fits` (rendered from the *device's* proprietary Vt-catalog) solved successfully: `Field 1: solved with index index-4107.fits`, field center `(181.204558, -64.165719)` deg — matching the fixture's known target to within arcminutes. This confirms real Tycho-2 star positions are consistent between the device's custom index build and the public release, so the renderer's synthetic star fields remain solvable once its catalog (`stars.npy`) is rebuilt from the public index instead of the device-staged one.

**Decision:** build the astrometry stack entirely from public sources (apt packages + public index downloads). No device-SSH staging, no cached device-staged binary artifact. `stage-astrometry.sh` is retired, not moved.

I also checked whether `seestar_alp`'s existing `data/alp.dat` (a small SQLite DB used for goto target-name lookup, e.g. "Vega" → RA/Dec) could substitute for the astrometry index — it can't. It holds a sparse set of named objects, not the dense (millions of point sources) star-position catalog `solve-field` needs for blind/near-blind quad matching.

---

### Task 1: Relocate emulator hardware stubs, seed data, and entrypoint

**Files:**
- Create: `emulator/stubs/Makefile`, `emulator/stubs/stub_easymedia.c`, `emulator/stubs/stub_hwid.c`, `emulator/stubs/stub_media_ctl.c`, `emulator/stubs/stub_mount.c`, `emulator/stubs/stub_mpp.c`, `emulator/stubs/stub_rkaiq.c`, `emulator/stubs/stub_rknn.c`
- Create: `emulator/seed/ASIAIR_general.xml`, `emulator/seed/ASIAIR_guider.xml`, `emulator/seed/ASIAIR_imager.xml`, `emulator/seed/eaf.xml`, `emulator/seed/sh_conf.txt`, `emulator/seed/userData.db3`
- Create: `emulator/entrypoint.sh`
- Create: `emulator/scripts/iw`, `emulator/scripts/iwconfig`, `emulator/scripts/wpa_supplicant`

These are unmodified copies from another repo's working tree (`seestar-api-research`, not a git remote of this repo), so this is a plain file copy, not `git mv`.

- [ ] **Step 1: Copy the files**

```bash
mkdir -p /Users/bguthro/Development/seestar_alp/emulator
cd /Users/bguthro/Development/seestar_alp/emulator
cp -R ~/dev/seestar-api-research/sandbox/stubs .
cp -R ~/dev/seestar-api-research/sandbox/seed .
cp ~/dev/seestar-api-research/sandbox/entrypoint.sh .
cp -R ~/dev/seestar-api-research/sandbox/scripts .
```

- [ ] **Step 2: Verify the copy is complete and unmodified**

```bash
diff -r ~/dev/seestar-api-research/sandbox/stubs /Users/bguthro/Development/seestar_alp/emulator/stubs
diff -r ~/dev/seestar-api-research/sandbox/seed /Users/bguthro/Development/seestar_alp/emulator/seed
diff ~/dev/seestar-api-research/sandbox/entrypoint.sh /Users/bguthro/Development/seestar_alp/emulator/entrypoint.sh
diff -r ~/dev/seestar-api-research/sandbox/scripts /Users/bguthro/Development/seestar_alp/emulator/scripts
```

Expected: no output from any `diff` (files identical).

- [ ] **Step 3: Commit**

```bash
cd /Users/bguthro/Development/seestar_alp
git add emulator/stubs emulator/seed emulator/entrypoint.sh emulator/scripts
git commit -m "$(cat <<'EOF'
feat: relocate emulator hardware stubs, seed data, entrypoint from seestar-api-research

Moves the armhf hardware-stub sources, .ZWO seed files, and container
entrypoint that make up the QEMU-based firmware emulator into this repo
as emulator/, unmodified. Part of building an in-repo CI regression
suite without checking firmware binaries into the repo.
EOF
)"
```

---

### Task 2: Relocate the synthetic-sky renderer (`sim/`), excluding device-staged astrometry blobs

**Files:**
- Create: `emulator/sim/__init__.py`, `emulator/sim/catalog.py`, `emulator/sim/fits_io.py`, `emulator/sim/geometry.py`, `emulator/sim/pointing.py`, `emulator/sim/probe_fits.py`, `emulator/sim/projection.py`, `emulator/sim/render.py`, `emulator/sim/renderd.py`, `emulator/sim/gen_catalog.py`
- Create: `emulator/sim/tests/__init__.py`, `emulator/sim/tests/test_catalog.py`, `emulator/sim/tests/test_fits_io.py`, `emulator/sim/tests/test_geometry.py`, `emulator/sim/tests/test_pointing.py`, `emulator/sim/tests/test_projection.py`, `emulator/sim/tests/test_render.py`
- Create: `emulator/sim/build_catalog.py` (copied, then edited — see Step 3)
- Create: `emulator/frame_format.json`

**Explicitly excluded** (device-staged binary blobs and spike scratch — do not copy): `sim/astrometry-stage/` entirely (all of `bin/`, `lib/`, `pylib/`, `sxlib/`, `share/`, `root/`, `etc/`, plus `*.npy`, `*.json`, `*.log`, `*.fits`, `Dockerfile.spike`, `dump_stars.py`, `make_synth.py`, `run_solve.sh` at that path), and `sim/data/` (gitignored derived artifact, regenerated locally, not staged from the old repo).

**Interfaces:**
- Produces: `emulator/sim/build_catalog.py`'s `build(index_path, out_npy, lib_path=DEFAULT_LIB)` — used manually (not by CI) to regenerate `emulator/sim/data/stars.npy` after Task 4's Dockerfile is built and Task 3's public index files are downloaded.

- [ ] **Step 1: Copy the renderer core and its tests**

```bash
cd /Users/bguthro/Development/seestar_alp/emulator
mkdir -p sim/tests
for f in __init__.py catalog.py fits_io.py geometry.py pointing.py probe_fits.py projection.py render.py renderd.py gen_catalog.py; do
  cp "$HOME/dev/seestar-api-research/sandbox/sim/$f" sim/
done
for f in __init__.py test_catalog.py test_fits_io.py test_geometry.py test_pointing.py test_projection.py test_render.py; do
  cp "$HOME/dev/seestar-api-research/sandbox/sim/tests/$f" sim/tests/
done
cp "$HOME/dev/seestar-api-research/sandbox/frame_format.json" .
```

- [ ] **Step 2: Run the renderer's existing unit tests to confirm the move didn't break them**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -m pytest emulator/sim/tests -q
```

Expected: all tests pass (these are pure-Python unit tests with no astrometry/device dependency — `numpy` and `astropy` are already top-level dependencies of this repo per `pyproject.toml`).

- [ ] **Step 3: Copy `build_catalog.py` and update its docstring for the new provenance and image name**

```bash
cp "$HOME/dev/seestar-api-research/sandbox/sim/build_catalog.py" /Users/bguthro/Development/seestar_alp/emulator/sim/build_catalog.py
```

Then edit `/Users/bguthro/Development/seestar_alp/emulator/sim/build_catalog.py`'s module docstring (the top comment block, lines 1-24) to replace:

```python
"""Build the renderer's real-star catalog (sim/data/stars.npy) directly from a
staged astrometry.net star-kdtree index, via libastrometry's own startree API
(ctypes). These are the exact reference stars solve-field searches against, so a
field rendered from them is guaranteed to be solvable.

Runs where libastrometry.so.0 exists — i.e. INSIDE the sandbox container (armhf),
not on a macOS host. The staged index (index-4107-Vt.fits, the densest) and the
lib are both present in the built image, so:

    # from sandbox/, with the image built and the stack staged:
    docker run --rm --platform linux/arm/v7 \
      -v "$PWD/sim:/sim" \
      -v "$PWD/sim/astrometry-stage/root/usr/local/astrometry/data:/usr/local/astrometry/data:ro" \
      --entrypoint python3 seestar-sandbox \
      /sim/build_catalog.py /usr/local/astrometry/data/index-4107-Vt.fits /sim/data/stars.npy

That writes sim/data/stars.npy on the host (via the bind mount). stars.npy is
git-ignored (~23MB derived); regenerate it with this command on a fresh checkout.
```

with:

```python
"""Build the renderer's real-star catalog (sim/data/stars.npy) directly from a
public astrometry.net star-kdtree index, via libastrometry's own startree API
(ctypes). These are real Tycho-2 star positions from the same index series
solve-field searches against (see emulator/astrometry/download_index.sh),
so a field rendered from them is guaranteed to be solvable.

Runs where libastrometry.so.0 exists — i.e. INSIDE the emulator container
(armhf), not on a macOS host. libastrometry is installed via apt (the
`astrometry.net` package) when the image is built (see ../Dockerfile); the
public index files are downloaded separately by
emulator/astrometry/download_index.sh into emulator/astrometry/index/, so:

    # from emulator/, with the image built (Task 4) and the index downloaded (Task 3):
    docker run --rm --platform linux/arm/v7 \
      -v "$PWD/sim:/sim" \
      -v "$PWD/astrometry/index:/usr/local/astrometry/data:ro" \
      --entrypoint python3 seestar-emulator \
      /sim/build_catalog.py /usr/local/astrometry/data/index-4107.fits /sim/data/stars.npy

That writes sim/data/stars.npy on the host (via the bind mount). stars.npy is
git-ignored (~23MB derived); regenerate it with this command on a fresh checkout.
```

(The rest of the file — `DEFAULT_LIB`, `read_index_radec()`, `build()` — is unchanged: `DEFAULT_LIB = "/usr/lib/arm-linux-gnueabihf/libastrometry.so.0"` is the standard Debian armhf multiarch path, and the apt-installed package puts the library there too.)

- [ ] **Step 4: Verify the docstring edit and commit**

```bash
cd /Users/bguthro/Development/seestar_alp
grep -n "seestar-emulator\|download_index.sh" emulator/sim/build_catalog.py
git add emulator/sim emulator/frame_format.json
git commit -m "$(cat <<'EOF'
feat: relocate synthetic-sky renderer (sim/) from seestar-api-research

Moves the plate-solve renderer's core modules and unit tests, excluding
the device-staged astrometry-stage/ blobs and gitignored derived data —
those are replaced by public-source downloads in a later task.
EOF
)"
```

---

### Task 3: Download public astrometry.net index files

**Files:**
- Create: `emulator/astrometry/download_index.sh`
- Modify: `.gitignore` (repo root)

**Interfaces:**
- Produces: `emulator/astrometry/index/index-4107.fits` .. `index-4112.fits` on disk (gitignored, not committed) — consumed by Task 4's Dockerfile comments/run instructions and Task 5's `run.sh` bind mount.

- [ ] **Step 1: Write the download script**

```bash
mkdir -p /Users/bguthro/Development/seestar_alp/emulator/astrometry
```

Create `/Users/bguthro/Development/seestar_alp/emulator/astrometry/download_index.sh`:

```bash
#!/usr/bin/env bash
# download_index.sh — download the public astrometry.net 4100-series index
# files (Tycho-2-derived star positions) that solve-field searches against.
#
# Replaces the old device-SSH staging approach (stage-astrometry.sh in
# seestar-api-research): these are the standard public releases from
# data.astrometry.net, not pulled from a real Seestar. Verified (2026-07-23)
# to successfully solve the emulator's synthetic star fields — see the
# "Findings from the astrometry feasibility spike" section of the plan that
# introduced this script.
#
# Usage: ./download_index.sh [--force]
#   --force  re-download even if the file already exists.
set -euo pipefail

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SCRIPT_DIR}/index"
mkdir -p "${DEST}"

FILES=(index-4107.fits index-4108.fits index-4109.fits index-4110.fits index-4111.fits index-4112.fits)
BASE_URL="http://data.astrometry.net/4100"

for f in "${FILES[@]}"; do
  dest_path="${DEST}/${f}"
  if [[ -f "${dest_path}" && ${FORCE} -eq 0 ]]; then
    echo "==> ${f} already present — skipping (use --force to re-download)"
    continue
  fi
  echo "==> Downloading ${f}..."
  curl -fSL -o "${dest_path}.partial" "${BASE_URL}/${f}"
  mv "${dest_path}.partial" "${dest_path}"
done

echo "==> Done. $(ls "${DEST}" | wc -l | tr -d ' ') index file(s), $(du -sh "${DEST}" | cut -f1) total."
```

- [ ] **Step 2: Make it executable and add the gitignore entry**

```bash
chmod +x /Users/bguthro/Development/seestar_alp/emulator/astrometry/download_index.sh
```

Add to `/Users/bguthro/Development/seestar_alp/.gitignore` (append, near the end):

```
emulator/astrometry/index/
emulator/sim/data/*.npy
```

- [ ] **Step 3: Run it and verify**

```bash
cd /Users/bguthro/Development/seestar_alp/emulator/astrometry
./download_index.sh
ls -la index/
du -sh index/
```

Expected: 6 files, total size ~350 MB (matches the sizes recorded during the spike: 4107=165MB, 4108=95MB, 4109=50MB, 4110=25MB, 4111=10MB, 4112=5MB).

- [ ] **Step 4: Commit**

```bash
cd /Users/bguthro/Development/seestar_alp
git add emulator/astrometry/download_index.sh .gitignore
git commit -m "$(cat <<'EOF'
feat: add public astrometry.net index-file downloader

Replaces the device-SSH staging approach with a downloader for the
standard public 4100-series index files (Tycho-2 positions), verified
via a live spike to successfully solve the emulator's synthetic star
fields. Index files themselves stay gitignored, never committed.
EOF
)"
```

---

### Task 4: Write the new `emulator/Dockerfile` (apt-based astrometry, no device staging)

**Files:**
- Create: `emulator/Dockerfile`
- Create: `emulator/.dockerignore`

**Interfaces:**
- Consumes: `emulator/stubs/` (Task 1), `emulator/entrypoint.sh` (Task 1), `emulator/scripts/` (Task 1).
- Produces: docker image tagged `seestar-emulator`, with `solve-field`, `sextractor`, `astrometry-engine` on `PATH`, `/etc/astrometry.cfg` configured with `add_path /usr/local/astrometry/data` (bind-mounted at runtime by Task 5's `run.sh`).

- [ ] **Step 1: Write the Dockerfile**

Create `/Users/bguthro/Development/seestar_alp/emulator/Dockerfile`:

```dockerfile
FROM arm32v7/debian:buster

# Buster reached EOL — repos moved to archive.debian.org.
RUN sed -i \
    -e 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g' \
    -e 's|http://security.debian.org|http://archive.debian.org/debian-security|g' \
    -e '/buster-updates/d' \
    /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid

# Install standard apt dependencies that zwoair_imager links against, plus
# gcc to compile the Rockchip stub libraries inside the container, plus
# astrometry.net + sextractor (the plate-solve stack — apt-installed from
# public Debian packages, verified against buster/armhf: see the plan's
# "Findings from the astrometry feasibility spike"). No device-staged
# binaries/libs are needed; apt resolves the full dependency closure.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    make \
    libc6-dev \
    libcfitsio7 \
    libopencv-core3.2 \
    libopencv-imgproc3.2 \
    libopencv-imgcodecs3.2 \
    libopencv-highgui3.2 \
    libopencv-features2d3.2 \
    libopencv-calib3d3.2 \
    libopencv-video3.2 \
    libnova-0.16-0 \
    libxml2 \
    libjpeg62-turbo \
    libssl1.1 \
    libwcs6 \
    libgsl23 \
    libgslcblas0 \
    libavcodec58 \
    libavformat58 \
    libavutil56 \
    libswscale5 \
    libcurl4 \
    libsqlite3-0 \
    sqlite3 \
    libidn2-0 \
    libgomp1 \
    procps \
    psmisc \
    net-tools \
    kmod \
    i2c-tools \
    alsa-utils \
    openssl \
    xxd \
    netcat-openbsd \
    strace \
    python3 \
    python3-numpy \
    python3-astropy \
    file \
    netpbm \
    astrometry.net \
    sextractor \
    && rm -rf /var/lib/apt/lists/*

# sudo: pass-through wrapper (we're already root)
RUN printf '#!/bin/sh\nexec "$@"\n' > /usr/local/bin/sudo && \
    chmod +x /usr/local/bin/sudo

# systemctl: no-op stub — the binary calls "systemctl restart hostapd.service"
# once per minute to manage the WiFi AP. Silently succeed so the popen output
# doesn't pollute the protocol logs.
RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/systemctl && \
    chmod +x /usr/local/bin/systemctl

# lsblk stub: report /dev/mmcblk0p8 mounted at /boot/Image (51 GiB emmc).
# zwoair_imager runs "lsblk -J -n -o NAME,MOUNTPOINT,SIZE" to decide whether
# local storage is "mounted" or "disconnected".
RUN printf '#!/bin/sh\ncase "$*" in\n  *-J*)\n    printf '"'"'{\n   "blockdevices": [\n      {"name":"mmcblk0", "mountpoint":null, "size":"59699M",\n         "children": [\n            {"name":"mmcblk0p8", "mountpoint":"/boot/Image", "size":"59699M"}\n         ]\n      }\n   ]\n}\n'"'"'\n    ;;\n  *) exec /bin/lsblk "$@" 2>/dev/null ;;\nesac\n' \
    > /usr/local/bin/lsblk && chmod +x /usr/local/bin/lsblk

# wpa_cli stub: fake wlan0 connected to "sandbox-net" on 5 GHz.
# The binary (via network.sh) checks "wpa_state=COMPLETED" and "ip_address=..."
# to determine station.server:true in get_device_state.
RUN printf '#!/bin/sh\ncase "$*" in\n  *status*)\n    printf "bssid=aa:bb:cc:dd:ee:ff\nfreq=5805\nssid=sandbox-net\nid=0\nmode=station\npairwise_cipher=CCMP\ngroup_cipher=CCMP\nkey_mgmt=WPA2-PSK\nwpa_state=COMPLETED\nip_address=192.168.1.100\naddress=aa:bb:cc:dd:ee:ff\n"\n    ;;\n  *list_networks*)\n    printf "Network id / ssid / bssid / flags\n0\tsandbox-net\tany\t[CURRENT]\n"\n    ;;\n  *) printf "OK\n" ;;\nesac\n' \
    > /usr/local/bin/wpa_cli && chmod +x /usr/local/bin/wpa_cli

# ifconfig wrapper: pass through to /sbin/ifconfig, but when called with no
# args (interface enumeration) append a fake wlan0.  When called with "wlan0"
# directly (e.g. "ifconfig wlan0 | grep netmask" in network.sh get_state),
# print the interface detail so the netmask line is visible.
RUN printf '#!/bin/sh\nREAL=/sbin/ifconfig\nWLAN_INFO="wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n        inet 192.168.1.100  netmask 255.255.255.0  broadcast 192.168.1.255\n        ether aa:bb:cc:dd:ee:ff  txqueuelen 1000  (Ethernet)"\ncase "$1" in\n  wlan0) printf "%s\n" "$WLAN_INFO" ;;\n  uap0) exit 0 ;;\n  "")\n    $REAL\n    printf "\n%s\n" "$WLAN_INFO"\n    ;;\n  *) $REAL "$@" ;;\nesac\n' \
    > /usr/local/bin/ifconfig && chmod +x /usr/local/bin/ifconfig

# ip wrapper: pass through, but "ip route" appends a fake default gateway on wlan0.
RUN printf '#!/bin/sh\ncase "$*" in\n  *route*)\n    /sbin/ip "$@"\n    printf "default via 192.168.1.1 dev wlan0 metric 302\n"\n    ;;\n  *) exec /sbin/ip "$@" ;;\nesac\n' \
    > /usr/local/bin/ip && chmod +x /usr/local/bin/ip

# iw / iwconfig / wpa_supplicant stubs: network.sh get_state relies on these.
#   iw wlan0 info       → must output "type managed"
#   iwconfig wlan0      → must output "Signal level=-71 dBm"
#   wpa_supplicant      → fake daemon; started with -c <conf> in entrypoint.sh
#                         so is_wpa_run() (ps | grep wpa_supplicant | grep .conf) succeeds.
# /var/log/wpa_supplicant.log must exist so network.sh prints "wpa_run_once".
COPY scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/iw /usr/local/bin/iwconfig /usr/local/bin/wpa_supplicant && \
    mkdir -p /var/log && touch /var/log/wpa_supplicant.log

# Build the Rockchip hardware stubs natively inside the armhf container.
COPY stubs/ /opt/stubs/
RUN make -C /opt/stubs

# astrometry.net plate-solve stack: apt-installed above (astrometry.net,
# sextractor packages). The ~350 MB public index files are downloaded by
# emulator/astrometry/download_index.sh and bind-mounted at runtime by
# run.sh — NOT baked into the image. solve-field execs astrometry-engine
# WITHOUT a -c flag, so the engine finds its config by a bindir-relative
# fallback: <bindir>/../etc/astrometry.cfg. With bindir=/usr/bin that
# resolves to /usr/etc/astrometry.cfg (NOT /etc) — so the cfg is symlinked
# there below, and also placed at /etc for tools that read the conventional
# path.
RUN printf 'cpulimit 90\ndepths 10 20 30\nminwidth 0.1\nadd_path /usr/local/astrometry/data\ninparallel\nautoindex\n' \
    > /etc/astrometry.cfg && \
    mkdir -p /usr/etc && ln -sf /etc/astrometry.cfg /usr/etc/astrometry.cfg

# Create the pi user and expected directory tree.
# zwoair_imager looks for config/data under /home/pi/ASIAIR/.
RUN useradd -m -s /bin/bash pi

# WiFi config files expected by network.sh (must come after useradd creates /home/pi).
# wlan0.conf holds key_mgmt/wpa_passphrase (read by ap_state for pi_get_ap);
# wpa_supplicant.conf is the wpa config (same file, see symlink below).
# sh_conf.txt (wpa_svr=1) goes into seed/ so it lands in the .ZWO volume mount.
RUN printf 'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\nupdate_config=1\ncountry=US\nwpa_passphrase=password123\n\nnetwork={\n    ssid="sandbox-net"\n    psk="password123"\n    key_mgmt=WPA2-PSK\n    wpa_key_mgmt=WPA2-PSK\n}\n' \
    > /home/pi/wpa_supplicant.conf && \
    ln -s /home/pi/wpa_supplicant.conf /home/pi/wlan0.conf

# zwoair_imager derives its data dir from HOME — in this container that is
# /root. Create the .ZWO directory and seed an empty userData.db3 so
# SQLite::Database can open it without throwing on first access.
# The real database from a live device can be bind-mounted over this at
# runtime (see run.sh) to get the full object catalog.
RUN mkdir -p /root/.ZWO && \
    sqlite3 /root/.ZWO/userData.db3 "VACUUM;" && \
    mkdir -p /tmp/zwo/log

WORKDIR /home/pi/ASIAIR

# entrypoint.sh detects the runtime SN and writes a synthetic zwoair_license
# before the binary's first periodic license check fires (~9 s after start).
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# LD_LIBRARY_PATH search order:
#   1. /opt/stubs   — Rockchip hardware stubs
#   2. /home/pi/ASIAIR/lib  — libyuv, libonnxruntime, libzhistogram
ENV LD_LIBRARY_PATH=/opt/stubs:/home/pi/ASIAIR/lib

# Intercept open("/proc/device-tree/model") and return the expected board
# identity string so hardware detection doesn't abort at startup.
ENV LD_PRELOAD=/opt/stubs/libhwid.so

# Prevent OpenMP/BLAS/ONNX background threads from initializing SIMD routines
# that QEMU can't emulate, which causes a SIGILL ~60s after startup and hangs
# the binary's TCP request-processing thread.
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV ORT_DISABLE_ALL=1

# TCP 4700/4701 — zwoair_imager main JSON-RPC control + secondary listener
# TCP 4800/4801 — zwoair_imager imaging / RTSP + secondary listener
# TCP 80        — zwoair_file_server (spawned by imager)
# UDP 4720      — zwoair_imager UDP channel
EXPOSE 4700 4701 4800 4801 80
EXPOSE 4720/udp

CMD ["/usr/local/bin/entrypoint.sh"]
```

- [ ] **Step 2: Write `.dockerignore`**

Create `/Users/bguthro/Development/seestar_alp/emulator/.dockerignore`:

```
astrometry/index
sim/shared
sim/data
**/__pycache__
run.log
```

- [ ] **Step 3: Build the image and verify it succeeds**

```bash
cd /Users/bguthro/Development/seestar_alp/emulator
docker run --privileged --rm tonistiigi/binfmt --install arm 2>/dev/null || true
docker build --platform linux/arm/v7 -t seestar-emulator .
```

Expected: `Successfully tagged seestar-emulator:latest` (or the final `docker build` success line for your Docker version). This does not require firmware or the index files — it only builds the base image; `solve-field`/`sextractor` install and run correctly per the spike, but running the actual imager binary needs Task 5's `run.sh` plus extracted firmware, which is exercised in Task 9's CI workflow, not here.

- [ ] **Step 4: Sanity-check solve-field is on PATH inside the built image**

```bash
docker run --rm --platform linux/arm/v7 --entrypoint solve-field seestar-emulator --version
docker run --rm --platform linux/arm/v7 --entrypoint sextractor seestar-emulator -v
```

Expected: both print version output without a "command not found" error.

- [ ] **Step 5: Commit**

```bash
cd /Users/bguthro/Development/seestar_alp
git add emulator/Dockerfile emulator/.dockerignore
git commit -m "$(cat <<'EOF'
feat: add emulator Dockerfile with apt-based astrometry stack

Rebuilds the QEMU-armhf container definition with astrometry.net and
sextractor installed via apt (verified against buster/armhf in the
astrometry feasibility spike) instead of staging binaries/libs from a
real device over SSH. Index files are bind-mounted at runtime, not
baked into the image.
EOF
)"
```

---

### Task 5: Update `run.sh` for the new astrometry path and image name

**Files:**
- Create: `emulator/run.sh` (adapted from `~/dev/seestar-api-research/sandbox/run.sh`)

**Interfaces:**
- Consumes: `emulator/astrometry/index/` (Task 3), `seestar-emulator` image (Task 4).

- [ ] **Step 1: Copy `run.sh` as a starting point**

```bash
cp "$HOME/dev/seestar-api-research/sandbox/run.sh" /Users/bguthro/Development/seestar_alp/emulator/run.sh
```

- [ ] **Step 2: Edit it** — three changes to `/Users/bguthro/Development/seestar_alp/emulator/run.sh`:

Change the image name (both the `docker build -t` and `docker run --name`/final image-arg lines) from `seestar-sandbox` to `seestar-emulator`:

```bash
echo "==> Building image (seestar-sandbox)..."
docker build --platform linux/arm/v7 -t seestar-sandbox "${SCRIPT_DIR}"
```
→
```bash
echo "==> Building image (seestar-emulator)..."
docker build --platform linux/arm/v7 -t seestar-emulator "${SCRIPT_DIR}"
```

and at the bottom:
```bash
  -v "${SIM_SHARED}:/run/seestar-sim" \
  seestar-sandbox
```
→
```bash
  -v "${SIM_SHARED}:/run/seestar-sim" \
  seestar-emulator
```

Replace the astrometry staging check/path (the `ASTRO_DATA` block) — old:
```bash
# astrometry.net index files (~350 MB) are bind-mounted at runtime rather than
# baked into the image (see Dockerfile / stage-astrometry.sh). The sim renderer
# and the mount/frame stubs share files through sim/shared <-> /run/seestar-sim.
ASTRO_DATA="${SCRIPT_DIR}/sim/astrometry-stage/root/usr/local/astrometry/data"
SIM_SHARED="${SCRIPT_DIR}/sim/shared"
mkdir -p "${SIM_SHARED}"
if [[ ! -f "${ASTRO_DATA}/index-4112-Vt.fits" ]]; then
  echo "WARNING: astrometry index files not staged at ${ASTRO_DATA}"
  echo "         plate solving will fail — run ./stage-astrometry.sh first."
fi
```
with:
```bash
# astrometry.net index files (~350 MB, public data.astrometry.net release)
# are bind-mounted at runtime rather than baked into the image (see
# Dockerfile / astrometry/download_index.sh). The sim renderer and the
# mount/frame stubs share files through sim/shared <-> /run/seestar-sim.
ASTRO_DATA="${SCRIPT_DIR}/astrometry/index"
SIM_SHARED="${SCRIPT_DIR}/sim/shared"
mkdir -p "${SIM_SHARED}"
if [[ ! -f "${ASTRO_DATA}/index-4112.fits" ]]; then
  echo "WARNING: astrometry index files not downloaded at ${ASTRO_DATA}"
  echo "         plate solving will fail — run ./astrometry/download_index.sh first."
fi
```

Also update the trailing usage hint:
```bash
Once running, in a second terminal:
  python3 auth_test.py --pem ~/dev/seestar_private_key.pem
```
stays as-is (that test script isn't moved in this plan — see the note at the end of this document about the remaining `*_test.py` files).

- [ ] **Step 3: Verify with a dry run of the option parsing** (does not require firmware)

```bash
cd /Users/bguthro/Development/seestar_alp/emulator
bash -n run.sh
./run.sh --help
```

Expected: `bash -n` prints nothing (no syntax error); `--help` prints the usage text with no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/bguthro/Development/seestar_alp
git add emulator/run.sh
git commit -m "feat: update emulator run.sh for public-source astrometry path and image rename"
```

---

### Task 6: Move `apk_utils.py` (unmodified)

**Files:**
- Create: `emulator/firmware/apk_utils.py`
- Create: `emulator/firmware/__init__.py`

**Interfaces:**
- Produces: `open_apk(path, containing=None)` context manager — consumed by Task 7's `extract_iscope.py` and Task 8's `provision.py`.

- [ ] **Step 1: Copy the file**

```bash
mkdir -p /Users/bguthro/Development/seestar_alp/emulator/firmware
touch /Users/bguthro/Development/seestar_alp/emulator/firmware/__init__.py
cp ~/dev/seestar-api-research/scripts/apk_utils.py /Users/bguthro/Development/seestar_alp/emulator/firmware/apk_utils.py
```

- [ ] **Step 2: Verify it's importable**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -c "from emulator.firmware.apk_utils import open_apk; print(open_apk)"
```

Expected: prints `<function open_apk at 0x...>` with no import error.

- [ ] **Step 3: Commit**

```bash
git add emulator/firmware/__init__.py emulator/firmware/apk_utils.py
git commit -m "feat: relocate apk_utils.py (APK/XAPK opening) from seestar-api-research"
```

---

### Task 7: Move and trim `extract_iscope.py` (extract-only, no repack)

**Files:**
- Create: `emulator/firmware/extract_iscope.py`

**Interfaces:**
- Consumes: `emulator.firmware.apk_utils.open_apk` (Task 6).
- Produces: `extract_iscope_from_apk(apk_path: str, output_dir: str, variant: str | None = None) -> Path` — the path to the extracted `iscope/` (or `iscope_64/`) directory. Consumed by Task 8's `provision.py`.

The original `extract_iscope.py` has an `extract` subcommand (needed) and a `repack` subcommand (uploading a *modified* firmware back to a real device — out of scope for the emulator, per Global Constraints). This task keeps only the extract path, and exposes it as an importable function (not just a CLI) so `provision.py` can call it directly.

- [ ] **Step 1: Write the trimmed file**

Create `/Users/bguthro/Development/seestar_alp/emulator/firmware/extract_iscope.py`:

```python
#!/usr/bin/env python3
"""Extract iscope firmware assets from a Seestar APK/XAPK.

Trimmed from seestar-api-research/scripts/extract_iscope.py: only the
extract path is kept here (no `repack`, which signs and re-uploads a
modified firmware to a real device — irrelevant to running the emulator).
"""

import argparse
import io
import shutil
import sys
import tarfile
from pathlib import Path

from emulator.firmware.apk_utils import open_apk

ISCOPE_ASSETS = ["assets/iscope", "assets/iscope_64"]
BAR_WIDTH = 40


def _bar(done, total):
    filled = int(BAR_WIDTH * done / total) if total else BAR_WIDTH
    return "[" + "#" * filled + "-" * (BAR_WIDTH - filled) + "]"


def _progress(label, done, total, suffix=""):
    pct = done / total * 100 if total else 100
    sys.stdout.write(f"\r  {label} {_bar(done, total)} {pct:5.1f}%{suffix}  ")
    sys.stdout.flush()


def _done(label, msg):
    sys.stdout.write(f"\r  {label} {_bar(1, 1)} 100.0%  \n")
    sys.stdout.flush()
    print(f"  -> {msg}")


def _read_zip_entry(z, name):
    """Read a ZIP entry in chunks, showing a progress bar."""
    total = z.getinfo(name).file_size
    label = f"Reading  {Path(name).name}"
    buf = io.BytesIO()
    with z.open(name) as src:
        while True:
            chunk = src.read(1 << 20)  # 1 MB
            if not chunk:
                break
            buf.write(chunk)
            _progress(label, buf.tell(), total, f"  {buf.tell() >> 20}/{total >> 20} MB")
    _done(label, f"{total >> 20} MB read")
    buf.seek(0)
    return buf.read()


def _extract_tar(data: bytes, variant: str, subdir: Path) -> None:
    if subdir.exists():
        shutil.rmtree(subdir)
    subdir.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as tar:
        members = tar.getmembers()
        label = f"Extracting {variant}"
        for i, member in enumerate(members):
            _progress(label, i, len(members), f"  {member.name[:30]}")
            tar.extract(member, subdir, filter="fully_trusted")
        _done(label, str(subdir) + "/")


def extract_iscope_from_apk(apk_path: str, output_dir: str, variant: str | None = None) -> Path:
    """Extract the iscope tar(s) from an APK/XAPK into output_dir.

    Returns the path to the extracted variant directory (output_dir/iscope
    or output_dir/iscope_64). If both variants are present and `variant` is
    not given, extracts both and returns the `iscope` path.
    """
    out = Path(output_dir)
    with open_apk(apk_path, containing=ISCOPE_ASSETS) as z:
        available = [n for n in ISCOPE_ASSETS if n in z.namelist()]
        if variant:
            available = [n for n in available if Path(n).name == variant]
        if not available:
            raise ValueError(f"No iscope assets found in {apk_path}")
        result_path = None
        for name in available:
            variant_name = Path(name).name
            print(f"\n{variant_name}")
            data = _read_zip_entry(z, name)
            variant_dir = out / variant_name
            _extract_tar(data, variant_name, variant_dir)
            if result_path is None or variant_name == "iscope":
                result_path = variant_dir
        return result_path


def main():
    parser = argparse.ArgumentParser(description="Extract iscope assets from a Seestar APK/XAPK")
    parser.add_argument("--apk", required=True, help="Path to the APK or XAPK file")
    parser.add_argument(
        "--variant", choices=["iscope", "iscope_64"], help="Extract only this variant (default: both)"
    )
    parser.add_argument("output_dir", help="Directory to extract into")
    args = parser.parse_args()
    extract_iscope_from_apk(args.apk, args.output_dir, variant=args.variant)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it runs against an already-locally-downloaded XAPK**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -m emulator.firmware.extract_iscope --apk ~/dev/firmware/v3.1.2/Seestar_v3.1.2_apkpure.com.xapk /tmp/extract_iscope_test
ls /tmp/extract_iscope_test/iscope
```

Expected: extraction progress output, then a listing showing `deb/`, `update_package.sh`, etc. under `/tmp/extract_iscope_test/iscope`.

- [ ] **Step 3: Clean up the scratch extraction and commit**

```bash
rm -rf /tmp/extract_iscope_test
git add emulator/firmware/extract_iscope.py
git commit -m "feat: relocate and trim extract_iscope.py (extract-only, no repack)"
```

---

### Task 8: Write the pinned firmware version matrix

**Files:**
- Create: `emulator/firmware/versions.yaml`

**Interfaces:**
- Produces: a YAML document consumed by Task 9's `provision.py` and Task 15's CI workflow.

- [ ] **Step 1: Write the file**

Version/version_code pairs below are real, taken directly from `seestar-api-research/README.md`'s tracked-versions table (not placeholders).

Create `/Users/bguthro/Development/seestar_alp/emulator/firmware/versions.yaml`:

```yaml
# Pinned firmware versions for the CI regression suite (tests/system).
#
# version_code is APKPure's numeric build identifier, required to fetch a
# specific historical release via https://d.apkpure.com/b/XAPK/com.zwo.seestar?versionCode=<code>
# (APKPure's UI only shows the latest version by default). Update this list
# via PR when a new firmware ships or an old one should be dropped —
# human-curated, per the project's design doc.
#
# `smoke` marks the single version used by the always-on PR smoke lane
# (emulator-smoke.yml). `full` marks every version used by the full-matrix
# lane (emulator-full.yml, label/nightly-gated).
smoke_version: "3.3.0"

full_versions:
  - version: "3.3.0"
    version_code: "2846"
  - version: "3.1.2"
    version_code: "2732"
  - version: "3.0.0"
    version_code: "2645"
```

- [ ] **Step 2: Verify it parses**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -c "
import yaml
with open('emulator/firmware/versions.yaml') as f:
    doc = yaml.safe_load(f)
assert doc['smoke_version'] == '3.3.0'
assert len(doc['full_versions']) == 3
assert doc['full_versions'][0]['version_code'] == '2846'
print('OK', doc)
"
```

Expected: prints `OK {...}` with no assertion error. (`PyYAML` is already a top-level dependency of this repo.)

- [ ] **Step 3: Commit**

```bash
git add emulator/firmware/versions.yaml
git commit -m "feat: add pinned firmware version matrix for CI (versions.yaml)"
```

---

### Task 9: Write `provision.py` (CI firmware acquisition)

**Files:**
- Create: `emulator/firmware/provision.py`
- Test: `emulator/firmware/test_provision.py`

**Interfaces:**
- Consumes: `emulator.firmware.apk_utils.open_apk` (Task 6), `emulator.firmware.extract_iscope.extract_iscope_from_apk` (Task 7).
- Produces: `download_xapk(version: str, version_code: str, dest_dir: Path) -> Path` (downloads or reuses a cached XAPK), `provision_firmware(version: str, version_code: str, work_dir: Path) -> Path` (returns the path to the extracted+dpkg-unpacked `deb/out` tree, matching what `run.sh`'s `FW_BASE` expects: `<version_dir>/iscope/deb/out`). Consumed by Task 15's CI workflow.

- [ ] **Step 1: Write the failing test first** (covers the parts that don't require a real network call or a real `.deb`)

Create `/Users/bguthro/Development/seestar_alp/emulator/firmware/test_provision.py`:

```python
import io
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from emulator.firmware.provision import download_xapk, provision_firmware


def test_download_xapk_reuses_existing_cached_file(tmp_path):
    dest_dir = tmp_path / "cache"
    dest_dir.mkdir()
    cached = dest_dir / "firmware-2732.xapk"
    cached.write_bytes(b"cached-bytes")

    with patch("emulator.firmware.provision._fetch_xapk_bytes") as mock_fetch:
        result = download_xapk(version="3.1.2", version_code="2732", dest_dir=dest_dir)

    mock_fetch.assert_not_called()
    assert result == cached
    assert result.read_bytes() == b"cached-bytes"


def test_download_xapk_fetches_on_cache_miss(tmp_path):
    dest_dir = tmp_path / "cache"

    with patch("emulator.firmware.provision._fetch_xapk_bytes", return_value=b"fresh-bytes") as mock_fetch:
        result = download_xapk(version="3.1.2", version_code="2732", dest_dir=dest_dir)

    mock_fetch.assert_called_once_with("2732")
    assert result == dest_dir / "firmware-2732.xapk"
    assert result.read_bytes() == b"fresh-bytes"


def test_provision_firmware_extracts_and_unpacks_debs(tmp_path):
    # Build a minimal fake XAPK containing one tiny .deb so dpkg -x has
    # something real to unpack, exercising the full provision_firmware path
    # without touching the network.
    import tarfile
    import zipfile

    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # A trivial .deb: dpkg-deb needs a real archive, so build one with
    # dpkg-deb if available; otherwise skip (CI/dev machines running this
    # test are expected to have dpkg-deb, same as the emulator provisioning
    # step itself requires dpkg -x).
    if subprocess.run(["which", "dpkg-deb"], capture_output=True).returncode != 0:
        pytest.skip("dpkg-deb not available on this machine")

    pkg_root = tmp_path / "pkg_root"
    (pkg_root / "DEBIAN").mkdir(parents=True)
    (pkg_root / "DEBIAN" / "control").write_text(
        "Package: testpkg\nVersion: 1.0\nArchitecture: armhf\nMaintainer: test\nDescription: test\n"
    )
    (pkg_root / "usr" / "bin").mkdir(parents=True)
    (pkg_root / "usr" / "bin" / "hello").write_text("#!/bin/sh\necho hi\n")
    deb_path = tmp_path / "testpkg.deb"
    subprocess.run(["dpkg-deb", "--build", str(pkg_root), str(deb_path)], check=True)

    iscope_dir = tmp_path / "iscope_src"
    (iscope_dir / "deb").mkdir(parents=True)
    (iscope_dir / "deb" / "testpkg.deb").write_bytes(deb_path.read_bytes())

    tar_path = tmp_path / "iscope.tar.bz2"
    with tarfile.open(tar_path, "w:bz2") as tar:
        tar.add(iscope_dir / "deb", arcname="deb")

    xapk_path = tmp_path / "firmware-9999.xapk"
    with zipfile.ZipFile(xapk_path, "w") as z:
        z.writestr("manifest.json", "{}")
        io_buf = io.BytesIO()
        with zipfile.ZipFile(io_buf, "w") as inner:
            inner.writestr("assets/iscope", tar_path.read_bytes())
        z.writestr("base.apk", io_buf.getvalue())

    with patch("emulator.firmware.provision.download_xapk", return_value=xapk_path):
        deb_out = provision_firmware(version="9.9.9", version_code="9999", work_dir=work_dir)

    assert deb_out == work_dir / "9.9.9" / "iscope" / "deb" / "out"
    assert (deb_out / "usr" / "bin" / "hello").exists()
```

- [ ] **Step 2: Run it to verify it fails** (module doesn't exist yet)

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -m pytest emulator/firmware/test_provision.py -v
```

Expected: `ModuleNotFoundError: No module named 'emulator.firmware.provision'`.

- [ ] **Step 3: Write `provision.py`**

Create `/Users/bguthro/Development/seestar_alp/emulator/firmware/provision.py`:

```python
#!/usr/bin/env python3
"""CI firmware acquisition: download (or reuse a cached) APKPure XAPK for a
pinned version, extract iscope, and dpkg -x the .deb packages into the
deb/out tree emulator/run.sh expects.

Adapted from seestar-api-research/scripts/install_firmware.py's
download_version() — trimmed to just the non-interactive download path
(no interactive version picker, no real-device upload; those are irrelevant
to CI provisioning).
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from emulator.firmware.extract_iscope import extract_iscope_from_apk

SEESTAR_PACKAGE = "com.zwo.seestar"


def _fetch_xapk_bytes(version_code: str) -> bytes:
    """Download the XAPK bytes for a given APKPure version code."""
    import cloudscraper

    url = f"https://d.apkpure.com/b/XAPK/{SEESTAR_PACKAGE}?versionCode={version_code}"
    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
    response = scraper.get(url, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Could not download version_code={version_code} from APKPure (HTTP {response.status_code})")
    return response.content


def download_xapk(version: str, version_code: str, dest_dir: Path) -> Path:
    """Return the path to the version's XAPK, downloading only on a cache miss."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"firmware-{version_code}.xapk"
    if dest_path.exists():
        print(f"  Using cached XAPK: {dest_path}")
        return dest_path
    print(f"  Downloading firmware v{version} (version_code={version_code})...")
    data = _fetch_xapk_bytes(version_code)
    dest_path.write_bytes(data)
    return dest_path


def _unpack_debs(deb_dir: Path, out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    debs = sorted(deb_dir.glob("*.deb"))
    if not debs:
        raise RuntimeError(f"No .deb files found in {deb_dir}")
    if shutil.which("dpkg") is None:
        raise RuntimeError("'dpkg' not found on PATH — required to unpack firmware .deb files")
    for deb in debs:
        result = subprocess.run(["dpkg", "-x", str(deb), str(out_dir)])
        if result.returncode != 0:
            print(f"  Warning: dpkg failed for {deb.name} (exit {result.returncode})", file=sys.stderr)


def provision_firmware(version: str, version_code: str, work_dir: Path) -> Path:
    """Ensure firmware `version` is downloaded and extracted under work_dir.

    Returns the path to <work_dir>/<version>/iscope/deb/out, matching what
    emulator/run.sh's FW_BASE expects.
    """
    work_dir = Path(work_dir)
    version_dir = work_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)

    xapk_path = download_xapk(version=version, version_code=version_code, dest_dir=work_dir / "_xapk_cache")
    iscope_dir = extract_iscope_from_apk(str(xapk_path), str(version_dir), variant="iscope")

    deb_dir = iscope_dir / "deb"
    out_dir = deb_dir / "out"
    _unpack_debs(deb_dir, out_dir)
    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Provision emulator firmware for CI")
    parser.add_argument("--version", required=True, help='e.g. "3.1.2"')
    parser.add_argument("--version-code", required=True, help='APKPure versionCode, e.g. "2732"')
    parser.add_argument("--work-dir", required=True, help="Directory to download/extract into")
    args = parser.parse_args()
    deb_out = provision_firmware(version=args.version, version_code=args.version_code, work_dir=Path(args.work_dir))
    print(deb_out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -m pytest emulator/firmware/test_provision.py -v
```

Expected: 3 passed (or 2 passed, 1 skipped if `dpkg-deb` isn't installed on this machine — install it via `brew install dpkg` on macOS to run all three).

- [ ] **Step 5: Commit**

```bash
git add emulator/firmware/provision.py emulator/firmware/test_provision.py
git commit -m "$(cat <<'EOF'
feat: add CI firmware provisioning (download-or-cache, extract, dpkg -x)

Adapted from install_firmware.py's non-interactive download path.
Idempotent: a pre-populated XAPK cache directory (restored from GitHub
Actions cache, keyed on version_code) skips the APKPure fetch entirely.
EOF
)"
```

---

### Task 10: Register the `emulator` extra and new pytest markers in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `pip install -e '.[emulator]'` installs `cloudscraper` + `beautifulsoup4` (needed by `provision.py`'s `_fetch_xapk_bytes`). Registers `smoke` and `full` pytest markers.

- [ ] **Step 1: Edit `pyproject.toml`**

In `/Users/bguthro/Development/seestar_alp/pyproject.toml`, change:

```toml
[project.optional-dependencies]
v2 = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "websockets>=12",
    "httpx>=0.27",
]
system = [
    "pytest-playwright>=0.5",
]
```

to:

```toml
[project.optional-dependencies]
v2 = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "websockets>=12",
    "httpx>=0.27",
]
system = [
    "pytest-playwright>=0.5",
]
emulator = [
    "cloudscraper>=1.2.71",
    "beautifulsoup4>=4.12.0",
]
```

And change:

```toml
markers = [
    "integration: end-to-end integration tests that may use sockets/processes",
    "system: manual-only system tests against a real Seestar or the QEMU sandbox; never auto-selected, requires --target",
]
```

to:

```toml
markers = [
    "integration: end-to-end integration tests that may use sockets/processes",
    "system: manual-only system tests against a real Seestar or the QEMU emulator; never auto-selected, requires --target",
    "smoke: tests/system subset requiring no plate-solving (startup w/o 3PPA, live-view) — used by the always-on CI emulator-smoke lane",
    "full: tests/system subset requiring plate-solving (3PPA, goto, schedule) — used by the label/nightly-gated CI emulator-full lane",
]
```

- [ ] **Step 2: Verify the TOML is well-formed and pip can resolve the new extra**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('OK')"
python3 -m pytest --markers | grep -E "^@pytest.mark.(smoke|full):"
```

Expected: `OK`, then two lines showing the new `smoke` and `full` marker descriptions.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add emulator optional-dependency group and smoke/full pytest markers"
```

---

### Task 11: Rename `--target sandbox` → `--target emulator` throughout `tests/system`

**Files:**
- Modify: `tests/system/conftest.py`
- Modify: `tests/system/target.py`
- Modify: `tests/system/test_target.py`

**Interfaces:**
- Produces: `SystemTestTarget.kind` values are `"emulator"` | `"real"` (was `"sandbox"` | `"real"`). `check_emulator_renderer_fresh()` replaces `check_sandbox_renderer_fresh()`.

- [ ] **Step 1: Edit `tests/system/target.py`** — rename the function and its "sandbox" references

In `/Users/bguthro/Development/seestar_alp/tests/system/target.py`, change:

```python
def check_sandbox_renderer_fresh(shared_dir: Path) -> None:
    """Verify the synthetic-sky renderer has produced output at least once.

    Only checks existence, not recency: sim.renderd re-renders solve.fits
    only in response to a pointing change (it watches pointing.json's `seq`
    field), so an idle-but-running renderer can leave a solve.fits that's
    hours old with no pointing activity to trigger a fresh render. A stale
    file is not evidence the renderer is down — only a missing file is.
    Actual renderer liveness during a run is proven by the goto/3PPA test
    itself succeeding (or timing out with a clear failure otherwise).
    """
    solve_fits = Path(shared_dir) / "solve.fits"
    if not solve_fits.exists():
        raise PreconditionError(
            f"{solve_fits} does not exist. Goto/3PPA against the sandbox is "
            f"closed-loop and needs the synthetic-sky renderer running on the "
            f"host first:\n"
            f"  python3 -m sim.renderd --shared {shared_dir} --model S50 "
            f"--catalog sim/data/stars.npy\n"
            f"(run from the seestar-api-research/sandbox checkout)"
        )
```

to:

```python
def check_emulator_renderer_fresh(shared_dir: Path) -> None:
    """Verify the synthetic-sky renderer has produced output at least once.

    Only checks existence, not recency: sim.renderd re-renders solve.fits
    only in response to a pointing change (it watches pointing.json's `seq`
    field), so an idle-but-running renderer can leave a solve.fits that's
    hours old with no pointing activity to trigger a fresh render. A stale
    file is not evidence the renderer is down — only a missing file is.
    Actual renderer liveness during a run is proven by the goto/3PPA test
    itself succeeding (or timing out with a clear failure otherwise).
    """
    solve_fits = Path(shared_dir) / "solve.fits"
    if not solve_fits.exists():
        raise PreconditionError(
            f"{solve_fits} does not exist. Goto/3PPA against the emulator is "
            f"closed-loop and needs the synthetic-sky renderer running on the "
            f"host first:\n"
            f"  python3 -m sim.renderd --shared {shared_dir} --model S50 "
            f"--catalog sim/data/stars.npy\n"
            f"(run from the emulator/ checkout)"
        )
```

Also change the dataclass comment `kind: str  # "sandbox" | "real"` to `kind: str  # "emulator" | "real"`.

- [ ] **Step 2: Edit `tests/system/conftest.py`**

Change:
```python
from tests.system.target import (  # noqa: E402
    PreconditionError,
    SystemTestTarget,
    build_config_toml,
    check_sandbox_renderer_fresh,
    find_free_port,
    probe_tcp_port,
)
```
to:
```python
from tests.system.target import (  # noqa: E402
    PreconditionError,
    SystemTestTarget,
    build_config_toml,
    check_emulator_renderer_fresh,
    find_free_port,
    probe_tcp_port,
)
```

Change:
```python
    group.addoption(
        "--target",
        choices=["sandbox", "real"],
        default=None,
        help="Run tests/system/ against the QEMU sandbox or a real Seestar. "
        "Omitting this skips the entire tests/system/ directory.",
    )
```
to:
```python
    group.addoption(
        "--target",
        choices=["emulator", "real"],
        default=None,
        help="Run tests/system/ against the QEMU emulator or a real Seestar. "
        "Omitting this skips the entire tests/system/ directory.",
    )
```

Change:
```python
    group.addoption(
        "--renderer-shared-dir",
        default=None,
        help="Path to seestar-api-research/sandbox/sim/shared "
        "(required when --target sandbox, for the goto precondition check).",
    )
```
to:
```python
    group.addoption(
        "--renderer-shared-dir",
        default=None,
        help="Path to emulator/sim/shared "
        "(required when --target emulator, for the goto precondition check).",
    )
```

Change:
```python
    if kind is None:
        pytest.skip("no --target given")

    if kind == "real" and request.config.getoption("--capture") != "no":
        raise PreconditionError(
            "--target real requires interactive confirmation before goto/"
            "schedule steps. Re-run with -s, e.g.:\n"
            "  pytest tests/system --target real --host <ip> -s"
        )
```
(unchanged — `kind == "real"` branch stays as-is)

Change:
```python
    probe_tcp_port(t.host, 4700, "device control port")
    probe_tcp_port(t.host, 4800, "device imaging port")
    if kind == "sandbox":
        if t.renderer_shared_dir is None:
            raise PreconditionError(
                "--target sandbox requires --renderer-shared-dir pointing at "
                "seestar-api-research/sandbox/sim/shared (goto/3PPA there is "
                "closed-loop and needs sim.renderd running on the host)."
            )
        check_sandbox_renderer_fresh(t.renderer_shared_dir)
```
to:
```python
    probe_tcp_port(t.host, 4700, "device control port")
    probe_tcp_port(t.host, 4800, "device imaging port")
    if kind == "emulator":
        if t.renderer_shared_dir is None:
            raise PreconditionError(
                "--target emulator requires --renderer-shared-dir pointing at "
                "emulator/sim/shared (goto/3PPA there is "
                "closed-loop and needs sim.renderd running on the host)."
            )
        check_emulator_renderer_fresh(t.renderer_shared_dir)
```

Also update the module docstring at the top:
```python
"""pytest configuration for the manual-only system test suite.

Never auto-selected: everything under tests/system/ is skipped unless
--target is explicitly passed, so a bare `pytest` run (or the CI lanes in
AGENTS.md) never reaches out to real hardware or the sandbox.
"""
```
to:
```python
"""pytest configuration for the manual-only system test suite.

Never auto-selected: everything under tests/system/ is skipped unless
--target is explicitly passed, so a bare `pytest` run (or the fast/simulator
CI lanes in AGENTS.md) never reaches out to real hardware or the emulator.
The CI lanes that DO exercise this suite (emulator-smoke.yml,
emulator-full.yml) pass --target emulator explicitly, same as a human would.
"""
```

- [ ] **Step 3: Edit `tests/system/test_target.py`** — rename the imported function and all `"sandbox"` string literals

Change:
```python
from tests.system.target import (
    PreconditionError,
    SystemTestTarget,
    build_config_toml,
    check_sandbox_renderer_fresh,
    find_free_port,
    probe_tcp_port,
)
```
to:
```python
from tests.system.target import (
    PreconditionError,
    SystemTestTarget,
    build_config_toml,
    check_emulator_renderer_fresh,
    find_free_port,
    probe_tcp_port,
)
```

Rename every call site and test name: `check_sandbox_renderer_fresh` → `check_emulator_renderer_fresh` (4 call sites: `test_check_sandbox_renderer_fresh_raises_when_missing`, `test_check_sandbox_renderer_fresh_passes_when_stale`, `test_check_sandbox_renderer_fresh_passes_when_recent`, plus the `build_config_toml` test's `kind="sandbox"`). Specifically:

```python
def test_check_sandbox_renderer_fresh_raises_when_missing(tmp_path):
    with pytest.raises(PreconditionError, match="renderd"):
        check_sandbox_renderer_fresh(tmp_path)
```
→
```python
def test_check_emulator_renderer_fresh_raises_when_missing(tmp_path):
    with pytest.raises(PreconditionError, match="renderd"):
        check_emulator_renderer_fresh(tmp_path)
```

```python
def test_check_sandbox_renderer_fresh_passes_when_stale(tmp_path):
    ...
    os.utime(solve_fits, (old_time, old_time))
    check_sandbox_renderer_fresh(tmp_path)
```
→
```python
def test_check_emulator_renderer_fresh_passes_when_stale(tmp_path):
    ...
    os.utime(solve_fits, (old_time, old_time))
    check_emulator_renderer_fresh(tmp_path)
```

```python
def test_check_sandbox_renderer_fresh_passes_when_recent(tmp_path):
    solve_fits = tmp_path / "solve.fits"
    solve_fits.write_bytes(b"x")
    check_sandbox_renderer_fresh(tmp_path)
```
→
```python
def test_check_emulator_renderer_fresh_passes_when_recent(tmp_path):
    solve_fits = tmp_path / "solve.fits"
    solve_fits.write_bytes(b"x")
    check_emulator_renderer_fresh(tmp_path)
```

```python
    target = SystemTestTarget(
        kind="sandbox",
```
→
```python
    target = SystemTestTarget(
        kind="emulator",
```

- [ ] **Step 4: Run the test file to verify it passes**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -m pytest tests/system/test_target.py -v
```

Expected: all tests pass, including the renamed ones.

- [ ] **Step 5: Verify nothing else in the repo still references the old names**

```bash
grep -rn "check_sandbox_renderer_fresh\|--target sandbox\|kind == \"sandbox\"\|kind=\"sandbox\"" /Users/bguthro/Development/seestar_alp --include="*.py" --include="*.md"
```

Expected: no output (README references are updated in Task 16).

- [ ] **Step 6: Commit**

```bash
git add tests/system/target.py tests/system/conftest.py tests/system/test_target.py
git commit -m "$(cat <<'EOF'
refactor: rename --target sandbox to --target emulator in tests/system

Renames check_sandbox_renderer_fresh -> check_emulator_renderer_fresh
and every "sandbox" string literal/reference, matching the emulator/
directory name. --target real is unaffected. The "never auto-selected
without --target" skip guard in conftest.py is unchanged in behavior.
EOF
)"
```

---

### Task 12: Add a `polar_align` toggle to `run_startup()` (enables the no-3PPA smoke path)

**Files:**
- Modify: `tests/system/ui_classic.py`
- Modify: `tests/system/ui_v2.py`

**Interfaces:**
- Produces: `run_startup(page, base_url, polar_align: bool = True)` in both drivers. `polar_align=True` (default) preserves today's behavior exactly (used by the full tier). `polar_align=False` unchecks `#polar_align` and only waits for `AutoFocus`/`DarkLibrary` to complete (used by the smoke tier — no plate-solving).

- [ ] **Step 1: Edit `tests/system/ui_classic.py`**

Change:
```python
def run_startup(page: Page, base_url: str) -> None:
    page.goto(_device_path(base_url, "/startup"))
    page.check("#auto_focus")
    page.check("#dark_frames")
    # Leave #polar_align at its default (checked) — full startup sequence.
    page.click("button[type='submit'][value='start']")

    status = page.locator("#eventStatusContent")
    expect(status).to_contain_text("AutoFocus", timeout=5000)

    deadline = time.time() + 180
    while time.time() < deadline:
        text = status.inner_text()
        if "fail" in text.lower():
            raise AssertionError(f"Startup sequence reported a failure:\n{text}")
        # All three enabled events (AutoFocus, DarkLibrary, 3PPA) must show
        # "complete" — Scheduler/WheelMove/PlateSolve cards may stay idle.
        watched = re.findall(
            r"(AutoFocus|DarkLibrary|PolarAlign)[\s\S]{0,120}?State:\s*(\S+)",
            text,
        )
        if len(watched) >= 3 and all(
            state.strip().lower() == "complete" for _, state in watched
        ):
            return
        page.wait_for_timeout(2000)
    raise AssertionError(
        f"Startup sequence did not complete within 180s:\n{status.inner_text()}"
    )
```

to:
```python
def run_startup(page: Page, base_url: str, polar_align: bool = True) -> None:
    page.goto(_device_path(base_url, "/startup"))
    page.check("#auto_focus")
    page.check("#dark_frames")
    if polar_align:
        pass  # #polar_align defaults to checked — full startup sequence.
    else:
        page.uncheck("#polar_align")
    page.click("button[type='submit'][value='start']")

    status = page.locator("#eventStatusContent")
    expect(status).to_contain_text("AutoFocus", timeout=5000)

    watched_events = ["AutoFocus", "DarkLibrary", "PolarAlign"] if polar_align else ["AutoFocus", "DarkLibrary"]
    pattern = re.compile(
        r"(" + "|".join(watched_events) + r")[\s\S]{0,120}?State:\s*(\S+)"
    )

    deadline = time.time() + 180
    while time.time() < deadline:
        text = status.inner_text()
        if "fail" in text.lower():
            raise AssertionError(f"Startup sequence reported a failure:\n{text}")
        # All enabled events must show "complete" — Scheduler/WheelMove/
        # PlateSolve cards may stay idle regardless.
        watched = pattern.findall(text)
        if len(watched) >= len(watched_events) and all(
            state.strip().lower() == "complete" for _, state in watched
        ):
            return
        page.wait_for_timeout(2000)
    raise AssertionError(
        f"Startup sequence did not complete within 180s:\n{status.inner_text()}"
    )
```

- [ ] **Step 2: Read and apply the equivalent change to `tests/system/ui_v2.py`**

First read the current `run_startup()` in `ui_v2.py`:

```bash
grep -n "def run_startup" -A 40 /Users/bguthro/Development/seestar_alp/tests/system/ui_v2.py
```

Apply the same shape of change as Step 1: add a `polar_align: bool = True` parameter, call `page.uncheck(...)` (or the v2-frontend equivalent locator/interaction for the polar-align checkbox — match whatever selector/pattern `ui_v2.py`'s existing startup driver already uses for its own checkbox/toggle elements and completion-polling regex) when `polar_align=False`, and narrow the completion-wait to only the enabled events. Keep `polar_align=True`'s behavior byte-for-byte identical to the current implementation (same selectors, same timeouts, same regex shape) — only the `False` branch is new behavior.

- [ ] **Step 3: Verify the default-argument behavior is unchanged (no emulator needed)**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -c "
import inspect
from tests.system import ui_classic
sig = inspect.signature(ui_classic.run_startup)
assert list(sig.parameters) == ['page', 'base_url', 'polar_align'], sig.parameters
assert sig.parameters['polar_align'].default is True
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add tests/system/ui_classic.py tests/system/ui_v2.py
git commit -m "$(cat <<'EOF'
feat: add polar_align toggle to run_startup() for the no-3PPA smoke path

Default True preserves today's full-startup behavior exactly. False
skips #polar_align and only waits for AutoFocus/DarkLibrary, enabling
a smoke-tier startup check with no plate-solving involved at all.
EOF
)"
```

---

### Task 13: Add `smoke`/`full` markers to the `tests/system` flow tests

**Files:**
- Modify: `tests/system/test_flow.py`

**Interfaces:**
- Consumes: `run_startup(page, base_url, polar_align=...)` (Task 12).
- Produces: `pytest tests/system --target emulator -m smoke` runs only `test_startup` (no 3PPA) + `test_live_imaging_standalone`. `pytest tests/system --target emulator -m full` runs the complete existing 4-step flow, unmodified in behavior.

- [ ] **Step 1: Edit `tests/system/test_flow.py`**

Change:
```python
"""The 4-step system test flow: startup -> goto -> live imaging ->
scheduled star capture with a concurrent live-imaging check.

Runs once per frontend selected via --frontend (classic, v2, or both).
"""

import time

import pytest

from tests.system import ui_classic, ui_v2

pytestmark = pytest.mark.system
```
to:
```python
"""The 4-step system test flow: startup -> goto -> live imaging ->
scheduled star capture with a concurrent live-imaging check.

Runs once per frontend selected via --frontend (classic, v2, or both).

test_startup and test_live_imaging_standalone are @pytest.mark.smoke: no
plate-solving is involved (startup runs with polar_align=False, skipping
3PPA). test_goto and test_schedule_capture_with_concurrent_live_check are
@pytest.mark.full: both target an RA/Dec and exercise the plate-solving-
dependent path (goto/3PPA against the emulator's synthetic-sky renderer).
"""

import time

import pytest

from tests.system import ui_classic, ui_v2

pytestmark = pytest.mark.system
```

Change:
```python
def test_startup(page, app_base_url, driver):
    driver.run_startup(page, app_base_url)
```
to:
```python
@pytest.mark.smoke
@pytest.mark.full
def test_startup(page, app_base_url, driver, request):
    polar_align = request.config.getoption("-m") != "smoke"
    driver.run_startup(page, app_base_url, polar_align=polar_align)
```

Change:
```python
def test_goto(page, app_base_url, driver, target, require_real_confirmation):
```
to:
```python
@pytest.mark.full
def test_goto(page, app_base_url, driver, target, require_real_confirmation):
```

Change:
```python
def test_live_imaging_standalone(page, app_base_url, driver):
```
to:
```python
@pytest.mark.smoke
@pytest.mark.full
def test_live_imaging_standalone(page, app_base_url, driver):
```

Change:
```python
def test_schedule_capture_with_concurrent_live_check(
    page, app_base_url, driver, target, require_real_confirmation
):
```
to:
```python
@pytest.mark.full
def test_schedule_capture_with_concurrent_live_check(
    page, app_base_url, driver, target, require_real_confirmation
):
```

**Important note for the implementer:** `request.config.getoption("-m")` reads pytest's raw `-m` expression string, which is fragile for anything beyond the exact literal `-m smoke`/`-m full` this repo's CI uses (e.g. `-m "smoke or full"` would break the `!= "smoke"` check). Since `test_startup` needs to know *which* tier selected it, and pytest doesn't expose "which markers caused this test to be selected" to the test itself, use a dedicated CLI option instead of parsing `-m`:

Add to `tests/system/conftest.py`'s `pytest_addoption` (alongside the other options from Task 11):
```python
    group.addoption(
        "--startup-polar-align",
        action="store_true",
        default=True,
        help="Run the startup flow's 3-point polar alignment (default: True). "
        "CI's smoke lane passes --no-startup-polar-align.",
    )
    group.addoption(
        "--no-startup-polar-align",
        action="store_false",
        dest="startup_polar_align",
        help="Skip 3PPA in the startup flow (used by the smoke CI lane).",
    )
```

And use it instead in `test_flow.py`:
```python
@pytest.mark.smoke
@pytest.mark.full
def test_startup(page, app_base_url, driver, request):
    polar_align = request.config.getoption("--startup-polar-align")
    driver.run_startup(page, app_base_url, polar_align=polar_align)
```

This way: local manual runs (no `-m`, no `--no-startup-polar-align`) keep today's exact behavior — full startup, every test runs. CI's smoke lane passes `-m smoke --no-startup-polar-align`. CI's full lane passes `-m full` (polar_align stays at its default `True`).

- [ ] **Step 2: Update `pytest_addoption` in `conftest.py`** — apply the block from Step 1 above.

- [ ] **Step 3: Verify collection with each marker selects the right tests**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -m pytest tests/system --target emulator -m smoke --collect-only -q
python3 -m pytest tests/system --target emulator -m full --collect-only -q
```

Expected: the `smoke` collection lists `test_startup` and `test_live_imaging_standalone` (x2 for classic+v2 = 4 items) and nothing else from `test_flow.py`; the `full` collection lists all 4 test functions (x2 frontends = 8 items). (This uses `--collect-only`, so it does not actually try to reach an emulator — `--target emulator` only needs to be non-`None` to avoid the skip guard; no live emulator is required for collection.)

- [ ] **Step 4: Commit**

```bash
git add tests/system/test_flow.py tests/system/conftest.py
git commit -m "$(cat <<'EOF'
feat: add smoke/full pytest markers to tests/system flow tests

smoke = test_startup(polar_align=False) + test_live_imaging_standalone,
no plate-solving. full = the complete existing 4-step flow, unchanged.
Adds --startup-polar-align/--no-startup-polar-align so test_startup can
tell which tier selected it without fragile -m string parsing.
EOF
)"
```

---

### Task 14: Write `.github/workflows/emulator-smoke.yml`

**Files:**
- Create: `.github/workflows/emulator-smoke.yml`

**Interfaces:**
- Consumes: `emulator/firmware/versions.yaml`'s `smoke_version` (Task 8), `emulator/firmware/provision.py` (Task 9), `emulator/Dockerfile` (Task 4), `-m smoke --no-startup-polar-align` (Task 13).

- [ ] **Step 1: Write the workflow**

Create `/Users/bguthro/Development/seestar_alp/.github/workflows/emulator-smoke.yml`:

```yaml
name: Emulator smoke test

on:
  pull_request:
    branches:
      - main

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python 3.13
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Set up QEMU (armhf emulation)
        uses: docker/setup-qemu-action@v3
        with:
          platforms: arm

      - name: Install backend + emulator + system-test dependencies
        run: |
          pip install -r requirements.txt
          pip install -e '.[emulator,system]'
          playwright install --with-deps chromium

      - name: Read smoke firmware version
        id: fw
        run: |
          python3 -c "
          import yaml
          doc = yaml.safe_load(open('emulator/firmware/versions.yaml'))
          version = doc['smoke_version']
          entry = next(v for v in doc['full_versions'] if v['version'] == version)
          print(f'version={entry[\"version\"]}')
          print(f'version_code={entry[\"version_code\"]}')
          " >> "$GITHUB_OUTPUT"

      - name: Cache firmware XAPK
        uses: actions/cache@v4
        with:
          path: /tmp/emulator-fw/unpacked/_xapk_cache
          key: firmware-xapk-${{ steps.fw.outputs.version_code }}

      - name: Provision firmware
        id: provision
        run: |
          python3 -m emulator.firmware.provision \
            --version "${{ steps.fw.outputs.version }}" \
            --version-code "${{ steps.fw.outputs.version_code }}" \
            --work-dir /tmp/emulator-fw/unpacked

      - name: Build emulator image
        run: docker build --platform linux/arm/v7 -t seestar-emulator emulator/

      - name: Launch emulator container
        run: |
          cd emulator
          ./run.sh --firmware-dir /tmp/emulator-fw --model S50 "${{ steps.fw.outputs.version }}" &
          echo $! > /tmp/emulator.pid

      - name: Wait for emulator ports
        run: |
          timeout 120 bash -c 'until nc -z 127.0.0.1 4700 && nc -z 127.0.0.1 4800; do sleep 2; done'

      - name: Run smoke tests
        run: |
          pytest tests/system --target emulator --host 127.0.0.1 \
            -m smoke --no-startup-polar-align \
            --screenshot=on --video=on -q

      - name: Upload Playwright artifacts on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: emulator-smoke-playwright-artifacts
          path: test-results/

      - name: Stop emulator container
        if: always()
        run: docker stop seestar-sandbox 2>/dev/null || true
```

**Path convention note:** `run.sh`'s `FW_BASE` is `<firmware-dir>/unpacked/<version>/iscope/deb/out`. `provision.py`'s output is `<work-dir>/<version>/iscope/deb/out` (no `unpacked/` segment). The workflow above reconciles this by passing `--work-dir /tmp/emulator-fw/unpacked` to `provision.py` (so its output lands at `/tmp/emulator-fw/unpacked/<version>/iscope/deb/out`) while passing plain `--firmware-dir /tmp/emulator-fw` to `run.sh` — the two `unpacked/` segments then line up, and `run.sh` itself needs no changes. The version string passed to `provision.py --version` and as `run.sh`'s trailing positional argument must be identical (e.g. `"3.3.0"`, no `v` prefix) — `run.sh` uses it as a literal directory-name selector, not a semantic version parse.

- [ ] **Step 2: Verify YAML syntax**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/emulator-smoke.yml')); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/emulator-smoke.yml
git commit -m "feat: add always-on PR smoke-lane CI workflow for the emulator"
```

(This workflow can't be fully exercised until it actually runs in GitHub Actions — local `docker build --platform linux/arm/v7` was already verified in Task 4. Flag to the user that the first real PR run of this workflow should be watched closely, per the plan's final note below.)

---

### Task 15: Write `.github/workflows/emulator-full.yml`

**Files:**
- Create: `.github/workflows/emulator-full.yml`

**Interfaces:**
- Consumes: `emulator/firmware/versions.yaml`'s `full_versions` (Task 8), `emulator/astrometry/download_index.sh` (Task 3), `-m full` (Task 13).

- [ ] **Step 1: Write the workflow**

Create `/Users/bguthro/Development/seestar_alp/.github/workflows/emulator-full.yml`:

```yaml
name: Emulator full regression (goto/3PPA)

on:
  pull_request:
    types: [labeled]
  schedule:
    - cron: "0 7 * * *"  # nightly, 07:00 UTC

jobs:
  full:
    if: github.event_name == 'schedule' || github.event.label.name == 'run-full-system'
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        firmware: ${{ fromJSON(needs.matrix.outputs.versions) }}
    needs: matrix
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python 3.13
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Set up QEMU (armhf emulation)
        uses: docker/setup-qemu-action@v3
        with:
          platforms: arm

      - name: Install backend + emulator + system-test dependencies
        run: |
          pip install -r requirements.txt
          pip install -e '.[emulator,system]'
          playwright install --with-deps chromium

      - name: Cache firmware XAPK
        uses: actions/cache@v4
        with:
          path: /tmp/emulator-fw/unpacked/_xapk_cache
          key: firmware-xapk-${{ matrix.firmware.version_code }}

      - name: Cache astrometry index files
        uses: actions/cache@v4
        with:
          path: emulator/astrometry/index
          key: astrometry-index-4100-series-v1

      - name: Download astrometry index files (cache miss only)
        run: emulator/astrometry/download_index.sh

      - name: Provision firmware
        run: |
          python3 -m emulator.firmware.provision \
            --version "${{ matrix.firmware.version }}" \
            --version-code "${{ matrix.firmware.version_code }}" \
            --work-dir /tmp/emulator-fw/unpacked

      - name: Build emulator image
        run: docker build --platform linux/arm/v7 -t seestar-emulator emulator/

      - name: Rebuild renderer star catalog for this run
        run: |
          docker run --rm --platform linux/arm/v7 \
            -v "$PWD/emulator/sim:/sim" \
            -v "$PWD/emulator/astrometry/index:/usr/local/astrometry/data:ro" \
            --entrypoint python3 seestar-emulator \
            /sim/build_catalog.py /usr/local/astrometry/data/index-4107.fits /sim/data/stars.npy

      - name: Launch emulator container
        run: |
          cd emulator
          ./run.sh --firmware-dir /tmp/emulator-fw --model S50 "${{ matrix.firmware.version }}" &
          echo $! > /tmp/emulator.pid

      - name: Wait for emulator ports
        run: |
          timeout 120 bash -c 'until nc -z 127.0.0.1 4700 && nc -z 127.0.0.1 4800; do sleep 2; done'

      - name: Launch synthetic-sky renderer
        run: |
          cd emulator
          python3 -m sim.renderd --shared sim/shared --model S50 --catalog sim/data/stars.npy &
          echo $! > /tmp/renderd.pid

      - name: Run full regression tests
        run: |
          pytest tests/system --target emulator --host 127.0.0.1 \
            --renderer-shared-dir emulator/sim/shared \
            -m full \
            --screenshot=on --video=on -q

      - name: Upload Playwright artifacts on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: emulator-full-playwright-artifacts-${{ matrix.firmware.version }}
          path: test-results/

      - name: Stop renderer and emulator container
        if: always()
        run: |
          kill "$(cat /tmp/renderd.pid)" 2>/dev/null || true
          docker stop seestar-sandbox 2>/dev/null || true

  matrix:
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule' || github.event.label.name == 'run-full-system'
    outputs:
      versions: ${{ steps.read.outputs.versions }}
    steps:
      - uses: actions/checkout@v4
      - id: read
        run: |
          python3 -c "
          import json, yaml
          doc = yaml.safe_load(open('emulator/firmware/versions.yaml'))
          print('versions=' + json.dumps(doc['full_versions']))
          " >> "$GITHUB_OUTPUT"
```

- [ ] **Step 2: Verify YAML syntax**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/emulator-full.yml')); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/emulator-full.yml
git commit -m "feat: add label/nightly-gated full-matrix CI workflow for the emulator"
```

---

### Task 16: Update `tests/system/README.md` and write `emulator/README.md`

**Files:**
- Modify: `tests/system/README.md`
- Create: `emulator/README.md`

- [ ] **Step 1: Update `tests/system/README.md`**

Read the current file, then apply these renames throughout (mirroring Task 11's code changes):
- `--target sandbox` → `--target emulator`
- References to `seestar-api-research/sandbox` (the "Against the sandbox" section's `cd`/`run.sh`/`--renderer-shared-dir` paths) → `emulator/` (the new in-repo location, no more `cd ~/dev/seestar-api-research/sandbox`)
- Add a new section documenting the CI lanes: "This suite also runs in CI — see `.github/workflows/emulator-smoke.yml` (every PR, no plate-solving) and `.github/workflows/emulator-full.yml` (the `run-full-system` PR label, or nightly)."

- [ ] **Step 2: Write `emulator/README.md`**, adapted from `~/dev/seestar-api-research/sandbox/README.md`'s setup/usage sections (Prerequisites, Usage, Against the sandbox → against the emulator), with these specific content changes from the original:
  - Replace any `stage-astrometry.sh` instructions with: "Plate-solving support is built from public sources — no real device or SSH access needed. Run `./astrometry/download_index.sh` once to fetch the public astrometry.net index files (~350 MB), then rebuild the renderer's star catalog: see `sim/build_catalog.py`'s module docstring for the exact command."
  - Replace `seestar-sandbox` image name references with `seestar-emulator`.
  - Keep the firmware extraction instructions, updated to reference `emulator/firmware/extract_iscope.py` instead of the old repo's `scripts/decompile_iscope.py extract` (e.g. `python3 -m emulator.firmware.extract_iscope --apk ~/Downloads/Seestar_v*.xapk <dest>/iscope`, followed by `dpkg -x` for each `.deb` in `<dest>/iscope/deb/` into `<dest>/iscope/deb/out` — or point at `emulator/firmware/provision.py` for the fully-automated version used by CI).

- [ ] **Step 3: Verify both files render sensibly** (visual check, no automated test — documentation)

```bash
cat /Users/bguthro/Development/seestar_alp/emulator/README.md | head -40
grep -n "seestar-api-research/sandbox\|--target sandbox" /Users/bguthro/Development/seestar_alp/tests/system/README.md
```

Expected: the `grep` finds nothing (all references updated).

- [ ] **Step 4: Commit**

```bash
git add tests/system/README.md emulator/README.md
git commit -m "docs: update tests/system and add emulator READMEs for the relocation"
```

---

### Task 17: Full local verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the fast unit lane**

```bash
cd /Users/bguthro/Development/seestar_alp
python3 -m pytest -m "not integration" -q
```

Expected: all pass (no regressions from the `tests/system` renames — `tests/system` itself is excluded from this lane by the skip guard).

- [ ] **Step 2: Run the simulator integration lane**

```bash
python3 -m pytest -m integration tests/integration -q
```

Expected: all pass (unaffected by this plan's changes).

- [ ] **Step 3: Run ruff**

```bash
python3 -m ruff check .
```

Expected: no errors. Fix any lint issues surfaced by the new `emulator/` Python files before proceeding.

- [ ] **Step 4: Collect `tests/system` under both new markers one more time, end to end**

```bash
python3 -m pytest tests/system --target emulator -m smoke --collect-only -q
python3 -m pytest tests/system --target emulator -m full --collect-only -q
python3 -m pytest tests/system --target emulator --collect-only -q  # no -m: everything, unchanged from before this plan
```

Expected: counts match Task 13's expectations; the unfiltered run collects every test in `tests/system` (same total as before this plan started).

- [ ] **Step 5: Final commit for the verification pass** (only if any fixes were needed in Steps 1-4; otherwise skip — nothing to commit)

```bash
git add -A
git status  # confirm only intended fixes are staged before committing
git commit -m "fix: address lint/test issues found in full verification pass"
```

---

## Explicitly NOT part of this plan (flag to the user, don't auto-execute)

- **Removing `seestar-api-research/sandbox/` and the moved `scripts/` files** (`apk_utils.py`, `extract_iscope.py`) from the old repo. That repo has its own git history and remote — deleting from it is a separate, explicitly-confirmed action to take only after this plan's `emulator/` is verified working end-to-end (ideally after the first real CI run of both new workflows). Do not delete anything from `~/dev/seestar-api-research` as part of executing this plan.
- **The `*_test.py` files at the old `sandbox/` root** (`auth_test.py`, `autofocus_test.py`, `dark_frame_test.py`, `live_frame_test.py`, `solve_test.py`, `wheel_probe.py`) are standalone manual scripts for poking the emulator directly (not part of `tests/system`'s pytest suite, not referenced by any task above) — out of scope for this plan; leave them in the old repo.
- **`install_firmware.py`'s real-device upload path** (`upload_file`, `wait_for_scope`) — irrelevant to CI provisioning (that's for pushing firmware *to* a physical Seestar), not moved.
- Confirming GitHub Actions runners can actually pull from APKPure without a Cloudflare challenge — flagged as a residual risk in the design doc; the first real `emulator-full.yml` run (nightly or label-triggered) is the actual test of this. If it's flaky, the next iteration should look at self-hosting a firmware artifact mirror (an alternative the design doc considered and the user explicitly deferred).
