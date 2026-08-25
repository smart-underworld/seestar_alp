# Emulator-based firmware regression suite — design

Date: 2026-07-23
Branch: `bguthro/emulator-ci` (branched off `bguthro/front_v2`)

## Summary

Move the QEMU-armhf Seestar firmware emulator (currently
`seestar-api-research/sandbox/`) into `seestar_alp` as `emulator/`, and turn
the existing manual-only `tests/system` suite into a two-tier CI regression
suite that runs against multiple firmware versions — without ever checking
firmware binaries into the repo.

Firmware is acquired at CI run time from APKPure (as the existing
`apk_utils.py`/`decompile_iscope.py extract` pipeline already does locally),
resolved from a small pinned version list, and cached by GitHub Actions
between runs. Plate-solving support (astrometry.net + sextractor + index
files), currently staged from a real physical device over SSH, is instead
reconstructed from public sources (apt packages + public index-file
downloads) — pending a feasibility spike.

## Goals

- Relocate the emulator into `seestar_alp` so it's versioned alongside the
  code it tests, without dragging in RE/decompilation tooling that's
  irrelevant to running it.
- Run a regression suite derived from `tests/system` automatically in CI
  against a small matrix of real firmware versions.
- Never commit firmware bytes (APKs, `.deb`s, extracted binaries, index
  files) to the repository.
- Keep the existing manual, human-driven use of `tests/system` (against a
  locally-launched emulator or real hardware) working unchanged.

## Non-goals

- Moving Ghidra decompilation, the Claude-API markdown-doc generation
  (`decompile_iscope.py analyze`), or any other reverse-engineering research
  tooling — that stays in `seestar-api-research`.
- Testing every device model (S50/S50V2/S50P/S30/S30P) per firmware version.
- Guaranteeing legal/ToS coverage for scripted APKPure downloads — flagged
  as a risk (see below), not resolved by this design.

## Repo layout

New top-level directory, replacing `seestar-api-research/sandbox/`:

```
emulator/
  Dockerfile            # armhf Buster container definition
  entrypoint.sh
  run.sh                # local manual launch (build+run container), updated
                         # for the new firmware/ provisioning helpers
  stubs/                # hardware stubs (stub_hwid.c etc.) — moved as-is
  sim/                  # synthetic-sky renderer + shared dir — moved as-is
  seed/                 # seed .ZWO files — moved as-is
  firmware/             # NEW
    apk_utils.py          # open_apk() — moved from seestar-api-research/scripts
    extract_iscope.py     # extract assets/iscope, dpkg -x -> deb/out — moved
    provision.py          # NEW: CI orchestration (see below)
    versions.yaml          # NEW: pinned firmware version list for the CI matrix
  astrometry/            # NEW, replaces stage-astrometry.sh's SSH device pull
    build.sh               # apt-install astrometry.net + sextractor (if
                            # available), download public index-41xx files
```

Left behind in `seestar-api-research`: `decompile_iscope.py`'s `decompile`
and `analyze` subcommands, Ghidra scripts, and all markdown-doc-generation
machinery. None of it is needed to build or run the emulator.

**Nothing under `emulator/firmware/versions.yaml` contains firmware bytes.**
It holds only version identifiers (version string + APKPure version code)
that CI resolves to bytes at run time.

## Firmware acquisition & provisioning

**Local/manual use** (`emulator/run.sh`): works as it does today — a human
extracts firmware locally (via `extract_iscope.py`, or by hand) and points
`run.sh` at the resulting `deb/out` tree. No behavior change.

**CI provisioning** (`emulator/firmware/provision.py`), given a version from
`versions.yaml`:
1. Check GitHub Actions cache for `firmware-{version_code}.xapk`; download
   via `apk_utils`/APKPure (cloudscraper) only on a cache miss.
2. Extract `assets/iscope`, `dpkg -x` the `.deb`s into a workspace-local
   `deb/out` tree — cached alongside the XAPK so repeat runs skip extraction
   too.
3. Hand the resulting path to the container-startup step (the emulator image
   itself is version-independent and built once per workflow run; only the
   bind-mounted firmware tree changes per version in the matrix).

## Astrometry sourcing

The firmware execs stock `solve-field --use-sextractor` (confirmed — not a
patched binary) against public Tycho-2 index files (`index-4107..4112-Vt.fits`,
the standard astrometry.net 41xx series). This makes public reconstruction
plausible: apt-install `astrometry.net` + `sextractor` into the Buster/armhf
image, and download the public index files from data.astrometry.net, instead
of pulling both from a real device over SSH.

**This needs a feasibility spike before the full-matrix lane is built** —
package availability for these two packages on Debian buster/armhf was not
confirmed during design (the packages.debian.org search didn't return a
clean answer in this session). This is the first implementation task. If a
package turns out unavailable for buster/armhf, this design will need
revisiting for that piece specifically — no fallback path is pre-designed,
per the explicit choice to pursue public reconstruction only.

Astrometry data (packages + index files) is version-independent — one
GitHub Actions cache entry shared across the whole firmware matrix, not
per-version.

## CI workflow structure

Two GitHub Actions workflows, both invoking `pytest tests/system` with
`--target emulator` (renamed from `--target sandbox`):

- **`emulator-smoke.yml`** — triggers on every PR. Single pinned "primary"
  firmware version, S50 model. Runs `pytest tests/system --target emulator
  -m smoke`. No astrometry setup needed at all.
- **`emulator-full.yml`** — triggers on the `run-full-system` PR label
  (via `labeled`) **and** nightly via `schedule`. Loops the full pinned
  version list from `versions.yaml`, S50 model only. Runs `pytest
  tests/system --target emulator -m full` per version. Includes the
  astrometry build/cache step.

Model coverage is intentionally S50-only across both lanes — model-specific
behavior differences are a separate, smaller concern from firmware-version
regressions, and testing all 5 models per firmware version would multiply
full-lane runtime 5x.

Both lanes use `--frontend both` (the existing default), exercising classic
and v2 for every run — AGENTS.md's top repo priority is preserving
user-facing behavior across both frontends, so frontend coverage isn't
trimmed the way model coverage is.

## Test structure (`tests/system`)

- `--target` gains `emulator` as the renamed value for what was `sandbox`
  (`real` is unchanged). Applies to `conftest.py`, `target.py`, and the
  README.
- `run_startup()` in both `ui_classic.py` and `ui_v2.py` gains a
  `polar_align: bool = True` parameter (default preserves today's behavior).
  Smoke-tier calls it with `polar_align=False` to skip 3PPA — no
  plate-solving involved.
- `@pytest.mark.smoke`: `test_startup` (polar_align=False) +
  `test_live_imaging_standalone`.
- `@pytest.mark.full`: the complete existing 4-step flow (startup incl.
  3PPA, goto, live, schedule-capture) — unmodified from what runs manually
  today.
- The existing "never auto-selected without `--target`" skip guard in
  `conftest.py` is untouched. CI satisfies it by passing `--target emulator`
  explicitly, exactly as a human does locally.
- Manual local runs without `-m` continue to run everything, unaffected.

`test_goto` and the schedule-capture test are full-tier only: both target an
RA/Dec, and whether they require a completed 3PPA/pointing state to succeed
against the emulator (independent of whether the assertions themselves check
solving) wasn't verified during this design — they're kept in the tier that
already exercises the complete, solving-capable startup sequence.

## Error handling / diagnosability

- Reuse `AppProcess`'s existing log-tail-on-failure behavior — no change.
- Firmware acquisition failure (APKPure blocked/cache miss+fetch fails)
  fails the workflow with a message pointing at `versions.yaml`, not a
  cryptic downstream container-start failure.
- Astrometry acquisition failure fails fast in a dedicated setup step
  before any pytest run starts.
- `--screenshot=on --video=on` (already supported by `tests/system`) is
  wired into the CI workflow's failure path so failed runs upload Playwright
  artifacts automatically.

## Open risks

- **Astrometry package availability on buster/armhf** — unconfirmed, first
  implementation task (see above).
- **APKPure scraping from CI/datacenter IPs** — `cloudscraper` exists
  because APKPure fronts Cloudflare; datacenter IPs are more likely to be
  challenged than residential ones. Mitigated by GitHub Actions caching
  (download once per version, not per run), but a fresh version's first
  fetch could still be flaky.
- **Legal/redistribution status of scripted firmware APK downloads** — not
  resolved by this design; noted as a known open question, not a blocker
  the design attempts to answer.
