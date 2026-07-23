# System tests

Drives the real seestar_alp application (both classic and v2 frontends)
against either the seestar-api-research QEMU sandbox or a real Seestar,
through actual browser automation (Playwright) — the full app is launched
as a real subprocess (`root_app.py`) and driven by clicking through the
actual rendered pages, not by calling internal functions or HTTP APIs
directly.

## What it does

For each selected frontend (`classic`, `v2`, or both), in one continuous
session against the chosen target:

1. **Startup routine** — runs the real startup sequence (auto focus, dark
   frames, 3-point polar alignment) through the Startup page and waits for
   it to report complete.
2. **Goto** — slews to a named target (RA/Dec) through the Goto page and
   waits for it to complete.
3. **Live imaging** — starts live view and confirms the video stream is
   actually delivering frames (liveness, not pixel content).
4. **Scheduled star capture** — adds and starts a schedule item that
   captures the same target, and while it's actively running, confirms live
   imaging still works *and* that the camera pipeline keeps processing
   frames throughout the capture.

## When this runs (and when it doesn't)

**Never runs automatically.** `tests/system/` is excluded from both CI
lanes (`pytest -m "not integration"` and `pytest -m integration
tests/integration`) and from a bare `pytest` invocation — a
`pytest_collection_modifyitems` hook in `conftest.py` skips every test here
unless `--target` is explicitly passed. There is no configuration that
makes this suite run unattended; it always requires a live target (the
sandbox or a real Seestar) reachable at the time it's invoked, and
`--target real` additionally blocks on an interactive confirmation.

Run it yourself, locally, whenever you want to validate a real end-to-end
flow — e.g. before a release, after changing anything in `device/`,
`front/`, or `front_v2/`, or when you suspect a regression that only shows
up against the real protocol (as opposed to the in-repo fake simulator
`tests/integration/` uses).

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

## Known limitations (sandbox)

- **The scheduled capture never actually stacks a frame against the
  sandbox.** The sandbox's synthetic star field is injected only into the
  offline `solve-field` FITS read (used for plate-solving/goto/3PPA), never
  into the live camera/stacking frame buffer, which is always a flat gray
  test pattern by design. So the capture step asserts on frames *processed*
  (stacked + dropped), not frames *stacked* — that's still a real, useful
  signal that the schedule genuinely runs and the camera pipeline keeps
  working throughout, but it can't prove real stacking success. Against a
  real Seestar, this would also naturally validate actual stacking.
- **v2's frontend is a hash-routed SPA** (`/#/startup`, `/#/goto`, etc.) —
  there's no server-side deep-link fallback, so a bare path 404s. The
  drivers already account for this; if you're extending `ui_v2.py`, always
  navigate via the `#/...` hash form.
- **Timings tuned for the sandbox's ~10s stack exposure cycle** (the
  `exposure_length_stack_ms` in the scratch config) may need adjusting for
  a real device with different exposure settings — see `--capture-duration`
  and the `window_s` used in `test_schedule_capture_with_concurrent_live_check`.

## Diagnosing a failed run

Add `--screenshot=on --video=on` (from `pytest-playwright`) to capture a
screenshot and video of the failing page, alongside the `AppProcess` log
tail included in any startup-timeout error message:

```bash
pytest tests/system --target sandbox --renderer-shared-dir ... --screenshot=on --video=on
```
