# Startup Schedule Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user launch `python3 root_app.py --schedule FILE` so seestar_alp boots and, once the scope is connected and controllable, automatically imports and runs that schedule.

**Architecture:** A small, duck-typed helper module (`device/startup_schedule.py`) owns the CLI parser, a connection-gated "import + start" routine, and a non-blocking launcher that runs it on a daemon thread. `root_app.py`'s `__main__` parses args and hands off to the launcher after the web servers start, so `READY=1`/`waitress.serve` are never blocked. The helper operates only through the public device methods (`is_connected`, `is_client_master()`, `import_schedule`, `start_scheduler`), so it is unit-testable with a fake device and needs no heavy imports.

**Tech Stack:** Python 3.13, argparse, threading, pathlib; pytest; the existing seestar_alp device/telescope layer and simulator.

**Spec:** This plan — distilled from the triage of GitHub issue #816 ("Automate Schedule Start"). Decisions locked in conversation: flag-only (no bare positional); config-key/env-var precedence is a future extension, out of scope for v1.

## Global Constraints

- Python 3.13; both `ruff check .` and `ruff format --check .` must pass (CI runs both).
- The no-arg invocation `python3 root_app.py` must behave exactly as today — packaging (`.deb`) and systemd units launch it with no arguments.
- The startup-schedule work must never block `n.notify("READY=1")` or `waitress.serve(...)`; it runs on a `daemon=True` thread.
- Readiness to start a schedule means **connected AND master**: gate on `device.is_connected` *and* `device.is_client_master()`, not connection alone (`start_scheduler` at `device/seestar_device.py:3255` refuses without master on guest-mode firmware).
- `import_schedule` reads `params["is_retain_state"]` unconditionally (`device/seestar_device.py:3141`) — always pass it; opens `params["filepath"]` server-side relative to the process cwd — always pass an absolute path.
- Do not remove or alter any existing behavior in `root_app.py`; only add.

## Review Focus

- **Scope powered off at boot** → device never reaches connected; the helper must time out and give up cleanly, never hang or crash the daemon thread. (Task 1)
- **Guest-mode firmware / phone holds control** → `is_connected` is true but `is_client_master()` stays false; the gate must keep waiting and then time out rather than calling `start_scheduler` into a refusal. (Task 1)
- **Missing or malformed schedule file** → `import_schedule` raises (e.g. `FileNotFoundError`); the helper must catch, log, and return False, not let the daemon thread die. (Task 1)
- **Relative path under a different cwd** (systemd `WorkingDirectory`, shell) → must be resolved to absolute before the server-side `open`. (Task 1)
- **No-arg launch** (the overwhelmingly common case) → parser defaults leave `schedule` unset and the launcher is a no-op; nothing spawns. (Tasks 2, 3)

---

### Task 1: Connection-gated import-and-start helper

**Files:**
- Create: `device/startup_schedule.py`
- Test: `tests/test_startup_schedule.py`

**Interfaces:**
- Consumes: a device object exposing attribute `is_connected: bool`, and methods `is_client_master() -> bool`, `import_schedule(params: dict) -> dict`, `start_scheduler(params: dict) -> dict`. `import_schedule` returns the schedule dict on success or a dict with a non-zero `"code"` on handled failure, and may raise `OSError`/`FileNotFoundError`. `start_scheduler` returns the schedule dict on success or a dict with a non-zero `"code"` on refusal.
- Produces: `run_startup_schedule(device, filepath, *, retain_state=False, connect_timeout=120.0, poll_interval=1.0, logger=None) -> bool` — resolves `filepath` to an absolute path, waits up to `connect_timeout` seconds for the device to be connected and master, then imports and starts the schedule. Returns True only if the scheduler was started; False on timeout, missing device, import/start failure, or any exception. Never raises.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_startup_schedule.py
import os
import pytest
from device.startup_schedule import run_startup_schedule


class FakeDevice:
    def __init__(self, connected=True, master=True, import_result=None,
                 start_result=None, import_exc=None):
        self.is_connected = connected
        self._master = master
        self._import_result = import_result if import_result is not None else {"state": "stopped"}
        self._start_result = start_result if start_result is not None else {"state": "working"}
        self._import_exc = import_exc
        self.import_params = None
        self.start_called = False

    def is_client_master(self):
        return self._master

    def import_schedule(self, params):
        self.import_params = params
        if self._import_exc:
            raise self._import_exc
        return self._import_result

    def start_scheduler(self, params):
        self.start_called = True
        return self._start_result


def test_happy_path_imports_and_starts(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice()
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is True
    assert dev.import_params["is_retain_state"] is False
    assert dev.start_called is True


def test_resolves_relative_path_to_absolute(tmp_path, monkeypatch):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    monkeypatch.chdir(tmp_path)
    dev = FakeDevice()
    run_startup_schedule(dev, "sched.json", connect_timeout=1, poll_interval=0.01)
    assert os.path.isabs(dev.import_params["filepath"])
    assert dev.import_params["filepath"].endswith("sched.json")


def test_retain_state_passed_through(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice()
    run_startup_schedule(dev, str(f), retain_state=True, connect_timeout=1, poll_interval=0.01)
    assert dev.import_params["is_retain_state"] is True


def test_waits_then_proceeds_when_connection_is_late(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(connected=False)

    calls = {"n": 0}
    real = type(dev).is_client_master

    # Flip to connected after the first poll.
    def flip():
        calls["n"] += 1
        if calls["n"] >= 2:
            dev.is_connected = True
        return True
    dev.is_client_master = flip
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is True
    assert dev.start_called is True


def test_times_out_when_never_connected(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(connected=False)
    assert run_startup_schedule(dev, str(f), connect_timeout=0.05, poll_interval=0.01) is False
    assert dev.import_params is None
    assert dev.start_called is False


def test_times_out_when_connected_but_not_master(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(connected=True, master=False)
    assert run_startup_schedule(dev, str(f), connect_timeout=0.05, poll_interval=0.01) is False
    assert dev.import_params is None
    assert dev.start_called is False


def test_import_exception_returns_false_without_starting(tmp_path):
    f = tmp_path / "missing.json"
    dev = FakeDevice(import_exc=FileNotFoundError("nope"))
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is False
    assert dev.start_called is False


def test_import_error_code_returns_false_without_starting(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(import_result={"code": -1, "result": "scheduler active"})
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is False
    assert dev.start_called is False


def test_start_refusal_returns_false(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    dev = FakeDevice(start_result={"code": -1, "result": "grab control first"})
    assert run_startup_schedule(dev, str(f), connect_timeout=1, poll_interval=0.01) is False


def test_none_device_returns_false(tmp_path):
    f = tmp_path / "sched.json"
    f.write_text("{}")
    assert run_startup_schedule(None, str(f), connect_timeout=0.05, poll_interval=0.01) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest tests/test_startup_schedule.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'device.startup_schedule'`.

- [ ] **Step 3: Implement `run_startup_schedule` in `device/startup_schedule.py`**

Signature exactly as the Produces block. Approach:
- `abspath = str(Path(filepath).expanduser().resolve())`.
- If `device is None`: log and return False.
- Poll loop until a monotonic deadline (`time.monotonic() + connect_timeout`): if `device.is_connected and device.is_client_master()` break and proceed; else `time.sleep(poll_interval)`. On deadline without readiness, log and return False (do not call import).
- Wrap import+start in `try/except Exception`: call `device.import_schedule({"filepath": abspath, "is_retain_state": retain_state})`; if the result is a dict with a non-zero `"code"`, log and return False. Call `device.start_scheduler({})`; if that result is a dict with a non-zero `"code"`, log and return False. On any exception, log and return False.
- Return True.
- Use `logger or logging.getLogger(__name__)`; every exit path (timeout, bad path, refusal, success) logs one line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest tests/test_startup_schedule.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add device/startup_schedule.py tests/test_startup_schedule.py
git commit -m "feat: add connection-gated startup-schedule helper"
```

---

### Task 2: CLI parser and non-blocking launcher

**Files:**
- Modify: `device/startup_schedule.py`
- Test: `tests/test_startup_schedule.py`

**Interfaces:**
- Consumes: `run_startup_schedule` from Task 1.
- Produces:
  - `build_arg_parser() -> argparse.ArgumentParser` — defines `--schedule FILE` (default None), `--device N` (int, default 1), `--retain-state` (store_true, default False), `--schedule-connect-timeout SECONDS` (float, default 120.0). All optional; parsing an empty argv yields `schedule=None`.
  - `maybe_launch_startup_schedule(args, get_device, *, logger=None) -> threading.Thread | None` — if `args.schedule` is falsy, returns None and does not call `get_device`. Otherwise spawns and starts a `daemon=True` thread whose target looks up the device via `get_device(args.device)` (catching exceptions so a bad device number logs and gives up) and calls `run_startup_schedule(device, args.schedule, retain_state=args.retain_state, connect_timeout=args.schedule_connect_timeout, logger=logger)`. Returns the thread.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_startup_schedule.py
from device.startup_schedule import build_arg_parser, maybe_launch_startup_schedule


def test_parser_defaults_are_inert():
    args = build_arg_parser().parse_args([])
    assert args.schedule is None
    assert args.device == 1
    assert args.retain_state is False
    assert args.schedule_connect_timeout == 120.0


def test_parser_reads_all_flags():
    args = build_arg_parser().parse_args(
        ["--schedule", "s.json", "--device", "2", "--retain-state",
         "--schedule-connect-timeout", "30"]
    )
    assert args.schedule == "s.json"
    assert args.device == 2
    assert args.retain_state is True
    assert args.schedule_connect_timeout == 30.0


def test_launcher_noop_when_no_schedule():
    args = build_arg_parser().parse_args([])
    called = []
    thread = maybe_launch_startup_schedule(args, lambda n: called.append(n))
    assert thread is None
    assert called == []


def test_launcher_spawns_and_invokes_run(tmp_path, monkeypatch):
    import device.startup_schedule as mod
    recorded = {}

    def fake_run(device, filepath, **kwargs):
        recorded["device"] = device
        recorded["filepath"] = filepath
        recorded["kwargs"] = kwargs
        return True

    monkeypatch.setattr(mod, "run_startup_schedule", fake_run)
    args = build_arg_parser().parse_args(["--schedule", "s.json", "--device", "3"])
    sentinel = object()
    thread = maybe_launch_startup_schedule(args, lambda n: sentinel if n == 3 else None)
    assert thread is not None
    thread.join(timeout=2)
    assert recorded["device"] is sentinel
    assert recorded["filepath"] == "s.json"


def test_launcher_survives_get_device_error(monkeypatch):
    import device.startup_schedule as mod
    monkeypatch.setattr(mod, "run_startup_schedule",
                        lambda *a, **k: pytest.fail("should not run"))

    def boom(n):
        raise KeyError(n)

    args = build_arg_parser().parse_args(["--schedule", "s.json", "--device", "9"])
    thread = maybe_launch_startup_schedule(args, boom)
    thread.join(timeout=2)
    assert not thread.is_alive()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest tests/test_startup_schedule.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_arg_parser'`.

- [ ] **Step 3: Implement `build_arg_parser` and `maybe_launch_startup_schedule` in `device/startup_schedule.py`**

Parser per the Produces block (argparse). `maybe_launch_startup_schedule`: guard `if not args.schedule: return None`; define a local `target()` that wraps `get_device(args.device)` then `run_startup_schedule(...)` in a `try/except Exception` that logs; create `threading.Thread(target=target, name="StartupScheduleThread", daemon=True)`, start it, return it. Reference `run_startup_schedule` as a module global (so the test's monkeypatch takes effect).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest tests/test_startup_schedule.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add device/startup_schedule.py tests/test_startup_schedule.py
git commit -m "feat: add startup-schedule CLI parser and launcher"
```

---

### Task 3: Wire the flag into `root_app.py`

**Files:**
- Modify: `root_app.py` (imports near the top; `__main__` block, after `front.start()` and before `waitress.serve(...)`)

**Interfaces:**
- Consumes: `build_arg_parser`, `maybe_launch_startup_schedule` from Task 2; `telescope.get_seestar_device` (already imported as `device.telescope`).

- [ ] **Step 1: Add the wiring**

- Add `from device.startup_schedule import build_arg_parser, maybe_launch_startup_schedule` with the other `device` imports.
- At the start of the `if __name__ == "__main__":` block, before other startup, parse: `args = build_arg_parser().parse_args()`. (Parsing first means `--help` and bad flags fail fast before servers spin up.)
- After `front.start()` and the config observer are running (the device watch threads are already started inside `DeviceMain`), call `maybe_launch_startup_schedule(args, telescope.get_seestar_device, logger=logger)`. Do not store or join the returned thread; it is a daemon.
- Leave `READY=1` and `waitress.serve(...)` exactly as they are.

- [ ] **Step 2: Verify no-arg launch still imports and parses cleanly**

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -c "import root_app"`
Expected: imports with no error (no servers start on import).

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python root_app.py --help`
Expected: usage text listing `--schedule`, `--device`, `--retain-state`, `--schedule-connect-timeout`; exit 0.

- [ ] **Step 3: Commit**

```bash
git add root_app.py
git commit -m "feat: run a schedule at startup via --schedule flag"
```

---

### Task 4: Simulator end-to-end integration test

**Files:**
- Modify: `tests/integration/test_simulator_e2e.py`

**Interfaces:**
- Consumes: `run_startup_schedule` from Task 1; the existing simulator fixtures/patterns (`SocketListener`, `_find_free_port`, `_wait_for_tcp`, `telescope.start_seestar_device`) as used by `two_simulator_servers` / `two_device_federation` (`tests/integration/test_simulator_e2e.py:896`).

- [ ] **Step 1: Write the failing test**

Add a test (e.g. `test_38_startup_schedule_connects_and_starts`) that:
- Starts one simulator instance on free ports and waits for TCP (mirror `two_simulator_servers`), isolating config as that fixture does (`monkeypatch.setattr(Config, "seestar_interop_pem", "", raising=False)` and clear `tel_module.seestar_dev`).
- Wires one device: `dev = tel_module.start_seestar_device(logger, "Seestar Alpha", host, port, 1)` and polls up to ~10s for `dev.is_connected`.
- Writes a minimal schedule to a tmp file: `{"list": [{"action": "wait_for", "params": {"timer_sec": 30}}]}` (a `wait_for` item keeps the scheduler in `working` without slewing).
- Calls `run_startup_schedule(dev, str(path), connect_timeout=10, poll_interval=0.1)` and asserts it returns True.
- Asserts `dev.schedule["state"] == "working"`.
- Cleanup: `dev.stop_scheduler({})` and tear down the listener/thread.

```python
@pytest.mark.integration
def test_38_startup_schedule_connects_and_starts(tmp_path, monkeypatch):
    from device.startup_schedule import run_startup_schedule
    # ... start simulator, wire device, wait for dev.is_connected ...
    sched = tmp_path / "startup.json"
    sched.write_text(json.dumps({"list": [{"action": "wait_for", "params": {"timer_sec": 30}}]}))
    assert run_startup_schedule(dev, str(sched), connect_timeout=10, poll_interval=0.1) is True
    assert dev.schedule["state"] == "working"
    dev.stop_scheduler({})
```

- [ ] **Step 2: Run the test**

This is an end-to-end characterization test over behavior already built in Tasks 1–3, so it should pass once the fixture wiring is correct — there is no meaningful red-first here. If it fails, read the failure: a connect timeout means the fixture/config isolation is wrong (fix the test setup); a `dev.schedule["state"]` mismatch or an exception from the helper means a real defect in `run_startup_schedule` (fix the helper, not the test).

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest tests/integration/test_simulator_e2e.py::test_38_startup_schedule_connects_and_starts -q`

- [ ] **Step 3: Resolve any failure at its real source**

Adjust fixture wiring/timeouts until the device connects and the scheduler reaches `working`. Production code should not need changing if Tasks 1–3 are correct; if it does, that is a real finding — fix the helper.

- [ ] **Step 4: Run the test to verify it passes**

Run: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest tests/integration/test_simulator_e2e.py::test_38_startup_schedule_connects_and_starts -q`
Expected: PASS.

- [ ] **Step 5: Full gate and commit**

```bash
/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m "not integration" -q
/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m integration tests/integration -q
/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m ruff check .
/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m ruff format --check .
git add tests/integration/test_simulator_e2e.py
git commit -m "test: simulator e2e for startup-schedule auto-start"
```

---

## Notes for the executor

- `--schedule` is flag-only by decision; do not add a bare positional argument.
- A `[startup] schedule = ...` config key and a `SEESTAR_STARTUP_SCHEDULE` env var (CLI flag > env > config > default) are a deliberate future extension and are **out of scope** here.
- The `__main__` daemon-thread wiring in Task 3 is glue and is not directly unit-tested; its behavior is covered by the Task 2 launcher tests (spawn/no-op/error paths) and the Task 4 end-to-end test (real connect + start). Keep the wiring to the two calls described and put no logic there.
