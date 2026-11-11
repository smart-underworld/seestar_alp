"""Every Seestar request written as a literal in the source matches seestar-spec.

The integration lane checks the requests that actually reach the simulator,
but only on paths the tests exercise, and never the CLI or MCP clients.
This scan covers every literal request in the code: a dict with a constant
"method" (and optional "params"), and helper calls that take the method
name first (method_sync, json_message, ...). Values computed at runtime are
replaced by UNKNOWN, so the method name and the literal structure (keys,
nesting, constant values) are checked.
"""

import ast
from pathlib import Path

import pytest

from tests.seestar_spec import UNKNOWN, validate_request

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ["device", "front", "lib", "cli/ssalp_api_client", "mcp/seestar_mcp"]

# Helpers whose first positional argument is a firmware method name, and
# where their params come from: a "params" keyword, or a positional index.
METHOD_HELPERS = {
    "method_sync": {"keyword": "params"},
    "method_async": {"keyword": "params"},
    "json_message": {},
    "_auth_rpc_sync": {"positional": 1},
}
# The CLI client's method_sync(method, params) takes params positionally.
CLI_METHOD_SYNC = {"positional": 1}


def _literal(node):
    """Convert an AST expression to a Python value, UNKNOWN where dynamic."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        if any(isinstance(e, ast.Starred) for e in node.elts):
            return UNKNOWN
        return [_literal(e) for e in node.elts]
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):  # {**spread}
            return UNKNOWN
        out = {}
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                return UNKNOWN
            out[k.value] = _literal(v)
        return out
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
    ):
        return -node.operand.value
    return UNKNOWN


def _requests_in(path):
    rel = path.relative_to(ROOT).as_posix()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            value = _literal(node)
            if (
                isinstance(value, dict)
                and isinstance(value.get("method"), str)
                # Scheduler items and Alpaca actions use "action", not this.
                and set(value) <= {"method", "params", "id", "jsonrpc"}
            ):
                request = {"method": value["method"]}
                if "params" in value:
                    request["params"] = value["params"]
                yield f"{rel}:{node.lineno}", request
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            how = METHOD_HELPERS.get(name)
            if name == "method_sync" and rel.startswith("cli/"):
                how = CLI_METHOD_SYNC
            if how is None or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            request = {"method": first.value}
            if "keyword" in how:
                for kw in node.keywords:
                    if kw.arg == how["keyword"]:
                        request["params"] = _literal(kw.value)
            elif "positional" in how and len(node.args) > how["positional"]:
                request["params"] = _literal(node.args[how["positional"]])
            yield f"{rel}:{node.lineno}", request


def _all_requests():
    found = []
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            if "tests" in path.relative_to(ROOT).parts:
                continue
            found.extend(_requests_in(path))
    return found


ALL_REQUESTS = _all_requests()


def test_scan_finds_requests():
    # Guards against the scanner silently matching nothing after a refactor.
    methods = {r["method"] for _, r in ALL_REQUESTS}
    assert {"scope_goto", "iscope_start_view", "set_setting"} <= methods
    assert len(ALL_REQUESTS) > 150


@pytest.mark.parametrize(
    "where,request_", ALL_REQUESTS, ids=[w for w, _ in ALL_REQUESTS]
)
def test_literal_request_matches_spec(where, request_):
    assert validate_request(request_) == []
