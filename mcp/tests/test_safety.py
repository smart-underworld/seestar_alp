from seestar_mcp.safety import gate


def test_gate_blocks_unconfirmed_physical():
    out = gate("shutdown", confirm=False)
    assert out["requires_confirmation"] is True


def test_gate_allows_confirmed_physical():
    assert gate("shutdown", confirm=True) is None


def test_gate_ignores_non_physical():
    assert gate("get_device_state", confirm=False) is None
