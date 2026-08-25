#!/usr/bin/env bash
# run.sh — build and launch zwoair_imager in an armhf Debian Buster container.
#
# Prerequisites:
#   - Docker with multi-arch (QEMU) support:
#       Mac/Windows: Docker Desktop (multi-arch enabled by default)
#       Linux: docker + qemu-user-static + binfmt-support
#   - Firmware extracted to ~/dev/firmware/unpacked/v3.1.2/iscope/deb/out/
#     (i.e. both asiair_armhf.deb and alpaca_libs_armhf.deb already dpkg-x'd)
#
# Usage:
#   ./run.sh [--model MODEL] [--firmware-dir DIR] [version]
#   version defaults to v3.1.2
#   --model (or the SEESTAR_MODEL env var) selects which device the binary
#   identifies as: S50 (default), S50V2, S50P, S30, S30P
#   --firmware-dir selects where extracted firmware lives (default: ~/dev/firmware)
#   e.g. ./run.sh --model S30P
#        SEESTAR_MODEL=S30P ./run.sh
#        ./run.sh --firmware-dir ~/Development/firmware

set -euo pipefail

usage() {
  cat <<EOF
Usage: ./run.sh [--model MODEL] [--firmware-dir DIR] [--skip-build] [version]

Build and launch zwoair_imager in an armhf Debian Buster emulator container.

Arguments:
  version             Firmware version directory under <firmware-dir>/unpacked/
                       (default: v3.1.2)

Options:
  --model MODEL        Device model the binary identifies as: S50 (default),
  --model=MODEL         S50V2, S50P, S30, S30P. Overrides SEESTAR_MODEL.
  --firmware-dir DIR    Root of extracted firmware (default: ${HOME}/dev/firmware)
  --firmware-dir=DIR
  --skip-build          Skip the docker build step and launch the
                         already-built seestar-emulator image directly. For
                         callers (e.g. CI) that already built the image
                         themselves — this script's own `docker build` uses
                         a separate, uncached builder/cache store from
                         buildx, so calling it again after an external
                         buildx build wastefully rebuilds from scratch.
  -h, --help           Show this help and exit

Environment variables:
  SEESTAR_MODEL        Same as --model; used if --model isn't given.

Examples:
  ./run.sh                                  # S50, firmware v3.1.2
  ./run.sh --model S30P                     # S30 Pro, firmware v3.1.2
  SEESTAR_MODEL=S30P ./run.sh               # same, via env var
  ./run.sh --model S30 v3.2.0               # S30, firmware v3.2.0
  ./run.sh --firmware-dir ~/Development/firmware

Once running, in a second terminal:
  python3 auth_test.py --pem ~/dev/seestar_private_key.pem
EOF
}

VERSION=""
MODEL_OPT=""
FIRMWARE_DIR=""
SKIP_BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --model)
      MODEL_OPT="${2:?--model requires a value}"
      shift 2
      ;;
    --model=*)
      MODEL_OPT="${1#--model=}"
      shift
      ;;
    --firmware-dir)
      FIRMWARE_DIR="${2:?--firmware-dir requires a value}"
      shift 2
      ;;
    --firmware-dir=*)
      FIRMWARE_DIR="${1#--firmware-dir=}"
      shift
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    -*)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -n "${VERSION}" ]]; then
        echo "ERROR: unexpected extra argument: $1" >&2
        exit 1
      fi
      VERSION="$1"
      shift
      ;;
  esac
done

VERSION="${VERSION:-v3.1.2}"
SEESTAR_MODEL="${MODEL_OPT:-${SEESTAR_MODEL:-S50}}"
FIRMWARE_DIR="${FIRMWARE_DIR:-${HOME}/dev/firmware}"

# Keep in sync with the model table in stubs/stub_hwid.c's model_str().
case "${SEESTAR_MODEL}" in
  S50|S50V2|S50P|S30|S30P) ;;
  *)
    echo "ERROR: invalid model '${SEESTAR_MODEL}'" >&2
    echo "Valid values: S50, S50V2, S50P, S30, S30P" >&2
    exit 1
    ;;
esac

FW_BASE="${FIRMWARE_DIR}/unpacked/${VERSION}/iscope/deb/out"
ASIAIR_DIR="${FW_BASE}/home/pi/ASIAIR"

if [[ ! -d "${ASIAIR_DIR}" ]]; then
  echo "ERROR: firmware directory not found: ${ASIAIR_DIR}"
  echo "Extract the firmware first:"
  echo "  python3 scripts/decompile_iscope.py run --apk ~/Downloads/Seestar_v*.xapk --version-dir ${FIRMWARE_DIR}/unpacked/${VERSION}"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  # One-time: register armhf binfmt_misc handler in Docker's Linux VM.
  # Safe to run repeatedly — tonistiigi/binfmt is idempotent.
  echo "==> Ensuring arm/v7 binfmt support..."
  docker run --privileged --rm tonistiigi/binfmt --install arm 2>/dev/null || true

  echo "==> Building image (seestar-emulator)..."
  docker build --platform linux/arm/v7 -t seestar-emulator "${SCRIPT_DIR}"
else
  echo "==> --skip-build: using already-built seestar-emulator image"
fi

# libonnxruntime.so is named without the version suffix in the firmware deb,
# but the binary NEEDS libonnxruntime.so.1.14.1 — create a symlink inside a
# temp overlay so we don't modify the source firmware directory.
TMPLIB=$(mktemp -d)
trap 'rm -rf "${TMPLIB}"' EXIT
cp "${ASIAIR_DIR}/lib/"*.so "${TMPLIB}/" 2>/dev/null || true
(cd "${TMPLIB}" && \
  [[ -f libonnxruntime.so && ! -f libonnxruntime.so.1.14.1 ]] && \
    ln -s libonnxruntime.so libonnxruntime.so.1.14.1 || true)

SEED_DIR="${SCRIPT_DIR}/seed"

# SQLite needs to create journal/lock files alongside the database, so the
# .ZWO directory must be writable. Copy seed files to a temp dir rather than
# mounting seed/ directly (keeps the originals clean).
TMPZWO=$(mktemp -d)
trap 'rm -rf "${TMPLIB}" "${TMPZWO}"' EXIT
cp "${SEED_DIR}/"* "${TMPZWO}/" 2>/dev/null || true

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

echo "==> Launching zwoair_imager as model ${SEESTAR_MODEL} (ports 4700/4701, 4800/4801, 80, UDP 4720 forwarded)..."
echo "    Ctrl-C to stop."
TTY_FLAG=""; [ -t 0 ] && TTY_FLAG="-t"
# shellcheck disable=SC2086
docker run --rm -i ${TTY_FLAG} \
  --platform linux/arm/v7 \
  --name seestar-emulator \
  -e HOME=/home/pi \
  -e SEESTAR_MODEL="${SEESTAR_MODEL}" \
  -p 4700:4700 \
  -p 4701:4701 \
  -p 4800:4800 \
  -p 4801:4801 \
  -p 8080:80 \
  -p 4720:4720/udp \
  -v "${ASIAIR_DIR}/bin:/home/pi/ASIAIR/bin:ro" \
  -v "${TMPLIB}:/home/pi/ASIAIR/lib:ro" \
  -v "${ASIAIR_DIR}/sound:/home/pi/ASIAIR/sound:ro" \
  -v "${ASIAIR_DIR}/config:/home/pi/ASIAIR/config:ro" \
  -v "${TMPZWO}:/home/pi/.ZWO" \
  -v "${ASTRO_DATA}:/usr/local/astrometry/data:ro" \
  -v "${SIM_SHARED}:/run/seestar-sim" \
  seestar-emulator
