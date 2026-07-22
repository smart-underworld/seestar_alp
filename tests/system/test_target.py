import socket
import time

import pytest
import tomlkit

from tests.system.target import (
    PreconditionError,
    SystemTestTarget,
    build_config_toml,
    check_sandbox_renderer_fresh,
    find_free_port,
    probe_tcp_port,
)


def test_find_free_port_returns_a_bindable_port():
    port = find_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_probe_tcp_port_succeeds_against_open_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        probe_tcp_port("127.0.0.1", port, "test-listener", timeout=1.0)


def test_probe_tcp_port_raises_actionable_error_against_closed_port():
    port = find_free_port()  # bound-and-released, nothing listening now
    with pytest.raises(PreconditionError, match="test-thing"):
        probe_tcp_port("127.0.0.1", port, "test-thing", timeout=0.5)


def test_check_sandbox_renderer_fresh_raises_when_missing(tmp_path):
    with pytest.raises(PreconditionError, match="renderd"):
        check_sandbox_renderer_fresh(tmp_path, max_age_s=30.0)


def test_check_sandbox_renderer_fresh_passes_when_stale(tmp_path):
    # sim.renderd only re-renders in response to a pointing change, so an
    # idle-but-running renderer can leave a solve.fits that's hours old with
    # no pointing activity to trigger a fresh render. Staleness alone must
    # not be treated as evidence the renderer is down -- only a missing file
    # is checked.
    solve_fits = tmp_path / "solve.fits"
    solve_fits.write_bytes(b"x")
    old_time = time.time() - 3600
    import os

    os.utime(solve_fits, (old_time, old_time))
    check_sandbox_renderer_fresh(tmp_path, max_age_s=30.0)


def test_check_sandbox_renderer_fresh_passes_when_recent(tmp_path):
    solve_fits = tmp_path / "solve.fits"
    solve_fits.write_bytes(b"x")
    check_sandbox_renderer_fresh(tmp_path, max_age_s=30.0)


def test_build_config_toml_produces_parseable_toml_with_expected_fields(tmp_path):
    target = SystemTestTarget(
        kind="sandbox",
        host="127.0.0.1",
        pem_path=str(tmp_path / "key.pem"),
        goto_target_name="Vega",
        goto_ra="279.2347",
        goto_dec="38.7836",
        capture_duration_s=120,
        renderer_shared_dir=None,
    )
    text = build_config_toml(
        target, frontend="v2", uiport=15432, imgport=17556, alpaca_port=15555
    )
    doc = tomlkit.parse(text)

    assert doc["webui_settings"]["uiport"] == 15432
    assert doc["webui_settings"]["frontend"] == "v2"
    assert doc["network"]["imgport"] == 17556
    assert doc["network"]["port"] == 15555
    assert doc["seestar_initialization"]["interop_pem"] == str(tmp_path / "key.pem")
    assert doc["seestars"][0]["ip_address"] == "127.0.0.1"
    assert doc["seestars"][0]["device_num"] == 1
