# Firmware Param-Shape Mismatch (issues #748, #758) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the root cause behind GitHub issues #748 and #758 — recent Seestar firmware (7.75+/2775, 8.46+/2846) rejects `pi_set_time`, `scope_goto`, and `scope_sync` with `code 107`/`108` ("expected object/float param"), which silently breaks the startup clock-set and any Alpaca `SlewToCoordinates`/sync call — and add regression tests so this class of bug (param-shape drift vs. real firmware) is caught by CI going forward.

**Architecture:** Two independent defects compound into the reported symptom:
1. `Seestar.transform_message_for_verify` (device/seestar_device.py) double-wraps *any* list-shaped `params` value into a nested list (`[[ra, dec], "verify"]`) when injecting the auth `"verify"` flag, instead of appending flatly (`[ra, dec, "verify"]`) — firmware then sees an array-of-arrays instead of an array of floats/objects and rejects it. A narrow special case for `set_wheel_position` already does the correct flat-append; this plan generalizes it to all list params and deletes the special case.
2. Independently, `_slew_to_ra_dec` (`scope_goto`), `_sync_target` (`scope_sync`), and the `pi_set_time` call in `start_up_thread_fn` send params in the wrong *shape* to begin with — real firmware (confirmed against decompiled firmware v3.3.1 binaries, which post-date the reporters' exact firmware build 8.46/2846) wants `scope_goto`/`scope_sync` params as a keyed object (`{"ra": ..., "dec": ...}`, not `[ra, dec]`) and `pi_set_time` params as a bare object (not `[obj]`). This plan switches all three call sites to the correct shape.

Both fixes are needed: switching only the call sites to the correct shape does resolve the two reported bugs (dict-shaped params bypass the list-wrapping bug entirely on firmware ≥2706), but leaves the wrapper's general list-nesting defect in place for any other/future list-param RPC method (e.g. `set_control_value`, which already sends `["gain", value]` today and is silently broken by the same defect on any firmware ≥2583). Fixing the wrapper is the actual root-cause fix per the investigation; fixing the three call sites addresses the literal reported symptom. This plan does both, plus a end-to-end regression test that reproduces the exact bug (firmware ≥2706 + verify injection enabled + list params) so it can't regress silently again.

**Tech Stack:** Python, pytest, existing `Seestar` device-layer class and TCP-based `SeestarSimulator` test double.

**Spec:** No separate spec doc — this plan is self-contained; see "Investigation summary" below for the evidence trail.

## Investigation summary (context for implementers — do not re-derive)

- Issue #758 (firmware 8.46/`firmware_ver_int: 2846`) and issue #748 (firmware 7.75/`firmware_ver_int: 2775`) both report the exact same two firmware error codes for the exact same two RPC methods:
  - `pi_set_time` sent as `{"params": [date_json]}` → `{"error": "expected object param", "code": 107}`
  - `scope_goto` sent as `{"params": [ra, dec]}` → `{"error": "expected float param", "code": 108}`
- Both reporters independently found that sending the bare object (`pi_set_time`) or a keyed object (`scope_goto`) fixes it on their real hardware.
- `device/seestar_device.py` already has `firmware_ver_int`-gated logic for a related-but-distinct issue: `transform_message_for_verify` (~line 778) stops injecting `verify` into **dict**-shaped params on firmware ≥2706, because the firmware started rejecting that. It does **not** have equivalent handling for **list**-shaped params — those still go through the generic `else` branch, which nests them: `data["params"] = [existing_params, "verify"]`.
- Running `transform_message_for_verify({"method": "pi_set_time", "params": [date_json]})` with `firmware_ver_int = 2846` (reproduced during investigation) produces `{"method": "pi_set_time", "params": [[date_json], "verify"]}` on the wire — an array wrapping another array, which is exactly what firmware would reject as "expected object param". The reporters never saw this: both logged `date_data` (the pre-transform dict) before it went through `send_message_param` → `transform_message_for_verify`, so their diagnosis (blaming only the `[date_json]` list-wrap in `start_up_thread_fn`) is real but incomplete.
- The codebase already patched this exact defect once, narrowly, for one method: `set_wheel_position` gets `existing_params + ["verify"]` (flat) instead of the general `[existing_params, "verify"]` (nested) — see `device/seestar_device.py` ~line 803. This plan generalizes that fix.
- Decompiled firmware v3.3.1 (`~/dev/firmware/unpacked/v3.3.1/iscope_decompiled/zwoair_guider/00075af8_scope_goto.c`) shows `scope_goto`'s handler does a keyed lookup (`Params::Params(..., "ra", "dec", param_2)`) with **no** positional/array code path at all — confirming the object shape is simply what the protocol wants, not a version-gated behavior. (v3.3.1's shipped `asiair` package version matches `firmware_ver_int` 2846 for v3.3.0, one patch version before it — the closest available decompiled source to the reporters' exact firmware.)

  **Correction (post-implementation):** The bullet above is wrong. A closer read of `Params::Params` itself (`~/dev/firmware/unpacked/v3.3.1/iscope_decompiled/zwoair_guider/0007f2dc_Params.c`, the constructor `scope_goto`'s handler actually calls) shows it has TWO branches: a `type==2` (JSON array) branch that binds array elements positionally to the given key names ("ra" → element 0, "dec" → element 1), and a `type==1` (object) branch that looks members up by their own names. So real firmware accepts BOTH a positional `[ra, dec]` list and a keyed `{"ra":...,"dec":...}` object for `scope_goto`/`scope_sync` — the object shape is not required. Likewise, `pi_set_time`'s `json_array2obj` (`~/dev/firmware/unpacked/v3.3.1/iscope_decompiled/zwoair_guider/0012d038_json_array2obj.c`) unwraps ANY single-level JSON array to its first element with no type check at that point, so the `[date_json]` list-wrap was also never the problem. **The true and only root cause of both #748 and #758 was `transform_message_for_verify`'s double-nesting (Task 1)** — `[[ra, dec], "verify"]` and `[[date_json], "verify"]` are what real firmware actually rejects, not the plain flat shapes it produced before verify-injection got involved. Tasks 2/3's switch to object-shaped params was therefore not strictly required to fix these two issues, but is kept as a defensive, hardware-verified choice (real-hardware testers on firmware 7.75/8.46 independently confirmed it works) that also has the side benefit of skipping the verify-injection wrapper path entirely on firmware >= 2706.
- The simulator (`simulator/src/seestar_simulator.py`) never validates `scope_goto`/`scope_sync`/`pi_set_time` param shape — it accepts anything and returns success — and reports `firmware_ver_int: 2470`, which is below the `2583` threshold where `should_inject_verify()` even activates. This is why CI never caught either bug: the simulated firmware is both too old to trigger verify-injection and too permissive to reject a malformed shape.

## Global Constraints

- Do not remove compatibility fallbacks unless explicitly requested (per `AGENTS.md`) — this plan does not remove any *working* fallback; it fixes a defective one (`set_wheel_position`'s special case is generalized, not removed in effect).
- Test commands (per `AGENTS.md`, adjusted for this machine's local pyenv):
  - Unit: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m "not integration" -q`
  - Integration: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m integration tests/integration -q`
  - Lint: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m ruff check .`
- Run all three after every task; do not move to the next task with failing tests or lint errors.
- Branch: work happens on `bguthro/fix-firmware-param-shape-mismatch` (already created off `origin/main`). Do not create additional branches.
- Make focused commits per task, referencing the user-visible impact (per `AGENTS.md` Commit Guidance).

---

### Task 1: Fix `transform_message_for_verify` list-param double-nesting (root cause)

**Files:**
- Modify: `device/seestar_device.py:778-812` (method `transform_message_for_verify`)
- Test: `tests/test_seestar_device.py:86-125` (existing tests `test_transform_message_for_verify_list_params` and `test_transform_message_for_verify_keeps_existing_verify_list` currently assert the *buggy* nested behavior and must be corrected, not just extended)

**Interfaces:**
- Consumes: nothing new — uses existing `self.should_inject_verify()`, `self._AUTH_METHODS`, `self.firmware_ver_int`.
- Produces: `transform_message_for_verify(data)` now returns flat-appended list params (`[..., "verify"]`) for **any** list-shaped `params`, not just `set_wheel_position`. Later tasks (2, 3, 4) rely on this: dict-shaped params from those tasks bypass this path entirely on firmware ≥2706, but the flat-list behavior is what makes the Task 4 end-to-end wire test pass for firmware <2706 dict-merge paths and for any remaining list-param methods like `set_control_value`.

- [ ] **Step 1: Update the two existing tests to assert correct (flat) behavior instead of the current buggy (nested) behavior**

Replace lines 86-101 and 115-125 of `tests/test_seestar_device.py` with:

```python
def test_transform_message_for_verify_list_params(seestar):
    seestar.firmware_ver_int = 3000
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        out = seestar.transform_message_for_verify(
            {"method": "scope_goto", "params": [12.3, 45.6]}
        )
        assert out["params"] == [12.3, 45.6, "verify"]

        wheel = seestar.transform_message_for_verify(
            {"method": "set_wheel_position", "params": [1]}
        )
        assert wheel["params"] == [1, "verify"]
    finally:
        Config.verify_injection = old_setting


def test_transform_message_for_verify_no_params_adds_verify(seestar):
    seestar.firmware_ver_int = 3000
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        out = seestar.transform_message_for_verify({"method": "noop"})
        assert out["params"] == ["verify"]
    finally:
        Config.verify_injection = old_setting


def test_transform_message_for_verify_keeps_existing_verify_list(seestar):
    seestar.firmware_ver_int = 3000
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        out = seestar.transform_message_for_verify(
            {"method": "scope_goto", "params": [12.3, 45.6, "verify"]}
        )
        assert out["params"] == [12.3, 45.6, "verify"]
    finally:
        Config.verify_injection = old_setting


def test_transform_message_for_verify_does_not_double_nest_list_params(seestar):
    """Regression test for issues #748/#758: on firmware >= 2706, verify
    injection was wrapping an already-list-shaped params value in ANOTHER
    list ([[value...], "verify"]) instead of appending "verify" flatly.
    Firmware rejects the double-nested shape as 'expected object/float
    param' (code 107/108). set_wheel_position had a narrow fix for this;
    this proves the fix now applies to any list-param method, e.g.
    set_control_value's ["gain", value].
    """
    seestar.firmware_ver_int = 2846
    old_setting = Config.verify_injection
    try:
        Config.verify_injection = True
        out = seestar.transform_message_for_verify(
            {"method": "set_control_value", "params": ["gain", 80]}
        )
        assert out["params"] == ["gain", 80, "verify"]
    finally:
        Config.verify_injection = old_setting
```

Note: `test_transform_message_for_verify_no_params_adds_verify` (previously at line 104) is reproduced above unchanged — it sits between the two edited tests and must remain present (it is unaffected by this change since it has no `params` key at all).

- [ ] **Step 2: Run the updated tests to verify they fail against current code**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest tests/test_seestar_device.py -k "transform_message_for_verify" -v`

Expected: `test_transform_message_for_verify_list_params`, `test_transform_message_for_verify_keeps_existing_verify_list`, and `test_transform_message_for_verify_does_not_double_nest_list_params` FAIL (current code produces `[[12.3, 45.6], "verify"]` etc., not the flat form).

- [ ] **Step 3: Fix `transform_message_for_verify` in `device/seestar_device.py`**

Replace lines 799-808:

```python
                if isinstance(existing_params, list) and existing_params:
                    if existing_params[-1] == "verify":
                        return data

                if data.get("method") == "set_wheel_position" and isinstance(
                    existing_params, list
                ):
                    data["params"] = existing_params + ["verify"]
                else:
                    data["params"] = [existing_params, "verify"]
```

with:

```python
                if isinstance(existing_params, list):
                    # Positional params (e.g. scope_goto's [ra, dec] before task 2,
                    # set_control_value's ["gain", value]) must stay a flat list with
                    # "verify" appended. Wrapping them in another list (e.g.
                    # [[ra, dec], "verify"]) makes firmware >= 2706 reject the whole
                    # payload as "expected float/object param" (code 107/108).
                    if existing_params and existing_params[-1] == "verify":
                        return data
                    data["params"] = existing_params + ["verify"]
                else:
                    data["params"] = [existing_params, "verify"]
```

- [ ] **Step 4: Run the tests again to verify they pass**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest tests/test_seestar_device.py -k "transform_message_for_verify" -v`

Expected: all PASS.

- [ ] **Step 5: Run the full unit lane and lint to make sure nothing else broke**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m "not integration" -q`
Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m ruff check device/seestar_device.py tests/test_seestar_device.py`

Expected: all PASS, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add device/seestar_device.py tests/test_seestar_device.py
git commit -m "fix: stop double-nesting list params when injecting verify flag

transform_message_for_verify wrapped any list-shaped params in another
list ([[ra, dec], \"verify\"]) instead of appending verify flatly
([ra, dec, \"verify\"]) on firmware >= 2706. Firmware rejects the
double-nested shape as 'expected object/float param' (code 107/108).
set_wheel_position already had a narrow fix for this; generalized it to
all list-param methods. Contributes to fixing #748 and #758."
```

---

### Task 2: Send `scope_goto`/`scope_sync` as keyed object params

**Files:**
- Modify: `device/seestar_device.py:1151-1183` (`_slew_to_ra_dec`, `_sync_target`)
- Test: `tests/test_seestar_device.py` (add new test near `test_slew_sync_stop_and_sound_paths`, ~line 1243)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_slew_to_ra_dec(params)` and `_sync_target(params)` now send `{"ra": ..., "dec": ...}` instead of `[ra, dec]`. Task 4's end-to-end test relies on this exact key naming (`"ra"`, `"dec"`). Task 5's simulator validation relies on this exact shape too.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_seestar_device.py` (after `test_slew_sync_stop_and_sound_paths`, ~line 1263):

```python
def test_slew_to_ra_dec_and_sync_target_send_object_params(monkeypatch, seestar):
    """Regression test for issue #758: firmware 8.46 rejected scope_goto/
    scope_sync when params were sent as a positional [ra, dec] list
    ('expected float param', code 108). Real firmware wants a keyed object.
    """
    sent = []
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda d: sent.append(d) or {"result": "ok"},
    )
    monkeypatch.setattr(seestar, "wait_end_op", lambda _e: True)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)

    seestar._slew_to_ra_dec([12.3, 45.6])
    assert sent[-1]["method"] == "scope_goto"
    assert sent[-1]["params"] == {"ra": 12.3, "dec": 45.6}

    seestar._sync_target([1.0, 2.0])
    assert sent[-1]["method"] == "scope_sync"
    assert sent[-1]["params"] == {"ra": 1.0, "dec": 2.0}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest tests/test_seestar_device.py -k test_slew_to_ra_dec_and_sync_target_send_object_params -v`

Expected: FAIL — `sent[-1]["params"] == [12.3, 45.6]`, not the expected dict.

- [ ] **Step 3: Update `_slew_to_ra_dec` and `_sync_target` in `device/seestar_device.py`**

Replace lines 1151-1163:

```python
    # {"method":"scope_goto","params":[1.2345,75.0]}
    def _slew_to_ra_dec(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info(f"slew to {in_ra}, {in_dec}")
        data: MessageParams = {"method": "scope_goto", "params": [in_ra, in_dec]}
        self.mark_op_state("goto_target", "stopped")
        result = self.send_message_param_sync(data)
        if "error" in result:
            self.logger.warning("Error while trying to move: %s", result)
            return False

        return self.wait_end_op("goto_target")
```

with:

```python
    # {"method":"scope_goto","params":{"ra":1.2345,"dec":75.0}}
    def _slew_to_ra_dec(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info(f"slew to {in_ra}, {in_dec}")
        data: MessageParams = {
            "method": "scope_goto",
            "params": {"ra": in_ra, "dec": in_dec},
        }
        self.mark_op_state("goto_target", "stopped")
        result = self.send_message_param_sync(data)
        if "error" in result:
            self.logger.warning("Error while trying to move: %s", result)
            return False

        return self.wait_end_op("goto_target")
```

Replace lines 1173-1183 (`_sync_target`):

```python
    def _sync_target(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info("%s: sync to target... %s %s", self.device_name, in_ra, in_dec)
        data: MessageParams = {"method": "scope_sync", "params": [in_ra, in_dec]}
        result = self.send_message_param_sync(data)
        if "error" in result:
            self.logger.info(f"Failed to sync: {result}")
        else:
            sleep(2)
        return result
```

with:

```python
    def _sync_target(self, params):
        in_ra = params[0]
        in_dec = params[1]
        self.logger.info("%s: sync to target... %s %s", self.device_name, in_ra, in_dec)
        data: MessageParams = {
            "method": "scope_sync",
            "params": {"ra": in_ra, "dec": in_dec},
        }
        result = self.send_message_param_sync(data)
        if "error" in result:
            self.logger.info(f"Failed to sync: {result}")
        else:
            sleep(2)
        return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest tests/test_seestar_device.py -k test_slew_to_ra_dec_and_sync_target_send_object_params -v`

Expected: PASS.

- [ ] **Step 5: Run the full unit lane (existing `test_slew_sync_stop_and_sound_paths` and other callers must still pass unchanged)**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m "not integration" -q`
Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m ruff check device/seestar_device.py tests/test_seestar_device.py`

Expected: all PASS, no lint errors. (`test_slew_sync_stop_and_sound_paths` mocks `send_message_param_sync` entirely and only checks the return value, so it is unaffected by the params-shape change.)

- [ ] **Step 6: Commit**

```bash
git add device/seestar_device.py tests/test_seestar_device.py
git commit -m "fix: send scope_goto/scope_sync params as {ra, dec} object

Firmware 7.75+/8.46+ rejects the positional [ra, dec] list shape with
'expected float param' (code 108). Confirmed against decompiled firmware
(scope_goto handler does a keyed ra/dec lookup with no positional path)
and against real-device reports in #758. Fixes the Alpaca
SlewToCoordinates(Async) and sync paths."
```

---

### Task 3: Send `pi_set_time` as a bare object and stop swallowing failures

**Files:**
- Modify: `device/seestar_device.py:1478` (payload construction) and `device/seestar_device.py:1537` (send + result handling, inside `start_up_thread_fn`)
- Test: `tests/test_seestar_device.py` (new test near `test_start_up_thread_fn_success_and_old_firmware`, ~line 1053)

**Interfaces:**
- Consumes: nothing new.
- Produces: `date_data["params"]` is now the bare `date_json` dict (not `[date_json]`), and a failed `pi_set_time` response now produces a `self.logger.warning(...)` call instead of being silently logged at info level. Task 4's end-to-end test relies on this exact shape.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_seestar_device.py` (after `test_start_up_thread_fn_success_and_old_firmware`, before `test_action_start_up_sequence_paths` — i.e. around line 1107):

```python
def test_start_up_thread_fn_sends_pi_set_time_as_object_and_logs_failure(
    monkeypatch, seestar
):
    """Regression test for issues #748/#758: pi_set_time was wrapped in a
    list ([date_json]), which firmware 7.75+/8.46+ rejects with 'expected
    object param' (code 107). The failure was also silently swallowed
    (logged at info level with no error check), which is how a user could
    lose a night of imaging to a stale scope clock without any warning in
    the logs.
    """
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone_name", lambda: "UTC"
    )
    import datetime as _dt

    monkeypatch.setattr(
        "device.seestar_device.tzlocal.get_localzone", lambda: _dt.timezone.utc
    )
    monkeypatch.setattr("device.seestar_device.EarthLocation", lambda **_k: object())
    monkeypatch.setattr(seestar, "set_setting", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(seestar, "play_sound", lambda _sid: None)

    sent = []
    warnings = []
    monkeypatch.setattr(
        seestar.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )

    def fake_sync(payload):
        if payload["method"] == "get_device_state":
            return {"result": {"device": {"firmware_ver_int": 2846}}}
        if payload["method"] == "pi_set_time":
            sent.append(payload)
            return {"error": "expected object param", "code": 107}
        return {"result": "ok"}

    monkeypatch.setattr(seestar, "send_message_param_sync", fake_sync)

    seestar.start_up_thread_fn(
        {
            "lat": 1.1,
            "lon": 2.2,
            "auto_focus": False,
            "3ppa": False,
            "dark_frames": False,
        }
    )

    assert sent, "pi_set_time was never sent"
    assert isinstance(sent[0]["params"], dict)
    assert "year" in sent[0]["params"] and "time_zone" in sent[0]["params"]
    assert warnings, "a failed pi_set_time must be logged as a warning, not swallowed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest tests/test_seestar_device.py -k test_start_up_thread_fn_sends_pi_set_time_as_object_and_logs_failure -v`

Expected: FAIL — `sent[0]["params"]` is currently `[date_json]` (a list, so `isinstance(..., dict)` fails), and `warnings` is empty (current code only calls `self.logger.info(...)`).

- [ ] **Step 3: Update `device/seestar_device.py`**

Replace line 1478:

```python
            date_data: MessageParams = {"method": "pi_set_time", "params": [date_json]}
```

with:

```python
            date_data: MessageParams = {"method": "pi_set_time", "params": date_json}
```

Replace line 1537:

```python
            self.logger.info(self.send_message_param_sync(date_data))
```

with:

```python
            time_result = self.send_message_param_sync(date_data)
            if "error" in time_result:
                self.logger.warning(f"Failed to set scope time: {time_result}")
            else:
                self.logger.info(f"Set scope time: {time_result}")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest tests/test_seestar_device.py -k test_start_up_thread_fn_sends_pi_set_time_as_object_and_logs_failure -v`

Expected: PASS.

- [ ] **Step 5: Run the full unit lane and lint**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m "not integration" -q`
Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m ruff check device/seestar_device.py tests/test_seestar_device.py`

Expected: all PASS (including `test_start_up_thread_fn_success_and_old_firmware` and `test_start_up_thread_full_sequence`, which don't inspect `pi_set_time`'s payload shape and are unaffected), no lint errors.

- [ ] **Step 6: Commit**

```bash
git add device/seestar_device.py tests/test_seestar_device.py
git commit -m "fix: send pi_set_time params as a bare object; stop swallowing errors

Firmware 7.75+/8.46+ rejects the [date_json] list-wrap with 'expected
object param' (code 107), leaving the scope on its stale post-power-on
clock -- every subsequent goto then fails looking like a mount/alignment
problem. The failure was also never checked, only logged at info level.
Now sends the bare object and logs a warning on failure. Fixes #748, #758."
```

---

### Task 4: End-to-end wire-payload regression test (the "class of bug" test)

**Files:**
- Test: `tests/test_seestar_device.py` (new test near `test_send_message_param_assigns_id_and_serializes`, ~line 128)

**Interfaces:**
- Consumes: `seestar.send_message_param(data)` (existing method, unchanged — calls `transform_message_for_verify` then serializes via `self.send_message`), the dict-shaped payloads produced by Tasks 2 and 3.
- Produces: nothing consumed by later tasks — this is a leaf regression test.

This test is the one most directly aimed at "catch this class of bug": it captures the actual JSON string that would be written to the socket (post-`transform_message_for_verify`) for firmware 2846 (issue #758's exact firmware) with verify injection enabled — the exact combination that broke for both reporters — and proves it now matches what both reporters confirmed works on real hardware.

- [ ] **Step 1: Write the test**

Add this test to `tests/test_seestar_device.py` (after `test_send_message_param_assigns_id_and_serializes`, ~line 142):

```python
def test_wire_payload_for_scope_goto_and_pi_set_time_on_firmware_2846(
    monkeypatch, seestar
):
    """End-to-end regression test for issues #748 (firmware 7.75/2775) and
    #758 (firmware 8.46/2846): captures the exact JSON that would be
    written to the socket, after transform_message_for_verify runs, for a
    firmware version where verify injection is active but dict-param
    verify-injection is skipped (>= 2706 short-circuits at
    transform_message_for_verify). This is the exact combination that
    silently broke pi_set_time and scope_goto for both reporters.
    """
    seestar.firmware_ver_int = 2846
    old_setting = Config.verify_injection
    sent = []
    monkeypatch.setattr(seestar, "send_message", lambda payload: sent.append(payload))
    try:
        Config.verify_injection = True

        seestar.send_message_param(
            {"method": "scope_goto", "params": {"ra": 22.8737, "dec": 67.479}}
        )
        wire = json.loads(sent[-1])
        assert wire["params"] == {"ra": 22.8737, "dec": 67.479}

        date_json = {
            "year": 2026,
            "mon": 8,
            "day": 17,
            "hour": 9,
            "min": 5,
            "sec": 37,
            "time_zone": "Europe/Paris",
        }
        seestar.send_message_param({"method": "pi_set_time", "params": date_json})
        wire = json.loads(sent[-1])
        assert wire["params"] == date_json
    finally:
        Config.verify_injection = old_setting
```

`json` is already imported at the top of `tests/test_seestar_device.py` (line 2).

- [ ] **Step 2: Run the test**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest tests/test_seestar_device.py -k test_wire_payload_for_scope_goto_and_pi_set_time_on_firmware_2846 -v`

Expected: PASS, since Tasks 1-3 already fixed both the shape and the wrapper. (If this task is implemented before Tasks 1-3 for some reason, it will FAIL — that's expected and confirms the test is meaningful. Implement Tasks 1-3 first as ordered.)

- [ ] **Step 3: Run the full unit lane and lint**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m "not integration" -q`
Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m ruff check tests/test_seestar_device.py`

Expected: all PASS, no lint errors.

- [ ] **Step 4: Commit**

```bash
git add tests/test_seestar_device.py
git commit -m "test: add end-to-end wire-payload regression test for #748/#758

Captures the exact post-transform_message_for_verify JSON for scope_goto
and pi_set_time on firmware 2846, the combination (list-param double-nest
+ wrong shape) that broke both issues."
```

---

### Task 5: Simulator param-shape validation + integration tests

**Files:**
- Modify: `simulator/src/seestar_simulator.py:409-420` (`scope_goto`/`scope_sync` branches) and `simulator/src/seestar_simulator.py:510-519` (`pi_set_time` branch)
- Test: `tests/integration/test_simulator_e2e.py` (new test at end of file, ~line 1250)

**Interfaces:**
- Consumes: nothing new — reads `data.get("params")` from the existing dispatch in `send_message_param_sync`.
- Produces: the simulator now enforces the real protocol contract (object-shaped params required) for these three methods, returning the same `code: 107`/`108` errors real firmware returns for the wrong shape. This closes the CI blind spot noted in the investigation summary: the simulator previously accepted any shape, so no CI run has ever exercised this contract.

- [ ] **Step 1: Write the failing integration test**

Add this test to `tests/integration/test_simulator_e2e.py` (at the end of the file, after `test_42_auto_af_round_trip_via_simulator`):

```python
def test_43_scope_goto_and_pi_set_time_require_object_params(simulator_server):
    """Regression test for issues #748/#758: the simulator must enforce the
    same param-shape contract real firmware does, so a future regression
    back to positional/list params is caught by CI instead of shipping to
    users' hardware."""
    host = simulator_server["host"]
    port = simulator_server["tcp_port"]

    good_goto = _send_tcp_command(
        host, port, {"id": 200, "method": "scope_goto", "params": {"ra": 1.0, "dec": 2.0}}
    )
    assert "error" not in good_goto

    bad_goto = _send_tcp_command(
        host, port, {"id": 201, "method": "scope_goto", "params": [1.0, 2.0]}
    )
    assert bad_goto.get("code") == 108
    assert "error" in bad_goto

    good_sync = _send_tcp_command(
        host, port, {"id": 202, "method": "scope_sync", "params": {"ra": 1.0, "dec": 2.0}}
    )
    assert "error" not in good_sync

    bad_sync = _send_tcp_command(
        host, port, {"id": 203, "method": "scope_sync", "params": [1.0, 2.0]}
    )
    assert bad_sync.get("code") == 108

    good_time = _send_tcp_command(
        host,
        port,
        {"id": 204, "method": "pi_set_time", "params": {"year": 2026, "mon": 1}},
    )
    assert "error" not in good_time

    bad_time = _send_tcp_command(
        host,
        port,
        {"id": 205, "method": "pi_set_time", "params": [{"year": 2026, "mon": 1}]},
    )
    assert bad_time.get("code") == 107
    assert "error" in bad_time
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m integration tests/integration/test_simulator_e2e.py -k test_43_scope_goto_and_pi_set_time_require_object_params -v`

Expected: FAIL — the `bad_goto`/`bad_sync`/`bad_time` assertions fail because the simulator currently returns success for any shape.

- [ ] **Step 3: Add validation to `simulator/src/seestar_simulator.py`**

Replace lines 409-420:

```python
        elif method == "scope_goto":
            # Simulate slewing
            self.state["mount"]["move_type"] = "goto"
            return {
                "jsonrpc": "2.0",
                "method": "scope_goto",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "scope_sync":
            # Simulate sync
            return {"jsonrpc": "2.0", "result": 0, "id": cur_cmdid}
```

with:

```python
        elif method == "scope_goto":
            params = data.get("params")
            if (
                not isinstance(params, dict)
                or not isinstance(params.get("ra"), (int, float))
                or not isinstance(params.get("dec"), (int, float))
            ):
                return {
                    "jsonrpc": "2.0",
                    "Timestamp": timestamp,
                    "method": "scope_goto",
                    "error": "expected float param",
                    "code": 108,
                    "id": cur_cmdid,
                }
            # Simulate slewing
            self.state["mount"]["move_type"] = "goto"
            return {
                "jsonrpc": "2.0",
                "method": "scope_goto",
                "result": 0,
                "id": cur_cmdid,
            }
        elif method == "scope_sync":
            params = data.get("params")
            if (
                not isinstance(params, dict)
                or not isinstance(params.get("ra"), (int, float))
                or not isinstance(params.get("dec"), (int, float))
            ):
                return {
                    "jsonrpc": "2.0",
                    "Timestamp": timestamp,
                    "method": "scope_sync",
                    "error": "expected float param",
                    "code": 108,
                    "id": cur_cmdid,
                }
            # Simulate sync
            return {"jsonrpc": "2.0", "result": 0, "id": cur_cmdid}
```

Replace lines 510-519:

```python
        elif method == "pi_set_time":
            # Simulate setting time
            self.scope_time = data.get("params", {})
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "pi_set_time",
                "result": 0,
                "id": cur_cmdid,
            }
```

with:

```python
        elif method == "pi_set_time":
            params = data.get("params")
            if not isinstance(params, dict):
                return {
                    "jsonrpc": "2.0",
                    "Timestamp": timestamp,
                    "method": "pi_set_time",
                    "error": "expected object param",
                    "code": 107,
                    "id": cur_cmdid,
                }
            # Simulate setting time
            self.scope_time = params
            return {
                "jsonrpc": "2.0",
                "Timestamp": timestamp,
                "method": "pi_set_time",
                "result": 0,
                "id": cur_cmdid,
            }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m integration tests/integration/test_simulator_e2e.py -k test_43_scope_goto_and_pi_set_time_require_object_params -v`

Expected: PASS.

- [ ] **Step 5: Run the full integration and unit lanes, and lint**

Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m integration tests/integration -q`
Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m "not integration" -q`
Run: `/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m ruff check simulator/src/seestar_simulator.py tests/integration/test_simulator_e2e.py`

Expected: all PASS, no lint errors. In particular, no other integration test sends `scope_goto`/`scope_sync`/`pi_set_time` with a non-object shape (confirmed during investigation via grep — only this new test and the unit tests in `tests/test_seestar_device.py` reference these methods), so nothing else should regress.

- [ ] **Step 6: Commit**

```bash
git add simulator/src/seestar_simulator.py tests/integration/test_simulator_e2e.py
git commit -m "test: simulator enforces real object-param contract for scope_goto/scope_sync/pi_set_time

The simulator previously accepted any params shape for these three
methods, which is why CI never caught #748/#758 (a positional-list
regression would ship silently). Now returns the same code 107/108
errors real firmware does for the wrong shape."
```

---

## Final verification (after all tasks)

- [ ] Run the full required test suite one more time end to end:

```bash
/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m "not integration" -q
/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m pytest -m integration tests/integration -q
/Users/bguthro/.pyenv/versions/ssc-3.12.5/bin/python -m ruff check .
```

Expected: all green.

- [ ] Confirm no unrelated files were touched: `git diff origin/main --stat` should show only `device/seestar_device.py`, `simulator/src/seestar_simulator.py`, `tests/test_seestar_device.py`, `tests/integration/test_simulator_e2e.py`, and this plan file.
