from seestar_mcp.server import call, make_client
from ssalp_api_client import SSAlpConnectionError


def test_make_client_uses_seestar_base_url(monkeypatch):
    monkeypatch.setenv("SEESTAR_BASE_URL", "http://10.0.0.9:5555")
    c = make_client()
    assert c._base_url == "http://10.0.0.9:5555"


def test_make_client_threads_telescope_id():
    c = make_client(telescope_id=0)
    assert c._device_num == 0


async def test_call_converts_connection_error():
    async def boom(client):
        raise SSAlpConnectionError("refused")

    out = await call(1, boom)
    assert out["ok"] is False and "refused" in out["error"]
