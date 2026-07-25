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
            _progress(
                label, buf.tell(), total, f"  {buf.tell() >> 20}/{total >> 20} MB"
            )
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


def extract_iscope_from_apk(
    apk_path: str, output_dir: str, variant: str | None = None
) -> Path:
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
    parser = argparse.ArgumentParser(
        description="Extract iscope assets from a Seestar APK/XAPK"
    )
    parser.add_argument("--apk", required=True, help="Path to the APK or XAPK file")
    parser.add_argument(
        "--variant",
        choices=["iscope", "iscope_64"],
        help="Extract only this variant (default: both)",
    )
    parser.add_argument("output_dir", help="Directory to extract into")
    args = parser.parse_args()
    extract_iscope_from_apk(args.apk, args.output_dir, variant=args.variant)


if __name__ == "__main__":
    main()
