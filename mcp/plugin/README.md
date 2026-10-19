# Seestar Claude Code plugin

Bundles the `seestar-mcp` MCP server and four skills (session-planning, building-schedules, settings-and-compatibility, safety).

## One-time server install
`ssalp-api-client` is not on PyPI; it lives in this repo at `cli/`, so `./cli` and `./mcp` must be installed together from a clone of `seestar_alp` (Python 3.13+). Then symlink the console script into `~/.local/bin`, so it resolves regardless of how Claude Code is launched (terminal, GUI, other shell):

```
python3.13 -m venv ~/.venvs/seestar
~/.venvs/seestar/bin/pip install ./cli ./mcp
mkdir -p ~/.local/bin
ln -sf ~/.venvs/seestar/bin/seestar-mcp ~/.local/bin/seestar-mcp
```

Ensure `~/.local/bin` is on the PATH of the environment Claude Code runs in (GUI launches often do not inherit your shell profile). WARNING: `.mcp.json` runs the bare command `seestar-mcp`; if it is not resolvable from Claude Code's environment, the MCP server will fail to start. If in doubt, edit `command` in `.mcp.json` to the absolute path (e.g. `/Users/you/.venvs/seestar/bin/seestar-mcp`). Alternative: `uv tool install --with ./cli ./mcp`.

Set `SEESTAR_BASE_URL` in `.mcp.json` if your seestar_alp server is not at `http://localhost:5555`.

## Install the plugin
```
claude plugin validate ./mcp/plugin
claude --plugin-dir ./mcp/plugin
```

## Usage
Start the seestar_alp server, then ask Claude e.g. "image M31 tonight". Physical actions (park, horizon, reboot, shutdown) require your explicit confirmation.

Marketplace install instructions will be added with the marketplace entry (Task 9).
