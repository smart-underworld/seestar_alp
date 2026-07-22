import threading
import time
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


def test_app_process_log_tail_thread_safe_during_concurrent_writes(tmp_path):
    # Concurrency invariant guard for log_tail()/_append_line(): both go
    # through self._output_lock, so a background thread hammering
    # _append_line() (the same internal path _read_output() uses) must never
    # cause log_tail(), called concurrently from the main thread, to observe
    # a torn/partial read or raise.
    #
    # Note on what this test can and cannot prove: under CPython-with-GIL,
    # "\n".join(deque_instance)" materializes the deque via a single
    # GIL-atomic C loop (PySequence_Fast), so a concurrent deque.append()
    # cannot land mid-iteration and raise "RuntimeError: deque mutated
    # during iteration" — that failure mode only reproduces with an
    # explicit Python-level `for line in deque_instance: ...` loop, which
    # log_tail() does not use. (Verified empirically: forcing
    # sys.setswitchinterval() very low and racing raw appends against a
    # Python for-loop over a deque *does* raise RuntimeError; racing the
    # same appends against "\n".join(deque_instance)" or list(deque_instance)
    # never does, with or without this fix.) So this test cannot force that
    # specific RuntimeError to fire against log_tail() as currently
    # implemented — there is no achievable RED for it on this interpreter.
    # The lock is still the right fix: it is required for correctness under
    # free-threaded CPython (3.13+ --disable-gil), where list(deque)
    # concurrent with deque.append() is a genuine data race, and it is
    # correct concurrency hygiene regardless of interpreter. This test
    # guards the invariant going forward (e.g. if log_tail() is ever
    # rewritten to iterate self._output directly with a Python for-loop).
    uiport = find_free_port()
    proc = AppProcess(REPO_ROOT, tmp_path / "unused.toml", uiport, ready_timeout=1.0)
    for i in range(300):
        proc._append_line(f"seed {i}")

    stop_event = threading.Event()
    errors: list[Exception] = []

    def writer():
        i = 0
        while not stop_event.is_set():
            proc._append_line(f"line {i}")
            i += 1

    def reader():
        while not stop_event.is_set():
            try:
                proc.log_tail()
            except RuntimeError as exc:
                errors.append(exc)
                return

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    reader_thread.start()

    time.sleep(1.5)
    stop_event.set()
    writer_thread.join(timeout=5.0)
    reader_thread.join(timeout=5.0)

    assert errors == [], f"log_tail() raised during concurrent writes: {errors}"


def test_app_process_fails_fast_on_immediate_crash(tmp_path):
    # Regression test: start() must not block for the full ready_timeout if
    # the child process has already exited (e.g. immediate crash on bad
    # config). Use a generous timeout and assert we fail well before it.
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("this is not valid toml [[[")
    uiport = find_free_port()
    proc = AppProcess(REPO_ROOT, bad_config, uiport, ready_timeout=20.0)

    start_time = time.monotonic()
    with pytest.raises(TimeoutError) as excinfo:
        proc.start()
    elapsed = time.monotonic() - start_time

    assert len(str(excinfo.value)) > 0
    assert elapsed < 5.0, f"start() took {elapsed:.1f}s to fail, expected fail-fast (<5s)"
    proc.stop()
