# System tests

Drives the real seestar_alp application (both classic and v2 frontends)
against either the seestar-api-research QEMU sandbox or a real Seestar,
through actual browser automation (Playwright). Never runs automatically —
always invoked explicitly.

## One-time setup

```bash
pip install -e '.[system]'
playwright install chromium
```

You need a firmware 7.18+ interop PEM key (see repo root `seestar_private_key.pem`
or wherever yours lives) — pass its path via `--pem` if it's not at
`~/dev/seestar_private_key.pem`.

## Against the sandbox

1. Start the sandbox (from the `seestar-api-research` checkout):
   ```bash
   cd ~/dev/seestar-api-research/sandbox
   ./run.sh
   ```
2. Start the synthetic-sky renderer **on the host** (goto/3PPA is closed-loop
   and needs this running the whole time):
   ```bash
   python3 -m sim.renderd --shared sim/shared --model S50 --catalog sim/data/stars.npy
   ```
3. Run the suite:
   ```bash
   pytest tests/system --target sandbox \
     --renderer-shared-dir ~/dev/seestar-api-research/sandbox/sim/shared
   ```

## Against a real Seestar

```bash
pytest tests/system --target real --host <scope-ip-or-seestar.local> -s
```

The `-s` is required — real-hardware runs pause for an interactive `yes`
confirmation before goto and before starting the schedule, since both
physically move/operate the telescope.

## Options

| Flag | Default | Notes |
|---|---|---|
| `--target` | *(none — suite is skipped)* | `sandbox` or `real` |
| `--host` | `127.0.0.1` | device/sandbox host |
| `--frontend` | `both` | `classic`, `v2`, or `both` |
| `--pem` | `~/dev/seestar_private_key.pem` | interop PEM path |
| `--goto-target-name` | `Vega` | display name only |
| `--goto-ra` / `--goto-dec` | Vega's coords | decimal degrees |
| `--capture-duration` | `120` | seconds, scheduled star-capture item |
| `--renderer-shared-dir` | *(none)* | required for `--target sandbox` |

## Diagnosing a failed run

Add `--screenshot=on --video=on` (from `pytest-playwright`) to capture a
screenshot and video of the failing page, alongside the `AppProcess` log
tail included in any startup-timeout error message:

```bash
pytest tests/system --target sandbox --renderer-shared-dir ... --screenshot=on --video=on
```
