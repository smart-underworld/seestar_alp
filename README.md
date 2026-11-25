# Seestar_Alp

Seestar_Alp is a standalone controller for command, control, and scheduling of
ZWO SeeStar smart telescopes (S30 / S50 and Pro variants).

It runs on your own computer (or a Raspberry Pi) as a backend server that talks
to the telescope, with a web-based interface for driving it. On top of that same
backend it also offers a command-line tool and a Python library, and an MCP
server so an AI assistant can plan and run imaging sessions.

```
          Web UI (browser)        CLI / Python library        AI assistant
                │                         │                         │
                └─────────────┬───────────┴────────────┬────────────┘
                              │   Alpaca HTTP API       │
                       seestar_alp device server ──────────────> SeeStar
```

## What's in this repo

| Surface | Where | Use it for |
|---|---|---|
| **Main app** — web UI + device server | `root_app.py`, `front/`, `device/` | The normal way to use Seestar_Alp: a browser GUI backed by a local server that controls the scope. |
| **CLI & Python library** (`ssalp`) | [`cli/`](cli/README.md) | Scripting and automation against a running device server over its HTTP API. |
| **MCP server & Claude Code plugin** | [`mcp/`](mcp/README.md) | Letting an AI assistant point, image, and schedule through the same server. |

---

## The main app

The main application starts two services together:

- a **device server** exposing the ASCOM **Alpaca HTTP API** (default port
  `5555`) that controls the telescope, and
- the **web UI** (default port `5432`) that you point your browser at.

(Additional ports for the imaging and Stellarium interfaces are set in the
config file — see `device/config.toml.example`.)

### Install and run

For most people the easiest path is a pre-built standalone package. The wiki has
the current, maintained step-by-step instructions for each platform:

**Standalone packages**
- [Windows](https://github.com/smart-underworld/seestar_alp/wiki/Running-standalone:-Windows)
- [macOS](https://github.com/smart-underworld/seestar_alp/wiki/Running-standalone:-Mac)
- [Linux](https://github.com/smart-underworld/seestar_alp/wiki/Running-Standalone:-Linux)

**From source**
- [Raspberry Pi](https://github.com/smart-underworld/seestar_alp/wiki/Running-from-source:-Raspberry-Pi)
- [macOS](https://github.com/smart-underworld/seestar_alp/wiki/Running-from-source:-Mac)
- [Windows](https://github.com/smart-underworld/seestar_alp/wiki/Running-from-source:-Windows)

Platform helpers also live in the repo: `raspberry_pi/` (setup + systemd),
`mac/`, `linux/deb/`, and `docker/`.

In brief, running from a source clone looks like:

```bash
# Python 3.13+
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# first run: create your config from the template
cp device/config.toml.example device/config.toml

python root_app.py
```

Then open <http://localhost:5432> in a browser.

---

## The CLI (`ssalp`)

`ssalp` is a command-line tool and async/sync Python library that wraps the
seestar_alp Alpaca HTTP API (it talks to a **running device server**, not to the
telescope directly). It's handy for scripting, automation, and headless setups.

```bash
pipx install "git+https://github.com/smart-underworld/seestar_alp.git#subdirectory=cli"

ssalp --host 192.168.1.51 info device-state
ssalp --host 192.168.1.51 mount goto-target --name M42 --ra "5h35m17s" --dec "-5d23m"
ssalp --host 192.168.1.51 schedule add-mosaic --target M42 --ra 5.588 --dec -5.391 --time 3600
```

Command groups: `info`, `mount`, `camera`, `focuser`, `filter`, `schedule`,
`mosaic`, `files`, `system`. Configuration resolves from CLI flags, `SSALP_*`
environment variables, and a `ssalp.toml` / `~/.config/ssalp/config.toml` file
(with named profiles).

**Full documentation — install, config, every command, and library usage — is in
[`cli/README.md`](cli/README.md).**

---

## AI assistant control (MCP)

The `mcp/` package is an [MCP](https://modelcontextprotocol.io) server that lets
an AI assistant control a Seestar — point at targets, image, read/change
settings, and build and run schedules — by wrapping the same `ssalp` client. It
ships as a Claude Code plugin (with skills for session planning, schedule
building, settings compatibility, and safety), or runs standalone for any MCP
client.

Quickest path, as a Claude Code plugin:

```
/plugin marketplace add smart-underworld/seestar_alp
/plugin install seestar@seestar-alp
```

Physical actions (park, move to horizon, reboot, shutdown) always require your
explicit confirmation. **Setup details are in [`mcp/README.md`](mcp/README.md)
and [`mcp/plugin/README.md`](mcp/plugin/README.md).**

---

## How to get help

Priority support is through GitHub and Discord:

- **Discord** (most up-to-date) — <https://discord.gg/B3zDCAMP4V>
- **Wiki** (install guides, FAQ, troubleshooting) — <https://github.com/smart-underworld/seestar_alp/wiki>
- **GitHub issues** (bug reports) — <https://github.com/smart-underworld/seestar_alp/issues>
- **Facebook group: Smart Telescope Underworld** — <https://www.facebook.com/groups/373417055173095/>
- **YouTube** — <https://www.youtube.com/channel/UCASdbiZUKFGf6VR4H_mijxA>
- **Source org** — <https://github.com/smart-underworld>

When filing a bug, please include:
- the Seestar_Alp **version** (shown in the UI and printed at startup),
- your **Seestar model and firmware version**,
- your platform and how you installed (standalone vs. source, OS),
- the relevant log (`alpyca.log` in the application directory), and
- the steps that reproduce the problem.

---

## Development

Tests, linting, and a telescope-free simulator let you develop without hardware.
Run from the repo root with a Python 3.13 environment:

```bash
pip install -r requirements.txt

# unit tests
python -m pytest -m "not integration" -q

# integration tests against the bundled simulator (see simulator/)
python -m pytest -m integration tests/integration -q

# lint + format check (CI runs both)
ruff check .
ruff format --check .
```

See [`AGENTS.md`](AGENTS.md) for repo conventions and testing expectations, and
the sub-package READMEs ([`cli/`](cli/README.md), [`mcp/`](mcp/README.md),
[`front/`](front/README.md)) for their own test suites.

### Contributing

Pull requests are welcome. A few things that help them land smoothly:

- **Talk first.** Most development discussion happens on the
  [Discord](https://discord.gg/B3zDCAMP4V) — for anything non-trivial, raise it
  there (or in a GitHub issue) before investing a lot of work, so we can agree on
  the approach.
- **Keep changes focused.** One behavior or fix per PR, with a clear description
  of the user-visible impact and any compatibility considerations.
- **Add tests and keep them green.** CI runs the unit and simulator-integration
  suites plus `ruff check` and `ruff format --check`; run them locally first (see
  above). Touching the web UI or settings? Include the nav/settings/HTMX test
  coverage described in [`AGENTS.md`](AGENTS.md).
- **Run the full regression when it matters.** The default PR checks skip the
  slow emulator regression (goto / plate-solve across firmware versions). To run
  it, add the **`run-full-system`** label to your PR — that triggers the full
  emulator lanes (armhf and arm64). It also runs nightly on `main`. Do this for
  anything touching imaging, scheduling, goto, or firmware-compatibility paths.
- **Preserve compatibility.** Don't remove firmware or settings fallbacks unless
  that's the explicit intent of the change.

---

## Releases

Downloads and release notes:
<https://github.com/smart-underworld/seestar_alp/releases>

## License

Seestar_Alp is licensed under the **GNU General Public License v3** — see
[`LICENSE.txt`](LICENSE.txt). It bundles components under their own licenses:
[Alpyca / AlpacaDevice](LICENSE-AlpacaDevice.txt) and
[PyIndi](LICENSE-PyIndi.txt).
