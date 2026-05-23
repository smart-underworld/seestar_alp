from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import Any

import httpx

from .commands.camera import CameraMixin
from .commands.files import FilesMixin
from .commands.filter_wheel import FilterWheelMixin
from .commands.focuser import FocuserMixin
from .commands.info import InfoMixin
from .commands.mount import MountMixin
from .commands.schedule import ScheduleMixin
from .commands.system import SystemMixin
from .config import Config, load_config
from .exceptions import SSAlpConnectionError, SSAlpError

logger = logging.getLogger("ssalp_api_client.client")

_SKIP_SYNC_WRAP = frozenset({"action", "method_sync", "method_async", "get_bytes"})


def _add_sync_wrappers(cls: type) -> type:
    """Decorator: add a ``<name>_sync`` wrapper for every public async method."""
    new_methods: dict[str, Any] = {}
    for name in dir(cls):
        if name.startswith("_") or name in _SKIP_SYNC_WRAP:
            continue
        method = getattr(cls, name)
        if not inspect.iscoroutinefunction(method):
            continue

        def _make_sync(m: Any) -> Any:
            def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                return asyncio.run(m(self, *args, **kwargs))

            sync_wrapper.__name__ = m.__name__ + "_sync"
            sync_wrapper.__qualname__ = m.__qualname__ + "_sync"
            return sync_wrapper

        new_methods[name + "_sync"] = _make_sync(method)

    for name, method in new_methods.items():
        setattr(cls, name, method)
    return cls


@_add_sync_wrappers
class SSAlpApiClient(
    InfoMixin,
    SystemMixin,
    MountMixin,
    CameraMixin,
    FocuserMixin,
    FilterWheelMixin,
    FilesMixin,
    ScheduleMixin,
):
    """Async client for the seestar_alp Alpaca API.

    All command methods are ``async def``.  Sync convenience wrappers are
    auto-generated as ``<method_name>_sync()``.

    Args:
        base_url: Full base URL (e.g. ``"http://192.168.1.51:5555"``).
                  When omitted, host/port are taken from *config*.
        device_num: Alpaca device number.  Overrides *config* when provided.
        client_id: Alpaca ClientID sent with every request.
        timeout: Request timeout in seconds.  Overrides *config* when provided.
        config: Pre-built :class:`Config`.  When ``None``, :func:`load_config`
                is called so config-file and env-var settings apply automatically.
    """

    def __init__(
        self,
        base_url: str | None = None,
        device_num: int | None = None,
        client_id: int = 1,
        timeout: float | None = None,
        config: Config | None = None,
    ) -> None:
        if config is None:
            config = load_config()

        self._base_url = (
            base_url.rstrip("/") if base_url else f"http://{config.host}:{config.port}"
        )
        self._device_num = device_num if device_num is not None else config.device
        self._client_id = client_id
        self._timeout = timeout if timeout is not None else config.timeout
        self._transaction_id = 0
        self._lock = asyncio.Lock()

    # ── transport primitives ──────────────────────────────────────────────

    @property
    def _action_url(self) -> str:
        return f"{self._base_url}/api/v1/telescope/{self._device_num}/action"

    async def _next_txn_id(self) -> int:
        async with self._lock:
            self._transaction_id += 1
            return self._transaction_id

    async def action(self, action: str, params: dict | None = None) -> Any:
        """Send a direct Alpaca action and return the unwrapped ``Value``.

        Args:
            action: The Alpaca ``Action`` field value.
            params: Dict serialised as JSON into the ``Parameters`` field.

        Raises:
            SSAlpError: When the response has a non-zero ``ErrorNumber``.
            SSAlpConnectionError: On network / HTTP failure.
        """
        txn_id = await self._next_txn_id()
        params_json = json.dumps(params) if params is not None else "{}"

        form_data = {
            "Action": action,
            "Parameters": params_json,
            "ClientID": str(self._client_id),
            "ClientTransactionID": str(txn_id),
        }

        logger.debug("→ action=%s params=%s txn_id=%d", action, params_json, txn_id)

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.put(self._action_url, data=form_data)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.error("Timeout action=%s txn_id=%d", action, txn_id)
            raise SSAlpConnectionError(f"Request timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            logger.error("Connection error action=%s txn_id=%d", action, txn_id)
            raise SSAlpConnectionError(f"Connection failed: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP %d action=%s txn_id=%d", exc.response.status_code, action, txn_id
            )
            raise SSAlpConnectionError(
                f"HTTP {exc.response.status_code}: {exc}"
            ) from exc

        elapsed_ms = (time.monotonic() - start) * 1000
        envelope = response.json()
        error_number: int = envelope.get("ErrorNumber", 0)
        error_message: str = envelope.get("ErrorMessage", "")
        value = envelope.get("Value")

        logger.debug(
            "← action=%s txn_id=%d error=%d elapsed_ms=%.1f value=%r",
            action,
            txn_id,
            error_number,
            elapsed_ms,
            value,
        )

        if error_number != 0:
            logger.warning(
                "action=%s error_number=%d message=%s",
                action,
                error_number,
                error_message,
            )
            raise SSAlpError(
                error_message or f"ErrorNumber={error_number}", error_number
            )

        return value

    async def method_sync(self, method: str, params: Any = None) -> Any:
        """Call the ``method_sync`` Alpaca action.

        Args:
            method: Name of the device method to invoke.
            params: Optional parameters forwarded as ``params`` in the JSON body.
        """
        payload: dict = {"method": method}
        if params is not None:
            payload["params"] = params
        return await self.action("method_sync", payload)

    async def method_async(self, method: str, params: Any = None) -> Any:
        """Call the ``method_async`` Alpaca action."""
        payload: dict = {"method": method}
        if params is not None:
            payload["params"] = params
        return await self.action("method_async", payload)

    async def get_bytes(self, url: str) -> bytes:
        """Download binary content (e.g. an image file) by URL.

        Raises:
            SSAlpConnectionError: On network / HTTP failure.
        """
        logger.debug("→ GET %s", url)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.get(url)
                response.raise_for_status()
                return response.content
        except httpx.TimeoutException as exc:
            raise SSAlpConnectionError(f"Request timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise SSAlpConnectionError(f"Connection failed: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise SSAlpConnectionError(
                f"HTTP {exc.response.status_code}: {exc}"
            ) from exc

    # ── manual sync wrappers for transport primitives ─────────────────────

    def action_sync(self, action: str, params: dict | None = None) -> Any:
        """Sync wrapper for :meth:`action`."""
        return asyncio.run(self.action(action, params))

    def get_bytes_sync(self, url: str) -> bytes:
        """Sync wrapper for :meth:`get_bytes`."""
        return asyncio.run(self.get_bytes(url))
