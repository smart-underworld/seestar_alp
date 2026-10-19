"""MCP tool modules. Each module defines ``register(mcp)``; add new modules to ``register_all``."""

from importlib import import_module
from typing import Any

_MODULES = ("state", "pointing", "imaging")


def register_all(mcp: Any) -> None:
    # Imported lazily so tool modules can import ``seestar_mcp.server`` without a cycle.
    for name in _MODULES:
        import_module(f"{__name__}.{name}").register(mcp)
