#!/usr/bin/env python3
"""Rebuild front/public/vendor/aladin-lite/aladin.js from the aladin-lite npm package.

The npm package ships dist/aladin.js as an ES module (it ends with
``export{f as default};``). The planner pages load it with a plain
``<script src>`` tag, where ``export`` is a SyntaxError and ``window.A`` is never
defined, so the sky map stays blank. CDS's hosted ``latest/aladin.js`` is a
classic script; this reproduces that: the module body is wrapped in a function
and the default export is assigned to ``window.A``.

Usage:
    npm pack aladin-lite
    tar -xzf aladin-lite-*.tgz
    python scripts/vendor_aladin_lite.py package/dist/aladin.js [version]
"""

import re
import sys
from pathlib import Path

DEST = (
    Path(__file__).resolve().parent.parent
    / "front"
    / "public"
    / "vendor"
    / "aladin-lite"
    / "aladin.js"
)
EXPORT = re.compile(r"export\s*\{\s*([A-Za-z_$][\w$]*)\s+as\s+default\s*\}\s*;?\s*$")


def wrap(source: str, version: str) -> str:
    source = source.rstrip()
    match = EXPORT.search(source)
    if not match:
        raise SystemExit("expected the bundle to end with `export{<name> as default};`")
    body = source[: match.start()]
    if re.search(r"\bexport\b\s*[{*d]|\bimport\.meta\b", body):
        raise SystemExit("bundle has other exports or import.meta; cannot wrap it")
    return (
        f"/* aladin-lite {version} (LGPL-3.0-or-later, https://github.com/cds-astro/aladin-lite).\n"
        " * npm dist/aladin.js wrapped as a classic script by scripts/vendor_aladin_lite.py:\n"
        " * module body inside a function, default export assigned to window.A. */\n"
        '(function(){"use strict";\n'
        f"{body}\n"
        f"window.A={match.group(1)};\n"
        "})();\n"
    )


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    src = Path(argv[1])
    version = argv[2] if len(argv) > 2 else "unknown version"
    DEST.write_text(wrap(src.read_text(encoding="utf-8"), version), encoding="utf-8")
    print(f"wrote {DEST} ({DEST.stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv)
