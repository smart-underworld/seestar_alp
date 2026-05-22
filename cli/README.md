# ssalp-api-client

Programmatic control library and CLI for [seestar_alp](https://github.com/seestarsmarttelescope/seestar_alp).

Wraps the seestar_alp Alpaca HTTP API, not the Seestar device directly.

---

## Installation

Requires Python 3.13+.

**Recommended — install the CLI with pipx:**

```bash
pipx install "git+https://github.com/your-org/seestar_alp.git#subdirectory=cli"
```

**As a library in a project:**

```bash
pip install "git+https://github.com/your-org/seestar_alp.git#subdirectory=cli"
```

**Development (from repo root):**

```bash
pip install -e cli/
```

---

## Configuration

Settings are resolved in priority order (highest wins):

```
CLI flags  >  environment variables  >  config file  >  built-in defaults
```

### Config file

Searched in order:
1. `--config FILE` flag or `SSALP_CONFIG` env var
2. `./ssalp.toml` (project-local)
3. `~/.config/ssalp/config.toml` (user-level)

```toml
# ~/.config/ssalp/config.toml

[default]
host = "localhost"
port = 5555
device = 1
timeout = 10.0
log_level = "WARNING"
output = "pretty"

[profiles.home]
host = "192.168.1.51"
device = 1

[profiles.observatory]
host = "10.0.0.100"
device = 2
log_level = "INFO"
```

Use `--profile NAME` to select a named profile.

### Environment variables

| Variable | Maps to |
|---|---|
| `SSALP_HOST` | `--host` |
| `SSALP_PORT` | `--port` |
| `SSALP_DEVICE` | `--device` |
| `SSALP_TIMEOUT` | `--timeout` |
| `SSALP_LOG_LEVEL` | `--log-level` |
| `SSALP_LOG_FILE` | `--log-file` |
| `SSALP_OUTPUT` | `--output` |
| `SSALP_PROFILE` | `--profile` |
| `SSALP_CONFIG` | `--config` |

---

## CLI usage

```
ssalp [OPTIONS] COMMAND [ARGS]...

Options:
  -H, --host TEXT              Device host
  -p, --port INT               Device port
  -d, --device INT             Alpaca device number
  --timeout FLOAT              Request timeout (seconds)
  -o, --output [json|table|pretty]
  --log-level [DEBUG|INFO|WARNING|ERROR]
  --log-file PATH
  --config PATH                Config file (overrides search path)
  --profile TEXT               Config file profile
  --env PATH                   Bruno .bru environment file
```

### Examples

```bash
# Test connectivity
ssalp --host 192.168.1.51 info test-connection

# Use an existing Bruno environment file
ssalp --env bruno/"Seestar Alpaca API"/environments/seestar_astro.bru info device-state

# Use a named profile from ~/.config/ssalp/config.toml
ssalp --profile home info device-state

# Slew to target
ssalp --host 192.168.1.51 mount goto --ra 5.588 --dec -5.391

# Slew to named target (sexagesimal RA/Dec)
ssalp --host 192.168.1.51 mount goto-target --name M42 --ra "5h35m17s" --dec "-5d23m"

# Start a single-panel mosaic
ssalp --host 192.168.1.51 mosaic start \
  --target M42 --ra 5.588 --dec -5.391 \
  --time 3600 --gain 80 --lp-filter

# Start a 2×2 mosaic
ssalp --host 192.168.1.51 mosaic start \
  --target NGC2244 --ra 6.532 --dec 4.94 \
  --time 7200 --panels-ra 2 --panels-dec 2 --overlap 20 --gain 80

# Build a schedule
ssalp --host 192.168.1.51 schedule create
ssalp --host 192.168.1.51 schedule add-mosaic \
  --target M42 --ra 5.588 --dec -5.391 --time 3600
ssalp --host 192.168.1.51 schedule add-wait-for --sec 300
ssalp --host 192.168.1.51 schedule add-shutdown
ssalp --host 192.168.1.51 schedule start

# JSON output (pipe-friendly)
ssalp --output json --host 192.168.1.51 info device-state | jq .

# Debug logging to file
ssalp --log-level DEBUG --log-file ssalp.log --host 192.168.1.51 info test-connection
```

### Command groups

| Group | Description |
|---|---|
| `info` | Query device state, settings, and system info |
| `mount` | Slew, park, solve, track, polar align |
| `camera` | Expose, gain, stacking |
| `focuser` | Position, auto-focus |
| `filter` | Filter wheel position and LP filter |
| `schedule` | Create and manage imaging schedules |
| `mosaic` | Direct mosaic and spectra capture |
| `files` | Albums, image naming, download |
| `system` | Startup sequence, reboot, shutdown, heater |

---

## Library usage

### Async (primary)

```python
import asyncio
from ssalp_api_client import SSAlpApiClient

async def main():
    client = SSAlpApiClient(base_url="http://192.168.1.51:5555", device_num=1)

    print(await client.test_connection())
    print(await client.get_device_state())

    # Slew to M42
    await client.scope_goto(ra=5.588, dec=-5.391)

    # Start a mosaic
    await client.start_mosaic(
        target_name="M42",
        ra=5.588,
        dec=-5.391,
        session_time_sec=3600,
        ra_num=2,
        dec_num=2,
        panel_overlap_percent=20,
        gain=80,
    )

asyncio.run(main())
```

### Sync convenience wrappers

Every async command method has a `_sync` counterpart for scripting:

```python
from ssalp_api_client import SSAlpApiClient

client = SSAlpApiClient(base_url="http://192.168.1.51:5555")

print(client.test_connection_sync())
client.scope_goto_sync(ra=5.588, dec=-5.391)
client.start_stack_sync(gain=80, restart=True)
```

### Config file and env vars apply automatically

When `SSAlpApiClient` is constructed without explicit arguments, settings are loaded
from the config file and environment variables:

```python
# Reads ~/.config/ssalp/config.toml (or ssalp.toml) and SSALP_* env vars automatically
client = SSAlpApiClient()
```

### Manual config

```python
from ssalp_api_client import SSAlpApiClient, load_config

config = load_config(
    config_file="/path/to/my.toml",
    profile="observatory",
    overrides={"timeout": 30.0},
)
client = SSAlpApiClient(config=config)
```

---

## Logging

The library logs to the `ssalp_api_client` logger hierarchy:

```python
import logging
logging.getLogger("ssalp_api_client").setLevel(logging.DEBUG)
logging.getLogger("ssalp_api_client").addHandler(logging.StreamHandler())
```

Sub-loggers: `ssalp_api_client.client`, `ssalp_api_client.commands.mount`, etc.

`ClientTransactionID` is included in every transport-layer log record, giving natural
request↔response correlation.

---

## Development

```bash
cd cli/
pip install -e ".[dev]"
pytest
pytest --cov --cov-report=term-missing
```

Run from the repo root to also run integration tests against the simulator:

```bash
pytest -m integration tests/integration
```
