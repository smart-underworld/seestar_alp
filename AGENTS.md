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
- Run commands from repo root.

## Required Test Commands
- Fast unit lane:
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m "not integration" -q`
- Simulator integration lane:
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m integration tests/integration -q`
- Ruff:
  - `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m ruff check .`

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
