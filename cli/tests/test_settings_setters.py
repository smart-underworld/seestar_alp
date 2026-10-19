"""HTTP-shape tests for the set_setting / set_stack_settings client setters."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import pytest

from ssalp_api_client.client import SSAlpApiClient
from ssalp_api_client.config import Config

from .conftest import make_alpaca_response

ACTION_URL = "http://localhost:5555/api/v1/telescope/1/action"


@pytest.fixture
def client() -> SSAlpApiClient:
    return SSAlpApiClient(
        config=Config(host="localhost", port=5555, device=1, timeout=5.0)
    )


def _sent_method_sync(httpx_mock) -> dict:
    form = parse_qs(httpx_mock.get_request().content.decode())
    assert form["Action"] == ["method_sync"]
    return json.loads(form["Parameters"][0])


async def test_set_setting_wraps_stack_payload(client, httpx_mock):
    httpx_mock.add_response(
        method="PUT", url=ACTION_URL, json=make_alpaca_response(value={})
    )
    await client.set_setting(exp_ms=10000, save_discrete_frame=True)
    payload = _sent_method_sync(httpx_mock)
    assert payload == {
        "method": "set_setting",
        "params": {"stack": {"exp_ms": 10000, "save_discrete_frame": True}},
    }


async def test_set_stack_settings_sends_action(client, httpx_mock):
    httpx_mock.add_response(
        method="PUT", url=ACTION_URL, json=make_alpaca_response(value={})
    )
    await client.set_stack_settings(exp_ms=10000, gain=80)
    payload = _sent_method_sync(httpx_mock)
    assert payload == {
        "method": "set_stack_settings",
        "params": {"exp_ms": 10000, "gain": 80},
    }
