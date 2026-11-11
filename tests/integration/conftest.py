"""Check every request the simulator receives against seestar-spec.

The simulator accepts almost anything, so a misspelled method or field
passes the integration tests while the real firmware answers "method not
found" (103) or silently ignores the field. This hook records each JSON
command the simulator's TCP listener processes and fails the test during
which a non-conforming one was sent.

A test that exercises a compatibility fallback or sends malformed requests
on purpose lists the problems it expects:

    @pytest.mark.allow_nonconforming_requests("set_setting: stack_cont_capt")

Each argument is matched as a substring of the reported problem; any other
problem still fails the test.
"""

import json
import sys
import threading
from pathlib import Path

import pytest

from tests.seestar_spec import validate_request

SIMULATOR_SRC = Path(__file__).resolve().parents[2] / "simulator" / "src"
if str(SIMULATOR_SRC) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_SRC))

import listener  # noqa: E402

_recorded = []
_lock = threading.Lock()


@pytest.fixture(scope="session", autouse=True)
def _record_simulator_requests():
    original = listener.SocketListener.process_tcp_command

    def recording(self, command):
        try:
            request = json.loads(command)
        except ValueError:
            request = None
        if isinstance(request, dict):
            with _lock:
                _recorded.append(request)
        return original(self, command)

    listener.SocketListener.process_tcp_command = recording
    yield
    listener.SocketListener.process_tcp_command = original


@pytest.fixture(autouse=True)
def _requests_conform_to_spec(request):
    with _lock:
        _recorded.clear()
    yield
    marker = request.node.get_closest_marker("allow_nonconforming_requests")
    allowed = marker.args if marker else ()
    with _lock:
        sent = list(_recorded)
    problems = sorted(
        p
        for p in {p for r in sent for p in validate_request(r)}
        if not any(a in p for a in allowed)
    )
    if problems:
        pytest.fail(
            "requests sent to the simulator do not match seestar-spec:\n  "
            + "\n  ".join(problems),
            pytrace=False,
        )
