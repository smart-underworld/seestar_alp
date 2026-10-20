# Seestar MCP server + Claude Code plugin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an MCP server that controls a live Seestar through the existing `ssalp_api_client`, packaged as a Claude Code plugin and distributed via a marketplace in this repo.

**Architecture:** A thin async MCP server (`seestar-mcp`) exposes curated tools that await `ssalp_api_client.SSAlpApiClient` methods. The client already owns the Alpaca HTTP transport and compatibility/unwrap logic, so the server adds no second client. A plugin wires the server via `.mcp.json` and carries workflow skills; a repo-root `marketplace.json` lists the plugin.

**Tech Stack:** Python 3.13, `mcp` SDK (FastMCP), `ssalp-api-client` (local, `cli/`), pytest + pytest-asyncio, ruff.

**Spec:** `docs/superpowers/specs/2026-10-19-seestar-mcp-plugin-design.md`

## Global Constraints

- **Python:** `requires-python = ">=3.13"` (match `cli/`). Ruff `target-version = "py312"` (match repo root `pyproject.toml`).
- **Interpreter/test env:** AGENTS.md names `ssc-3.13.5`; on this machine use the project's Python 3.13 env. The server and client must both be installed editable in the test env: `pip install -e cli/ -e mcp/`.
- **Lint (both, separately):** `ruff check .` AND `ruff format --check .` must pass.
- **No second HTTP client:** all device I/O goes through `ssalp_api_client`. Reuse its response-unwrap/compatibility behavior; do not reimplement it in the server.
- **Settings:** support both read paths (`get_setting`, `get_stack_setting`) and all three save variants (`set_setting` with a `stack` payload, `set_stack_setting`, `set_stack_settings`). Prefer payload/feature detection over firmware-version assumptions. Do not remove compatibility fallbacks.
- **No open `method_sync` passthrough.** Only curated tools. Physical/destructive actions require explicit confirmation.
- **Plugin naming:** plugin name is `seestar` (kebab-case; must not start with `claude-`/`anthropic-`/`cc-plugin-`). The marketplace entry `name` must equal the plugin's `plugin.json` `name`.
- **MCP dependency pin:** pin `mcp` to an exact version at least two weeks old; do not use a bare/floating spec.

## Review Focus

- **Device server unreachable / wrong base URL:** a tool call must return a clear error (surface `SSAlpConnectionError`), not hang or crash the server. → Task 1.
- **RA/Dec as sexagesimal strings vs decimals:** `goto_target` must accept both (the client already does). → Task 3.
- **Save variant the firmware lacks:** writing a setting via an unsupported variant must degrade/report, not hard-fail the session. → Task 5.
- **Physical action without `confirm=true`:** park / horizon-move / reboot / shutdown must be refused before any device call. → Task 7.
- **Federation / alternate `telescope_id` (incl. 0):** the id argument must be threaded into the client (`device_num`) so the right scope is targeted. → Task 3.

---

### Task 1: `seestar-mcp` package skeleton, client factory, standalone launch

**Files:**
- Create: `mcp/pyproject.toml`
- Create: `mcp/seestar_mcp/__init__.py`
- Create: `mcp/seestar_mcp/__main__.py`
- Create: `mcp/seestar_mcp/server.py`
- Test: `mcp/tests/test_server.py`

**Interfaces:**
- Produces: `server.py` exposes `mcp: FastMCP` (the server instance) and `make_client(telescope_id: int | None = None) -> SSAlpApiClient`. `make_client` reads `SEESTAR_BASE_URL` (env) for `base_url`; when unset, constructs `SSAlpApiClient()` so the client's own `load_config()` (SSALP_* env / toml) applies. `telescope_id`, when given, is passed as `device_num`.
- Produces: `__main__.py` runs `mcp.run()` over stdio, so `python -m seestar_mcp` launches the server.
- Produces: a `call(telescope_id, coro_factory)` async helper (or equivalent) that builds a client, awaits the given client coroutine, and converts `SSAlpError`/`SSAlpConnectionError` into a structured tool error dict `{"ok": false, "error": str}`. Later tasks route every tool through this helper.

- [ ] **Step 1: Write failing tests**

```python
def test_make_client_uses_seestar_base_url(monkeypatch):
    monkeypatch.setenv("SEESTAR_BASE_URL", "http://10.0.0.9:5555")
    c = make_client()
    assert c._base_url == "http://10.0.0.9:5555"

def test_make_client_threads_telescope_id():
    c = make_client(telescope_id=0)
    assert c._device_num == 0

async def test_call_converts_connection_error():
    async def boom(client):
        raise SSAlpConnectionError("refused")
    out = await call(1, boom)
    assert out["ok"] is False and "refused" in out["error"]
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest mcp/tests/test_server.py -v` → FAIL (names undefined).
- [ ] **Step 3: Implement `mcp/pyproject.toml`** (package `seestar-mcp`, `requires-python>=3.13`, deps: pinned `mcp`, `ssalp-api-client`; `[project.scripts] seestar-mcp = "seestar_mcp.__main__:main"`; hatchling build).
- [ ] **Step 4: Implement `server.py`** (`mcp = FastMCP("seestar")`, `make_client`, `call`) and `__main__.py` (`def main(): mcp.run()`), `__init__.py` (`__version__`).
- [ ] **Step 5: Run tests to verify they pass** — same command → PASS.
- [ ] **Step 6: Commit** — `git add mcp/ && git commit -m "feat(mcp): package skeleton, client factory, stdio launch"`.

---

### Task 2: Safety confirmation gate

**Files:**
- Create: `mcp/seestar_mcp/safety.py`
- Test: `mcp/tests/test_safety.py`

**Interfaces:**
- Produces: `PHYSICAL_ACTIONS: frozenset[str]` = `{"scope_park", "scope_move_to_horizon", "reboot", "shutdown"}`.
- Produces: `gate(action: str, confirm: bool) -> dict | None` — returns a refusal dict `{"ok": false, "error": "<action> requires confirm=true", "requires_confirmation": true}` when `action` is physical and `confirm` is False; returns `None` otherwise. Task 8 calls `gate(...)` and returns its result (if not `None`) before touching the client.

- [ ] **Step 1: Write failing tests**

```python
def test_gate_blocks_unconfirmed_physical():
    out = gate("shutdown", confirm=False)
    assert out["requires_confirmation"] is True

def test_gate_allows_confirmed_physical():
    assert gate("shutdown", confirm=True) is None

def test_gate_ignores_non_physical():
    assert gate("get_device_state", confirm=False) is None
```

- [ ] **Step 2: Run to verify fail.** `python -m pytest mcp/tests/test_safety.py -v` → FAIL.
- [ ] **Step 3: Implement `safety.py`.**
- [ ] **Step 4: Run to verify pass.** → PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat(mcp): physical-action confirmation gate"`.

---

### Task 3: State + pointing tools

**Files:**
- Create: `mcp/seestar_mcp/tools/__init__.py`
- Create: `mcp/seestar_mcp/tools/state.py`
- Create: `mcp/seestar_mcp/tools/pointing.py`
- Test: `mcp/tests/test_tools_pointing.py`

**Interfaces:**
- Consumes: `make_client`/`call` (Task 1).
- Produces: registered tools `get_device_state(telescope_id=1)`, `get_view_state(telescope_id=1)`, `goto_target(target_name, ra, dec, is_j2000=True, telescope_id=1)`, `scope_goto(ra, dec, telescope_id=1)`, `start_solve(telescope_id=1)`, `get_solve_result(telescope_id=1)`, `is_goto_completed_ok(telescope_id=1)`, `stop_goto_target(telescope_id=1)`. Each awaits the matching client method via `call`. A `register(mcp)` function in each module registers its tools; `tools/__init__.py` exposes `register_all(mcp)` and `server.py` calls it at import.

- [ ] **Step 1: Write failing tests** (mock `make_client` to return an `AsyncMock` client; assert the tool calls the right method with the right args):

```python
async def test_goto_target_accepts_sexagesimal(mock_client):
    await goto_target_tool(target_name="M31", ra="00:42:44", dec="+41:16:09")
    mock_client.goto_target.assert_awaited_once_with("M31", "00:42:44", "+41:16:09", True)

async def test_get_device_state_threads_telescope_id(make_client_spy):
    await get_device_state_tool(telescope_id=0)
    make_client_spy.assert_called_once_with(telescope_id=0)
```

- [ ] **Step 2: Run to verify fail.** → FAIL.
- [ ] **Step 3: Implement `state.py` and `pointing.py`** registering the tools above; wire `register_all` in `tools/__init__.py` and call it from `server.py`.
- [ ] **Step 4: Run to verify pass.** → PASS.
- [ ] **Step 5: Commit.**

---

### Task 4: Imaging tools

**Files:**
- Create: `mcp/seestar_mcp/tools/imaging.py`
- Test: `mcp/tests/test_tools_imaging.py`

**Interfaces:**
- Consumes: `call` (Task 1), `register_all` (Task 3).
- Produces: tools `start_stack(gain, restart=True, telescope_id=1)`, `stop_view(stage=None, telescope_id=1)`, `set_gain(gain, telescope_id=1)`, `set_exposure(stack_l_ms, continuous_ms, telescope_id=1)`, `get_last_image(telescope_id=1)`. (Image bytes handling — inline base64 vs. saved path — is the builder's call; default to returning the device's image id/URL dict from the client, no raw bytes in the tool result.)

- [ ] **Step 1: Write failing tests** (one per tool, mocked client, asserting method + args). Example:

```python
async def test_start_stack_passes_gain_and_restart(mock_client):
    await start_stack_tool(gain=80, restart=False)
    mock_client.start_stack.assert_awaited_once_with(80, restart=False)
```

- [ ] **Step 2: Run to verify fail.** → FAIL.
- [ ] **Step 3: Implement `imaging.py`; register in `register_all`.**
- [ ] **Step 4: Run to verify pass.** → PASS.
- [ ] **Step 5: Commit.**

---

### Task 5: Settings tools (read + all save variants)

**Files:**
- Create: `mcp/seestar_mcp/tools/settings.py`
- Modify: `cli/ssalp_api_client/commands/info.py` (add missing setters) and `cli/ssalp_api_client/commands/__init__.py` if needed
- Test: `mcp/tests/test_tools_settings.py`, `cli/tests/test_settings_setters.py`

**Interfaces:**
- Consumes: `call` (Task 1).
- Produces (client additions, async, mirroring existing mixin style):
  - `InfoMixin.set_setting(**kwargs)` → sends action `set_setting` with a `stack` payload wrapper.
  - `InfoMixin.set_stack_settings(**kwargs)` → sends action `set_stack_settings`.
  - (`set_stack_setting` already exists on `MountMixin`.)
- Produces (MCP tools):
  - `read_settings(telescope_id=1)` → returns a merged dict from **both** `get_setting` and `get_stack_setting` (keyed e.g. `{"setting": ..., "stack_setting": ...}`), tolerating either call erroring on old firmware (include what succeeds).
  - `write_setting(values: dict, variant: str = "auto", telescope_id=1)` → `variant` in `{"auto","set_setting","set_stack_setting","set_stack_settings"}`; `auto` picks `set_stack_settings` when multiple keys are present, else `set_stack_setting`; explicit variant forces that client method; a variant unsupported by firmware returns `{"ok": false, ...}` without aborting.

- [ ] **Step 1: Write failing tests**

```python
# cli/tests/test_settings_setters.py
async def test_set_setting_wraps_stack_payload(httpx_mock): ...   # asserts Action=set_setting, Parameters has {"stack": {...}}
async def test_set_stack_settings_sends_action(httpx_mock): ...

# mcp/tests/test_tools_settings.py
async def test_read_settings_merges_both_paths(mock_client):
    out = await read_settings_tool()
    mock_client.get_setting.assert_awaited_once()
    mock_client.get_stack_setting.assert_awaited_once()

async def test_read_settings_tolerates_stack_path_error(mock_client):
    mock_client.get_stack_setting.side_effect = SSAlpError("no method")
    out = await read_settings_tool()
    assert "setting" in out            # still returns the path that worked

async def test_write_setting_auto_uses_plural_for_many_keys(mock_client):
    await write_setting_tool(values={"exp_ms": 10000, "gain": 80})
    mock_client.set_stack_settings.assert_awaited_once()
```

- [ ] **Step 2: Run to verify fail.** → FAIL.
- [ ] **Step 3: Implement client setters in `info.py`, then `settings.py` tools; register in `register_all`.**
- [ ] **Step 4: Run to verify pass.** → PASS.
- [ ] **Step 5: Commit.**

---

### Task 6: Scheduling tools

**Files:**
- Create: `mcp/seestar_mcp/tools/scheduling.py`
- Test: `mcp/tests/test_tools_scheduling.py`

**Interfaces:**
- Consumes: `call` (Task 1).
- Produces: tools `get_schedule(telescope_id=1)`, `create_schedule(telescope_id=1)`, `add_schedule_item(action, params=None, telescope_id=1)`, `schedule_mosaic(...matching client signature..., telescope_id=1)`, `start_mosaic(...matching client signature..., telescope_id=1)`, `start_scheduler(telescope_id=1)`, `stop_scheduler(telescope_id=1)`, `export_schedule(filepath, telescope_id=1)`, `import_schedule(filepath, retain_state=False, telescope_id=1)`. Mirror each client method's exact signature (read from `cli/ssalp_api_client/commands/schedule.py`).

- [ ] **Step 1: Write failing tests** (mocked client; assert method + args for `add_schedule_item`, `start_scheduler`, and `schedule_mosaic`).
- [ ] **Step 2: Run to verify fail.** → FAIL.
- [ ] **Step 3: Implement `scheduling.py`; register in `register_all`.**
- [ ] **Step 4: Run to verify pass.** → PASS.
- [ ] **Step 5: Commit.**

---

### Task 7: System/physical tools (behind the gate)

**Files:**
- Create: `mcp/seestar_mcp/tools/system.py`
- Test: `mcp/tests/test_tools_system.py`

**Interfaces:**
- Consumes: `call` (Task 1), `gate`/`PHYSICAL_ACTIONS` (Task 2).
- Produces: tools `scope_park(confirm=False, telescope_id=1)`, `scope_move_to_horizon(confirm=False, telescope_id=1)`, `reboot(confirm=False, telescope_id=1)`, `shutdown(confirm=False, telescope_id=1)`. Each calls `gate(<action>, confirm)` first and returns its refusal if non-`None`, else awaits the client method. (Map to the client's actual method names; confirm `reboot`/`shutdown` exist on `SystemMixin` and adjust names if the client uses e.g. `pi_reboot`/`pi_shutdown`.)

- [ ] **Step 1: Write failing tests**

```python
async def test_shutdown_blocked_without_confirm(mock_client):
    out = await shutdown_tool(confirm=False)
    assert out["requires_confirmation"] is True
    mock_client.shutdown.assert_not_awaited()

async def test_shutdown_runs_with_confirm(mock_client):
    await shutdown_tool(confirm=True)
    mock_client.shutdown.assert_awaited_once()
```

- [ ] **Step 2: Run to verify fail.** → FAIL.
- [ ] **Step 3: Implement `system.py`; register in `register_all`.**
- [ ] **Step 4: Run to verify pass.** → PASS.
- [ ] **Step 5: Commit.**

---

### Task 8: Plugin package (manifest, `.mcp.json`, skills)

**Files:**
- Create: `mcp/plugin/.claude-plugin/plugin.json`
- Create: `mcp/plugin/.mcp.json`
- Create: `mcp/plugin/skills/session-planning/SKILL.md`
- Create: `mcp/plugin/skills/building-schedules/SKILL.md`
- Create: `mcp/plugin/skills/settings-and-compatibility/SKILL.md`
- Create: `mcp/plugin/skills/safety/SKILL.md`

**Interfaces:**
- Produces: an installable Claude Code plugin named `seestar`.

- [ ] **Step 1: Write `plugin.json`** — `{ "name": "seestar", "version": "0.1.0", "description": "...", "author": {"name": "..."} }`.
- [ ] **Step 2: Write `.mcp.json`** — stdio server using `${CLAUDE_PLUGIN_ROOT}`:

```json
{
  "mcpServers": {
    "seestar": {
      "command": "seestar-mcp",
      "env": { "SEESTAR_BASE_URL": "http://localhost:5555" }
    }
  }
}
```
  (If a bundled interpreter is preferred over a `PATH` console-script, use `"command": "python", "args": ["-m","seestar_mcp"]` with `${CLAUDE_PLUGIN_ROOT}`-anchored paths — builder's call; the `mcpServers.seestar` stdio shape is the contract.)
- [ ] **Step 3: Write the four `SKILL.md` files.** Each has YAML frontmatter (`name`, `description` per the skills format) and body. Purposes: *session-planning* (target → goto + stack plan, using `get_device_state`/`get_view_state` for readiness); *building-schedules* (compose items/mosaics via the schedule tools, then `start_scheduler`); *settings-and-compatibility* (both read paths, the three save variants, feature-detect); *safety* (always `confirm=true` for park/horizon/reboot/shutdown; never slew near the Sun; park before shutdown). Follow superpowers:writing-skills for structure.
- [ ] **Step 4: Validate** — `claude plugin validate ./mcp/plugin`; expect no errors.
- [ ] **Step 5: Commit** — `git add mcp/plugin && git commit -m "feat(mcp): claude code plugin with mcp server + skills"`.

---

### Task 9: Marketplace manifest (repo root)

**Files:**
- Create: `.claude-plugin/marketplace.json`

**Interfaces:**
- Produces: a marketplace listing the `seestar` plugin at `./mcp/plugin`.

- [ ] **Step 1: Write `marketplace.json`**

```json
{
  "name": "seestar-alp",
  "owner": { "name": "smart-underworld" },
  "plugins": [
    { "name": "seestar", "source": "./mcp/plugin",
      "description": "Control a Seestar from your AI assistant: point, image, and schedule." }
  ]
}
```
- [ ] **Step 2: Validate** — `claude plugin validate .` (repo root as marketplace root); expect no errors. Entry `name` must equal the plugin manifest `name` (`seestar`).
- [ ] **Step 3: Commit** — `git add .claude-plugin/marketplace.json && git commit -m "feat(mcp): marketplace listing seestar plugin"`.

---

### Task 10: Simulator end-to-end integration test

**Files:**
- Create: `tests/integration/test_mcp_simulator_e2e.py`

**Interfaces:**
- Consumes: the registered MCP tools (Tasks 3–7) and the simulator-boot pattern in `tests/integration/test_simulator_e2e.py` (`_find_free_port`, `_wait_for_tcp`, `SocketListener` import).

**Approach (fixed contract; fixture wiring is the builder's):** Boot the simulator, then serve the Alpaca device server (`device/app.py` — `DeviceMain`/`ThreadingWSGIServer`) on a free TCP port pointed at the simulator. Set `SEESTAR_BASE_URL` to that server and drive the MCP tools (not the client directly) so the path is tool → `ssalp_api_client` → real HTTP → device server → simulator. Mark `@pytest.mark.integration`. Keep runtime well under 5 minutes.

- [ ] **Step 1: Write the e2e test** asserting, against the simulator-backed server:
  - `get_device_state` returns a dict (connectivity smoke).
  - `goto_target("M31", ...)` then `is_goto_completed_ok` round-trips without error.
  - `read_settings` returns at least one of the two paths; `write_setting({...single stack field...})` succeeds and a follow-up `read_settings` reflects it.
  - `create_schedule` → `add_schedule_item(...)` → `get_schedule` shows the item; `start_scheduler`/`stop_scheduler` smoke.
  - A physical tool (`shutdown(confirm=False)`) returns the refusal and makes no device call.
- [ ] **Step 2: Run** — `python -m pytest -m integration tests/integration/test_mcp_simulator_e2e.py -v` → PASS.
- [ ] **Step 3: Run full lanes + lint** — `python -m pytest -m "not integration" -q`, `python -m pytest -m integration tests/integration -q`, `ruff check .`, `ruff format --check .` → all green.
- [ ] **Step 4: Commit** — `git add tests/integration/test_mcp_simulator_e2e.py && git commit -m "test(mcp): simulator e2e for tools + compatibility + safety gate"`.
