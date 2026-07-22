from pathlib import Path

import pytest
import tomlkit

from tests.system.app_process import AppProcess
from tests.system.target import SystemTestTarget, build_config_toml, find_free_port

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def unreachable_target_config(tmp_path):
    # 127.0.0.1:1 is a privileged, always-closed port — the device layer will
    # keep retrying in the background but must never block root_app.py's own
    # HTTP servers from binding and printing "Startup Complete".
    target = SystemTestTarget(
        kind="sandbox",
        host="127.0.0.1",
        pem_path=str(tmp_path / "unused.pem"),
        goto_target_name="Vega",
        goto_ra="279.2347",
        goto_dec="38.7836",
        capture_duration_s=5,
        renderer_shared_dir=None,
    )
    uiport = find_free_port()
    imgport = find_free_port()
    alpaca_port = find_free_port()
    text = build_config_toml(
        target, frontend="classic", uiport=uiport, imgport=imgport, alpaca_port=alpaca_port
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(text)
    return config_path, uiport


def test_app_process_starts_and_stops_cleanly(unreachable_target_config):
    config_path, uiport = unreachable_target_config
    proc = AppProcess(REPO_ROOT, config_path, uiport, ready_timeout=30.0)
    try:
        proc.start()
        assert "http://127.0.0.1" in proc.base_url
    finally:
        proc.stop()

    # stop() must be idempotent
    proc.stop()


def test_app_process_raises_with_log_tail_on_bad_config(tmp_path):
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("this is not valid toml [[[")
    uiport = find_free_port()
    proc = AppProcess(REPO_ROOT, bad_config, uiport, ready_timeout=5.0)
    with pytest.raises(TimeoutError) as excinfo:
        proc.start()
    assert len(str(excinfo.value)) > 0
    proc.stop()
