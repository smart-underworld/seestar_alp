"""Shared helper for tool modules."""

from collections.abc import Awaitable, Callable
from typing import Any


async def call(
    telescope_id: int | None, coro_factory: Callable[[Any], Awaitable[Any]]
) -> Any:
    # Lazy import: server.py calls register_all() at import time, so importing it at
    # module top would create a cycle when a tool module is imported first.
    from seestar_mcp import server

    return await server.call(telescope_id, coro_factory)
