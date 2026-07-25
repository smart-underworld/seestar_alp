#!/usr/bin/env python3
"""Extract the firmware interop private key (PEM) from a Seestar APK/XAPK.

Firmware 7.18+ requires interop authentication, and the client-side private
key that authenticates it is baked directly into the app's own native
library (libopenssllib.so) — the same APK/XAPK provision.py already
downloads for the emulator's firmware payload. This is not a secret we need
to manage separately: any copy of the official app contains it, so it's
extracted fresh from the same cached XAPK on every CI run rather than
stored anywhere.

Adapted from seestar-api-research/scripts/extract_pem.py.
"""

import argparse
import re
import tempfile
from pathlib import Path

from emulator.firmware.apk_utils import open_apk

_OPENSSL_LIB_PATHS = [
    "lib/arm64-v8a/libopenssllib.so",
    "lib/armeabi-v7a/libopenssllib.so",
]
_PEM_BLOCK_RE = re.compile(
    rb"-----BEGIN PRIVATE KEY-----.*?-----END PRIVATE KEY-----", re.DOTALL
)


def _find_pem_blocks(binary: bytes) -> list[str]:
    """Return each distinct PEM private-key block found in `binary`."""
    seen = []
    for match in _PEM_BLOCK_RE.finditer(binary):
        text = match.group(0).decode("ascii", errors="ignore")
        if text not in seen:
            seen.append(text)
    return seen


def extract_interop_pem(apk_path: str, out_path: str) -> Path:
    """Extract the interop private key from apk_path and write it to out_path.

    Raises RuntimeError if no libopenssllib.so is found in the APK, or no
    PEM key is found within it.
    """
    out_path = Path(out_path)

    with tempfile.TemporaryDirectory() as tempdir:
        with open_apk(apk_path, containing=_OPENSSL_LIB_PATHS) as z:
            names = z.namelist()
            found = [p for p in _OPENSSL_LIB_PATHS if p in names]
            if not found:
                raise RuntimeError(
                    f"No {' or '.join(_OPENSSL_LIB_PATHS)} found in {apk_path}"
                )
            for so_path in found:
                z.extract(so_path, tempdir)

        keys: list[str] = []
        for so_path in found:
            binary = (Path(tempdir) / so_path).read_bytes()
            for key in _find_pem_blocks(binary):
                if key not in keys:
                    keys.append(key)

    if not keys:
        raise RuntimeError(f"No interop private key found in {apk_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(keys[0] + "\n")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Extract the interop PEM key from a Seestar APK/XAPK"
    )
    parser.add_argument("--apk", required=True, help="Path to the APK or XAPK file")
    parser.add_argument(
        "--out", required=True, help="Path to write the extracted .pem file"
    )
    args = parser.parse_args()
    out_path = extract_interop_pem(args.apk, args.out)
    print(out_path)


if __name__ == "__main__":
    main()
