---
name: settings-and-compatibility
description: Use when reading or changing Seestar stack/imaging settings, especially across different firmware versions - explains read_settings, write_setting variants, and feature detection.
---

# Settings and firmware compatibility

Firmware versions differ in which settings calls they support. Handle this by detecting, not assuming.

## Reading
`read_settings` tries both read paths (`get_setting` and `get_stack_setting`) and merges what it can; any path that failed is reported in `errors`. Use whatever keys come back rather than assuming a fixed set.

## Writing
`write_setting(values, variant="auto")`:
- `auto` (default): one key uses `set_stack_setting`, several keys use `set_stack_settings`.
- Explicit variants: `set_setting` (nested `stack` payload), `set_stack_setting`, `set_stack_settings`.
- If a variant is rejected the tool returns `{"ok": false, ...}`; retry with another variant, starting with `auto`, then explicit ones.

## Rules
- After writing, call `read_settings` and verify the values took effect.
- Prefer feature/payload detection (is the key present in the read result? did the write succeed?) over firmware-version checks.
- Never claim a setting is unsupported because of a version number; try it and report the actual result.
- Change only the keys the user asked for.
