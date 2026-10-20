# Design: Seestar MCP server + Claude Code plugin

**Date:** 2026-10-19
**Status:** Draft for approval
**Author:** Ben Guthro (with Claude)

## Intent and why

Let people drive a live Seestar from an AI assistant in natural language:
point and image a target, read and change settings, and build/run imaging
schedules. The repo already exposes everything needed over HTTP, and a
well-structured async client (`cli/ssalp_api_client`) already wraps that HTTP
surface. This project adds a thin **MCP server** over that client so any MCP
client can call it, and packages it as a **Claude Code plugin** published
through a **marketplace** so the broader seestar_alp community can install it
in one step.

The win is not raw API access — it's the *workflow knowledge* (how to plan a
session, build a mosaic, interpret device state, stay safe) carried in skills
alongside the tools.

## Goals

- Expose curated MCP tools for the three core jobs: **pointing** (goto/solve),
  **imaging** (stack/capture), **settings** (read/write), and **schedules**
  (build/run/import/export).
- Ship primarily as a **Claude Code plugin** (first-class install experience),
  while the MCP server underneath stays **standalone-launchable** so Claude
  Desktop and other MCP clients work too.
- Distribute via a **marketplace in this repo**, so tools version alongside the
  API they wrap.
- Be **testable against the simulator** in the existing integration lane,
  under the ~5-minute CI budget.
- Reuse `ssalp_api_client` as the single HTTP/compatibility layer — no second
  client.

## Non-goals

- Reimplementing the device protocol or the Alpaca HTTP transport (the client
  already does this).
- A new GUI. This is an assistant-facing control surface, not a replacement
  for `front/`.
- Firmware/APK emulator work (the Android "emulator" from other threads).
  "Testable with the emulator" here means the `simulator/` device simulator the
  integration lane already uses. *(Guess — confirm if you meant the Android
  firmware emulator instead.)*

## Anti-goals (what makes this a failure even if it "works")

- A raw `method_sync` passthrough tool that lets the model fire arbitrary
  device commands with no guardrails.
- Physical actions (park, reboot/shutdown, slewing near the Sun, long
  unattended runs) triggered without explicit confirmation.
- Duplicating the response-unwrapping / settings compatibility logic that
  already lives in the client and `front/app.py`.

## Architecture

Three layers, bottom to top:

```
Seestar device  ⇄  seestar_alp device server (HTTP :5555, /api/v1/telescope/{id}/action)
                        ⇑  (or simulator in tests)
              ssalp_api_client   (cli/ — async client, mixins, compat/unwrap logic)  [EXISTS]
                        ⇑
              seestar-mcp        (new thin MCP server: tool defs → client method calls)
                        ⇑
       Claude Code plugin  +  marketplace.json   (new packaging/distribution)
```

### 1. MCP server (`seestar-mcp`) — the core deliverable

- New small Python package. Dependencies: the MCP Python SDK + `ssalp-api-client`
  (declared as a dependency so standalone installs pull the client in).
- `ssalp_api_client.SSAlpApiClient` is already `async def` throughout, which
  matches the MCP SDK's async model directly — tools await client methods.
- **Configuration:** `base_url` from an env var (device servers commonly run on
  a Pi on the LAN; the client already reads host/port from config/env). Every
  tool takes a `telescope_id` argument (default 1) because of multiple scopes
  and federation (`dev_num: 0`).
- **Curated tools**, grouped to match the client mixins:
  - *Pointing:* `goto_target`, `scope_goto`, `start_solve` / `get_solve_result`,
    `is_goto_completed_ok`, `stop_goto_target`.
  - *Imaging:* start/stop stack, exposure/gain, last image / download.
  - *Settings:* read + write (see compatibility rules below).
  - *Schedules:* `get_schedule`, `create_schedule`, `add_schedule_item`,
    `schedule_mosaic`, `start_mosaic`, `import_schedule`/`export_schedule`,
    `start_scheduler`/`stop_scheduler`.
  - *State:* `get_device_state` / view state for situational awareness.
- **No open passthrough.** If a thin escape hatch is ever wanted, it is a
  separate, explicitly-guarded tool — not the default surface.
- **Confirmation gate** on physical/destructive actions (park, reboot,
  shutdown, horizon move). Mechanism (a `confirm: true` argument vs. a
  two-step tool) is left to the builder; the *requirement* is fixed.
- **Standalone launch:** a console-script / `uvx`-friendly entry point so it
  runs with no Claude Code present.

### 2. Claude Code plugin (the prioritized install path)

Plugin root layout (per current Claude Code plugin reference):

```
<plugin-root>/
├── .claude-plugin/
│   └── plugin.json          # name (kebab-case, required), version, description, author
├── .mcp.json                # declares the seestar-mcp stdio server
└── skills/
    ├── session-planning/SKILL.md
    ├── building-schedules/SKILL.md
    ├── settings-and-compatibility/SKILL.md
    └── safety/SKILL.md
```

- **MCP declaration** in `.mcp.json` at the plugin root, top-level `mcpServers`
  map, stdio shape, using `${CLAUDE_PLUGIN_ROOT}` in `command`/`args`/`env`:

  ```json
  {
    "mcpServers": {
      "seestar": {
        "command": "python",
        "args": ["-m", "seestar_mcp"],
        "env": { "SEESTAR_BASE_URL": "http://localhost:5555" }
      }
    }
  }
  ```
  *(Exact command/args are a builder call — e.g. a bundled venv or `uvx`
  invocation under `${CLAUDE_PLUGIN_ROOT}`. The shape above is the contract.)*

- **Skills are auto-discovered** from `skills/<name>/SKILL.md`; nothing needs
  listing in `plugin.json`. They namespace as `/<plugin>:<skill>`. Skills are
  where the workflow value lives:
  - *session-planning* — go from "image the Veil Nebula tonight" to a concrete
    goto + stack plan, using state tools to check readiness.
  - *building-schedules* — compose schedule items / mosaics correctly.
  - *settings-and-compatibility* — the read/save rules below.
  - *safety* — when to require confirmation; never slew near the Sun; parking.

### 3. Marketplace (distribution, in this repo)

- `.claude-plugin/marketplace.json` at the **repo root** (repo root = marketplace
  root, which is what the `github`/`owner/repo` install form expects).
- The plugin lives in a subdirectory (proposed `mcp/plugin/`, with the server
  package at `mcp/seestar_mcp/`), referenced by a relative `source`:

  ```json
  {
    "name": "seestar-alp",
    "owner": { "name": "smart-underworld" },
    "plugins": [
      {
        "name": "seestar",
        "source": "./mcp/plugin",
        "description": "Control a Seestar from your AI assistant: point, image, and schedule."
      }
    ]
  }
  ```
- Community install:
  ```
  /plugin marketplace add smart-underworld/seestar_alp
  /plugin install seestar@seestar-alp
  ```
  (Entry `name` and the plugin's `plugin.json` `name` must match.)

## Constraints (must be honored)

- **Settings compatibility (from AGENTS.md).** Support both read paths
  (`get_setting`, `get_stack_setting`) and all save variants (`set_setting`
  with a `stack` payload, `set_stack_setting`, `set_stack_settings`). Prefer
  feature detection / payload presence over firmware-version assumptions. The
  settings tools route through the client; do not reimplement this logic in the
  MCP layer.
- **Response unwrapping / quirks.** The compatibility behavior in
  `front/app.py` (the `method_sync` unwrap around lines 692–714 and the
  `False == 0` handling near 819) already lives in the client. Reuse it; do not
  re-derive a slightly different version in the server.
- **Compatibility fallbacks** must not be silently removed (AGENTS.md).
- **Physical safety.** Curated tools + confirmation gate on destructive/physical
  actions, documented in the safety skill.

## Testing

- **Integration lane (primary):** drive the MCP tools against a device server
  pointed at the `simulator/`, as an extension of the existing
  `tests/integration` suite. Cover: pointing round-trip, a settings
  read→write→read on discrete stack fields (both read paths + save variants),
  building a small schedule and a mosaic, and start/stop scheduler smoke. Keep
  total integration runtime under ~5 minutes.
- **Unit lane:** mock the client; assert each tool maps to the right client
  call with the right params, and that the confirmation gate blocks
  unconfirmed physical actions.
- **Lint:** both `ruff check .` and `ruff format --check .` must pass (CI runs
  them separately).
- Reuse `Seestar Alpaca API.json` and `bruno/` as the authoritative API surface
  when defining/validating tool parameters.

## Decided (the "how" settled in brainstorming)

- Build on `ssalp_api_client`; no second HTTP client.
- MCP server is the core; Claude Code plugin is the prioritized delivery; Claude
  Desktop / other MCP clients supported via standalone launch.
- Marketplace lives in this repo; plugin in a subdirectory.
- Curated tools only; confirmation gate on physical actions.
- Skills carry the workflow knowledge; auto-discovered.

## Left to the builder

- Exact MCP SDK choice and server module layout.
- Precise tool list, names, and parameter schemas (curated down from the client
  surface; cross-checked against `bruno/`).
- The standalone launch mechanism and how `.mcp.json` invokes it under
  `${CLAUDE_PLUGIN_ROOT}` (bundled venv vs `uvx` vs system Python).
- Confirmation-gate mechanism (argument vs two-step).
- Whether image bytes are returned inline, written to a path, or both.
- Final directory names (`mcp/plugin`, `mcp/seestar_mcp` are proposals).

## Open question for the user

- "Testable with the emulator" — treated here as the **`simulator/` device
  simulator** used by the integration lane. Confirm that's what you meant, or
  say if you meant the Android firmware emulator.
