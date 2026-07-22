"""Launches and tears down the real seestar_alp application (root_app.py) as
a subprocess, pointed at a scratch config.toml, for the tests/system/ suite."""

import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

READY_LINE = "Startup Complete"


class AppProcess:
    def __init__(
        self,
        repo_root: Path,
        config_path: Path,
        uiport: int,
        ready_timeout: float = 30.0,
    ):
        self.repo_root = repo_root
        self.config_path = config_path
        self.uiport = uiport
        self.ready_timeout = ready_timeout
        self.base_url = f"http://127.0.0.1:{uiport}"
        self._proc: subprocess.Popen | None = None
        self._output: deque[str] = deque(maxlen=400)
        self._ready = threading.Event()
        self._reader_thread: threading.Thread | None = None

    def _read_output(self):
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            self._output.append(line.rstrip("\n"))
            if READY_LINE in line:
                self._ready.set()

    def start(self) -> None:
        env = dict(os.environ)
        env["SEESTAR_ALP_CONFIG_PATH"] = str(self.config_path)
        env["PYTHONUNBUFFERED"] = "1"

        self._proc = subprocess.Popen(
            [sys.executable, "-u", "root_app.py"],
            cwd=str(self.repo_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()

        if not self._ready.wait(timeout=self.ready_timeout):
            tail = self.log_tail()
            self.stop()
            raise TimeoutError(
                f"root_app.py did not print '{READY_LINE}' within "
                f"{self.ready_timeout}s. Captured output:\n{tail}"
            )

    def log_tail(self) -> str:
        return "\n".join(self._output)

    def stop(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5.0)
        self._proc = None
