# Seestar Claude Code plugin

Bundles the `seestar-mcp` MCP server and four skills (session-planning, building-schedules, settings-and-compatibility, safety).

## One-time server install
`ssalp-api-client` is not on PyPI; it lives in this repo at `cli/`, so `./cli` and `./mcp` must be installed together from a clone of `seestar_alp` (Python 3.13+). Then symlink the console script into `~/.local/bin`, so `seestar-mcp` resolves once `~/.local/bin` is on Claude Code's PATH (see below):

```
python3.13 -m venv ~/.venvs/seestar
~/.venvs/seestar/bin/pip install ./cli ./mcp
mkdir -p ~/.local/bin
ln -sf ~/.venvs/seestar/bin/seestar-mcp ~/.local/bin/seestar-mcp
```

Verify resolution with `which seestar-mcp` (or `command -v seestar-mcp`); it should print `~/.local/bin/seestar-mcp`.

Ensure `~/.local/bin` is on the PATH of the environment Claude Code runs in (GUI launches often do not inherit your shell profile). WARNING: `.mcp.json` runs the bare command `seestar-mcp`; if it is not resolvable from Claude Code's environment, the MCP server will fail to start. If in doubt, edit `command` in `.mcp.json` to the absolute path (e.g. `/Users/you/.venvs/seestar/bin/seestar-mcp`). Alternative: `uv tool install --with ./cli ./mcp`.

The seestar_alp server URL comes from the client's normal config (`SSALP_*` environment variables or your ssalp toml config; default `localhost:5555`), so an existing LAN/Pi setup is picked up automatically. To override, set `SEESTAR_BASE_URL` in your own environment (do not edit `.mcp.json`; marketplace updates overwrite it).

## Install the plugin

From the marketplace:
```
/plugin marketplace add smart-underworld/seestar_alp
/plugin install seestar@seestar-alp
```

From a local clone:
```
claude plugin validate ./mcp/plugin
claude --plugin-dir ./mcp/plugin
```

## Usage
Start the seestar_alp server, then ask Claude e.g. "image M31 tonight". Physical actions (park, horizon, reboot, shutdown) require your explicit confirmation.
