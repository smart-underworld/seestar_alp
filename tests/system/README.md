# System tests

Drives the real seestar_alp application (both classic and v2 frontends)
against either the in-repo QEMU emulator (`emulator/`) or a real Seestar,
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
emulator or a real Seestar) reachable at the time it's invoked, and
`--target real` additionally blocks on an interactive confirmation.

Run it yourself, locally, whenever you want to validate a real end-to-end
flow — e.g. before a release, after changing anything in `device/`,
`front/`, or `front_v2/`, or when you suspect a regression that only shows
up against the real protocol (as opposed to the in-repo fake simulator
`tests/integration/` uses).

This suite also runs in CI — see `.github/workflows/emulator-smoke.yml`
(every PR — startup + live-view) and `.github/workflows/emulator-full.yml`
(the `run-full-system` PR label, or nightly — adds goto + a scheduled
capture, across every pinned firmware version). See
[CI lanes](#ci-lanes) below for details.

## One-time setup

```bash
pip install -e '.[system]'
playwright install chromium
```

You need a firmware 7.18+ interop PEM key (see repo root `seestar_private_key.pem`
or wherever yours lives) — pass its path via `--pem` if it's not at
`~/dev/seestar_private_key.pem`.

## Against the emulator

1. Start the emulator (from the repo root):
   ```bash
   cd emulator
   ./run.sh
   ```
2. Start the synthetic-sky renderer **on the host** (goto/3PPA is closed-loop
   and needs this running the whole time):
   ```bash
   python3 -m sim.renderd --shared sim/shared --model S50 --catalog sim/data/stars.npy
   ```
3. Run the suite:
   ```bash
   pytest tests/system --target emulator \
     --renderer-shared-dir emulator/sim/shared
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
| `--target` | *(none — suite is skipped)* | `emulator` or `real` |
| `--host` | `127.0.0.1` | device/emulator host |
| `--frontend` | `both` | `classic`, `v2`, or `both` |
| `--pem` | `~/dev/seestar_private_key.pem` | interop PEM path |
| `--goto-target-name` | `Vega` | display name only |
| `--goto-ra` / `--goto-dec` | Vega's coords | decimal degrees |
| `--capture-duration` | `120` | seconds, scheduled star-capture item |
| `--renderer-shared-dir` | *(none)* | optional; not enforced as a precondition — pass it (pointing at `emulator/sim/shared`) so `sim.renderd` and the suite agree on where solved frames land when running `-m full`. A stuck `test_goto` is itself the liveness proof if the renderer isn't running. |
| `--startup-polar-align` / `--no-startup-polar-align` | polar align on | skip 3PPA in the startup flow. Neither CI lane uses `--no-startup-polar-align` (device/seestar_device.py skips AutoFocus too when polar align is off, so a partial startup check isn't useful there) — this remains available for a faster manual/local check. |

## Known limitations (emulator)

- **The scheduled capture never actually stacks a frame against the
  emulator.** The emulator's synthetic star field is injected only into the
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
- **Timings tuned for the emulator's ~10s stack exposure cycle** (the
  `exposure_length_stack_ms` in the scratch config) may need adjusting for
  a real device with different exposure settings — see `--capture-duration`
  and the `window_s` used in `test_schedule_capture_with_concurrent_live_check`.

## CI lanes

This suite also runs in CI, in two lanes driven off the same `pytest
tests/system --target emulator` invocation used locally:

- **`.github/workflows/emulator-smoke.yml`** — runs on every PR. Provisions
  the smoke firmware version (`versions.yaml`'s `smoke_version`), downloads
  the astrometry index files, rebuilds the renderer's star catalog, launches
  both the emulator and `sim.renderd`, and runs `pytest tests/system -m
  smoke --renderer-shared-dir emulator/sim/shared` — the full startup
  sequence (AutoFocus + DarkLibrary + 3-point polar alignment) plus a
  live-view liveness check, but not goto or a scheduled capture.
- **`.github/workflows/emulator-full.yml`** — runs on the `run-full-system`
  PR label, or nightly on a schedule. Same astrometry/renderer setup as the
  smoke lane, and runs `pytest tests/system -m full --renderer-shared-dir
  emulator/sim/shared` (startup, goto, live-view, and a full scheduled
  capture) across every firmware version listed in `versions.yaml`'s
  `full_versions`.

Both lanes need plate-solving: `device/seestar_device.py`'s startup sequence
skips AutoFocus outright when polar alignment is off ("Seestar starts in a
parked position... Skipping."), so a smoke lane without 3PPA couldn't
meaningfully validate AutoFocus either — the astrometry/renderer setup cost
is paid on every PR to keep that coverage.

Neither lane needs a pre-existing interop PEM key: `provision.py` extracts
one fresh from the same XAPK it downloads (see `extract_pem.py` — the key is
baked into the app's own `libopenssllib.so`, not a secret CI needs to
manage) and passes it via `--pem`.

The `smoke`/`full` pytest markers select which tests each lane runs;
goto/3PPA-driving tests are marked `full` since they need the renderer and
astrometry data, while tests that don't depend on plate solving are marked
`smoke`.

## Diagnosing a failed run

Add `--screenshot=on --video=on` (from `pytest-playwright`) to capture a
screenshot and video of the failing page, alongside the `AppProcess` log
tail included in any startup-timeout error message:

```bash
pytest tests/system --target emulator --renderer-shared-dir ... --screenshot=on --video=on
```
