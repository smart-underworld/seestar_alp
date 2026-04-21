"""Minimal HTTP client for the Alpaca action endpoint exposed by root_app.py.

Used by CLI tools and in-process integrations that need to send firmware
RPCs (e.g. `scope_speed_move`, `scope_get_equ_coord`) through the running
application rather than talking to the Seestar directly.

The server wraps each RPC in a JSON-RPC envelope and unwraps the response's
`Value` field; this client mirrors that contract.
"""

from __future__ import annotations

import json

import requests


class AlpacaClient:
    def __init__(self, host: str, port: int, device: int):
        self.base = f"http://{host}:{port}/api/v1/telescope/{device}"
        self._txn = 1000

    def _txn_next(self) -> int:
        self._txn += 1
        return self._txn

    def action(self, action_name: str, parameters: dict, timeout: float = 30.0):
        data = {
            "Action": action_name,
            "Parameters": json.dumps(parameters),
            "ClientID": 1,
            "ClientTransactionID": self._txn_next(),
        }
        r = requests.put(f"{self.base}/action", data=data, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def method_sync(self, method: str, params=None):
        payload = {"method": method}
        if params is not None:
            payload["params"] = params
        resp = self.action("method_sync", payload)
        # Alpaca wraps the RPC payload under "Value"
        return resp.get("Value")

    def get_event_state(self, event_name: str | None = None):
        params = {"event_name": event_name} if event_name else {}
        return self.action("get_event_state", params).get("Value")


def current_radec(cli: AlpacaClient) -> tuple[float, float]:
    resp = cli.method_sync("scope_get_equ_coord")
    result = resp["result"]
    return float(result["ra"]), float(result["dec"])
