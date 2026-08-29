# Framed Mosaic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Framed Mosaic" capture mode — a single enlarged/rotated frame (device-native `scale`/`angle`, distinct from the existing grid-panel Mosaic) — runnable immediately, schedulable, federatable, and plannable from the Planning page, in the old (`front/`) UI.

**Architecture:** A new scheduler action `start_framed_mosaic` parallels the existing `start_mosaic`/`start_spectra` actions in `device/seestar_device.py`: it does one `goto` (reusing the existing retry/autofocus/LP-filter logic), sends `set_setting {"mosaic": {"scale", "angle", "star_map_angle"}}`, runs one stack session, then resets the mosaic setting in a `finally`. `device/seestar_federation.py` gets a matching `start_framed_mosaic` shortcut plus `duplicate`/`by_time` fan-out. The old UI gets a new create/schedule page pair (mirroring Image/Mosaic) and a new, separate Planning-page card with a live rotated-rectangle preview drawn via Aladin's own overlay API.

**Tech Stack:** Python (Falcon web framework, existing `device.seestar_device`/`device.seestar_federation` modules), Jinja2 templates, vanilla JS + Aladin Lite (already loaded elsewhere in the app), pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-framed-mosaic-design.md`

## Global Constraints

- No `Config.experimental` gating anywhere in this feature — it ships as a normal, always-available feature (per spec §2/§7/§8/§11, updated after review).
- Scale range: `1.0`–`2.0` (float, step `0.1` in the UI). Angle range: `-90`–`90` (float, step `5` in the UI). These match the real Seestar app's own control ranges (spec §2, §7).
- No `by_panels` federation mode for this action — there are no discrete panels (spec §3, §6).
- No changes to the existing grid-panel `start_mosaic` action, math, or templates (spec §3).
- Field names reuse existing conventions wherever an equivalent concept already exists: `target_name`, `ra`, `dec`, `is_j2000`, `panel_time_sec`, `gain`, `is_use_lp_filter`, `is_use_autofocus`, `num_tries`, `retry_wait_s`, `stack_type`, `federation_mode`, `max_devices`. New fields are `mosaic_scale` and `mosaic_angle`.
- Test commands (from `AGENTS.md`), run from repo root:
  - Fast unit lane: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m "not integration" -q`
  - Simulator integration lane: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m pytest -m integration tests/integration -q`
  - Ruff: `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python -m ruff check .`
  - If `/home/bguthro/.pyenv/versions/ssc-3.13.5/bin/python` doesn't exist on this machine, fall back to the active `python`/`pytest` on `PATH` and note the substitution when reporting results.

---

## Task 1: Device layer — `start_framed_mosaic` scheduler action

**Files:**
- Modify: `device/seestar_device.py` (new methods near the existing mosaic methods; new `elif` branch in `scheduler_thread_fn`)
- Modify: `device/telescope.py:218-220` (new Alpaca action dispatch branch)
- Test: `tests/test_seestar_device.py`

**Interfaces:**
- Consumes: `Util.parse_coordinate(is_j2000, ra, dec)` (returns a `SkyCoord`-like object with `.ra.hour`/`.dec.deg`), `self.mosaic_goto_inner_worker(ra, dec, target_name, is_use_autofocus, is_use_lp_filter)` (returns `bool`), `self.start_stack(params)` (returns `bool`), `self.stop_stack()`, `self.send_message_param_sync(msg)`, `self.update_scheduler_state_obj(item_state)`, `self.create_schedule`/`self.add_schedule_item`/`self.start_scheduler` (all pre-existing on `Seestar`).
- Produces: `Seestar.start_framed_mosaic(params) -> dict`, `Seestar.start_framed_mosaic_item(params: dict) -> None`, `Seestar.framed_mosaic_thread_fn(target_name, center_RA, center_Dec, is_use_LP_filter, panel_time_sec, mosaic_scale, mosaic_angle, gain, is_use_autofocus, num_tries, retry_wait_s, stack_type="DeepSky") -> None`. Task 2 (federation) and Task 3 (front-end) call `start_framed_mosaic` by name via the Alpaca action dispatch.

- [ ] **Step 1: Write failing tests for `start_framed_mosaic_item` validation and dispatch**

Add to `tests/test_seestar_device.py` (place near `test_start_mosaic_item_paths`, e.g. after line 1689):

```python
def test_start_framed_mosaic_item_paths(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)

    class FakeCoord:
        ra = SimpleNamespace(hour=1.5)
        dec = SimpleNamespace(deg=2.5)

    monkeypatch.setattr(
        "device.seestar_device.Util.parse_coordinate", lambda *_a, **_k: FakeCoord
    )

    started = {"count": 0}

    class FakeThread:
        def __init__(self, target=None):
            self.target = target
            self.name = ""

        def start(self):
            started["count"] += 1

    monkeypatch.setattr("device.seestar_device.threading.Thread", FakeThread)
    monkeypatch.setattr(seestar, "framed_mosaic_thread_fn", lambda *a, **k: None)

    # scheduler not working branch
    seestar.schedule["state"] = "stopped"
    assert (
        seestar.start_framed_mosaic_item({"target_name": "T", "ra": 1, "dec": 2})
        is None
    )

    base_params = {
        "target_name": "T",
        "ra": 1.0,
        "dec": 2.0,
        "is_j2000": False,
        "is_use_lp_filter": False,
        "panel_time_sec": 5,
        "mosaic_scale": 1.5,
        "mosaic_angle": 45.0,
        "gain": 80,
    }

    # invalid scale
    seestar.schedule["state"] = "working"
    bad_scale = dict(base_params, mosaic_scale=2.5)
    assert seestar.start_framed_mosaic_item(bad_scale) is None
    assert started["count"] == 0

    # invalid angle
    bad_angle = dict(base_params, mosaic_angle=-91.0)
    assert seestar.start_framed_mosaic_item(bad_angle) is None
    assert started["count"] == 0

    # valid params start a thread
    assert seestar.start_framed_mosaic_item(base_params) is None
    assert started["count"] == 1
    assert seestar.is_cur_scheduler_item_working is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_seestar_device.py::test_start_framed_mosaic_item_paths -v`
Expected: FAIL with `AttributeError: 'Seestar' object has no attribute 'start_framed_mosaic_item'`

- [ ] **Step 3: Implement `start_framed_mosaic_item`**

In `device/seestar_device.py`, add immediately after the end of `start_mosaic_item` (the method currently ending at line 2314, right before the blank line preceding `# scheduler state example` comment at line 2596 — i.e. insert this as its own new method placed directly after `start_mosaic_item`):

```python
    def start_framed_mosaic_item(self, params: dict[str, Any]) -> None:
        self.is_cur_scheduler_item_working = False

        if self.schedule["state"] != "working":
            self.logger.info("Run Scheduler is stopping")
            self.schedule["state"] = "stopped"
            return

        target_name = params["target_name"]
        center_RA = params["ra"]
        center_Dec = params["dec"]
        is_j2000 = params["is_j2000"]
        is_use_LP_filter = params["is_use_lp_filter"]
        panel_time_sec = params["panel_time_sec"]
        mosaic_scale = params.get("mosaic_scale", 1.0)
        mosaic_angle = params.get("mosaic_angle", 0.0)
        gain = params["gain"]
        is_use_autofocus = params.get("is_use_autofocus", False)
        num_tries = params.get("num_tries", 1)
        retry_wait_s = params.get("retry_wait_s", 300)
        stack_type = params.get("stack_type", "DeepSky")

        if mosaic_scale < 1.0 or mosaic_scale > 2.0:
            self.logger.info(
                "Framed mosaic scale is invalid. Moving to next schedule item if any."
            )
            return
        if mosaic_angle < -90 or mosaic_angle > 90:
            self.logger.info(
                "Framed mosaic angle is invalid. Moving to next schedule item if any."
            )
            return

        if not isinstance(center_RA, str) and center_RA == -1 and center_Dec == -1:
            center_RA = self.ra
            center_Dec = self.dec
            is_j2000 = False

        parsed_coord = Util.parse_coordinate(is_j2000, center_RA, center_Dec)
        center_RA = parsed_coord.ra.hour
        center_Dec = parsed_coord.dec.deg

        self.logger.info("received framed mosaic parameters:")
        self.logger.info("  target        : " + target_name)
        self.logger.info("  RA            : %s", center_RA)
        self.logger.info("  Dec           : %s", center_Dec)
        self.logger.info("  scale         : %s", mosaic_scale)
        self.logger.info("  angle         : %s", mosaic_angle)
        self.logger.info("  panel time (s): %s", panel_time_sec)

        self.is_cur_scheduler_item_working = True
        self.framed_mosaic_thread = threading.Thread(
            target=lambda: self.framed_mosaic_thread_fn(
                target_name,
                center_RA,
                center_Dec,
                is_use_LP_filter,
                panel_time_sec,
                mosaic_scale,
                mosaic_angle,
                gain,
                is_use_autofocus,
                num_tries,
                retry_wait_s,
                stack_type,
            )
        )
        self.framed_mosaic_thread.name = f"FramedMosaicThread:{self.device_name}"
        self.framed_mosaic_thread.start()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_seestar_device.py::test_start_framed_mosaic_item_paths -v`
Expected: PASS

- [ ] **Step 5: Write failing test for `framed_mosaic_thread_fn` happy path**

Add to `tests/test_seestar_device.py` (near `test_mosaic_thread_fn_happy_path`):

```python
def test_framed_mosaic_thread_fn_happy_path(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    monkeypatch.setattr(seestar, "mosaic_goto_inner_worker", lambda *_a, **_k: True)
    monkeypatch.setattr(seestar, "set_target_name", lambda _n: {"ok": True})
    monkeypatch.setattr(seestar, "start_stack", lambda _p: True)
    monkeypatch.setattr(seestar, "stop_stack", lambda: {"ok": True})

    sent = []
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda p: sent.append(p) or {"ok": True},
    )
    seestar.schedule["state"] = "working"
    seestar.schedule["is_skip_requested"] = False
    seestar.schedule["current_item_id"] = "fm1"
    seestar.event_state["scheduler"] = {"cur_scheduler_item": {}}

    seestar.framed_mosaic_thread_fn(
        "T1", 1.0, 2.0, False, 5, 1.5, 45.0, 80, False, 1, 5, "DeepSky"
    )

    assert (
        seestar.event_state["scheduler"]["cur_scheduler_item"]["action"] == "complete"
    )
    assert seestar.is_cur_scheduler_item_working is False

    mosaic_sets = [
        p["params"]["mosaic"] for p in sent if "mosaic" in p.get("params", {})
    ]
    assert mosaic_sets[0] == {"scale": 1.5, "angle": 45.0, "star_map_angle": 0.0}
    assert mosaic_sets[-1] == {"scale": 1.0, "angle": 0.0, "star_map_angle": 0.0}


def test_framed_mosaic_thread_fn_skips_mosaic_setting_on_goto_failure(
    monkeypatch, seestar
):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    monkeypatch.setattr(seestar, "mosaic_goto_inner_worker", lambda *_a, **_k: False)

    sent = []
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda p: sent.append(p) or {"ok": True},
    )
    seestar.schedule["state"] = "working"
    seestar.schedule["is_skip_requested"] = False
    seestar.schedule["current_item_id"] = "fm2"
    seestar.event_state["scheduler"] = {"cur_scheduler_item": {}}

    seestar.framed_mosaic_thread_fn(
        "T1", 1.0, 2.0, False, 5, 1.5, 45.0, 80, False, 1, 1, "DeepSky"
    )

    assert seestar.is_cur_scheduler_item_working is False
    assert not any("mosaic" in p.get("params", {}) for p in sent)


def test_framed_mosaic_thread_fn_resets_mosaic_setting_on_stack_failure(
    monkeypatch, seestar
):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    monkeypatch.setattr("device.seestar_device.sleep", lambda _s: None)
    monkeypatch.setattr(seestar, "mosaic_goto_inner_worker", lambda *_a, **_k: True)
    monkeypatch.setattr(seestar, "set_target_name", lambda _n: {"ok": True})
    monkeypatch.setattr(seestar, "start_stack", lambda _p: False)

    sent = []
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda p: sent.append(p) or {"ok": True},
    )
    seestar.schedule["state"] = "working"
    seestar.schedule["is_skip_requested"] = False
    seestar.schedule["current_item_id"] = "fm3"
    seestar.event_state["scheduler"] = {"cur_scheduler_item": {}}

    seestar.framed_mosaic_thread_fn(
        "T1", 1.0, 2.0, False, 5, 1.5, 45.0, 80, False, 1, 1, "DeepSky"
    )

    mosaic_sets = [
        p["params"]["mosaic"] for p in sent if "mosaic" in p.get("params", {})
    ]
    assert mosaic_sets == [
        {"scale": 1.5, "angle": 45.0, "star_map_angle": 0.0},
        {"scale": 1.0, "angle": 0.0, "star_map_angle": 0.0},
    ]
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `pytest tests/test_seestar_device.py -k framed_mosaic_thread_fn -v`
Expected: FAIL with `AttributeError: 'Seestar' object has no attribute 'framed_mosaic_thread_fn'`

- [ ] **Step 7: Implement `framed_mosaic_thread_fn`**

In `device/seestar_device.py`, add directly after `start_framed_mosaic_item` (the method just added in Step 3):

```python
    def framed_mosaic_thread_fn(
        self,
        target_name,
        center_RA,
        center_Dec,
        is_use_LP_filter,
        panel_time_sec,
        mosaic_scale,
        mosaic_angle,
        gain,
        is_use_autofocus,
        num_tries,
        retry_wait_s,
        stack_type="DeepSky",
    ):
        try:
            total_time_s = round(panel_time_sec)
            item_state: SchedulerItemState = {
                "type": "framed_mosaic",
                "schedule_item_id": self.schedule["current_item_id"],
                "target_name": target_name,
                "action": "start",
                "item_total_time_s": total_time_s,
                "item_remaining_time_s": total_time_s,
            }
            self.update_scheduler_state_obj(item_state)

            self.send_message_param_sync(
                {"method": "set_setting", "params": {"stack_lenhance": is_use_LP_filter}}
            )

            result = False
            for try_index in range(num_tries):
                try_count = try_index + 1
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = (
                    f"attempt #{try_count} slewing to target centered at "
                    f"{center_RA:.2f}, {center_Dec:.2f}"
                )
                self.logger.info(f"Trying to reach target, attempt #{try_count}")
                result = self.mosaic_goto_inner_worker(
                    center_RA,
                    center_Dec,
                    target_name,
                    is_use_autofocus,
                    is_use_LP_filter,
                )
                if result:
                    break
                if try_count < num_tries:
                    for i in range(round(retry_wait_s / 5)):
                        if self.schedule["state"] != "working":
                            self.logger.info(
                                "Scheduler was requested to stop. Stopping at current framed mosaic."
                            )
                            self.schedule["state"] = "stopped"
                            return
                        waited_time = i * 5
                        msg = f"waited {waited_time}s of requested {retry_wait_s}s before retry GOTO target."
                        self.logger.info(msg)
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "action"
                        ] = msg
                        time.sleep(5)

            if not result:
                msg = f"Failed to goto target after {num_tries} tries."
                self.logger.warning(msg)
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
                return

            self.send_message_param_sync(
                {
                    "method": "set_setting",
                    "params": {
                        "mosaic": {
                            "scale": mosaic_scale,
                            "angle": mosaic_angle,
                            "star_map_angle": 0.0,
                        }
                    },
                }
            )
            try:
                msg = f"stacking the framed mosaic for {panel_time_sec} seconds"
                self.logger.info(msg)
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg

                self.set_target_name(target_name)

                if not self.start_stack(
                    {"gain": gain, "restart": True, "stack_type": stack_type}
                ):
                    msg = "Failed to start stacking."
                    self.logger.warning(msg)
                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "action"
                    ] = msg
                    return

                remaining_time_s = round(panel_time_sec)
                for i in range(round(panel_time_sec / 5)):
                    self.event_state["scheduler"]["cur_scheduler_item"][
                        "item_remaining_time_s"
                    ] = remaining_time_s
                    threading.current_thread().last_run = datetime.now()

                    if self.schedule["state"] != "working":
                        self.logger.info(
                            "Scheduler was requested to stop. Stopping at current framed mosaic."
                        )
                        self.stop_stack()
                        self.schedule["state"] = "stopped"
                        self.event_state["scheduler"]["cur_scheduler_item"][
                            "item_remaining_time_s"
                        ] = 0
                        return
                    if self.schedule["is_skip_requested"]:
                        self.logger.info(
                            "current framed mosaic stacking was requested to skip."
                        )
                        return

                    time.sleep(5)
                    remaining_time_s -= 5

                self.event_state["scheduler"]["cur_scheduler_item"][
                    "item_remaining_time_s"
                ] = 0
                self.stop_stack()
                msg = "Framed mosaic stacking operation finished " + target_name
                self.logger.info(msg)
                self.event_state["scheduler"]["cur_scheduler_item"]["action"] = msg
            finally:
                self.send_message_param_sync(
                    {
                        "method": "set_setting",
                        "params": {
                            "mosaic": {
                                "scale": 1.0,
                                "angle": 0.0,
                                "star_map_angle": 0.0,
                            }
                        },
                    }
                )

            self.event_state["scheduler"]["cur_scheduler_item"]["action"] = "complete"
        finally:
            self.is_cur_scheduler_item_working = False
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest tests/test_seestar_device.py -k framed_mosaic -v`
Expected: PASS (all `framed_mosaic` tests, including the Step 1 test)

- [ ] **Step 9: Write failing test for `start_framed_mosaic` shortcut and scheduler dispatch**

Add to `tests/test_seestar_device.py`:

```python
def test_start_framed_mosaic_rejects_when_scheduler_active(seestar):
    seestar.schedule["state"] = "working"
    out = seestar.start_framed_mosaic({"target_name": "T", "ra": 1, "dec": 2})
    assert out["code"] == -1


def test_start_framed_mosaic_creates_and_starts_schedule(monkeypatch, seestar):
    seestar.schedule["state"] = "stopped"
    calls = []
    monkeypatch.setattr(
        seestar, "create_schedule", lambda p: calls.append(("create_schedule", p))
    )
    monkeypatch.setattr(
        seestar,
        "add_schedule_item",
        lambda item: calls.append(("add_schedule_item", item)),
    )
    monkeypatch.setattr(
        seestar, "start_scheduler", lambda p: calls.append(("start_scheduler", p))
    )

    params = {"target_name": "T", "ra": 1, "dec": 2}
    seestar.start_framed_mosaic(params)

    assert calls[0] == ("create_schedule", params)
    assert calls[1] == (
        "add_schedule_item",
        {"action": "start_framed_mosaic", "params": params},
    )
    assert calls[2] == ("start_scheduler", params)


def test_scheduler_thread_fn_dispatches_start_framed_mosaic(monkeypatch, seestar):
    monkeypatch.setattr("device.seestar_device.time.sleep", lambda _s: None)
    calls = []
    monkeypatch.setattr(
        seestar,
        "start_framed_mosaic_item",
        lambda p: calls.append(p) or setattr(seestar, "is_cur_scheduler_item_working", False),
    )
    monkeypatch.setattr(seestar, "play_sound", lambda _v: None)

    seestar.schedule = {
        "state": "stopped",
        "list": [
            {
                "action": "start_framed_mosaic",
                "schedule_item_id": "fm1",
                "params": {"target_name": "T"},
            }
        ],
        "item_number": 1,
        "is_stacking": False,
        "is_stacking_paused": False,
    }
    seestar.scheduler_thread_fn()

    assert calls == [{"target_name": "T"}]
```

- [ ] **Step 10: Run the tests to verify they fail**

Run: `pytest tests/test_seestar_device.py -k "start_framed_mosaic_rejects or start_framed_mosaic_creates or scheduler_thread_fn_dispatches" -v`
Expected: FAIL with `AttributeError: 'Seestar' object has no attribute 'start_framed_mosaic'`

- [ ] **Step 11: Implement `start_framed_mosaic` and the scheduler dispatch branch**

In `device/seestar_device.py`, add immediately after the `start_spectra` method (which currently ends right before `def json_result` at line 2510):

```python
    # shortcut to start a new scheduler with only a framed mosaic request
    def start_framed_mosaic(self, params):
        if self.schedule["state"] != "stopped" and self.schedule["state"] != "complete":
            return self.json_result(
                "start_framed_mosaic",
                -1,
                "An existing scheduler is active. Returned with no action.",
            )
        self.create_schedule(params)
        schedule_item = {"action": "start_framed_mosaic", "params": params}
        self.add_schedule_item(schedule_item)
        return self.start_scheduler(params)
```

Then, in `scheduler_thread_fn`, immediately after the existing `elif action == "start_mosaic":` block (`device/seestar_device.py:2630-2634`), add:

```python
            elif action == "start_framed_mosaic":
                self.start_framed_mosaic_item(cur_schedule_item["params"])
                while self.is_cur_scheduler_item_working:
                    update_time()
                    time.sleep(2)
```

- [ ] **Step 12: Run the tests to verify they pass**

Run: `pytest tests/test_seestar_device.py -k "start_framed_mosaic or framed_mosaic_thread_fn or scheduler_thread_fn_dispatches" -v`
Expected: PASS

- [ ] **Step 13: Wire the Alpaca action dispatch in `device/telescope.py`**

In `device/telescope.py`, immediately after the existing block:

```python
            elif action_name == "start_mosaic":
                result = cur_dev.start_mosaic(params)
                resp.text = MethodResponse(req, value=result).json
```

(lines 218-220), add:

```python
            elif action_name == "start_framed_mosaic":
                result = cur_dev.start_framed_mosaic(params)
                resp.text = MethodResponse(req, value=result).json
```

There is no existing unit test file that exercises `device/telescope.py`'s action dispatch directly (it's covered indirectly through `tests/test_front_app_state.py` and `tests/integration/test_simulator_e2e.py`, both of which go through `front_app.do_action_device`). Task 6 covers this path end-to-end; no standalone test is added here.

- [ ] **Step 14: Run the full fast unit lane for this module**

Run: `pytest tests/test_seestar_device.py -q`
Expected: PASS, no regressions in existing mosaic/scheduler tests

- [ ] **Step 15: Commit**

```bash
git add device/seestar_device.py device/telescope.py tests/test_seestar_device.py
git commit -m "$(cat <<'EOF'
feat: add start_framed_mosaic scheduler action

Single enlarged/rotated frame capture mode, distinct from the
grid-panel Mosaic. Reuses the existing goto/retry logic, sends the
device's mosaic scale/angle setting before stacking, and resets it
in a finally block so it never leaks into later captures.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018EZTGjJtfW58UqkuTRGeUB
EOF
)"
```

---

## Task 2: Federation layer — fan-out and validation

**Files:**
- Modify: `device/seestar_federation.py`
- Test: `tests/test_seestar_federation.py`

**Interfaces:**
- Consumes: `Seestar_Federation.get_schedule`, `.add_schedule_item`, `.create_schedule`, `.start_scheduler` (all pre-existing), and `start_framed_mosaic` from Task 1 (called on individual `seestar_devices[key]` instances, not on the federation object itself, inside `start_scheduler`'s fan-out loop).
- Produces: `Seestar_Federation.start_framed_mosaic(params) -> dict`, extended `construct_schedule_item` and `start_scheduler` behavior for `action == "start_framed_mosaic"`.

- [ ] **Step 1: Write failing test for `construct_schedule_item` validation**

Add to `tests/test_seestar_federation.py` (near `test_construct_schedule_item_rejects_negative_ra_float`, e.g. after line 175):

```python
def test_construct_schedule_item_validates_framed_mosaic_coords():
    federation = Seestar_Federation(DummyLogger(), {})
    item = federation.construct_schedule_item(
        {
            "action": "start_framed_mosaic",
            "params": {"ra": 1.234567, "dec": 2.987654, "is_j2000": True},
        }
    )
    assert item["params"]["ra"] == 1.2346
    assert item["params"]["dec"] == 2.9877

    with pytest.raises(Exception):
        federation.construct_schedule_item(
            {
                "action": "start_framed_mosaic",
                "params": {"ra": -1.0, "dec": 2.0, "is_j2000": True},
            }
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_seestar_federation.py::test_construct_schedule_item_validates_framed_mosaic_coords -v`
Expected: FAIL — `item["params"]["ra"]` is `1.234567` unrounded (the mosaic-specific branch is skipped for this action name), and the negative-RA case does not raise.

- [ ] **Step 3: Extend the `construct_schedule_item` condition**

In `device/seestar_federation.py:209`, change:

```python
        if item["action"] == "start_mosaic":
```

to:

```python
        if item["action"] in ("start_mosaic", "start_framed_mosaic"):
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_seestar_federation.py::test_construct_schedule_item_validates_framed_mosaic_coords -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for `start_scheduler` fan-out**

Add to `tests/test_seestar_federation.py` (near `test_start_scheduler_by_time`):

```python
def test_start_scheduler_framed_mosaic_duplicate_default(monkeypatch):
    dev1 = FakeDevice(connected=True)
    dev2 = FakeDevice(connected=True)
    federation = Seestar_Federation(DummyLogger(), {1: dev1, 2: dev2})

    federation.schedule["list"] = collections.deque(
        [
            {
                "action": "start_framed_mosaic",
                "params": {
                    "ra": 1.2,
                    "dec": 3.4,
                    "is_j2000": True,
                    "panel_time_sec": 30,
                    "mosaic_scale": 1.5,
                    "mosaic_angle": 45.0,
                },
            }
        ]
    )
    monkeypatch.setattr("device.seestar_federation.random.shuffle", lambda x: None)
    out = federation.start_scheduler({})
    assert "available_device_list" in out

    added = [c[1] for c in dev1.called if c[0] == "add_schedule_item"]
    assert added[0]["params"]["federation_mode"] == "duplicate"
    assert added[0]["params"]["panel_time_sec"] == 30


def test_start_scheduler_framed_mosaic_by_time_splits_duration(monkeypatch):
    dev1 = FakeDevice(connected=True)
    dev2 = FakeDevice(connected=True)
    federation = Seestar_Federation(DummyLogger(), {1: dev1, 2: dev2})

    federation.schedule["list"] = collections.deque(
        [
            {
                "action": "start_framed_mosaic",
                "params": {
                    "ra": 1.2,
                    "dec": 3.4,
                    "is_j2000": True,
                    "federation_mode": "by_time",
                    "panel_time_sec": 30,
                    "mosaic_scale": 1.5,
                    "mosaic_angle": 45.0,
                },
            }
        ]
    )
    monkeypatch.setattr("device.seestar_federation.random.shuffle", lambda x: None)
    federation.start_scheduler({})

    added = [c[1] for c in dev1.called if c[0] == "add_schedule_item"]
    assert added[0]["params"]["panel_time_sec"] == 15


def test_start_scheduler_framed_mosaic_by_panels_falls_back_to_duplicate(monkeypatch):
    dev1 = FakeDevice(connected=True)
    federation = Seestar_Federation(DummyLogger(), {1: dev1})

    federation.schedule["list"] = collections.deque(
        [
            {
                "action": "start_framed_mosaic",
                "params": {
                    "ra": 1.2,
                    "dec": 3.4,
                    "is_j2000": True,
                    "federation_mode": "by_panels",
                    "panel_time_sec": 30,
                    "mosaic_scale": 1.5,
                    "mosaic_angle": 45.0,
                },
            }
        ]
    )
    monkeypatch.setattr("device.seestar_federation.random.shuffle", lambda x: None)
    federation.start_scheduler({})

    added = [c[1] for c in dev1.called if c[0] == "add_schedule_item"]
    assert added[0]["params"]["federation_mode"] == "duplicate"
    assert added[0]["params"]["panel_time_sec"] == 30


def test_start_scheduler_and_start_framed_mosaic_shortcut(monkeypatch):
    dev1 = FakeDevice(connected=True)
    federation = Seestar_Federation(DummyLogger(), {1: dev1})
    monkeypatch.setattr("device.seestar_federation.random.shuffle", lambda x: None)

    out = federation.start_framed_mosaic(
        {"target_name": "T", "ra": 1.2, "dec": 3.4, "is_j2000": True}
    )
    assert "device" in out


def test_start_framed_mosaic_no_devices_returns_error():
    federation = Seestar_Federation(DummyLogger(), {})
    out = federation.start_framed_mosaic(
        {"target_name": "T", "ra": 1.2, "dec": 3.4, "is_j2000": True}
    )
    assert "error" in out
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `pytest tests/test_seestar_federation.py -k framed_mosaic -v`
Expected: FAIL — the `duplicate`/`by_time` branches don't exist yet for `start_framed_mosaic` (params pass through unchanged, so `federation_mode` is absent and `panel_time_sec` is never split), and `Seestar_Federation.start_framed_mosaic` doesn't exist yet.

- [ ] **Step 7: Implement the `start_scheduler` branch**

In `device/seestar_federation.py`, the existing mosaic-specific block reads:

```python
            if schedule_item["action"] == "start_mosaic":
                # federation_mode : duplicate, by_panels or by_time
                if "federation_mode" not in cur_params or num_devices == 1:
                    cur_params["federation_mode"] = "duplicate"
                elif cur_params["federation_mode"] == "by_time":
                    cur_params["panel_time_sec"] = round(
                        cur_params["panel_time_sec"] / num_devices
                    )

                if cur_params["federation_mode"] == "by_panels":
                    section_dict = self.get_section_array_for_mosaic(
                        available_devices, cur_params
                    )
                    self.logger.info(f"federation mode split ->  {section_dict}")

                for key in available_devices:
                    cur_device = self.seestar_devices[key]
                    new_item = {}
                    new_item["action"] = "start_mosaic"
                    new_item["params"] = cur_params.copy()
                    if (
                        cur_params["federation_mode"] == "by_panels"
                        and key in section_dict
                    ):
                        new_item["params"]["selected_panels"] = section_dict[key]
                        self.logger.info(
                            f"federation mode by panels ->   key: {key}; panel: {new_item['params']['selected_panels']}"
                        )
                    cur_device.add_schedule_item(new_item)
            else:
```

Change the trailing `else:` to `elif schedule_item["action"] == "start_framed_mosaic":` and add its body, then restore a final `else:` for every other action. The full replacement block:

```python
            if schedule_item["action"] == "start_mosaic":
                # federation_mode : duplicate, by_panels or by_time
                if "federation_mode" not in cur_params or num_devices == 1:
                    cur_params["federation_mode"] = "duplicate"
                elif cur_params["federation_mode"] == "by_time":
                    cur_params["panel_time_sec"] = round(
                        cur_params["panel_time_sec"] / num_devices
                    )

                if cur_params["federation_mode"] == "by_panels":
                    section_dict = self.get_section_array_for_mosaic(
                        available_devices, cur_params
                    )
                    self.logger.info(f"federation mode split ->  {section_dict}")

                for key in available_devices:
                    cur_device = self.seestar_devices[key]
                    new_item = {}
                    new_item["action"] = "start_mosaic"
                    new_item["params"] = cur_params.copy()
                    if (
                        cur_params["federation_mode"] == "by_panels"
                        and key in section_dict
                    ):
                        new_item["params"]["selected_panels"] = section_dict[key]
                        self.logger.info(
                            f"federation mode by panels ->   key: {key}; panel: {new_item['params']['selected_panels']}"
                        )
                    cur_device.add_schedule_item(new_item)
            elif schedule_item["action"] == "start_framed_mosaic":
                # federation_mode : duplicate or by_time (no by_panels — there
                # are no discrete panels in a framed mosaic)
                if "federation_mode" not in cur_params or num_devices == 1:
                    cur_params["federation_mode"] = "duplicate"
                elif cur_params["federation_mode"] == "by_time":
                    cur_params["panel_time_sec"] = round(
                        cur_params["panel_time_sec"] / num_devices
                    )
                elif cur_params["federation_mode"] == "by_panels":
                    self.logger.warning(
                        "federation_mode 'by_panels' is not supported for "
                        "start_framed_mosaic; falling back to 'duplicate'."
                    )
                    cur_params["federation_mode"] = "duplicate"

                for key in available_devices:
                    cur_device = self.seestar_devices[key]
                    new_item = {
                        "action": "start_framed_mosaic",
                        "params": cur_params.copy(),
                    }
                    cur_device.add_schedule_item(new_item)
            else:
```

- [ ] **Step 8: Run the fan-out tests to verify they pass**

Run: `pytest tests/test_seestar_federation.py -k "start_scheduler_framed_mosaic" -v`
Expected: PASS

- [ ] **Step 9: Implement the `start_framed_mosaic` shortcut**

In `device/seestar_federation.py`, immediately after `start_mosaic` (which currently ends at line 373, right before `def start_scheduler`), add:

```python
    # shortcut to start a new scheduler with only a framed mosaic request
    def start_framed_mosaic(self, cur_params):
        cur_schedule = self.get_schedule(cur_params)
        num_devices = len(cur_schedule["available_device_list"])
        if num_devices < 1:
            return {
                "error": "Failed: No available devices found to execute a schedule."
            }

        self.schedule = {
            "list": [],
            "state": "stopped",
            "schedule_id": str(uuid.uuid4()),
        }
        schedule_item = {"action": "start_framed_mosaic", "params": cur_params}
        self.add_schedule_item(schedule_item)
        return self.start_scheduler(cur_params)
```

- [ ] **Step 10: Run the remaining new tests to verify they pass**

Run: `pytest tests/test_seestar_federation.py -k framed_mosaic -v`
Expected: PASS (all tests added in Steps 1 and 5)

- [ ] **Step 11: Wire the Alpaca action dispatch for the federation shortcut**

`device/telescope.py`'s `action.on_put` resolves `cur_dev = seestar_federation` when `devnum == 0` (see `device/telescope.py:163-164`) and then dispatches by the same `elif action_name == "start_framed_mosaic": result = cur_dev.start_framed_mosaic(params)` branch added in Task 1 Step 13 — no separate dispatch code is needed here since `cur_dev` is resolved generically before the action `elif` chain. Confirm this by re-reading `device/telescope.py:156-220` and verifying no federation-specific branch exists for `start_mosaic` either (there isn't one — the same pattern applies). No code change in this step; it's a verification-only step.

- [ ] **Step 12: Run the full federation test suite**

Run: `pytest tests/test_seestar_federation.py -q`
Expected: PASS, no regressions

- [ ] **Step 13: Commit**

```bash
git add device/seestar_federation.py tests/test_seestar_federation.py
git commit -m "$(cat <<'EOF'
feat: federate start_framed_mosaic (duplicate and by_time modes)

Extends construct_schedule_item's RA/Dec validation to cover
start_framed_mosaic items, and adds a start_scheduler fan-out branch
supporting duplicate (default) and by_time federation modes. by_panels
falls back to duplicate with a warning since there are no discrete
panels to split.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018EZTGjJtfW58UqkuTRGeUB
EOF
)"
```

---

## Task 3: Front-end — create page, schedule tab, nav, schedule list rendering

**Files:**
- Create: `front/templates/framed_mosaic.html`
- Create: `front/templates/framed_mosaic_create.html`
- Create: `front/templates/schedule_framed_mosaic.html`
- Modify: `front/app.py` (new `do_create_framed_mosaic` function, `FramedMosaicResource`, `ScheduleFramedMosaicResource` classes, route registrations)
- Modify: `front/templates/nav.html`
- Modify: `front/templates/partials/schedule_tab_header.html`
- Modify: `front/templates/partials/schedule_list.html`
- Test: `tests/test_front_app_state.py`

**Interfaces:**
- Consumes: `do_action_device`, `do_schedule_action_device`, `do_insert_schedule_item`, `check_ra_value`, `check_dec_value`, `hms_to_sec`, `_parse_stack_type`, `flash`, `get_context`, `render_schedule_tab`, `render_template` (all pre-existing in `front/app.py`); `start_framed_mosaic` action name from Task 1.
- Produces: `do_create_framed_mosaic(req, resp, schedule, telescope_id) -> (values, errors)`, `FramedMosaicResource`, `ScheduleFramedMosaicResource` — consumed by Task 4's Planning-card "Send to Schedule" flow (which posts to `/{telescope_id}/schedule/framed_mosaic`, the same route registered here).

- [ ] **Step 1: Write failing tests for `do_create_framed_mosaic`**

Add to `tests/test_front_app_state.py`, immediately after `_make_mosaic_form` (after line 1619):

```python
def _make_framed_mosaic_form(extra=None):
    base = {
        "targetName": "Test Target",
        "ra": "10.5",
        "dec": "-5.0",
        "mosaicScale": "1.5",
        "mosaicAngle": "45",
        "panelTime": "3600",
        "gain": "80",
        "num_tries": "1",
        "retry_wait_s": "300",
    }
    if extra:
        base.update(extra)
    return base
```

Then add, after `test_do_create_image_stack_type_included_in_start_mosaic_params` (after line 1709):

```python
def test_do_create_framed_mosaic_builds_expected_params(monkeypatch):
    captured = {}

    def fake_do_action_device(action, dev_num, params, is_schedule=False):
        captured["action"] = action
        captured["params"] = params
        return {"ErrorNumber": 0, "Value": {}}

    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)

    form = _make_framed_mosaic_form()
    req = _FormReq(form)
    resp = DummyResp()

    values, errors = front_app.do_create_framed_mosaic(req, resp, False, 1)

    assert not errors
    assert captured["action"] == "start_framed_mosaic"
    assert values["mosaic_scale"] == 1.5
    assert values["mosaic_angle"] == 45.0
    assert values["target_name"] == "Test Target"
    assert values["panel_time_sec"] == 3600
    assert values["gain"] == 80


def test_do_create_framed_mosaic_rejects_scale_out_of_range(monkeypatch):
    called = {"device": False}

    def fake_do_action_device(action, dev_num, params, is_schedule=False):
        called["device"] = True
        return {"ErrorNumber": 0, "Value": {}}

    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)

    form = _make_framed_mosaic_form({"mosaicScale": "3.0"})
    req = _FormReq(form)
    resp = DummyResp()

    values, errors = front_app.do_create_framed_mosaic(req, resp, False, 1)

    assert "mosaic_scale" in errors
    assert called["device"] is False


def test_do_create_framed_mosaic_rejects_angle_out_of_range(monkeypatch):
    called = {"device": False}

    def fake_do_action_device(action, dev_num, params, is_schedule=False):
        called["device"] = True
        return {"ErrorNumber": 0, "Value": {}}

    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)

    form = _make_framed_mosaic_form({"mosaicAngle": "120"})
    req = _FormReq(form)
    resp = DummyResp()

    values, errors = front_app.do_create_framed_mosaic(req, resp, False, 1)

    assert "mosaic_angle" in errors
    assert called["device"] is False


def test_do_create_framed_mosaic_invalid_ra_does_not_call_device(monkeypatch):
    called = {"device": False}

    def fake_do_action_device(action, dev_num, params, is_schedule=False):
        called["device"] = True
        return {"ErrorNumber": 0, "Value": {}}

    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)

    form = _make_framed_mosaic_form({"ra": "not_valid"})
    req = _FormReq(form)
    resp = DummyResp()

    values, errors = front_app.do_create_framed_mosaic(req, resp, False, 1)

    assert "ra" in errors
    assert called["device"] is False


def test_do_create_framed_mosaic_schedule_append(monkeypatch):
    captured = {}

    def fake_do_action_device(action, dev_num, params, is_schedule=False):
        captured["action"] = action
        captured["params"] = params
        return {"ErrorNumber": 0, "Value": {}}

    monkeypatch.setattr(front_app, "do_action_device", fake_do_action_device)

    form = _make_framed_mosaic_form({"action": "append"})
    req = _FormReq(form)
    resp = DummyResp()

    front_app.do_create_framed_mosaic(req, resp, True, 1)

    assert captured["action"] == "add_schedule_item"
    assert captured["params"]["action"] == "start_framed_mosaic"
    assert captured["params"]["params"]["mosaic_scale"] == 1.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_front_app_state.py -k do_create_framed_mosaic -v`
Expected: FAIL with `AttributeError: module 'front.app' has no attribute 'do_create_framed_mosaic'`

- [ ] **Step 3: Implement `do_create_framed_mosaic`**

In `front/app.py`, add immediately after `do_create_mosaic` (which ends at line 1422, right before `def do_goto_target`):

```python
def do_create_framed_mosaic(req, resp, schedule, telescope_id):
    form = req.media
    targetName = form["targetName"]
    ra = form["ra"]
    dec = form["dec"]
    useJ2000 = form.get("useJ2000") == "on"
    mosaicScale = form["mosaicScale"]
    mosaicAngle = form["mosaicAngle"]
    panelTime = hms_to_sec(form["panelTime"])
    useLpfilter = form.get("useLpFilter") == "on"
    useAutoFocus = form.get("useAutoFocus") == "on"
    gain = form["gain"]
    num_tries = form.get("num_tries")
    retry_wait_s = form.get("retry_wait_s")
    stack_type = _parse_stack_type(form)
    action = form.get("action", "")
    selected_items = form.get("selected_items", "")
    errors = {}
    values = {
        "target_name": targetName,
        "is_j2000": useJ2000,
        "ra": ra,
        "dec": dec,
        "mosaic_scale": float(mosaicScale),
        "mosaic_angle": float(mosaicAngle),
        "is_use_lp_filter": useLpfilter,
        "panel_time_sec": int(panelTime),
        "gain": int(gain),
        "is_use_autofocus": useAutoFocus,
        "num_tries": int(num_tries) if num_tries else 1,
        "retry_wait_s": int(retry_wait_s) if retry_wait_s else 300,
        "stack_type": stack_type,
    }

    if telescope_id == 0:
        fedMode = form.get("federation_mode")
        if fedMode:
            values["federation_mode"] = fedMode
        maxDev = form.get("max_devices")
        if maxDev:
            values["max_devices"] = maxDev

    if not check_ra_value(ra):
        flash(resp, "Invalid RA value")
        errors["ra"] = ra

    if not check_dec_value(dec):
        flash(resp, "Invalid DEC Value")
        errors["dec"] = dec

    if values["mosaic_scale"] < 1.0 or values["mosaic_scale"] > 2.0:
        flash(resp, "Mosaic scale must be between 1.0 and 2.0")
        errors["mosaic_scale"] = mosaicScale

    if values["mosaic_angle"] < -90.0 or values["mosaic_angle"] > 90.0:
        flash(resp, "Mosaic angle must be between -90 and 90")
        errors["mosaic_angle"] = mosaicAngle

    if errors:
        flash(resp, "ERROR detected in framed mosaic parameters")
        return values, errors

    if schedule:
        if action == "append":
            response = do_schedule_action_device(
                "start_framed_mosaic", values, telescope_id
            )
        else:
            response = do_insert_schedule_item(
                "start_framed_mosaic", values, selected_items, telescope_id
            )

        logger.info("POST scheduled request %s %s", values, response)
    else:
        response = do_action_device("start_framed_mosaic", telescope_id, values, False)
        logger.info("POST immediate request %s %s", values, response)

    return values, errors
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_front_app_state.py -k do_create_framed_mosaic -v`
Expected: PASS

- [ ] **Step 5: Create the create-page template**

Create `front/templates/framed_mosaic_create.html`:

```html
<script src="/public/fit_import.js"></script>
    <div class="card border-primary mb-3">
        <div class="card-body">
            <!-- First Row: Target Name and Search For -->
            <div class="mb-3 row">
                <div class="d-flex align-items-center">
                    <!-- Target Name -->
                    <div class="col me-3">
                        <label for="targetName" class="form-label">Target Name</label>
                        <input type="text" class="form-control" id="targetName" name="targetName"
                               aria-describedby="targetNameHelp" value="{{ values.target_name }}" required>
                        <div id="targetNameHelp" class="form-text">Enter a descriptive name for the target. (e.g. ...)</div>
                    </div>

                    <!-- Search For -->
                    <div class="col">
                        <label for="searchFor" class="form-label">Search For</label>
                        <div class="d-flex mb-0">
                            <select class="form-select" id="searchFor" name="searchFor" title="Select type of target">
                                <option value="DS" selected>Simbad Deepsky (Online)</option>
                                <option value="LS" >Local Deepsky DB</option>
                                <option value="PL">Planet</option>
                                <option value="MP">Minor Planet (Asteroid)</option>
                                <option value="CO">Comet</option>
                                <option value="VS"> AAVSO Varible Star (Online)</option>
                            </select>
                            <button type="button" id="getSimbad" class="btn btn-primary ms-2" title="Search for Coordinates" onclick="fetchCoordinates()">
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-search" viewBox="0 0 16 16">
                                    <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001q.044.06.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1 1 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0"/>
                                </svg>
                            </button>
                        </div>
                        <div id="searchForHelp" class="form-text mb-0">Choose the type of object you are searching for.</div>
                    </div>
                </div>
            </div>

            <!-- Second Row: RA and Dec -->
            <div class="mb-3 row">
                <div class="col">
                    <label for="ra" class="form-label">Right Ascension</label>
                    <input type="text" class="form-control" id="ra" name="ra" aria-describedby="raHelp"
                           value="{{ values.ra }}" required>
                    <div id="raHelp" class="form-text">Target center in decimal hours or hours/minutes/seconds (e.g. -1.2 or 6h32m32.5s)</div>
                    {% if errors.ra %}
                        <div id="raError" class="form-text" style="color:red;">The RA value you provided {{errors.ra}} is not valid.</div>
                    {% endif %}
                </div>
                <div class="col">
                    <label for="dec" class="form-label">Declination</label>
                    <input type="text" class="form-control" id="dec" name="dec" aria-describedby="decHelp"
                           value="{{ values.dec }}" required>
                    <div id="decHelp" class="form-text">Target center in decimal degrees or degrees/minutes/seconds (e.g. -1.2 or +6d32m32.5s)</div>
                    {% if errors.dec %}
                        <div id="decError" class="form-text" style="color:red;">The DEC value you provided {{errors.dec}} is not valid.</div>
                    {% endif %}
                </div>
            </div>

            <!-- Checkbox for J2000 -->
            <div class="mb-3">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="useJ2000" name="useJ2000"
                           {% if values.is_j2000 %}checked{% endif %}>
                    <label class="form-check-label" for="useJ2000">Use J2000?</label>
                </div>
            </div>

            <!-- Scale and Angle -->
            <div class="mb-3 row">
                <div class="col">
                    <label for="mosaicScale" class="form-label">Scale ({{ values.mosaic_scale or "1.0" }}x)</label>
                    <input type="range" class="form-range" id="mosaicScale" name="mosaicScale"
                           min="1.0" max="2.0" step="0.1" value="{{ values.mosaic_scale or 1.0 }}"
                           oninput="document.querySelector('label[for=mosaicScale]').textContent = 'Scale (' + this.value + 'x)'">
                    <div id="mosaicScaleHelp" class="form-text">Enlarges the frame relative to a single Seestar frame (1.0x-2.0x)</div>
                    {% if errors.mosaic_scale %}
                        <div id="mosaicScaleError" class="form-text" style="color:red;">The scale value you provided {{errors.mosaic_scale}} is not valid.</div>
                    {% endif %}
                </div>
                <div class="col">
                    <label for="mosaicAngle" class="form-label">Angle ({{ values.mosaic_angle or "0" }}&deg;)</label>
                    <input type="range" class="form-range" id="mosaicAngle" name="mosaicAngle"
                           min="-90" max="90" step="5" value="{{ values.mosaic_angle or 0 }}"
                           oninput="document.querySelector('label[for=mosaicAngle]').textContent = 'Angle (' + this.value + '°)'">
                    <div id="mosaicAngleHelp" class="form-text">Rotation of the frame, -90&deg; to +90&deg;</div>
                    {% if errors.mosaic_angle %}
                        <div id="mosaicAngleError" class="form-text" style="color:red;">The angle value you provided {{errors.mosaic_angle}} is not valid.</div>
                    {% endif %}
                </div>
            </div>

            <!-- Buttons for importing coordinates from other sources -->
            <div class="mb-3 row justify-content-center">
                <div class="col text-center">
                    <label for="getClipboard" class="form-label">&nbsp;</label><br>
                    <button type="button" id="getStallarium" class="btn btn-primary" title="Parse RA/Dec from clipboard" onclick="fetchClipboard()">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-clipboard-fill" viewBox="0 0 16 16">
                            <path fill-rule="evenodd" d="M10 1.5a.5.5 0 0 0-.5-.5h-3a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h3a.5.5 0 0 0 .5-.5zm-5 0A1.5 1.5 0 0 1 6.5 0h3A1.5 1.5 0 0 1 11 1.5v1A1.5 1.5 0 0 1 9.5 4h-3A1.5 1.5 0 0 1 5 2.5zm-2 0h1v1A2.5 2.5 0 0 0 6.5 5h3A2.5 2.5 0 0 0 12 2.5v-1h1a2 2 0 0 1 2 2V14a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V3.5a2 2 0 0 1 2-2"/>
                        </svg>
                    </button>
                    <div id="targetNameHelp" class="form-text">Paste RA/Dec from Clipboard</div>
                </div>
                <div class="col text-center">
                    <label for="getStallarium" class="form-label">&nbsp;</label><br>
                    <button type="button" id="getStallarium" class="btn btn-primary" title="Copy RA/Dec from Stellarium" onclick="fetchStellarium()">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-star-fill" viewBox="0 0 16 16">
                            <path d="M3.612 15.443c-.386.198-.824-.149-.746-.592l.83-4.73L.173 6.765c-.329-.314-.158-.888.283-.95l4.898-.696L7.538.792c.197-.39.73-.39.927 0l2.184 4.327 4.898.696c.441.062.612.636.282.95l-3.522 3.356.83 4.73c.078.443-.36.79-.746.592L8 13.187l-4.389 2.256z"/>
                        </svg>
                    </button>
                    <div id="targetNameHelp" class="form-text">Retrieve RA/Dec from Stellarium</div>
                </div>
                <div class="col text-center">
                    <label for="getHeaders" class="form-label">&nbsp;</label><br>
                    <button type="button" id="getHeaders" class="btn btn-primary" title="Retrieve info from previous FIT image">
                        <svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 16 16">
                            <path fill="currentColor" d="M.002 3a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-12a2 2 0 0 1-2-2zm1 9v1a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5l-3.777-1.947a.5.5 0 0 0-.577.093l-3.71 3.71l-2.66-1.772a.5.5 0 0 0-.63.062zm5-6.5a1.5 1.5 0 1 0-3 0a1.5 1.5 0 0 0 3 0"/>
                        </svg>
                    </button>
                    <input type="file" id="fileInput" style="display:none;" />
                    <div id="targetNameHelp" class="form-text">Retrieve from previous Seestar FIT File</div>
                </div>
            </div>

        </div>
    </div>

    {% if telescope["device_num"] == 0 %}
	<h5 class="card-title mb-2">Federation Settings</h5>
	<div class="card border-primary mb-3">
		<div class="card-body">
			<div class="form-group row g-2">
					<div class="col-md-3 col-sm-3">
						<label for="federation_mode" class="form-label">Mode</label>
						<select id="federation_mode" name="federation_mode" class="form-select app-select">
	            <option value="duplicate">Duplicate</option>
							<option value="by_time">Split By Time</option>
						</select>
					</div>
					<div class="col-md-3 col-sm-3">
						<label for="max_devices" class="form-label">Max Devices</label>
						<input type="number" id="max_devices" name="max_devices" min="1" value="1" required class="form-control">
					</div>
			</div>
		</div>
	</div>
    {% endif %}

    <h5 class="card-title mb-2">Exposure Settings</h5>
    <div class="card border-primary mb-3">
        <div class="card-body">

            <div class="mb-3">
                <label for="panelTime" class="form-label">Acquisition Time</label>
                <input type="text" class="form-control" id="panelTime" name="panelTime"
                       aria-describedby="panelTimeHelp" value="{{ values.panel_time_sec }}" required>
                <div id="panelTimeHelp" class="form-text">How much acquisition time (ex: 1h 30m or 5400).
                </div>
            </div>

            <div class="mb-3">
                {% if values.gain %}
                    <input type="text" class="form-control" id="gain" name="gain" aria-describedby="gainHelp"
                        value="{{ values.gain }}" required>
                {% else %}
                    <input type="text" class="form-control" id="gain" name="gain" aria-describedby="gainHelp"
                        value="{{ defgain }}" required>
                {% endif %}
                <div id="gainHelp" class="form-text">Gain. (ex: 80)</div>
            </div>

            <div class="mb-3">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="useLpFilter" name="useLpFilter">
                    <label class="form-check-label" for="useLpFilter">
                        Use Light Pollution Filter?
                    </label>
                </div>
            </div>
            <div class="mb-3">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="useAutoFocus" name="useAutoFocus">
                    <label class="form-check-label" for="useAutoFocus">
                        Use Auto Focus?
                    </label>
                </div>
            </div>

        </div>

    </div>

	<h5 class="card-title mb-2">Retry Settings</h5>
	<div class="card border-primary mb-3">
		<div class="card-body">
			<div class="row">
				<div class="col-sm-6 mb-3">
					<label for="num_tries" class="form-label">Number of Retries</label>
					<input type="text" id="num_tries" name="num_tries" class="form-control"
					       aria-describedby="num_triesHelp" value="{{ values.num_tries }}">
					<div id="num_triesHelp" class="form-text">Number of times to retry a failed GoTo (Default 1)</div>
				</div>
				<div class="col-sm-6 mb-3">
					<label for="retry_wait_s" class="form-label">Delay between retries in seconds</label>
					<input type="text" id="retry_wait_s" name="retry_wait_s" class="form-control"
					       aria-describedby="retry_wait_sHelp" value="{{ values.retry_wait_s }}">
					<div id="retry_wait_sHelp" class="form-text">Delay between retry attempts (Default 300)</div>
				</div>
			</div>
		</div>
	</div>
```

- [ ] **Step 6: Create the immediate-action page wrapper**

Create `front/templates/framed_mosaic.html`:

```html
{% extends 'base.html' %}

{% block header %}
    <div class="container mt-3">
		<p class="h1">{% block title %}Framed Mosaic{% endblock %}</p>
	</div>
{% endblock %}

{% block content %}

	{% if client_master and online %}
		<div class="mb-3 card card-body p-3">
			<div class="acordion" id="eventStatusAccordion">
				<div class="accordion-item">
					<h2 class="accordion-header" id="headingOne">
						<button class="accordion-button fs-5 fw-bold" type="button"
								data-bs-toggle="collapse"
								data-bs-target="#eventStatusDiv"
								aria-expanded="true"
								aria-controls="eventStatusDiv">
							Event status
						</button>
					</h2>
				</div>
			</div>
			<div id="eventStatusDiv" class="accordion-collapse collapse show"
				 aria-labelledby="headingOne"
				 data-bs-parent="#eventStatusAccordion">
				<div class="accordion-body no-htmx-fx" id="eventStatusContent"
					 hx-get="{{ root }}/eventstatus?action=framed_mosaic"
					 hx-trigger="load, every 1s"
					 hx-swap="innerHTML">
					Loading event status...
				</div>
			</div>
		</div>
		<div class="container mt-3">
			<p>Creates and immediately runs a framed mosaic (a single enlarged/rotated frame). For scheduling, see <a href="/schedule">scheduler</a>.</p>
      <form id="scheduleForm" action="{{ root }}/framed_mosaic" method="post" enctype="application/x-www-form-urlencoded">
			  {% include 'framed_mosaic_create.html' with context %}
        <button type="submit" class="btn btn-primary">Submit</button>
      </form>
		</div>
  {% elif not client_master %}
    <div class="container mt-3">
      <p>You are currently in guest mode. You can release this in the Advanced->Guest Mode of the SeeStar app.</p>
      <p>See the <a href="https://github.com/smart-underworld/seestar_alp/wiki/Guest-Mode">Guest Mode</a> wiki page for details</p>
    </div>
  {% else %}
		<div class="container mt-3">
			<p>You are currently in offline mode.</p>
		</div>
	{% endif %}

	<footer class="bg-body-tertiary text-center mt-3">
		Version: {{ version }}
	</footer>
{% endblock %}

{% block scripts %}
	<script src="/public/command.js"></script>
{% endblock %}
```

- [ ] **Step 7: Create the schedule-tab wrapper**

Create `front/templates/schedule_framed_mosaic.html`:

```html
{% extends 'schedule_base.html' %}

{% block schedule_tab_content %}
    {% with action=root ~ "/schedule/framed_mosaic" %}
        {% include 'framed_mosaic_create.html' with context %}
    {% endwith %}
{% endblock %}
```

- [ ] **Step 8: Add the `FramedMosaicResource` and `ScheduleFramedMosaicResource` classes**

In `front/app.py`, add immediately after `MosaicResource` (which ends at line 2412, right before `class ScheduleResource`):

```python
class FramedMosaicResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.framed_mosaic(req, resp, {}, {}, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        values, errors = do_create_framed_mosaic(req, resp, False, telescope_id)
        self.framed_mosaic(req, resp, values, errors, telescope_id)

    @staticmethod
    def framed_mosaic(req, resp, values, errors, telescope_id):
        context = get_context(telescope_id, req)
        if not context["online"]:
            telescope_id = 0

        current = do_action_device("get_schedule", telescope_id, {})
        if current is None:
            return
        state = current["Value"]["state"]
        schedule = current["Value"]

        render_template(
            req,
            resp,
            "framed_mosaic.html",
            state=state,
            schedule=schedule,
            values=values,
            errors=errors,
            action=f"/{telescope_id}/framed_mosaic",
            **context,
        )
```

Add `ScheduleFramedMosaicResource` immediately after `ScheduleMosaicResource` (which ends at line 2624, right before `class ScheduleStartupResource`):

```python
class ScheduleFramedMosaicResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req,
            resp,
            telescope_id,
            "schedule_framed_mosaic.html",
            "framed_mosaic",
            {},
            {},
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        values, errors = do_create_framed_mosaic(req, resp, True, telescope_id)
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req,
            resp,
            telescope_id,
            "schedule_framed_mosaic.html",
            "framed_mosaic",
            values,
            errors,
        )
```

- [ ] **Step 9: Register the routes**

In `front/app.py`, add `app.add_route("/framed_mosaic", FramedMosaicResource())` immediately after line 5364 (`app.add_route("/mosaic", MosaicResource())`).

Add `app.add_route("/schedule/framed_mosaic", ScheduleFramedMosaicResource())` immediately after line 5378 (`app.add_route("/schedule/mosaic", ScheduleMosaicResource())`).

Add `app.add_route("/{telescope_id:int}/framed_mosaic", FramedMosaicResource())` immediately after line 5425 (`app.add_route("/{telescope_id:int}/mosaic", MosaicResource())`).

Add `app.add_route("/{telescope_id:int}/schedule/framed_mosaic", ScheduleFramedMosaicResource())` immediately after line 5443 (`app.add_route("/{telescope_id:int}/schedule/mosaic", ScheduleMosaicResource())`).

- [ ] **Step 10: Write a failing render-contract test for the routes**

Add to `tests/test_front_app_state.py`:

```python
def test_framed_mosaic_resource_renders_form(monkeypatch):
    monkeypatch.setattr(
        front_app,
        "get_context",
        lambda telescope_id, req: {
            "online": True,
            "client_master": True,
            "root": "",
            "defgain": 80,
            "telescope": {"device_num": telescope_id},
        },
    )
    monkeypatch.setattr(
        front_app,
        "do_action_device",
        lambda action, dev_num, params, is_schedule=False: {
            "Value": {"state": "stopped"}
        },
    )

    app = falcon.App()
    app.add_route("/{telescope_id:int}/framed_mosaic", front_app.FramedMosaicResource())
    client = testing.TestClient(app)

    resp = client.simulate_get("/1/framed_mosaic")

    assert resp.status_code == 200
    assert "Framed Mosaic" in resp.text
    assert 'id="mosaicScale"' in resp.text
    assert 'id="mosaicAngle"' in resp.text
```

`tests/test_front_app_state.py` already has `import falcon` (line 3) and `from falcon import testing` (line 6) at module level — reuse them directly, no new imports needed for this test.

- [ ] **Step 11: Run the test to verify it fails**

Run: `pytest tests/test_front_app_state.py::test_framed_mosaic_resource_renders_form -v`
Expected: FAIL with `AttributeError: module 'front.app' has no attribute 'FramedMosaicResource'`

- [ ] **Step 12: Run the test to verify it passes**

(No additional implementation needed beyond Steps 5-9.)

Run: `pytest tests/test_front_app_state.py::test_framed_mosaic_resource_renders_form -v`
Expected: PASS

- [ ] **Step 13: Add the nav entry**

In `front/templates/nav.html`, immediately after line 39 (`<a class="dropdown-item" href="{{ root }}/mosaic">Mosaic</a>` and its closing `</li>`), add:

```html
						<li>
							<a class="dropdown-item" href="{{ root }}/framed_mosaic">Framed Mosaic</a>
						</li>
```

- [ ] **Step 14: Add the schedule tab header entry**

In `front/templates/partials/schedule_tab_header.html`, immediately after the Mosaic tab block (lines 68-75), add:

```html
    <li class="nav-item" role="presentation">
        <a href="{{ root }}/schedule/framed_mosaic"
          class="nav-link {% if tab == "framed_mosaic" %}active{% endif %}"
          type="button"
          aria-controls="framed_mosaic"
          aria-selected="false">Framed Mosaic
        </a>
    </li>
```

- [ ] **Step 15: Add the schedule-list render case**

In `front/templates/partials/schedule_list.html`, the mosaic branch starts at `{% if item["action"] == 'start_mosaic' %}` (line 7) and its matching `{% else %}` (non-collapsible actions) is at line 210. Change line 210 from:

```
      {% else %}
```

to:

```
      {% elif item["action"] == 'start_framed_mosaic' %}
        {% if current_item['schedule_item_id'] == item['schedule_item_id'] %}
          <div class="accordion-item">
            <div class="accordion-header" id="heading{{ item['schedule_item_id'] }}">
              <button
                class="btn btn-link fw-bold text-white text-decoration-none text-start w-100"
                type="button"
                data-bs-toggle="collapse"
                data-bs-target="#collapse{{ item['schedule_item_id'] }}"
                aria-expanded="{% if open_accordion_id == 'collapse' ~ item['schedule_item_id'] %}true{% else %}false{% endif %}"
                aria-controls="collapse{{ item['schedule_item_id'] }}">
                <div class="row w-100">
                  <div class="col-2 align-self-start text-break">{{ item["params"]["target_name"] }}</div>
                  <div class="col-2 align-self-start">
                    <p class="mt-0 mb-0">RA: {{ item["params"]["ra"] }}</p>
                    <p class="mt-0 mb-0">DEC: {{ item["params"]["dec"] }}</p>
                  </div>
                  <div class="col align-self-start">{{ item["params"]["mosaic_scale"] }}x</div>
                  <div class="col align-self-start">{{ item["params"]["mosaic_angle"] }}&deg;</div>
                  <div class="col align-self-start">{{ seconds_to_hms(item["params"]["panel_time_sec"]) }}</div>
                  <div class="col align-self-start">{{ item["params"]["gain"] }}</div>
                </div>
              </button>
            </div>
            <div id="collapse{{ item['schedule_item_id'] }}"
                 class="accordion-collapse collapse{% if open_accordion_id == 'collapse' ~ item['schedule_item_id'] %} show{% endif %}"
                 aria-labelledby="heading{{ item['schedule_item_id'] }}" data-bs-parent="#scheduleAccordion">
              <div class="accordion-body">
                {% if schedule["is_stacking"] %}
                  {% if current_item is defined and current_item['item_remaining_time_s'] is defined %}
                    {% set item_time = current_item['item_total_time_s'] %}
                    {% set item_remain = current_item['item_remaining_time_s'] %}
                    {% set item_elapse = item_time - item_remain %}
                    <p>Time Elapsed: {{ seconds_to_hms(item_elapse) }}</p>
                    <p>Time Remaining: {{ seconds_to_hms(item_remain) }}</p>
                  {% endif %}
                {% endif %}
                {% if item["params"]['federation_mode'] %}
                  <p>Federation Mode: {{ item["params"]['federation_mode'] }}</p>
                  <p>Max Devices: {{ item["params"]['max_devices'] }}</p>
                {% endif %}
                <p>Retries: {{ item["params"]['num_tries'] }}</p>
                <p>Retry Wait: {{ item["params"]['retry_wait_s'] }}s</p>
              </div>
            </div>
          </div>
        {% else %}
          <div class="row w-100">
            <div class="col-2 align-self-start text-break">{{ item["params"]["target_name"] }}</div>
            <div class="col-2 align-self-start">
              <p class="mt-0 mb-0">RA: {{ item["params"]["ra"] }}</p>
              <p class="mt-0 mb-0">DEC: {{ item["params"]["dec"] }}</p>
            </div>
            <div class="col align-self-start">{{ item["params"]["mosaic_scale"] }}x</div>
            <div class="col align-self-start">{{ item["params"]["mosaic_angle"] }}&deg;</div>
            <div class="col align-self-start">{{ seconds_to_hms(item["params"]["panel_time_sec"]) }}</div>
            <div class="col align-self-start">{{ item["params"]["gain"] }}</div>
          </div>
        {% endif %}
      {% else %}
```

(This inserts a new `{% elif %}` branch between the existing `start_mosaic` block and the pre-existing `{% else %}` fallback that handles `wait_until`/`wait_for`/etc. — the fallback `{% else %}` and everything after it, starting from the original line 210 onward, is otherwise unchanged.)

- [ ] **Step 16: Write a failing render-contract test for the schedule-list case**

`front/app.py:1794` defines a module-level `env = Environment(loader=FileSystemLoader(template_dir))`, with `env.globals["seconds_to_hms"] = seconds_to_hms` registered at `front/app.py:1803` — so `seconds_to_hms` is already available inside any template rendered through `env` without passing it explicitly. Jinja's default (non-strict) `Undefined` means `current_item['schedule_item_id']` on `current_item={}` renders as empty/falsy rather than raising, so the "not current item" (static) branch is what gets exercised when `current_item={}`.

Add to `tests/test_front_app_state.py`:

```python
def test_schedule_list_renders_framed_mosaic_item():
    template = front_app.env.get_template("partials/schedule_list.html")
    html = template.render(
        schedule={
            "list": [
                {
                    "schedule_item_id": "fm1",
                    "action": "start_framed_mosaic",
                    "params": {
                        "target_name": "M31",
                        "ra": 0.7,
                        "dec": 41.27,
                        "mosaic_scale": 1.5,
                        "mosaic_angle": 45.0,
                        "panel_time_sec": 3600,
                        "gain": 80,
                        "num_tries": 1,
                        "retry_wait_s": 300,
                    },
                }
            ],
            "is_stacking": False,
        },
        current_item={},
    )

    assert "M31" in html
    assert "1.5x" in html
    assert "45.0&deg;" in html
```

- [ ] **Step 17: Run the test to verify it fails, then passes**

Run: `pytest tests/test_front_app_state.py::test_schedule_list_renders_framed_mosaic_item -v`
Expected: FAIL before Step 15 is applied (no `start_framed_mosaic` branch exists yet, so the item falls into the generic `{% else %}` fallback and `1.5x`/`45.0&deg;` never appear in the output). PASS after Step 15.

- [ ] **Step 18: Run the full front app state test suite**

Run: `pytest tests/test_front_app_state.py -q`
Expected: PASS, no regressions

- [ ] **Step 19: Commit**

```bash
git add front/app.py front/templates/framed_mosaic.html front/templates/framed_mosaic_create.html front/templates/schedule_framed_mosaic.html front/templates/nav.html front/templates/partials/schedule_tab_header.html front/templates/partials/schedule_list.html tests/test_front_app_state.py
git commit -m "$(cat <<'EOF'
feat: add Framed Mosaic create page, schedule tab, and nav entry

New immediate-action page and schedule tab mirroring the existing
Image/Mosaic pattern, with scale/angle sliders matching the real
Seestar app's control ranges. Schedule list gets a render case
showing scale/angle instead of panel grid info.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018EZTGjJtfW58UqkuTRGeUB
EOF
)"
```

---

## Task 4: Front-end — Planning page card

**Files:**
- Create: `front/templates/partials/framed_mosaic_planning.html`
- Create: `front/public/framed_mosaic.js`
- Modify: `front/planning.json.example`
- Modify: `front/app.py` (`get_planning_cards` merge fix)
- Test: `tests/test_front_app_state.py`

**Interfaces:**
- Consumes: `front_app.get_planning_cards()` (existing), the `/{telescope_id}/schedule/framed_mosaic` route from Task 3, the Aladin Lite JS global (`A`, loaded the same way `partials/astro_mosaic.html` loads it).
- Produces: an always-visible "Framed Mosaic" Planning card; a general-purpose "merge missing cards" behavior in `get_planning_cards()` that any future card addition also benefits from.

- [ ] **Step 1: Write a failing test for the `get_planning_cards` merge behavior**

Add to `tests/test_front_app_state.py`, immediately after `test_update_planning_card_state_invalidates_cache` (after line 313):

```python
def test_get_planning_cards_merges_missing_cards_from_example(monkeypatch, tmp_path):
    planning_file = tmp_path / "planning.json"
    planning_file.write_text(
        json.dumps(
            [
                {
                    "card_name": "twilight_times",
                    "card_friendly_name": "Twilight Times",
                    "template": "partials/twilight_times.html",
                    "planning_page_enable": False,
                    "planning_page_collapsed": True,
                }
            ]
        )
    )
    example_file = tmp_path / "planning.json.example"
    example_file.write_text(
        json.dumps(
            [
                {
                    "card_name": "twilight_times",
                    "card_friendly_name": "Twilight Times",
                    "template": "partials/twilight_times.html",
                    "planning_page_enable": True,
                    "planning_page_collapsed": False,
                },
                {
                    "card_name": "framed_mosaic",
                    "card_friendly_name": "Framed Mosaic",
                    "template": "partials/framed_mosaic_planning.html",
                    "planning_page_enable": True,
                    "planning_page_collapsed": False,
                },
            ]
        )
    )

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    front_app._planning_cards_cache = None
    front_app._planning_cards_cache_mtime = None

    cards = front_app.get_planning_cards()

    names = {card["card_name"] for card in cards}
    assert names == {"twilight_times", "framed_mosaic"}

    # the user's existing settings for a card they already have must be preserved
    twilight = next(c for c in cards if c["card_name"] == "twilight_times")
    assert twilight["planning_page_enable"] is False
    assert twilight["planning_page_collapsed"] is True

    # the merge is persisted so a second load doesn't need the cache
    front_app._planning_cards_cache = None
    front_app._planning_cards_cache_mtime = None
    persisted = json.loads(planning_file.read_text())
    assert {c["card_name"] for c in persisted} == {"twilight_times", "framed_mosaic"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_front_app_state.py::test_get_planning_cards_merges_missing_cards_from_example -v`
Expected: FAIL — `cards` only contains `twilight_times`, `framed_mosaic` is missing.

- [ ] **Step 3: Run the two pre-existing planning-card tests to confirm the baseline**

Run: `pytest tests/test_front_app_state.py -k "get_planning_cards_uses_file_mtime_cache or update_planning_card_state_invalidates_cache" -v`
Expected: PASS (these must keep passing after Step 4 — they exercise `tmp_path` directories with no `planning.json.example` file present, which the merge step must handle by skipping the merge, not raising)

- [ ] **Step 4: Implement the merge in `get_planning_cards`**

In `front/app.py`, replace the current `get_planning_cards` function body (`front/app.py:448-485`) with:

```python
def get_planning_cards():
    global _planning_cards_cache, _planning_cards_cache_mtime
    if getattr(
        sys, "frozen", False
    ):  # frozen means that we are running from a bundled app
        card_state_file_location = os.path.abspath(
            os.path.join(sys._MEIPASS, "planning.json")
        )
        card_state_example_file_location = os.path.abspath(
            os.path.join(sys._MEIPASS, "planning.json.example")
        )
    else:
        card_state_file_location = os.path.join(
            os.path.dirname(__file__), "planning.json"
        )
        card_state_example_file_location = os.path.join(
            os.path.dirname(__file__), "planning.json.example"
        )

    # Check to see if there is cached planning.json, if not create it.
    if not os.path.isfile(card_state_file_location):
        shutil.copyfile(card_state_example_file_location, card_state_file_location)

    file_mtime = os.path.getmtime(card_state_file_location)
    with _planning_cards_cache_lock:
        if (
            _planning_cards_cache is not None
            and _planning_cards_cache_mtime == file_mtime
        ):
            return json.loads(json.dumps(_planning_cards_cache))
        with open(card_state_file_location, "r") as card_state_file:
            state_data = json.load(card_state_file)

        # Merge in any cards present in the shipped example that the user's
        # local planning.json (created once, on first run) doesn't have yet —
        # otherwise a card added after a user's first run is never seen.
        if os.path.isfile(card_state_example_file_location):
            with open(card_state_example_file_location, "r") as example_file:
                example_cards = json.load(example_file)
            existing_names = {card["card_name"] for card in state_data}
            missing_cards = [
                card
                for card in example_cards
                if card["card_name"] not in existing_names
            ]
            if missing_cards:
                state_data.extend(missing_cards)
                with open(card_state_file_location, "w") as card_state_file:
                    json.dump(state_data, card_state_file, indent=4)
                file_mtime = os.path.getmtime(card_state_file_location)

        _planning_cards_cache = state_data
        _planning_cards_cache_mtime = file_mtime
        return json.loads(json.dumps(state_data))
```

- [ ] **Step 5: Run all three planning-card tests to verify they pass**

Run: `pytest tests/test_front_app_state.py -k "planning_cards" -v`
Expected: PASS (Step 1's new test, plus the two pre-existing ones from Step 3, all green)

- [ ] **Step 6: Add the `framed_mosaic` card entry**

In `front/planning.json.example`, add a new entry to the JSON array (after the existing `astro_mosaic` entry, before `twilight_times`):

```json
    {
        "card_name": "framed_mosaic",
        "card_friendly_name": "Framed Mosaic",
        "template": "partials/framed_mosaic_planning.html",
        "planning_page_enable": true,
        "planning_page_collapsed": false
    },
```

- [ ] **Step 7: Create the Planning-card partial**

Create `front/templates/partials/framed_mosaic_planning.html`:

```html
{% block html_header %}
    <link href="https://aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.css" rel="stylesheet">
    <script type="text/javascript" src="https://code.jquery.com/jquery-1.12.1.min.js" charset="utf-8"></script>
    <script type="text/javascript" src="https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js" charset="utf-8"></script>
    <script type="text/javascript" src="/public/framed_mosaic.js"></script>
{% endblock %}
<div>
    <fieldset class="border rounded-3 mb-3 pb-3">
        <legend class="float-none w-auto">
           <h5>Controls</h5>
        </legend>
        <div class="planning-controls-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.6rem 0.75rem; align-items: end; padding: 0 0.75rem;">
            <div>
                <label for="framed_mosaic_search_text" class="form-label">Search</label>
                <input type="text" class="form-control" id="framed_mosaic_search_text" value="M31">
            </div>
            <div>
                <label for="framed_mosaic_search_button" class="form-label">Find Target</label>
                <button type="button" id="framed_mosaic_search_button" class="btn btn-primary" title="Search for object." onclick="update_framed_mosaic()">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-search" viewBox="0 0 16 16">
                        <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001q.044.06.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1 1 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0"/>
                    </svg>
                </button>
            </div>
            <div>
                <label for="framed_mosaic_scale" class="form-label">Scale (<span id="framed_mosaic_scale_display">1.0</span>x)</label>
                <input type="range" class="form-range" id="framed_mosaic_scale" min="1.0" max="2.0" step="0.1" value="1.0" oninput="update_framed_mosaic()">
            </div>
            <div>
                <label for="framed_mosaic_angle" class="form-label">Angle (<span id="framed_mosaic_angle_display">0</span>&deg;)</label>
                <input type="range" class="form-range" id="framed_mosaic_angle" min="-90" max="90" step="5" value="0" oninput="update_framed_mosaic()">
            </div>
            <div>
                <label for="open_framed_mosaic_schedule_modal_btn" class="form-label">Send to Schedule</label>
                <button type="button" id="open_framed_mosaic_schedule_modal_btn" class="btn btn-primary" title="Send to Schedule">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-journal-arrow-up" viewBox="0 0 16 16">
                        <path fill-rule="evenodd" d="M8 11a.5.5 0 0 0 .5-.5V6.707l1.146 1.147a.5.5 0 0 0 .708-.708l-2-2a.5.5 0 0 0-.708 0l-2 2a.5.5 0 1 0 .708.708L7.5 6.707V10.5a.5.5 0 0 0 .5.5"/>
                        <path d="M3 0h10a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2v-1h1v1a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v1H1V2a2 2 0 0 1 2-2"/>
                        <path d="M1 5v-.5a.5.5 0 0 1 1 0V5h.5a.5.5 0 0 1 0 1h-2a.5.5 0 0 1 0-1zm0 3v-.5a.5.5 0 0 1 1 0V8h.5a.5.5 0 0 1 0 1h-2a.5.5 0 0 1 0-1zm0 3v-.5a.5.5 0 0 1 1 0v.5h.5a.5.5 0 0 1 0 1h-2a.5.5 0 0 1 0-1z"/>
                    </svg>
                </button>
            </div>
        </div>
    </fieldset>
</div>
<div id="framed-mosaic-aladin-div" style="height:500px; width: 100%;"></div>

<dialog id="framed_mosaic_schedule_modal">
    <form method="post" action="/{{ telescope['device_num'] }}/schedule/framed_mosaic">
        <div class="card border-primary mb-3">
            <div class="card-body">
                <h5 class="card-title">Target</h5>
                <div class="mb-3 row">
                    <div class="col">
                        <label for="fm_targetName" class="form-label">Target Name</label>
                        <input type="text" class="form-control" id="fm_targetName" name="targetName" required>
                    </div>
                </div>
                <div class="mb-3 row">
                    <div class="col">
                        <label for="fm_ra" class="form-label">Right Ascension</label>
                        <input type="text" class="form-control" id="fm_ra" name="ra" required>
                    </div>
                    <div class="col">
                        <label for="fm_dec" class="form-label">Declination</label>
                        <input type="text" class="form-control" id="fm_dec" name="dec" required>
                    </div>
                </div>
                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="fm_useJ2000" name="useJ2000" checked>
                        <label class="form-check-label" for="fm_useJ2000">Use J2000?</label>
                    </div>
                </div>
                <input type="hidden" id="fm_mosaicScale" name="mosaicScale" value="1.0">
                <input type="hidden" id="fm_mosaicAngle" name="mosaicAngle" value="0">
            </div>
        </div>
        <div class="card border-primary mb-3">
            <div class="card-body">
                <h5 class="card-title">Exposure</h5>
                <div class="mb-3">
                    <label for="fm_panelTime" class="form-label">Acquisition Time</label>
                    <input type="text" class="form-control" id="fm_panelTime" name="panelTime" value="1h" required>
                </div>
                <div class="mb-3">
                    <input type="text" class="form-control" id="fm_gain" name="gain" value="80" required>
                </div>
            </div>
        </div>
        <button type="submit" class="btn btn-primary">Submit</button>
        <button type="button" class="btn btn-primary float-end" id="close_framed_mosaic_schedule_modal_btn">Close</button>
    </form>
</dialog>
```

- [ ] **Step 8: Create the overlay/slider JS**

Create `front/public/framed_mosaic.js`:

```javascript
// Live preview of a Framed Mosaic (scale + rotation) over an Aladin sky view.
// Base FOV matches the Seestar S50's telephoto camera (43.8 x 77.4 arcmin);
// this is a visual planning aid only — it does not compute device commands.
(function () {
  const BASE_FOV_X_DEG = 43.8 / 60.0;
  const BASE_FOV_Y_DEG = 77.4 / 60.0;

  let aladin = null;
  let overlay = null;
  let currentRaDeg = 10.68;
  let currentDecDeg = 41.27;

  function rectangleCorners(raDeg, decDeg, scale, angleDeg) {
    const halfW = (BASE_FOV_X_DEG * scale) / 2.0;
    const halfH = (BASE_FOV_Y_DEG * scale) / 2.0;
    const angleRad = (angleDeg * Math.PI) / 180.0;
    const cosA = Math.cos(angleRad);
    const sinA = Math.sin(angleRad);
    const cosDec = Math.cos((decDeg * Math.PI) / 180.0) || 1e-6;

    const localCorners = [
      [-halfW, -halfH],
      [halfW, -halfH],
      [halfW, halfH],
      [-halfW, halfH],
    ];

    return localCorners.map(([x, y]) => {
      const rotatedX = x * cosA - y * sinA;
      const rotatedY = x * sinA + y * cosA;
      return [raDeg + rotatedX / cosDec, decDeg + rotatedY];
    });
  }

  window.update_framed_mosaic = function update_framed_mosaic() {
    const scale = parseFloat(document.getElementById("framed_mosaic_scale").value);
    const angle = parseFloat(document.getElementById("framed_mosaic_angle").value);
    document.getElementById("framed_mosaic_scale_display").textContent = scale.toFixed(1);
    document.getElementById("framed_mosaic_angle_display").textContent = angle;

    if (!aladin) return;

    overlay.removeAll();
    const corners = rectangleCorners(currentRaDeg, currentDecDeg, scale, angle);
    overlay.add(A.polygon(corners, { color: "#f59e0b", lineWidth: 2 }));

    document.getElementById("fm_mosaicScale").value = scale.toFixed(1);
    document.getElementById("fm_mosaicAngle").value = angle;
  };

  window.init_framed_mosaic_aladin = function init_framed_mosaic_aladin() {
    aladin = A.aladin("#framed-mosaic-aladin-div", {
      survey: "P/DSS2/color",
      fov: 2,
      target: document.getElementById("framed_mosaic_search_text").value,
    });
    overlay = A.graphicOverlay({ color: "#f59e0b", lineWidth: 2 });
    aladin.addOverlay(overlay);
    update_framed_mosaic();
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof A !== "undefined" && A.init) {
      A.init.then(init_framed_mosaic_aladin);
    }

    const searchBtn = document.getElementById("framed_mosaic_search_button");
    if (searchBtn) {
      searchBtn.addEventListener("click", function () {
        if (!aladin) return;
        aladin.gotoObject(
          document.getElementById("framed_mosaic_search_text").value,
          function () {
            const [ra, dec] = aladin.getRaDec();
            currentRaDeg = ra;
            currentDecDeg = dec;
            update_framed_mosaic();
          }
        );
      });
    }

    const openBtn = document.getElementById("open_framed_mosaic_schedule_modal_btn");
    const modal = document.getElementById("framed_mosaic_schedule_modal");
    const closeBtn = document.getElementById("close_framed_mosaic_schedule_modal_btn");
    if (openBtn && modal) {
      openBtn.addEventListener("click", function () {
        document.getElementById("fm_targetName").value =
          document.getElementById("framed_mosaic_search_text").value;
        if (aladin) {
          const [ra, dec] = aladin.getRaDec();
          document.getElementById("fm_ra").value = ra;
          document.getElementById("fm_dec").value = dec;
        }
        modal.showModal();
      });
    }
    if (closeBtn && modal) {
      closeBtn.addEventListener("click", function () {
        modal.close();
      });
    }
  });
})();
```

- [ ] **Step 9: Write a failing render-contract test for the Planning page card**

`tests/test_front_app_state.py` does not currently import `os` or `shutil` at module level (only `json`, `falcon`, and `from falcon import testing` — confirmed by inspection). Add `import os` and `import shutil` to its import block at the top of the file, then add:

```python
def test_planning_page_includes_framed_mosaic_card(monkeypatch, tmp_path):
    example_source = os.path.join(
        os.path.dirname(front_app.__file__), "planning.json.example"
    )
    shutil.copyfile(example_source, tmp_path / "planning.json")

    monkeypatch.setattr(front_app.os.path, "dirname", lambda _: str(tmp_path))
    front_app._planning_cards_cache = None
    front_app._planning_cards_cache_mtime = None

    cards = front_app.get_planning_cards()
    names = {card["card_name"] for card in cards}
    assert "framed_mosaic" in names

    framed_mosaic_card = next(c for c in cards if c["card_name"] == "framed_mosaic")
    assert framed_mosaic_card["template"] == "partials/framed_mosaic_planning.html"
```

- [ ] **Step 10: Run the test to verify it fails, then passes**

Run: `pytest tests/test_front_app_state.py::test_planning_page_includes_framed_mosaic_card -v`
Expected: FAIL before Step 6 is applied (`planning.json.example` has no `framed_mosaic` entry), PASS after.

- [ ] **Step 11: Run the full front app state test suite**

Run: `pytest tests/test_front_app_state.py -q`
Expected: PASS, no regressions

- [ ] **Step 12: Commit**

```bash
git add front/app.py front/planning.json.example front/templates/partials/framed_mosaic_planning.html front/public/framed_mosaic.js tests/test_front_app_state.py
git commit -m "$(cat <<'EOF'
feat: add Framed Mosaic Planning card

Separate Planning card (own Aladin instance, own search box) with a
live rotated/scaled rectangle preview and a Send to Schedule modal.
get_planning_cards() now merges any card present in
planning.json.example but missing from the user's local
planning.json, so this (and any future) card addition reaches
existing installs after upgrading, not just fresh installs.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018EZTGjJtfW58UqkuTRGeUB
EOF
)"
```

---

## Task 5: Bruno API collection examples

**Files:**
- Create: `bruno/Seestar Alpaca API/Schedule - Mosaic/action-start_framed_mosaic.bru`
- Create: `bruno/Seestar Alpaca API/Schedule - Mosaic/action-add_schedule_item_framed_mosaic.bru`

**Interfaces:**
- Consumes: the `start_framed_mosaic` action from Task 1, the `add_schedule_item` action (pre-existing) with `action: "start_framed_mosaic"`.
- Produces: manual-verification examples for use against real hardware or the emulator — no automated test (bruno collections aren't pytest-covered in this repo; verified by inspection and, per spec §9/§11, prioritized for a near-term manual hardware/emulator check).

- [ ] **Step 1: Find the next available `seq` number**

Run: `ls "bruno/Seestar Alpaca API/Schedule - Mosaic/" | wc -l` and `grep -h "seq:" "bruno/Seestar Alpaca API/Schedule - Mosaic/"*.bru | sort -t: -k2 -n | tail -3` to find the highest existing `seq` value, then use the next two integers for the new files.

- [ ] **Step 2: Create `action-start_framed_mosaic.bru`**

Create `bruno/Seestar Alpaca API/Schedule - Mosaic/action-start_framed_mosaic.bru` (replace `<N>` with the next sequence number found in Step 1):

```
meta {
  name: action-start_framed_mosaic
  type: http
  seq: <N>
}

put {
  url: {{base_url}}/api/v1/telescope/{{dev_num}}/action
  body: formUrlEncoded
  auth: none
}

headers {
  Content-Type: application/x-www-form-urlencoded
  Accept: application/json
}

body:form-urlencoded {
  Action: start_framed_mosaic
  Parameters: {"target_name":"M31", "ra":-1.0, "dec":-1.0, "is_j2000": false, "is_use_lp_filter":false, "panel_time_sec":3600, "mosaic_scale": 1.5, "mosaic_angle": 45.0, "gain": 80}
  ClientID: 1
  ClientTransactionID: 999
}
```

- [ ] **Step 3: Create `action-add_schedule_item_framed_mosaic.bru`**

Create `bruno/Seestar Alpaca API/Schedule - Mosaic/action-add_schedule_item_framed_mosaic.bru` (use `<N+1>`):

```
meta {
  name: action-add_schedule_item_framed_mosaic
  type: http
  seq: <N+1>
}

put {
  url: {{base_url}}/api/v1/telescope/{{dev_num}}/action
  body: formUrlEncoded
  auth: none
}

headers {
  Content-Type: application/x-www-form-urlencoded
  Accept: application/json
}

body:form-urlencoded {
  Action: add_schedule_item
  Parameters: {"action":"start_framed_mosaic", "params":{"target_name":"M31", "ra":-1.0, "dec":-1.0, "is_j2000": false, "is_use_lp_filter":false, "is_use_autofocus":true, "panel_time_sec":3600, "mosaic_scale": 1.5, "mosaic_angle": 45.0, "gain": 80}}
  ClientID: 1
  ClientTransactionID: 999
}
```

- [ ] **Step 4: Commit**

```bash
git add "bruno/Seestar Alpaca API/Schedule - Mosaic/action-start_framed_mosaic.bru" "bruno/Seestar Alpaca API/Schedule - Mosaic/action-add_schedule_item_framed_mosaic.bru"
git commit -m "$(cat <<'EOF'
docs: add bruno examples for start_framed_mosaic

Manual-verification examples for the new action, for use against
real hardware or the emulator per the design spec's rollout notes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018EZTGjJtfW58UqkuTRGeUB
EOF
)"
```

---

## Task 6: Integration tests — simulator round trip

**Files:**
- Modify: `tests/integration/test_simulator_e2e.py`

**Interfaces:**
- Consumes: the `simulator_server` and `front_sim_bridge` pytest fixtures (pre-existing in this file's conftest — confirm their exact fixture names/behavior by re-reading `tests/integration/test_simulator_e2e.py`'s existing tests before writing new ones, e.g. `test_28_simulator_handles_set_stack_type` for `simulator_server`'s TCP helpers and `test_29_stack_type_in_image_form_reaches_device_layer` for `front_sim_bridge`'s falcon `TestClient` pattern), `_send_tcp_command(host, port, message)` (pre-existing helper), `front_app.do_action_device` (for monkeypatch-capture style tests).
- Produces: end-to-end coverage proving the full stack — HTTP form → `front/app.py` → Alpaca action → `device/seestar_device.py` scheduler → TCP `set_setting`/`get_setting` against the real simulator process.

- [ ] **Step 1: Write a failing test for the simulator's `mosaic` setting round trip**

Add to `tests/integration/test_simulator_e2e.py`, near `test_28_simulator_handles_set_stack_type`:

```python
def test_38_simulator_mosaic_setting_round_trips(simulator_server):
    """set_setting with a mosaic sub-object updates get_setting's response."""
    host = simulator_server["host"]
    port = simulator_server["tcp_port"]

    _send_tcp_command(
        host,
        port,
        {
            "id": 3100,
            "method": "set_setting",
            "params": {"mosaic": {"scale": 1.5, "angle": 45.0, "star_map_angle": 0.0}},
        },
    )
    state = _send_tcp_command(host, port, {"id": 3101, "method": "get_setting"})
    assert state["result"]["mosaic"]["scale"] == 1.5
    assert state["result"]["mosaic"]["angle"] == 45.0

    _send_tcp_command(
        host,
        port,
        {
            "id": 3102,
            "method": "set_setting",
            "params": {"mosaic": {"scale": 1.0, "angle": 0.0, "star_map_angle": 0.0}},
        },
    )
    reset_state = _send_tcp_command(host, port, {"id": 3103, "method": "get_setting"})
    assert reset_state["result"]["mosaic"]["scale"] == 1.0
    assert reset_state["result"]["mosaic"]["angle"] == 0.0
```

- [ ] **Step 2: Run the test to verify it passes immediately**

Run: `pytest tests/integration/test_simulator_e2e.py::test_38_simulator_mosaic_setting_round_trips -v -m integration`
Expected: PASS — the simulator's `set_setting`/`get_setting` handlers already generically support arbitrary keys including `mosaic` (verified in Task 0 research: `simulator/src/seestar_simulator.py`'s `set_setting` does `self.state["setting"].update(data.get("params", {}))`). This test exists to lock in that behavior as a regression guard for this feature, not to drive new simulator code.

- [ ] **Step 3: Write a failing end-to-end test through the HTTP form**

Add to `tests/integration/test_simulator_e2e.py`, near `test_29_stack_type_in_image_form_reaches_device_layer`:

```python
def test_39_framed_mosaic_form_reaches_device_layer(monkeypatch, front_sim_bridge):
    """A Framed Mosaic form POST reaches the device layer as start_framed_mosaic."""
    captured = {}
    original_action = front_app.do_action_device

    def capturing_do_action(action, dev_num, params, is_schedule=False):
        if action == "start_framed_mosaic":
            captured["params"] = params
            return {"ErrorNumber": 0, "Value": {}}
        return original_action(action, dev_num, params, is_schedule)

    monkeypatch.setattr(front_app, "do_action_device", capturing_do_action)

    app = falcon.App()
    app.add_route(
        "/{telescope_id:int}/framed_mosaic", front_app.FramedMosaicResource()
    )
    client = testing.TestClient(app)

    form = {
        "targetName": "M31",
        "ra": "0.7",
        "dec": "41.27",
        "mosaicScale": "1.5",
        "mosaicAngle": "45",
        "panelTime": "3600",
        "gain": "80",
        "num_tries": "1",
        "retry_wait_s": "300",
    }
    resp = client.simulate_post("/1/framed_mosaic", json=form)
    assert resp.status_code == 200
    assert captured["params"]["mosaic_scale"] == 1.5
    assert captured["params"]["mosaic_angle"] == 45.0
    assert captured["params"]["target_name"] == "M31"
```

- [ ] **Step 4: Run the test to verify it fails, then passes**

Run: `pytest tests/integration/test_simulator_e2e.py::test_39_framed_mosaic_form_reaches_device_layer -v -m integration`
Expected: FAIL before Task 3 is complete (`FramedMosaicResource` doesn't exist yet — if Task 3 is already done by the time this task runs, it should PASS immediately). If it fails for any other reason, fix forward rather than skip.

- [ ] **Step 5: Write a failing federated `by_time` end-to-end test using the real two-device fixture**

`tests/integration/test_simulator_e2e.py` already has a `two_device_federation` fixture (built on the `two_simulator_servers` fixture) that wires two real `Seestar` device instances to two real simulator processes, plus a real `Seestar_Federation`, and exposes an `alpaca_action(dev_num, action, parameters)` helper that PUTs to the actual Alpaca action endpoint (see `test_24_two_devices_respond_to_method_sync` for the exact usage pattern, e.g. `alpaca_action(devnum, "method_sync", {...})` returning a Falcon test response with `.json["ErrorNumber"]`/`.json["Value"]`). This is a stronger test than a hand-rolled `FakeDevice` — it proves the real `device/telescope.py` dispatch branch from Task 1 Step 13 and the real `Seestar_Federation.start_framed_mosaic`/`start_scheduler` from Task 2 all wire together correctly, not just that the federation class's internal logic is correct in isolation (already covered by Task 2's unit tests).

Add, near `test_27_federation_home_lists_both_devices`:

```python
def test_40_framed_mosaic_federation_by_time_reaches_both_devices(
    two_device_federation,
):
    """A federated by_time start_framed_mosaic splits panel_time_sec across both devices."""
    alpaca_action = two_device_federation["alpaca_action"]
    dev1 = two_device_federation["dev1"]
    dev2 = two_device_federation["dev2"]

    resp = alpaca_action(
        0,
        "start_framed_mosaic",
        {
            "target_name": "M31",
            "ra": 0.7,
            "dec": 41.27,
            "is_j2000": True,
            "is_use_lp_filter": False,
            "federation_mode": "by_time",
            "panel_time_sec": 20,
            "mosaic_scale": 1.5,
            "mosaic_angle": 45.0,
            "gain": 80,
        },
    )
    assert resp.status_code == 200
    assert resp.json["ErrorNumber"] == 0

    deadline = time.time() + 10.0
    while time.time() < deadline:
        if dev1.schedule["list"] and dev2.schedule["list"]:
            break
        time.sleep(0.1)
    else:
        pytest.fail("Timed out waiting for the framed mosaic item to reach both devices")

    assert dev1.schedule["list"][0]["action"] == "start_framed_mosaic"
    assert dev1.schedule["list"][0]["params"]["panel_time_sec"] == 10
    assert dev2.schedule["list"][0]["action"] == "start_framed_mosaic"
    assert dev2.schedule["list"][0]["params"]["panel_time_sec"] == 10

    # Don't wait out the full stacking duration on both real devices — stop
    # both schedulers now that the routing/splitting behavior is confirmed.
    dev1.stop_scheduler({})
    dev2.stop_scheduler({})
```

- [ ] **Step 6: Run the test to verify it fails, then passes**

Run: `pytest tests/integration/test_simulator_e2e.py::test_40_framed_mosaic_federation_by_time_reaches_both_devices -v -m integration`
Expected: FAIL before Tasks 1 and 2 are complete (`start_framed_mosaic` unknown to `device/telescope.py`'s action dispatch), PASS after both are done.

- [ ] **Step 7: Run the full integration suite**

Run: `pytest -m integration tests/integration -q`
Expected: PASS, no regressions, runtime still under ~5 minutes per `AGENTS.md`

- [ ] **Step 8: Run the full fast unit lane and ruff one more time across the whole change**

Run:
```bash
pytest -m "not integration" -q
ruff check .
```
Expected: both PASS

- [ ] **Step 9: Commit**

```bash
git add tests/integration/test_simulator_e2e.py
git commit -m "$(cat <<'EOF'
test: add simulator integration coverage for start_framed_mosaic

Covers the mosaic setting round trip against the real simulator
process, the HTTP form -> device-layer path, and federated by_time
duration splitting.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018EZTGjJtfW58UqkuTRGeUB
EOF
)"
```

---

## Self-Review Notes

**Spec coverage:**
- §5 (device layer, params, methods, dispatch) → Task 1.
- §6 (federation) → Task 2.
- §7 (create page/routes/nav/schedule-list) → Task 3.
- §8 (Planning card, §8.1 upgrade path) → Task 4.
- §10 (bruno examples) → Task 5.
- §10 (device unit tests, front render-contract tests, simulator integration tests) → distributed across Tasks 1-4 (unit/render) and Task 6 (integration).
- §9 risks are documentation/process items (hardware verification, firmware version coverage) rather than code changes — not separately tasked, consistent with the spec treating them as rollout follow-ups, not blockers.
- §11 (rollout, no experimental gate) → reflected by the absence of any `Config.experimental` check anywhere in Tasks 1-4 (verified: no task references it).

**Type/name consistency check:** `start_framed_mosaic` / `start_framed_mosaic_item` / `framed_mosaic_thread_fn` / `mosaic_scale` / `mosaic_angle` / `FramedMosaicResource` / `ScheduleFramedMosaicResource` / `do_create_framed_mosaic` are used identically across Tasks 1, 2, 3, and 6 — no aliasing drift.
