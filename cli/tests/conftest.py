"""Shared pytest fixtures for ssalp_api_client tests."""

from __future__ import annotations

import pytest

from ssalp_api_client.config import Config
from ssalp_api_client.client import SSAlpApiClient


@pytest.fixture
def default_config() -> Config:
    return Config(host="localhost", port=5555, device=1, timeout=5.0)


@pytest.fixture
def client(default_config: Config) -> SSAlpApiClient:
    return SSAlpApiClient(config=default_config)


@pytest.fixture
def action_url() -> str:
    return "http://localhost:5555/api/v1/telescope/1/action"


def make_alpaca_response(
    value=None, error_number: int = 0, error_message: str = ""
) -> dict:
    """Build a minimal Alpaca response envelope."""
    return {
        "ClientTransactionID": 1,
        "ServerTransactionID": 1,
        "ErrorNumber": error_number,
        "ErrorMessage": error_message,
        "Value": value,
    }
