# Seestar Claude Code plugin

Bundles the `seestar-mcp` MCP server and four skills (session-planning, building-schedules, settings-and-compatibility, safety).

## One-time server install
`ssalp-api-client` is not on PyPI; it lives in this repo at `cli/`. From a clone of `seestar_alp` (Python 3.13+), install both packages into one environment so the `seestar-mcp` command is on your `PATH`:

```
python3.13 -m venv ~/.venvs/seestar
~/.venvs/seestar/bin/pip install ./cli ./mcp
export PATH="$HOME/.venvs/seestar/bin:$PATH"   # or symlink seestar-mcp into ~/.local/bin
```
Any method works as long as `seestar-mcp` runs and can import `ssalp_api_client`. Verify with `which seestar-mcp`.

`.mcp.json` launches the `seestar-mcp` command from `PATH`; set `SEESTAR_BASE_URL` in it if your seestar_alp server is not at `http://localhost:5555`.

## Install the plugin
```
claude plugin validate ./mcp/plugin
claude --plugin-dir ./mcp/plugin
```

## Usage
Start the seestar_alp server, then ask Claude e.g. "image M31 tonight". Physical actions (park, horizon, reboot, shutdown) require your explicit confirmation.
