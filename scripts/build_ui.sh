#!/usr/bin/env bash
# Build the front_v2/ui Svelte app.
# Called by: linux/deb/build-deb.sh, CI workflows, setup/update scripts,
#            and root_app.py auto-build on first dev startup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_DIR="$SCRIPT_DIR/../front_v2/ui"

echo "Building v2 UI..."
cd "$UI_DIR"
npm ci
npm run build
echo "Built: $UI_DIR/dist"
