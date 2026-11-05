"""Generate a PyInstaller Windows version-resource file from a git version.

Usage:
    python scripts/make_win_version_file.py <git_version> <output_path>

<git_version> is the `git describe` string written to version.txt, e.g.
"v3.3.1" or "v3.3.1-17-g5b35e2c-dirty". The numeric part becomes the
FileVersion/ProductVersion tuple (major, minor, patch, commits-since-tag),
and the full string is shown verbatim in the exe's Properties > Details tab.
"""

import re
import sys

_VERSION_RE = re.compile(r"^v(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-(\d+)-g[0-9a-f]+)?")


def parse_version(git_version: str) -> tuple[int, int, int, int]:
    """Map a git describe string to a 4-part numeric tuple (0s if unparseable)."""
    m = _VERSION_RE.match(git_version.strip())
    if not m:
        return (0, 0, 0, 0)
    # Windows version fields are 16-bit.
    return tuple(min(int(g or 0), 0xFFFF) for g in m.groups())  # type: ignore[return-value]


def render(git_version: str) -> str:
    git_version = git_version.strip()
    nums = parse_version(git_version)
    # repr() yields a valid Python string literal for the version text.
    ver = repr(git_version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums},
    prodvers={nums},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'smart-underworld'),
        StringStruct('FileDescription', 'Seestar ALP'),
        StringStruct('FileVersion', {ver}),
        StringStruct('InternalName', 'seestar_alp'),
        StringStruct('OriginalFilename', 'seestar_alp.exe'),
        StringStruct('ProductName', 'Seestar ALP'),
        StringStruct('ProductVersion', {ver})
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[2], "w", encoding="utf-8") as f:
        f.write(render(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
