from seestar_mcp.safety import gate, require_confirm


def test_gate_blocks_unconfirmed_physical():
    out = gate("shutdown", confirm=False)
    assert out["requires_confirmation"] is True


def test_gate_allows_confirmed_physical():
    assert gate("shutdown", confirm=True) is None


def test_gate_ignores_non_physical():
    assert gate("get_device_state", confirm=False) is None


def test_require_confirm_blocks_without_confirm():
    out = require_confirm("start_mosaic", confirm=False)
    assert out["ok"] is False and out["requires_confirmation"] is True


def test_require_confirm_passes_with_confirm():
    assert require_confirm("start_mosaic", confirm=True) is None


def test_require_confirm_custom_reason():
    out = require_confirm("startup_sequence", confirm=False, reason="moves the mount")
    assert out["error"] == "moves the mount"
