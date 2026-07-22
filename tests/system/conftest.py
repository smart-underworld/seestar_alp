"""pytest configuration for the manual-only system test suite.

Never auto-selected: everything under tests/system/ is skipped unless
--target is explicitly passed, so a bare `pytest` run (or the CI lanes in
AGENTS.md) never reaches out to real hardware or the sandbox.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.system.app_process import AppProcess  # noqa: E402
from tests.system.target import (  # noqa: E402
    PreconditionError,
    SystemTestTarget,
    build_config_toml,
    check_sandbox_renderer_fresh,
    find_free_port,
    probe_tcp_port,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def pytest_addoption(parser):
    group = parser.getgroup("system")
    group.addoption(
        "--target",
        choices=["sandbox", "real"],
        default=None,
        help="Run tests/system/ against the QEMU sandbox or a real Seestar. "
        "Omitting this skips the entire tests/system/ directory.",
    )
    group.addoption("--host", default="127.0.0.1", help="Device/sandbox host.")
    group.addoption(
        "--frontend",
        choices=["classic", "v2", "both"],
        default="both",
        help="Which frontend(s) to exercise.",
    )
    group.addoption(
        "--pem",
        default=str(Path.home() / "dev" / "seestar_private_key.pem"),
        help="Path to the firmware 7.18+ interop PEM key.",
    )
    group.addoption("--goto-target-name", default="Vega")
    group.addoption("--goto-ra", default="279.2347", help="Decimal degrees.")
    group.addoption("--goto-dec", default="38.7836", help="Decimal degrees.")
    group.addoption(
        "--capture-duration",
        type=int,
        default=120,
        help="Seconds for the scheduled star-capture item.",
    )
    group.addoption(
        "--renderer-shared-dir",
        default=None,
        help="Path to seestar-api-research/sandbox/sim/shared "
        "(required when --target sandbox, for the goto precondition check).",
    )


def pytest_collection_modifyitems(config, items):
    system_items = [
        item for item in items if str(Path(__file__).parent) in str(item.fspath)
    ]
    if not system_items:
        return
    if config.getoption("--target") is None:
        skip = pytest.mark.skip(
            reason="tests/system/ requires --target sandbox|real; skipped by default"
        )
        for item in system_items:
            item.add_marker(skip)
        return
    for item in system_items:
        item.add_marker(pytest.mark.system)


@pytest.fixture(scope="session")
def target(request) -> SystemTestTarget:
    kind = request.config.getoption("--target")
    if kind is None:
        pytest.skip("no --target given")

    if kind == "real" and request.config.getoption("--capture") != "no":
        raise PreconditionError(
            "--target real requires interactive confirmation before goto/"
            "schedule steps. Re-run with -s, e.g.:\n"
            "  pytest tests/system --target real --host <ip> -s"
        )

    host = request.config.getoption("--host")
    renderer_shared_dir = request.config.getoption("--renderer-shared-dir")
    renderer_shared_dir = Path(renderer_shared_dir) if renderer_shared_dir else None

    t = SystemTestTarget(
        kind=kind,
        host=host,
        pem_path=request.config.getoption("--pem"),
        goto_target_name=request.config.getoption("--goto-target-name"),
        goto_ra=request.config.getoption("--goto-ra"),
        goto_dec=request.config.getoption("--goto-dec"),
        capture_duration_s=request.config.getoption("--capture-duration"),
        renderer_shared_dir=renderer_shared_dir,
    )

    probe_tcp_port(t.host, 4700, "device control port")
    probe_tcp_port(t.host, 4800, "device imaging port")
    if kind == "sandbox":
        if t.renderer_shared_dir is None:
            raise PreconditionError(
                "--target sandbox requires --renderer-shared-dir pointing at "
                "seestar-api-research/sandbox/sim/shared (goto/3PPA there is "
                "closed-loop and needs sim.renderd running on the host)."
            )
        check_sandbox_renderer_fresh(t.renderer_shared_dir)

    return t


@pytest.fixture
def require_real_confirmation(target):
    def _confirm(action_description: str) -> None:
        if target.kind != "real":
            return
        print(f"\n[system-test] About to run against REAL hardware: {action_description}")
        response = input("Type 'yes' to proceed, anything else aborts: ")
        if response.strip().lower() != "yes":
            pytest.fail(f"Aborted by user before: {action_description}")

    return _confirm


@pytest.fixture(scope="module")
def running_app(request, target):
    started: dict[str, AppProcess] = {}

    def _start(frontend: str) -> AppProcess:
        if frontend in started:
            return started[frontend]
        uiport = find_free_port()
        imgport = find_free_port()
        alpaca_port = find_free_port()
        config_text = build_config_toml(
            target, frontend=frontend, uiport=uiport, imgport=imgport, alpaca_port=alpaca_port
        )
        config_dir = Path(request.node.name.replace("/", "_") + f"_{frontend}_scratch")
        config_dir = Path("/tmp") / "seestar_alp_system_test" / config_dir.name
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.toml"
        config_path.write_text(config_text)

        proc = AppProcess(REPO_ROOT, config_path, uiport, ready_timeout=45.0)
        proc.start()
        started[frontend] = proc
        return proc

    yield _start

    for proc in started.values():
        proc.stop()
