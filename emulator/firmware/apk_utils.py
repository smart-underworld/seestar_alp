"""Shared utilities for opening APK and XAPK files."""

import io
import zipfile
from contextlib import contextmanager
from pathlib import Path


def _is_xapk(z: zipfile.ZipFile) -> bool:
    names = z.namelist()
    return "manifest.json" in names and any(n.endswith(".apk") for n in names)


@contextmanager
def open_apk(path, containing=None):
    """
    Context manager yielding a ZipFile for the relevant APK.

    For plain APKs: yields the file directly.
    For XAPKs:
      - If `containing` is given (a str or list of str), searches all split APKs
        for the first one that contains any of those paths.
      - Otherwise, prefers base.apk, falling back to the first root-level .apk entry.
    """
    needles = (
        ([containing] if isinstance(containing, str) else containing)
        if containing
        else []
    )

    with zipfile.ZipFile(Path(path)) as outer:
        if _is_xapk(outer):
            apk_entries = [
                n for n in outer.namelist() if n.endswith(".apk") and "/" not in n
            ]
            if not apk_entries:
                raise ValueError(f"No APK entries found inside XAPK: {path}")

            chosen = None
            if needles:
                for entry in apk_entries:
                    with zipfile.ZipFile(io.BytesIO(outer.read(entry))) as probe:
                        if any(n in probe.namelist() for n in needles):
                            chosen = entry
                            break
                if chosen is None:
                    raise ValueError(f"No split APK in {path} contains: {needles}")
            else:
                chosen = "base.apk" if "base.apk" in apk_entries else apk_entries[0]

            print(f"  XAPK: using {chosen}")
            with zipfile.ZipFile(io.BytesIO(outer.read(chosen))) as inner:
                yield inner
        else:
            yield outer
