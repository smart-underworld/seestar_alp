"""Tests for SSAlpApiClient transport layer."""

from __future__ import annotations

import asyncio

import pytest
import pytest_httpx

from ssalp_api_client.client import SSAlpApiClient
from ssalp_api_client.config import Config
from ssalp_api_client.exceptions import SSAlpConnectionError, SSAlpError

from .conftest import make_alpaca_response


ACTION_URL = "http://localhost:5555/api/v1/telescope/1/action"


@pytest.fixture
def cfg() -> Config:
    return Config(host="localhost", port=5555, device=1, timeout=5.0)


@pytest.fixture
def client(cfg: Config) -> SSAlpApiClient:
    return SSAlpApiClient(config=cfg)


# ── helpers ────────────────────────────────────────────────────────────────

def _stub(httpx_mock: pytest_httpx.HTTPXMock, value=None, error_number: int = 0) -> None:
    httpx_mock.add_response(
        method="PUT",
        url=ACTION_URL,
        json=make_alpaca_response(value=value, error_number=error_number,
                                   error_message="" if error_number == 0 else "device error"),
    )


# ── constructor ────────────────────────────────────────────────────────────

class TestConstructor:
    def test_explicit_base_url(self):
        c = SSAlpApiClient(base_url="http://10.0.0.1:9000")
        assert c._base_url == "http://10.0.0.1:9000"

    def test_explicit_base_url_trailing_slash_stripped(self):
        c = SSAlpApiClient(base_url="http://10.0.0.1:9000/")
        assert c._base_url == "http://10.0.0.1:9000"

    def test_uses_config_host_port(self):
        cfg = Config(host="192.168.1.50", port=8888)
        c = SSAlpApiClient(config=cfg)
        assert c._base_url == "http://192.168.1.50:8888"

    def test_device_num_override(self):
        cfg = Config(device=1)
        c = SSAlpApiClient(device_num=3, config=cfg)
        assert c._device_num == 3

    def test_timeout_override(self):
        cfg = Config(timeout=10.0)
        c = SSAlpApiClient(timeout=30.0, config=cfg)
        assert c._timeout == 30.0

    def test_invalid_device_type(self):
        with pytest.raises((ValueError, TypeError)):
            Config(device="bad")


# ── action() ──────────────────────────────────────────────────────────────

class TestAction:
    async def test_happy_path_returns_value(self, client, httpx_mock):
        _stub(httpx_mock, value={"status": "ok"})
        result = await client.action("test_connection")
        assert result == {"status": "ok"}

    async def test_form_fields_present(self, client, httpx_mock):
        _stub(httpx_mock, value=None)
        await client.action("my_action", {"key": "val"})
        req = httpx_mock.get_request()
        body = req.content.decode()
        assert "Action=my_action" in body
        assert "ClientID=" in body
        assert "ClientTransactionID=" in body
        assert "Parameters=" in body

    async def test_parameters_json_encoded(self, client, httpx_mock):
        _stub(httpx_mock, value=None)
        await client.action("my_action", {"ra": 1.23, "dec": -5.0})
        req = httpx_mock.get_request()
        body = req.content.decode()
        # Parameters value must be a JSON string (double-encoded)
        assert "%7B" in body or "Parameters=%7B" in body or '"ra"' in body

    async def test_transaction_id_increments(self, client, httpx_mock):
        _stub(httpx_mock, value=1)
        _stub(httpx_mock, value=2)
        await client.action("a")
        await client.action("b")
        requests = httpx_mock.get_requests()
        ids = [
            int(r.content.decode().split("ClientTransactionID=")[1].split("&")[0])
            for r in requests
        ]
        assert ids[1] == ids[0] + 1

    async def test_transaction_ids_unique_under_concurrency(self, client, httpx_mock):
        for _ in range(10):
            _stub(httpx_mock, value=None)
        await asyncio.gather(*[client.action("x") for _ in range(10)])
        requests = httpx_mock.get_requests()
        ids = [
            int(r.content.decode().split("ClientTransactionID=")[1].split("&")[0])
            for r in requests
        ]
        assert len(set(ids)) == 10

    async def test_error_number_raises_ssalp_error(self, client, httpx_mock):
        _stub(httpx_mock, error_number=1025)
        with pytest.raises(SSAlpError) as exc_info:
            await client.action("bad_action")
        assert exc_info.value.error_number == 1025

    async def test_zero_error_number_not_raised(self, client, httpx_mock):
        _stub(httpx_mock, value=None, error_number=0)
        result = await client.action("ok_action")
        assert result is None

    async def test_null_value_not_an_error(self, client, httpx_mock):
        _stub(httpx_mock, value=None)
        result = await client.action("no_value_action")
        assert result is None

    async def test_connection_refused_raises_connection_error(self, client, httpx_mock):
        import httpx as _httpx
        httpx_mock.add_exception(_httpx.ConnectError("refused"))
        with pytest.raises(SSAlpConnectionError, match="Connection failed"):
            await client.action("x")

    async def test_timeout_raises_connection_error(self, client, httpx_mock):
        import httpx as _httpx
        httpx_mock.add_exception(_httpx.TimeoutException("timed out"))
        with pytest.raises(SSAlpConnectionError, match="timed out"):
            await client.action("x")

    async def test_http_5xx_raises_connection_error(self, client, httpx_mock):
        httpx_mock.add_response(method="PUT", url=ACTION_URL, status_code=500)
        with pytest.raises(SSAlpConnectionError):
            await client.action("x")


# ── method_async() ────────────────────────────────────────────────────────

class TestMethodAsync:
    async def test_wraps_method_async_action(self, client, httpx_mock):
        _stub(httpx_mock, value="async_result")
        result = await client.method_async("get_focuser_position", {"ret_obj": True})
        body = httpx_mock.get_request().content.decode()
        assert "Action=method_async" in body
        assert "get_focuser_position" in body
        assert result == "async_result"

    async def test_method_async_no_params(self, client, httpx_mock):
        _stub(httpx_mock, value=None)
        await client.method_async("some_method")
        body = httpx_mock.get_request().content.decode()
        assert "Action=method_async" in body


# ── method_sync() ─────────────────────────────────────────────────────────

class TestMethodSync:
    async def test_wraps_method_sync_action(self, client, httpx_mock):
        _stub(httpx_mock, value="pong")
        result = await client.method_sync("test_connection")
        req = httpx_mock.get_request()
        body = req.content.decode()
        assert "Action=method_sync" in body
        assert "test_connection" in body
        assert result == "pong"

    async def test_passes_params(self, client, httpx_mock):
        _stub(httpx_mock, value=None)
        await client.method_sync("get_control_value", ["gain"])
        req = httpx_mock.get_request()
        body = req.content.decode()
        assert "gain" in body


# ── get_bytes() ───────────────────────────────────────────────────────────

class TestGetBytes:
    async def test_downloads_bytes(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:5555/images/test.jpg",
            content=b"\xff\xd8\xff",
        )
        data = await client.get_bytes("http://localhost:5555/images/test.jpg")
        assert data == b"\xff\xd8\xff"

    async def test_connect_error_raises(self, client, httpx_mock):
        import httpx as _httpx
        httpx_mock.add_exception(_httpx.ConnectError("no route"))
        with pytest.raises(SSAlpConnectionError):
            await client.get_bytes("http://localhost:5555/images/x.jpg")


# ── sync wrappers ─────────────────────────────────────────────────────────

class TestSyncWrappers:
    def test_sync_wrapper_generated(self):
        assert hasattr(SSAlpApiClient, "test_connection_sync")
        assert hasattr(SSAlpApiClient, "get_device_state_sync")
        assert hasattr(SSAlpApiClient, "scope_goto_sync")
        assert hasattr(SSAlpApiClient, "start_mosaic_sync")

    def test_action_sync_exists(self):
        assert hasattr(SSAlpApiClient, "action_sync")

    def test_get_bytes_sync_exists(self):
        assert hasattr(SSAlpApiClient, "get_bytes_sync")


# ── command layer smoke tests ─────────────────────────────────────────────

class TestCommandSmoke:
    """Verify that command methods send the correct action/method to the wire."""

    async def _assert_action(self, httpx_mock, coro, expected_action: str):
        _stub(httpx_mock, value=None)
        await coro
        body = httpx_mock.get_request().content.decode()
        assert f"Action={expected_action}" in body

    async def _assert_method(self, httpx_mock, coro, expected_method: str):
        _stub(httpx_mock, value=None)
        await coro
        body = httpx_mock.get_request().content.decode()
        assert "Action=method_sync" in body
        assert expected_method in body

    async def test_test_connection(self, client, httpx_mock):
        await self._assert_method(httpx_mock, client.test_connection(), "test_connection")

    async def test_get_device_state(self, client, httpx_mock):
        await self._assert_method(httpx_mock, client.get_device_state(), "get_device_state")

    async def test_scope_goto(self, client, httpx_mock):
        await self._assert_method(httpx_mock, client.scope_goto(1.0, 2.0), "scope_goto")

    async def test_scope_park(self, client, httpx_mock):
        await self._assert_method(httpx_mock, client.scope_park(), "scope_park")

    async def test_start_mosaic(self, client, httpx_mock):
        await self._assert_action(
            httpx_mock,
            client.start_mosaic("M42", 1.0, 2.0, 3600),
            "start_mosaic",
        )

    async def test_start_scheduler(self, client, httpx_mock):
        await self._assert_action(
            httpx_mock, client.start_scheduler(), "start_scheduler"
        )

    async def test_play_sound(self, client, httpx_mock):
        await self._assert_action(httpx_mock, client.play_sound(81), "play_sound")

    async def test_startup_sequence(self, client, httpx_mock):
        await self._assert_action(
            httpx_mock, client.startup_sequence(lat=0.0, lon=0.0), "action_start_up_sequence"
        )


# ── input validation ──────────────────────────────────────────────────────

class TestInputValidation:
    async def test_set_gain_negative_rejected(self, client):
        with pytest.raises(ValueError, match="gain"):
            await client.set_gain(-1)

    async def test_set_brightness_out_of_range(self, client):
        with pytest.raises(ValueError):
            await client.set_brightness(101)

    async def test_set_brightness_negative(self, client):
        with pytest.raises(ValueError):
            await client.set_brightness(-1)

    async def test_set_exposure_zero_rejected(self, client):
        with pytest.raises(ValueError):
            await client.set_exposure(0, 500)

    async def test_set_heater_value_out_of_range(self, client):
        with pytest.raises(ValueError):
            await client.set_heater(True, value=101)

    async def test_set_wheel_position_zero_rejected(self, client):
        with pytest.raises(ValueError):
            await client.set_wheel_position(0)

    async def test_start_mosaic_negative_time(self, client):
        with pytest.raises(ValueError):
            await client.start_mosaic("T", 1.0, 2.0, session_time_sec=-1)

    async def test_schedule_wait_for_zero_rejected(self, client):
        with pytest.raises(ValueError):
            await client.schedule_wait_for(0)

    async def test_start_exposure_invalid_type(self, client):
        with pytest.raises(ValueError):
            await client.start_exposure(exp_type="unknown")
