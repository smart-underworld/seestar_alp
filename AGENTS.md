# AGENTS.md

## Purpose
Guidance for AI/code agents working in `seestar_alp` to keep changes safe, testable, and consistent with this repo’s patterns.

## Repo Priorities
1. Preserve user-facing behavior in `front/` (especially navigation, settings, polling/HTMX).
2. Maintain firmware compatibility paths (older/newer Seestar variants).
3. Keep PR validation reliable (unit + integration).

## Environment
- Preferred Python for tests: `ssc-3.13.5`
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python`
  - This is the maintainer's pyenv path; substitute any Python 3.13 interpreter
    or venv (`pip install -r requirements.txt`). The commands below spell out the
    full path, but `python -m ...` from an activated 3.13 venv is equivalent.
- Run commands from repo root.
- `cli/` (the `ssalp` client) and `mcp/` (the MCP server) are separate packages
  with their own suites — see their READMEs. Changes there should keep both the
  package tests and the repo-root integration tests green.

## Required Test Commands
- Fast unit lane:
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m "not integration" -q`
- Simulator integration lane:
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m integration tests/integration -q`
- Ruff (CI runs both; passing `check` alone is not enough):
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m ruff check .`
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m ruff format --check .`

## Change Rules
- Do not remove compatibility fallbacks unless explicitly requested.
- Avoid page-specific nav behavior unless truly necessary; shared UI elements should be consistent across pages.
- For HTMX auto-refresh changes, ensure no destructive empty swaps and no whole-page loading overlays.
- For settings changes:
  - Support both read paths: `get_setting` and `get_stack_setting`.
  - Support save variants: `set_setting` (`stack` payload), `set_stack_setting`, and `set_stack_settings` when applicable.
- Treat firmware-gated behavior carefully; prefer feature-detection/payload-presence over strict version assumptions when practical.

## Testing Expectations for UI/Frontend Backend
When touching `front/app.py` or `front/templates`:
- Add/adjust tests in `tests/test_front_app_state.py` for template/render contracts.
- Add/adjust `tests/integration/test_simulator_e2e.py` for end-to-end behavior.
- Verify federation option in nav/device dropdown is present where expected.
- Verify settings load + save for discrete stack fields.

## Integration Test Scope
`tests/integration/test_simulator_e2e.py` is expected to cover:
- Simulator TCP/UDP basics.
- Settings round-trip and compatibility paths.
- Federation route smoke.
- HTMX fragment endpoint behavior.
- Live/schedule/guestmode flow smoke.
- Error/fallback and wrapped response compatibility.
- Basic performance/concurrency smoke.

## CI Notes
- Main test workflow runs both:
  - `pytest -m "not integration"`
  - `pytest -m integration tests/integration`
- Keep integration runtime under ~5 minutes where possible.
- An always-on emulator-smoke lane runs on every PR (live-view/startup, no
  plate-solving).
- The full emulator regression lanes (goto / 3PPA / plate-solve across firmware
  versions, armhf and arm64) are **gated**: they run nightly, on manual
  dispatch, and on a PR only when the `run-full-system` label is applied. Add
  that label to a PR to exercise the full suite before merge.

## Commit Guidance
- Make focused commits grouped by behavior/fix.
- Include clear commit messages with:
  - User-visible impact
  - Compatibility behavior
  - Test coverage added/updated

## Avoid
- Silent removal of fallback behavior.
- Unbounded polling/animations that can cause flashing/hangs.
- Shipping UI behavior changes without tests for nav/settings/HTMX contracts.
