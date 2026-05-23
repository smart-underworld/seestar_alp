"""Parse Bruno .bru environment files to extract variable definitions.

Only the ``vars { ... }`` block is read; the full .bru grammar is not implemented.
"""

from __future__ import annotations

import re
from pathlib import Path

_VAR_LINE = re.compile(r"^\s*([\w_]+)\s*:\s*(.+?)\s*$")
_BLOCK_OPEN = re.compile(r"^\s*vars\s*\{")
_BLOCK_CLOSE = re.compile(r"^\s*\}")


def load_env(path: str | Path) -> dict[str, str]:
    """Parse a Bruno .bru environment file and return its vars as a dict.

    Args:
        path: Path to a ``.bru`` environment file.

    Returns:
        Dict mapping variable names to their string values.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be parsed.
    """
    resolved = Path(path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Bruno env file not found: {resolved}")

    text = resolved.read_text(encoding="utf-8")
    return _parse_vars_block(text, source=str(resolved))


def _parse_vars_block(text: str, source: str = "<string>") -> dict[str, str]:
    result: dict[str, str] = {}
    in_vars = False

    for line in text.splitlines():
        if not in_vars:
            if _BLOCK_OPEN.match(line):
                in_vars = True
            continue

        if _BLOCK_CLOSE.match(line):
            break

        m = _VAR_LINE.match(line)
        if m:
            result[m.group(1)] = m.group(2)

    return result
