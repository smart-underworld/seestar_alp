#!/usr/bin/env python3
"""CI firmware acquisition: download (or reuse a cached) APKPure XAPK for a
pinned version, extract iscope, and dpkg -x the .deb packages into the
deb/out tree emulator/run.sh expects.

Adapted from seestar-api-research/scripts/install_firmware.py's
download_version() — trimmed to just the non-interactive download path
(no interactive version picker, no real-device upload; those are irrelevant
to CI provisioning).

Fetches from api.pureapk.com — the backend API APKPure's own Android app
talks to — rather than the consumer website (d.apkpure.com/apkpure.com).
The website is fronted by a Cloudflare bot challenge that blocks GitHub
Actions runners outright (confirmed via a live CI run: "cf-mitigated:
challenge", a "Just a moment..." interstitial). The same challenge also
blocks other Cloudflare-fronted mirrors (apkcombo.com), so it isn't
APKPure-specific — it's Cloudflare flagging GitHub Actions' well-known IP
ranges. api.pureapk.com is not behind that challenge (verified via a live
CI run: clean HTTP 200s all the way through a real XAPK download). This
mirrors the approach used by EFForg's `apkeep` tool (github.com/EFForg/apkeep),
including its header set and its regex-based extraction of a version's
download URL from the API's binary (protobuf-ish) response body.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests

from emulator.firmware.extract_iscope import extract_iscope_from_apk
from emulator.firmware.extract_pem import extract_interop_pem

SEESTAR_PACKAGE = "com.zwo.seestar"

PUREAPK_APP_VERSION_URL = "https://api.pureapk.com/m/v3/cms/app_version"
# Headers mimicking APKPure's own Android app (x-cv/x-sv = client/SDK
# version, x-abis = supported ABIs, x-gp = "has Google Play" flag) — this is
# what api.pureapk.com expects from legitimate app traffic.
PUREAPK_HEADERS = {
    "x-cv": "3172501",
    "x-sv": "29",
    "x-abis": "arm64-v8a,armeabi-v7a,armeabi,x86,x86_64",
    "x-gp": "1",
}
# Matches an "(X?APKJ)" file-type marker followed by 2 bytes then a URL.
_DOWNLOAD_URL_RE = (
    rb"(X?APKJ)..(https?://(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}"
    rb"\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_+.~#?&//=]*))"
)


def _extract_download_url(body: bytes, version: str) -> str:
    """Find the download URL for `version` in an app_version API response.

    The response body mixes protobuf binary framing with embedded UTF-8
    strings (version numbers, URLs). This searches for the literal version
    string (preceded by a non-digit byte, so e.g. "3.0.0" doesn't match
    inside "23.0.0") followed by ":" and, somewhere after it, that version's
    download URL.
    """
    pattern = re.compile(
        rb"[^0-9]" + re.escape(version.encode()) + rb":(?s:.)+?" + _DOWNLOAD_URL_RE
    )
    match = pattern.search(body)
    if not match:
        raise RuntimeError(
            f"Could not find a download URL for version {version} in the app_version API response"
        )
    return match.group(2).decode()


def _fetch_xapk_bytes(version: str) -> bytes:
    """Download the XAPK bytes for a given human-readable version string."""
    response = requests.get(
        PUREAPK_APP_VERSION_URL,
        params={"hl": "en-US", "package_name": SEESTAR_PACKAGE},
        headers=PUREAPK_HEADERS,
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Could not query app_version for {SEESTAR_PACKAGE} (HTTP {response.status_code})"
        )
    download_url = _extract_download_url(response.content, version)

    file_response = requests.get(download_url, timeout=120)
    if file_response.status_code != 200:
        raise RuntimeError(
            f"Could not download version={version} from {download_url} (HTTP {file_response.status_code})"
        )
    return file_response.content


def download_xapk(version: str, dest_dir: Path) -> Path:
    """Return the path to the version's XAPK, downloading only on a cache miss."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"firmware-{version}.xapk"
    if dest_path.exists():
        print(f"  Using cached XAPK: {dest_path}")
        return dest_path
    print(f"  Downloading firmware v{version}...")
    data = _fetch_xapk_bytes(version)
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
        raise RuntimeError(
            "'dpkg' not found on PATH — required to unpack firmware .deb files"
        )
    failed: list[str] = []
    for deb in debs:
        result = subprocess.run(["dpkg", "-x", str(deb), str(out_dir)])
        if result.returncode != 0:
            print(
                f"  Warning: dpkg failed for {deb.name} (exit {result.returncode})",
                file=sys.stderr,
            )
            failed.append(deb.name)
    if failed:
        raise RuntimeError(
            f"dpkg -x failed for {len(failed)} package(s), unpacked tree at "
            f"{out_dir} is incomplete: {', '.join(failed)}"
        )


def provision_firmware(version: str, work_dir: Path) -> Path:
    """Ensure firmware `version` is downloaded and extracted under work_dir.

    Also extracts the firmware's interop private key (see extract_pem.py)
    from the same XAPK, writing it to <work_dir>/<version>/interop.pem —
    firmware 7.18+ requires interop authentication, and the emulator is no
    exception. tests/system's --pem option should point at that file.

    Returns the path to <work_dir>/<version>/iscope/deb/out, matching what
    emulator/run.sh's FW_BASE expects.
    """
    work_dir = Path(work_dir)
    version_dir = work_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)

    xapk_path = download_xapk(version=version, dest_dir=work_dir / "_xapk_cache")
    extract_interop_pem(str(xapk_path), str(version_dir / "interop.pem"))
    iscope_dir = extract_iscope_from_apk(
        str(xapk_path), str(version_dir), variant="iscope"
    )

    deb_dir = iscope_dir / "deb"
    out_dir = deb_dir / "out"
    _unpack_debs(deb_dir, out_dir)
    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Provision emulator firmware for CI")
    parser.add_argument("--version", required=True, help='e.g. "3.1.2"')
    parser.add_argument(
        "--work-dir", required=True, help="Directory to download/extract into"
    )
    args = parser.parse_args()
    deb_out = provision_firmware(version=args.version, work_dir=Path(args.work_dir))
    print(deb_out)


if __name__ == "__main__":
    main()
