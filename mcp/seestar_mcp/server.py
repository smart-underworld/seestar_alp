"""Seestar MCP server: FastMCP instance, client factory and error-mapping helper."""

import os
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from ssalp_api_client import SSAlpApiClient, SSAlpConnectionError, SSAlpError

mcp = FastMCP("seestar")


def make_client(telescope_id: int | None = None) -> SSAlpApiClient:
    """Build a client. SEESTAR_BASE_URL overrides; otherwise the client's own config applies."""
    base_url = os.environ.get("SEESTAR_BASE_URL")
    if base_url:
        return SSAlpApiClient(base_url=base_url, device_num=telescope_id)
    return SSAlpApiClient(device_num=telescope_id)


async def call(
    telescope_id: int | None,
    coro_factory: Callable[[SSAlpApiClient], Awaitable[Any]],
) -> Any:
    """Run a client coroutine, mapping client errors to {"ok": False, "error": str}."""
    client = make_client(telescope_id)
    try:
        return await coro_factory(client)
    except (SSAlpConnectionError, SSAlpError) as exc:
        return {"ok": False, "error": str(exc)}
