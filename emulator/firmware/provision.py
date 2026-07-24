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
