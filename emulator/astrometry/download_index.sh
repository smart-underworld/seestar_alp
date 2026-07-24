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
