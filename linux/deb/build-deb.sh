#!/usr/bin/env bash
# Build a seestar-alp .deb package.
#
# Run from anywhere — the script locates the repo root automatically.
#
# Usage:
#   ./linux/deb/build-deb.sh [version]
#   Version defaults to the value in pyproject.toml.
#
# Prerequisites (on the build host):
#   dpkg-deb, rsync
#
# The resulting .deb installs the application to /opt/seestar_alp and manages
# it via two systemd services (seestar and INDI).  Python dependencies are
# resolved at install time using uv, so no pre-built wheel cache is needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Version
#
# APP_VERSION  — written to device/version.txt; what the UI displays.
#                Matches git describe output exactly (e.g. v1.2.3 or v1.2.3-4-gabcdef).
# DEB_VERSION  — used in the .deb control file; must satisfy dpkg version rules.
#                Leading 'v' stripped; git distance/hash encoded with '+' separator
#                (e.g. 1.2.3 or 1.2.3+4.gabcdef).
# ---------------------------------------------------------------------------
if [ "${1:-}" != "" ]; then
    # Explicit version supplied — use it for both
    APP_VERSION="${1}"
    DEB_VERSION="${APP_VERSION#v}"   # strip leading 'v' if present
else
    # Use the same git describe flags as device/version.py so the deb version
    # and the in-app version are always identical.
    GIT_DESCRIBE=$(git describe --tags --always \
        --exclude '*[0-9]-g*' --match 'v*' 2>/dev/null || true)

    if [ -n "$GIT_DESCRIBE" ]; then
        APP_VERSION="$GIT_DESCRIBE"
        # Convert v1.2.3-4-gabcdef  →  1.2.3+4.gabcdef  (dpkg-safe)
        DEB_VERSION=$(echo "$GIT_DESCRIBE" \
            | sed 's/^v//' \
            | sed 's/-\([0-9]*\)-g\(.*\)/+\1.\2/')
    else
        # No git tags — fall back to pyproject.toml
        DEB_VERSION=$(python3 -c "
import re
with open('pyproject.toml') as f:
    content = f.read()
m = re.search(r'^version\s*=\s*\"([^\"]+)\"', content, re.MULTILINE)
print(m.group(1) if m else '0.0.0')
")
        APP_VERSION="$DEB_VERSION"
    fi
fi

PKG_NAME="seestar-alp"

# Map the host kernel architecture to the Debian architecture name.
# Pass ARCH=<value> on the command line to cross-build (e.g. ARCH=armhf).
case "${ARCH:-$(uname -m)}" in
    aarch64|arm64) ARCH="arm64"  ;;
    armv7l|armhf)  ARCH="armhf"  ;;
    x86_64)        ARCH="amd64"  ;;
    *)             ARCH=$(uname -m) ;;
esac
DEB_FILE="${REPO_ROOT}/${PKG_NAME}_${DEB_VERSION}_${ARCH}.deb"

echo "Building ${PKG_NAME} ${DEB_VERSION} (${ARCH})  [app version: ${APP_VERSION}]..."

# ---------------------------------------------------------------------------
# Staging tree
# ---------------------------------------------------------------------------
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

APP="$STAGE/opt/seestar_alp"
SYSTEMD="$STAGE/lib/systemd/system"
SYSCTL="$STAGE/etc/sysctl.d"
ETCSEESTAR="$STAGE/etc/seestar"
DEBIAN="$STAGE/DEBIAN"

mkdir -p "$APP" "$SYSTEMD" "$SYSCTL" "$ETCSEESTAR" "$DEBIAN"

# ---------------------------------------------------------------------------
# Copy application source
# Exclude: venv, git internals, caches, test fixtures, build artefacts,
#          runtime-generated files, and developer tooling.
# ---------------------------------------------------------------------------
rsync -a --delete \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='.pyenv/' \
    --exclude='node_modules/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='logs/' \
    --exclude='*.db' \
    --exclude='*.db-journal' \
    --exclude='.vscode/' \
    --exclude='.claude/' \
    --exclude='.codex/' \
    --exclude='.copilot/' \
    --exclude='tests/' \
    --exclude='simulator/' \
    --exclude='decompiles/' \
    --exclude='bruno/' \
    --exclude='thunder-tests/' \
    --exclude='doc/' \
    --exclude='mac/' \
    --exclude='deb/' \
    --exclude='*.deb' \
    --exclude='*.patch' \
    "$REPO_ROOT/" "$APP/"

# Remove any config.toml that may be present — the postinst generates it
# from config.toml.example so that upgrades don't overwrite user edits.
rm -f "$APP/device/config.toml"

# Replace the pyenv virtualenv name in .python-version with a plain version
# number that uv understands (e.g. "ssc-3.13.5" -> "3.13").
if [ -f "$APP/.python-version" ]; then
    sed 's/^[^0-9]*//' "$APP/.python-version" \
        | grep -oE '^[0-9]+\.[0-9]+' > "$APP/.python-version.tmp"
    mv "$APP/.python-version.tmp" "$APP/.python-version"
fi

# Write version.txt so the app displays the correct version without needing
# git at runtime (device/version.py checks for this file first).
echo "$APP_VERSION" > "$APP/device/version.txt"

# ---------------------------------------------------------------------------
# Bundle uv binary for the target architecture
# Downloading at install time requires working SSL and network access.
# Bundling it avoids both problems and makes offline installs possible.
# ---------------------------------------------------------------------------
echo "Bundling uv..."
case "$ARCH" in
    amd64) UV_ARCH="x86_64-unknown-linux-gnu" ;;
    arm64) UV_ARCH="aarch64-unknown-linux-gnu" ;;
    armhf) UV_ARCH="armv7-unknown-linux-gnueabihf" ;;
    *)     echo "No uv binary known for arch: $ARCH"; exit 1 ;;
esac
mkdir -p "$APP/.local/bin"
curl -LsSf "https://github.com/astral-sh/uv/releases/latest/download/uv-${UV_ARCH}.tar.gz" \
    | tar -xz --strip-components=1 -C "$APP/.local/bin" \
        "uv-${UV_ARCH}/uv" "uv-${UV_ARCH}/uvx"

# ---------------------------------------------------------------------------
# Pre-build pyindi wheel
# pyindi is specified as a git URL in requirements.txt, so git is required on
# the build host but not on the install target.  The resulting wheel is
# architecture-independent (pure Python) and is bundled into the package.
# ---------------------------------------------------------------------------
echo "Pre-building pyindi wheel..."
PYINDI_REQ=$(grep '^pyindi' "$REPO_ROOT/requirements.txt")
mkdir -p "$APP/wheels"
python3 -m pip wheel --no-deps --wheel-dir "$APP/wheels" "$PYINDI_REQ" 2>&1 | tail -3

# Rewrite requirements.txt to reference the bundled wheel via a file:// URL
# so uv does not need git on the install target.
PYINDI_WHEEL=$(basename "$APP/wheels"/pyindi*.whl)
sed "s|^pyindi.*|pyindi @ file:///opt/seestar_alp/wheels/${PYINDI_WHEEL}|" \
    "$REPO_ROOT/requirements.txt" > "$APP/requirements.txt"

# ---------------------------------------------------------------------------
# Systemd service units
# ---------------------------------------------------------------------------
cp "$SCRIPT_DIR/seestar.service" "$SYSTEMD/seestar.service"
cp "$SCRIPT_DIR/INDI.service"    "$SYSTEMD/INDI.service"

# ---------------------------------------------------------------------------
# /etc/seestar/seestar.env — ship as a conffile so dpkg preserves local edits
# ---------------------------------------------------------------------------
cp "$SCRIPT_DIR/seestar.env" "$ETCSEESTAR/seestar.env"

# Register conffiles so dpkg handles upgrade conflicts gracefully
cat > "$DEBIAN/conffiles" <<EOF
/etc/seestar/seestar.env
EOF

# ---------------------------------------------------------------------------
# sysctl: disable IPv6 (mirrors what setup.sh does)
# ---------------------------------------------------------------------------
echo "net.ipv6.conf.all.disable_ipv6 = 1" > "$SYSCTL/98-ssc.conf"

# ---------------------------------------------------------------------------
# DEBIAN maintainer scripts
# ---------------------------------------------------------------------------
for script in postinst prerm postrm; do
    cp "$SCRIPT_DIR/$script" "$DEBIAN/$script"
    chmod 755 "$DEBIAN/$script"
done

# ---------------------------------------------------------------------------
# DEBIAN/control
# ---------------------------------------------------------------------------
INSTALLED_SIZE=$(du -sk "$STAGE" | cut -f1)

cat > "$DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${DEB_VERSION}
Section: science
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE}
Depends: rsync, libxml2-dev, libxslt1-dev
Recommends: avahi-daemon, indi-bin
Maintainer: smart-underworld <https://github.com/smart-underworld/seestar_alp>
Homepage: https://github.com/smart-underworld/seestar_alp
Description: Seestar ALP telescope controller
 ALPACA/INDI bridge and web interface for ZWO Seestar smart telescopes.
 Runs as a pair of systemd services (seestar, INDI) accessible from any
 device on the local network.  Python dependencies are managed with uv
 and installed into an isolated virtual environment at install time.
EOF

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
dpkg-deb --build --root-owner-group "$STAGE" "$DEB_FILE"
echo "Built: $DEB_FILE ($(du -h "$DEB_FILE" | cut -f1))"
echo ""
echo "Install with:  sudo apt install ./$(basename "$DEB_FILE")"
echo "Remove with:   sudo apt remove seestar-alp"
echo "Purge with:    sudo apt purge seestar-alp   (removes config + venv)"
