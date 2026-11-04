# seestar-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant
control a Seestar telescope — point at targets, image, read/change settings,
and build and run schedules — by wrapping the seestar_alp
[`ssalp_api_client`](../cli). It talks to a **running seestar_alp device
server** over its Alpaca HTTP API; it does not talk to the telescope directly.

```
AI assistant (MCP client)
        │  MCP stdio
   seestar-mcp            ← this package (thin async tool layer)
        │  ssalp_api_client
seestar_alp device server ──HTTP──> Seestar
```

Two ways to use it:

- **As a Claude Code plugin** (recommended) — see [`plugin/README.md`](plugin/README.md)
  for marketplace/plugin install. The plugin also ships skills that teach the
  assistant how to plan sessions, build schedules, handle settings
  compatibility, and stay safe.
- **Standalone** — as an MCP server for Claude Desktop or any other MCP client,
  described below.

## Requirements

- Python 3.13+
- A reachable seestar_alp device server (the normal seestar_alp install,
  default `http://localhost:5555`).

## Install

`ssalp-api-client` is not on PyPI — it lives in this repo at [`cli/`](../cli) —
so install both from a clone, into the same environment:

```bash
python -m venv ~/.venvs/seestar
~/.venvs/seestar/bin/pip install -e ./cli -e ./mcp
```

This puts the `seestar-mcp` console script in `~/.venvs/seestar/bin`. Make sure
that directory is on the PATH of whatever launches the MCP client, or symlink
the script somewhere that is (e.g. `ln -sf ~/.venvs/seestar/bin/seestar-mcp ~/.local/bin/seestar-mcp`).

## Configure

The device-server URL is resolved by `ssalp_api_client`'s own config, so the
MCP server honors the same settings as the CLI:

| Source | Example | Notes |
|---|---|---|
| `SEESTAR_BASE_URL` env | `http://192.168.1.51:5555` | Explicit override; wins if set |
| `SSALP_HOST` / `SSALP_PORT` env | `192.168.1.51` / `5555` | |
| `ssalp.toml` / `~/.config/ssalp/config.toml` | | |
| default | `http://localhost:5555` | |

Every tool also takes a `telescope_id` argument (default `1`; use `0` for a
federated/all-devices call).

## Run

```bash
seestar-mcp          # stdio MCP server
# or
python -m seestar_mcp
```

### Register with an MCP client

Point your client at the command. Example client config entry:

```json
{
  "mcpServers": {
    "seestar": { "command": "seestar-mcp" }
  }
}
```

(The Claude Code plugin ships this wiring in `plugin/.mcp.json` — you don't
write it by hand when installing via the plugin.)

## Tools

Each returns the device's response, or `{"ok": false, "error": "..."}` on a
connection/API error.

| Group | Tools |
|---|---|
| **State** | `get_device_state`, `get_view_state` |
| **Pointing** | `goto_target`, `scope_goto`, `start_solve`, `get_solve_result`, `is_goto_completed_ok`, `stop_goto_target` |
| **Alignment** | `polar_align`, `get_pa_error`, `set_3ppa_calibration` |
| **Horizon** | `get_horizon`, `check_target_visibility` |
| **Focuser** | `get_focuser_position`, `adjust_focus`, `start_auto_focus`, `stop_auto_focus` |
| **Filter wheel** | `get_wheel_position`, `get_wheel_state`, `get_wheel_setting`, `set_wheel_position`, `set_lp_filter` |
| **Imaging** | `start_stack`, `stop_view`, `set_gain`, `set_exposure`, `get_last_image`, `create_dark` |
| **Settings** | `read_settings`, `write_setting` |
| **Scheduling** | `get_schedule`, `create_schedule`, `add_schedule_item`, `schedule_mosaic`, `start_mosaic`, `start_scheduler`, `stop_scheduler`, `export_schedule`, `import_schedule` |
| **Startup / system** | `startup_sequence`, `set_heater` |
| **System (physical, gated)** | `scope_park`, `scope_move_to_horizon`, `reboot`, `shutdown` |

### Settings

- `read_settings` merges both device read paths (`get_setting` and
  `get_stack_setting`), returning what each provides and listing any that
  failed under `errors` (older firmware may not support one).
- `write_setting(values, variant="auto")` supports all three save variants
  (`set_setting` with a stack payload, `set_stack_setting`, `set_stack_settings`).
  `auto` uses `set_stack_settings` for multiple keys, else `set_stack_setting`;
  pass an explicit `variant` to force one. An inline device rejection is
  returned as `{"ok": false, ...}` rather than reported as success.

### Safety

There is no raw command passthrough — only curated tools. Physical and
destructive actions require explicit confirmation: `scope_park`,
`scope_move_to_horizon`, `reboot`, and `shutdown` each refuse unless called with
`confirm=true`, and making no device call when refused. Because the scheduler
can execute physical actions too, `add_schedule_item` (for a physical action)
and `start_scheduler` likewise require `confirm=true`.

## Development

```bash
. ~/.venvs/seestar/bin/activate   # or your editable-install env
cd mcp && python -m pytest tests/ -q          # unit tests
ruff check . && ruff format --check .
```

End-to-end tests (MCP tools → device server → simulator) live at
[`../tests/integration/test_mcp_simulator_e2e.py`](../tests/integration/test_mcp_simulator_e2e.py)
and run under the `integration` marker.
