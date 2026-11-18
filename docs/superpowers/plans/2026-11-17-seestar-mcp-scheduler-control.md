# Seestar MCP Scheduler-Control Tools + Two Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scheduler operation/editing tools to the Seestar MCP server, fix the `schedule_auto_focus` param-name bug in the client, and close the safety-gate gap so `start_mosaic` and `startup_sequence` require confirmation like the other unattended/mount-moving entry points.

**Architecture:** The MCP server is a thin async layer over `ssalp_api_client`; each tool awaits one client method and returns its result (or `{"ok": false, "error": ...}` via `server.call`). This plan adds seven already-supported client methods as curated tools, fixes one client helper, and routes two more tools through a shared confirmation helper in `safety.py`. No new client HTTP work — every method already exists and is handled by the device server (`device/telescope.py`).

**Tech Stack:** Python 3.13, `mcp==1.30.0` (FastMCP), `pytest` + `pytest-asyncio`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-10-19-seestar-mcp-plugin-design.md` (the MCP design) and this session's gap analysis. Authoritative API surface: `cli/ssalp_api_client/commands/schedule.py` (client methods) and `device/telescope.py` (device-server action handlers).

## Global Constraints

- Python for tests: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python` (or the local `.venv-mcp`). Run from repo root.
- Both must pass, run separately: `ruff check .` and `ruff format --check .`.
- Both test lanes must pass: `pytest -m "not integration" -q` and `pytest -m integration tests/integration -q`. Integration lane stays under ~5 minutes.
- Every MCP tool takes `telescope_id: int = 1` as its last/keyword parameter and threads it to `call(telescope_id, ...)`.
- Curated tools only — no raw passthrough. Do not remove existing compatibility fallbacks.
- Confirmation gate on physical/unattended actions returns `{"ok": false, "error": ..., "requires_confirmation": True}` and makes **no** device call when it refuses.
- New tools register by appending to the module's `register(mcp)` tuple; tool name = function name minus the `_tool` suffix.

## Review Focus

- `replace_schedule_item` / `insert_schedule_item_before` called with a **physical** action string (`shutdown`, `reboot`, `scope_park`, `scope_move_to_horizon`) and no confirm must refuse and make no device call — same rule as `add_schedule_item`. (Task 3.)
- `start_mosaic` / `startup_sequence` with default args (no `confirm`) must refuse and make no device call — today they fire immediately. (Task 2.)
- `schedule_auto_focus()` must put the try-count under `try_count`; the scheduler reads `params["try_count"]` (`device/seestar_device.py:3349`) and a wrong key makes it `KeyError` at run time. (Task 1.)
- A scheduler-control action against an unknown/absent item id surfaces the device error as `{"ok": false, ...}` rather than raising — this is already handled by `server.call`'s exception mapping; a round-trip test confirms the happy path. (Task 4.)
- `start_scheduler`'s existing refusal contract (`ok is False`, `requires_confirmation is True`) must still hold after the `safety.py` refactor. (Task 2.)

---

### Task 1: Fix `schedule_auto_focus` param key (bug #1)

**Files:**
- Modify: `cli/ssalp_api_client/commands/schedule.py` (method `schedule_auto_focus`, the `{"ry_count": try_count}` payload)
- Test: `cli/tests/test_ssalp_commands.py` (strengthen existing `test_schedule_auto_focus`)

**Interfaces:**
- Produces: `schedule_auto_focus(try_count: int = 2) -> dict` — unchanged signature; the emitted `add_schedule_item` params become `{"try_count": try_count}`.

- [ ] **Step 1: Strengthen the failing test.** In `cli/tests/test_ssalp_commands.py`, replace the body of `test_schedule_auto_focus` so it asserts the request body carries the correct key. Use the existing `_stub`/`_body` helpers rather than `_check_action` so the body is inspectable:

```python
async def test_schedule_auto_focus(self, client, httpx_mock):
    _stub(httpx_mock)
    await client.schedule_auto_focus(3)
    body = _body(httpx_mock)
    assert "try_count" in body
    assert "ry_count" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && python -m pytest tests/test_ssalp_commands.py -k schedule_auto_focus -q`
Expected: FAIL — body contains `ry_count`, not `try_count`.

- [ ] **Step 3: Fix the payload** in `cli/ssalp_api_client/commands/schedule.py`: change `{"ry_count": try_count}` to `{"try_count": try_count}` in `schedule_auto_focus`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && python -m pytest tests/test_ssalp_commands.py -k schedule_auto_focus -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/ssalp_api_client/commands/schedule.py cli/tests/test_ssalp_commands.py
git commit -m "fix(client): send try_count (not ry_count) for scheduled auto_focus"
```

---

### Task 2: Confirmation gate for `start_mosaic` and `startup_sequence` (bug #2)

**Files:**
- Modify: `mcp/seestar_mcp/safety.py` (add a shared always-confirm helper)
- Modify: `mcp/seestar_mcp/tools/scheduling.py` (`start_mosaic_tool`; refactor `start_scheduler_tool` onto the helper)
- Modify: `mcp/seestar_mcp/tools/system.py` (`startup_sequence_tool`)
- Test: `mcp/tests/test_safety.py`, `mcp/tests/test_tools_scheduling.py`, `mcp/tests/test_tools_system.py`

**Interfaces:**
- Produces: `require_confirm(action: str, confirm: bool, reason: str | None = None) -> dict | None` in `safety.py` — returns the refusal dict when `confirm` is falsy, else `None`. The refusal dict is `{"ok": False, "error": reason or f"{action} requires confirm=true", "requires_confirmation": True}`.
- `PHYSICAL_ACTIONS` and the existing `gate(action, confirm)` are unchanged — `start_mosaic`/`startup_sequence` are gated at the tool level and are deliberately **not** added to `PHYSICAL_ACTIONS` (an existing test requires `add_schedule_item("start_mosaic", …)` to need no confirm).

- [ ] **Step 1: Write the failing `safety` test.** In `mcp/tests/test_safety.py` add:

```python
from seestar_mcp.safety import require_confirm

def test_require_confirm_blocks_without_confirm():
    out = require_confirm("start_mosaic", confirm=False)
    assert out["ok"] is False and out["requires_confirmation"] is True

def test_require_confirm_passes_with_confirm():
    assert require_confirm("start_mosaic", confirm=True) is None

def test_require_confirm_custom_reason():
    out = require_confirm("startup_sequence", confirm=False, reason="moves the mount")
    assert out["error"] == "moves the mount"
```

- [ ] **Step 2: Write the failing tool tests.**
  - In `mcp/tests/test_tools_scheduling.py`, add a test that `start_mosaic_tool(...)` with no `confirm` refuses and calls nothing:

    ```python
    async def test_start_mosaic_requires_confirm(make_client_spy, mock_client):
        out = await start_mosaic_tool("M31", 10.5, 41.2, 300)
        assert out["ok"] is False and out["requires_confirmation"] is True
        make_client_spy.assert_not_called()
        mock_client.start_mosaic.assert_not_awaited()
    ```

    Then update the existing `test_start_mosaic` to pass `confirm=True` (its assertion on the client call args is otherwise unchanged).
  - In `mcp/tests/test_tools_system.py`, **replace** `test_startup_sequence_not_gated` with the gated contract:

    ```python
    async def test_startup_sequence_requires_confirm(make_client_spy, mock_client):
        out = await startup_sequence_tool(37.12, -123.45)
        assert out["ok"] is False and out["requires_confirmation"] is True
        mock_client.startup_sequence.assert_not_awaited()

    async def test_startup_sequence_with_confirm(make_client_spy, mock_client):
        await startup_sequence_tool(37.12, -123.45, confirm=True)
        mock_client.startup_sequence.assert_awaited_once_with(37.12, -123.45)
    ```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd mcp && python -m pytest tests/test_safety.py tests/test_tools_scheduling.py::test_start_mosaic_requires_confirm tests/test_tools_system.py -q`
Expected: FAIL (`require_confirm` undefined; `start_mosaic`/`startup_sequence` fire without confirm).

- [ ] **Step 4: Implement.**
  - Add `require_confirm(action, confirm, reason=None)` to `safety.py` per the Interfaces block.
  - In `tools/scheduling.py`: add `confirm: bool = False` to `start_mosaic_tool`; at the top, `refusal = require_confirm("start_mosaic", confirm, "start_mosaic begins an unattended capture that moves the mount; pass confirm=true after the user confirms")` and return it if not `None`. Refactor `start_scheduler_tool`'s hand-written refusal onto `require_confirm("start_scheduler", confirm, "<existing message>")`, preserving the existing message text.
  - In `tools/system.py`: add `confirm: bool = False` to `startup_sequence_tool`; gate with `require_confirm("startup_sequence", confirm, "startup_sequence moves the mount; pass confirm=true after the user confirms")`.

- [ ] **Step 5: Run the full MCP unit lane to verify pass + no regressions**

Run: `cd mcp && python -m pytest tests/ -q`
Expected: PASS (including the unchanged `test_start_scheduler_requires_confirm`).

- [ ] **Step 6: Commit**

```bash
git add mcp/seestar_mcp/safety.py mcp/seestar_mcp/tools/scheduling.py mcp/seestar_mcp/tools/system.py mcp/tests/
git commit -m "feat(mcp): gate start_mosaic and startup_sequence behind confirm"
```

---

### Task 3: Scheduler operation and editing tools

**Files:**
- Modify: `mcp/seestar_mcp/tools/scheduling.py` (seven new tools + `register` tuple)
- Test: `mcp/tests/test_tools_scheduling.py`

**Interfaces:**
- Consumes: `require_confirm` is **not** needed here; editing tools reuse the existing `gate(action, confirm)` + `PHYSICAL_ACTIONS` from `safety.py` (already imported in this module).
- Produces these tools (name = function minus `_tool`), each a thin wrapper `return await call(telescope_id, lambda c: c.<method>(...))`:
  - `pause_scheduler_tool(telescope_id=1)` → `c.pause_scheduler()`
  - `continue_scheduler_tool(telescope_id=1)` → `c.continue_scheduler()`
  - `skip_scheduler_cur_item_tool(telescope_id=1)` → `c.skip_scheduler_cur_item()`
  - `reset_scheduler_cur_item_tool(telescope_id=1)` → `c.reset_scheduler_cur_item()`
  - `remove_schedule_item_tool(schedule_item_id: str, telescope_id=1)` → `c.remove_schedule_item(schedule_item_id)`
  - `replace_schedule_item_tool(item_id: str, action: str, params: dict | None = None, telescope_id=1, confirm=False)` → gated via `gate(action, confirm)` when `action in PHYSICAL_ACTIONS`, then `c.replace_schedule_item(item_id, action, params)`
  - `insert_schedule_item_before_tool(before_id: str, action: str, params: dict | None = None, telescope_id=1, confirm=False)` → gated the same way, then `c.insert_schedule_item_before(before_id, action, params)`

- [ ] **Step 1: Write the failing tests** in `mcp/tests/test_tools_scheduling.py`:
  - No-arg mapping for the four operation tools + `remove_schedule_item`, following the existing `test_no_arg_tools` / `test_add_schedule_item` mock patterns:

    ```python
    async def test_pause_scheduler(make_client_spy, mock_client):
        await pause_scheduler_tool()
        mock_client.pause_scheduler.assert_awaited_once_with()

    async def test_remove_schedule_item(make_client_spy, mock_client):
        await remove_schedule_item_tool("abc123")
        mock_client.remove_schedule_item.assert_awaited_once_with("abc123")
    ```

    (Add equivalents for `continue_scheduler`, `skip_scheduler_cur_item`, `reset_scheduler_cur_item`.)
  - Editing happy-path threads args:

    ```python
    async def test_replace_schedule_item(make_client_spy, mock_client):
        await replace_schedule_item_tool("id1", "start_mosaic", {"gain": 80})
        mock_client.replace_schedule_item.assert_awaited_once_with("id1", "start_mosaic", {"gain": 80})

    async def test_insert_schedule_item_before(make_client_spy, mock_client):
        await insert_schedule_item_before_tool("id1", "wait_for", {"timer_sec": 5})
        mock_client.insert_schedule_item_before.assert_awaited_once_with("id1", "wait_for", {"timer_sec": 5})
    ```

  - Physical-action gate on both editing tools (Review Focus item):

    ```python
    @pytest.mark.parametrize("action", ["shutdown", "reboot", "scope_park", "scope_move_to_horizon"])
    async def test_replace_physical_requires_confirm(make_client_spy, mock_client, action):
        out = await replace_schedule_item_tool("id1", action)
        assert out["ok"] is False and out["requires_confirmation"] is True
        make_client_spy.assert_not_called()
        mock_client.replace_schedule_item.assert_not_awaited()

    async def test_insert_physical_with_confirm(make_client_spy, mock_client):
        await insert_schedule_item_before_tool("id1", "shutdown", confirm=True)
        mock_client.insert_schedule_item_before.assert_awaited_once_with("id1", "shutdown", None)
    ```

    Add the new tool symbols to the module's import block at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd mcp && python -m pytest tests/test_tools_scheduling.py -q`
Expected: FAIL (ImportError on the new tool names).

- [ ] **Step 3: Implement the seven tools** in `tools/scheduling.py` following the module's existing wrapper style, and the editing tools' gate following `add_schedule_item_tool`'s pattern:

```python
if action in PHYSICAL_ACTIONS:
    refusal = gate(action, confirm)
    if refusal is not None:
        return refusal
```

Append all seven functions to the `register(mcp)` tuple.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd mcp && python -m pytest tests/test_tools_scheduling.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp/seestar_mcp/tools/scheduling.py mcp/tests/test_tools_scheduling.py
git commit -m "feat(mcp): add scheduler pause/continue/skip/reset and schedule edit tools"
```

---

### Task 4: Integration round-trip + docs

**Files:**
- Modify: `tests/integration/test_mcp_simulator_e2e.py` (extend `test_schedule_flow`)
- Modify: `mcp/README.md` (Scheduling tool table row)
- Modify: `mcp/plugin/skills/building-schedules/SKILL.md` (document edit + runtime-control tools)

**Interfaces:**
- Consumes: the Task 3 tools and the Task 2 `start_mosaic` gate, driven against the simulator-backed device server exactly as the existing `_run(...)` helper does.

- [ ] **Step 1: Extend the integration test.** In `test_schedule_flow`, after the existing `add_schedule_item` + `get_schedule`, add an edit round-trip: read the created item's id from the schedule payload, call `remove_schedule_item_tool(<id>)`, then `get_schedule_tool()` again and assert the item is gone. Keep it resilient to the device's schedule JSON shape — locate the id via the same `repr`/dict traversal style already used in the file. Also assert `start_mosaic_tool(...)` with no confirm returns `requires_confirmation`.

```python
# within test_schedule_flow, after the wait_for item is present:
refused_mosaic = _run(scheduling.start_mosaic_tool("M31", "00:42:44", "+41:16:09", 60))
assert refused_mosaic["ok"] is False and refused_mosaic["requires_confirmation"] is True
```

- [ ] **Step 2: Run the integration lane to verify it passes**

Run: `python -m pytest -m integration tests/integration/test_mcp_simulator_e2e.py -q`
Expected: PASS, under the time budget.

- [ ] **Step 3: Update docs.** Add the new tools to the Scheduling row of the tool table in `mcp/README.md`. In `building-schedules/SKILL.md`, add a short "Fixing and running an in-progress schedule" note covering `remove_schedule_item` / `replace_schedule_item` / `insert_schedule_item_before` for edits and `pause_scheduler` / `continue_scheduler` / `skip_scheduler_cur_item` / `reset_scheduler_cur_item` for a running scheduler, and note that `start_mosaic` now requires `confirm=true`.

- [ ] **Step 4: Full verification**

Run: `cd mcp && python -m pytest tests/ -q` then from repo root `python -m pytest -m "not integration" -q`, `python -m pytest -m integration tests/integration -q`, `ruff check .`, `ruff format --check .`
Expected: all PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_mcp_simulator_e2e.py mcp/README.md mcp/plugin/skills/building-schedules/SKILL.md
git commit -m "test(mcp): schedule edit round-trip; document scheduler-control tools"
```
