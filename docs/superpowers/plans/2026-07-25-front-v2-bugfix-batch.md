# front_v2 tester bug-fix batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five front_v2 bugs (catalog search, Live View exposure/gain, dark-frame-on-every-exposure-set, Live View zoom letterbox, Manual Exposure override) and add Live View lunar/solar goto shortcuts, reported by a beta tester on Discord; add emulator-CI regression coverage for the two firmware-facing bugs.

**Architecture:** Each bug is fixed in its existing file(s) with no new abstractions — this is a bug-fix batch, not a redesign. The one new piece of plumbing is a device-layer accessor (`get_last_gain`) that exposes already-tracked event telemetry through the existing action-dispatch pattern, because gain currently has no HTTP-reachable read path at all.

**Tech Stack:** Python (FastAPI backend, `device/` device-control layer), Svelte 4 + TypeScript (front_v2 UI), pytest (unit + emulator system tests), Vitest + @testing-library/svelte (frontend component tests).

## Global Constraints

- Every fix must be traceable to a specific finding in `docs/superpowers/specs/2026-07-25-front-v2-bugfix-batch-design.md` — no speculative changes beyond what that spec covers.
- Non-goals from the spec are out of scope for this plan: Photo/Timelapse/Video capture modes, a general search-subsystem refactor, and fully confirming the Manual Exposure *write* path end-to-end against real hardware.
- Follow existing code conventions in each file (see individual tasks for the exact patterns being matched).
- Commit after every task.

---

### Task 1: Fix catalog search returning the wrong object

**Files:**
- Modify: `front_v2/api/router_goto.py:47-69` (`_search_local`)
- Test: `tests/test_router_goto.py`

**Interfaces:**
- Produces: `_search_local(query: str) -> dict | None` — same signature and return shape as today (`{"ra": ..., "dec": ..., "objectName": ...}` or `None`), used unchanged by `search_object` (`router_goto.py:300-303`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_router_goto.py`:

```python
import sqlite3

from front_v2.api import router_goto as _rg


@pytest.fixture
def alp_dat(tmp_path, monkeypatch):
    """A tiny objects DB reproducing the real M8/M82 collision: both an
    exact-token collision (M8 vs M82) and a comma-joined multi-identifier
    row, so the ranking logic is exercised for both shapes."""
    db_path = tmp_path / "alp.dat"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE objects (ra varchar(12), dec varchar(12), "
        "constellation varchar(5), objectType varchar(15), "
        "commonNames varchar(30), identifiers varchar(30))"
    )
    con.executemany(
        "INSERT INTO objects (ra, dec, commonNames, identifiers) VALUES (?, ?, ?, ?)",
        [
            ("09h55m52.73s", "+69d40m45.8s", "Cigar Galaxy", "M82"),
            ("18h03m37.00s", "-24d23m12.0s", "Lagoon Nebula", "M8,NGC6523"),
            ("20h12m06.55s", "+38d21m17.8s", "Crescent Nebula", "NGC6888"),
        ],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(_rg, "_ALP_DAT", db_path)
    return db_path


def test_search_local_m8_returns_exact_match_not_m82(alp_dat):
    result = _rg._search_local("M8")
    assert result is not None
    assert result["objectName"] == "Lagoon Nebula"


def test_search_local_handles_comma_joined_identifiers(alp_dat):
    result = _rg._search_local("NGC6523")
    assert result is not None
    assert result["objectName"] == "Lagoon Nebula"


def test_search_local_ignores_spacing_and_case(alp_dat):
    result = _rg._search_local("ngc 6888")
    assert result is not None
    assert result["objectName"] == "Crescent Nebula"


def test_search_local_falls_back_to_prefix_match(alp_dat):
    # No exact/normalized token matches "M82X" -- prefix match on "M82" should win.
    result = _rg._search_local("M82X")
    assert result is None  # no prefix match either -- confirms we don't over-match
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_router_goto.py -k "search_local" -v`
Expected: `test_search_local_m8_returns_exact_match_not_m82` FAILS with
`assert 'Cigar Galaxy' == 'Lagoon Nebula'` (reproduces the reported bug);
`test_search_local_handles_comma_joined_identifiers` and
`test_search_local_ignores_spacing_and_case` FAIL because today's code
does no normalization.

- [ ] **Step 3: Replace `_search_local` with a ranked, normalized lookup**

Replace `front_v2/api/router_goto.py:47-69`:

```python
def _normalize_token(s: str) -> str:
    return "".join(s.split()).upper()


def _search_local(query: str) -> dict | None:
    """Search the local object catalogue. Returns first match as {ra, dec, objectName} or None.

    Tiered lookup (exact -> prefix -> substring) over every row's identifier
    and common-name tokens, normalized (whitespace stripped, uppercased) on
    both sides. A plain `LIKE '%q%' LIMIT 1` with no ORDER BY returns
    SQLite's arbitrary scan order, which resolves "M8" to "M82" before ever
    reaching the actual M8 row -- this fixes that by only returning a match
    from the highest-priority tier that has one. The catalog is small
    (~15k rows, ~1.6MB) and this runs once per human-triggered search, so a
    full-table scan in Python is simpler and more correct here than trying
    to express comma-joined multi-identifier exact-matching in SQL.
    """
    if not _ALP_DAT.exists():
        return None
    norm = _normalize_token(query)
    if not norm:
        return None
    try:
        con = sqlite3.connect(str(_ALP_DAT))
        cur = con.cursor()
        cur.execute("SELECT ra, dec, commonNames, identifiers FROM objects")
        rows = cur.fetchall()
        con.close()
    except Exception as exc:
        logger.warning("local object search failed: %s", exc)
        return None

    def _tokens(row) -> list[str]:
        raw = f"{row[2] or ''},{row[3] or ''}"
        return [_normalize_token(t) for t in raw.split(",") if t.strip()]

    prefix_match = None
    substring_match = None
    for row in rows:
        tokens = _tokens(row)
        if norm in tokens:
            return _row_to_result(row, query)
        if prefix_match is None and any(t.startswith(norm) for t in tokens):
            prefix_match = row
        if substring_match is None and any(norm in t for t in tokens):
            substring_match = row

    match = prefix_match or substring_match
    return _row_to_result(match, query) if match else None


def _row_to_result(row, query: str) -> dict:
    name = row[2] or row[3] or query
    if isinstance(name, str) and "," in name:
        name = name.split(",")[0].strip()
    return {"ra": row[0], "dec": row[1], "objectName": name}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_router_goto.py -k "search_local" -v`
Expected: all 4 PASS.

- [ ] **Step 5: Run the full router_goto test file to confirm no regression**

Run: `pytest tests/test_router_goto.py -v`
Expected: all PASS (the pre-existing goto/cancel/force-stop tests are unaffected).

- [ ] **Step 6: Commit**

```bash
git add front_v2/api/router_goto.py tests/test_router_goto.py
git commit -m "fix: rank local catalog search matches (exact > prefix > substring)

Unranked LIKE '%q%' LIMIT 1 with no ORDER BY returned SQLite's arbitrary
scan order -- 'M8' resolved to 'M82' (Cigar Galaxy) because that row's
identifier collided as a substring match ahead of the real M8 row.
Normalizes spacing/case and handles comma-joined multi-identifier rows
(e.g. 'M8,NGC6523') along the way."
```

---

### Task 2: Fix Live View exposure to read/write the real nested `exp_ms` shape

**Files:**
- Modify: `front_v2/api/router_live.py:91-104` (`get_exposure`, `set_exposure`)
- Test: `tests/test_router_live.py` (new file)

**Interfaces:**
- Consumes: `method_sync(method: str, dev_num: int, **kwargs) -> Any` and `do_action(action: str, dev_num: int, parameters: dict) -> dict | None` from `front_v2.device_client` (unchanged, already imported at `router_live.py:7`).
- Produces: `GET /devices/{dev_num}/live/exposure` still returns `{"exp_ms": int, "gain": int}` (gain unchanged in this task — see Task 8); `POST /devices/{dev_num}/live/exposure` still accepts `{"exp_ms": int}` and returns `{"status": "ok", "exp_ms": int}`. No API contract change, only which device field is read/written.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_router_live.py`:

```python
"""
Unit tests for front_v2 live-view router (/api/v1/devices/{n}/live/*).

Regression coverage for the exposure key-mismatch bug: the real firmware's
get_setting response nests exposure as exp_ms: {stack_l, continuous}
(confirmed from a real device's alpyca.log capture), but the code read/wrote
a flat exp_ms_continuous key that never exists -- so get_exposure always
fell back to its hardcoded default (10000ms) and set_exposure's writes were
silently dropped by the firmware.
"""

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from front_v2.api import router_live  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(router_live, "check_api_state", lambda dev_num: True)
    app = FastAPI()
    app.include_router(router_live.router)
    return TestClient(app)


def _fake_method_sync(stage: str, exp_ms: dict):
    def _inner(method, dev_num, **kwargs):
        if method == "get_setting":
            return {"exp_ms": exp_ms, "gain": 999}  # gain intentionally wrong shape here
        if method == "get_view_state":
            return {"View": {"stage": stage}}
        return None

    return _inner


def test_get_exposure_returns_stack_l_while_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("Stack", {"stack_l": 20000, "continuous": 2000}),
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["exp_ms"] == 20000


def test_get_exposure_returns_continuous_when_not_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("", {"stack_l": 20000, "continuous": 2000}),
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["exp_ms"] == 2000


def test_set_exposure_writes_stack_l_while_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live, "method_sync", _fake_method_sync("Stack", {})
    )
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(router_live, "do_action", fake_do_action)

    r = client.post("/api/v1/devices/1/live/exposure", json={"exp_ms": 20000})
    assert r.status_code == 200
    assert captured["action"] == "set_setting"
    assert captured["params"] == {"exp_ms": {"stack_l": 20000}}


def test_set_exposure_writes_continuous_when_not_stacking(client, monkeypatch):
    monkeypatch.setattr(
        router_live, "method_sync", _fake_method_sync("Idle", {})
    )
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(router_live, "do_action", fake_do_action)

    r = client.post("/api/v1/devices/1/live/exposure", json={"exp_ms": 2000})
    assert r.status_code == 200
    assert captured["params"] == {"exp_ms": {"continuous": 2000}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_router_live.py -v`
Expected: all 4 FAIL — `get_exposure` returns the hardcoded `10000` default
instead of `20000`/`2000`, and `set_exposure`'s captured params show
`{"exp_ms_continuous": N}` instead of the nested shape.

- [ ] **Step 3: Fix `get_exposure`/`set_exposure`**

Replace `front_v2/api/router_live.py:91-104`:

```python
def _current_stage(dev_num: int) -> str:
    view_state = method_sync("get_view_state", dev_num) or {}
    return view_state.get("View", {}).get("stage", "")


@router.get("/devices/{dev_num}/live/exposure")
def get_exposure(dev_num: int):
    _require_connected(dev_num)
    result = method_sync("get_setting", dev_num) or {}
    exp_ms = result.get("exp_ms") or {}
    key = "stack_l" if _current_stage(dev_num) == "Stack" else "continuous"
    exp = exp_ms.get(key, 10000)
    gain = result.get("gain", 80)
    return {"exp_ms": exp, "gain": gain}


@router.post("/devices/{dev_num}/live/exposure")
def set_exposure(dev_num: int, body: ExposureRequest):
    _require_connected(dev_num)
    key = "stack_l" if _current_stage(dev_num) == "Stack" else "continuous"
    do_action("set_setting", dev_num, {"exp_ms": {key: body.exp_ms}})
    return {"status": "ok", "exp_ms": body.exp_ms}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_router_live.py -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add front_v2/api/router_live.py tests/test_router_live.py
git commit -m "fix: read/write the firmware's real nested exp_ms shape in Live View

get_exposure/set_exposure used a flat exp_ms_continuous key that the
firmware's get_setting/set_setting never expose -- confirmed from a real
device log showing exp_ms: {stack_l, continuous}. get_exposure always
silently fell back to its hardcoded 10000ms default, and set_exposure's
writes were dropped. Now reads/writes stack_l while actively stacking,
continuous otherwise."
```

---

### Task 3: Gate dark-frame calibration behind an explicit flag

**Files:**
- Modify: `device/seestar_device.py:1771-1780` (`action_set_exposure`)
- Modify: `tests/test_seestar_device.py:969-977` (existing assertion, now needs both branches)

**Interfaces:**
- Produces: `action_set_exposure(self, params: dict) -> dict` — same signature/return keys (`set_response`, `dark_response`), but `dark_response` is now `None` unless `params.get("dark_frames")` is truthy. `params` is `cur_schedule_item["params"]`, already passed through unchanged by the scheduler dispatch at `seestar_device.py:2803` and by `device/telescope.py:279`.

- [ ] **Step 1: Update the existing test to show today's (buggy) behavior, then split it**

In `tests/test_seestar_device.py`, replace lines 975-977 (inside
`test_scheduler_pause_continue_skip_and_actions`):

```python
    out = seestar.action_set_exposure({"exp": 1200})
    assert out["set_response"]["method"] == "set_setting"
    assert out["dark_response"] is None
```

Then add a new test right after `test_scheduler_pause_continue_skip_and_actions`
(same file):

```python
def test_action_set_exposure_runs_dark_frame_when_requested(monkeypatch, seestar):
    monkeypatch.setattr(
        seestar,
        "send_message_param_sync",
        lambda payload: {"method": payload["method"]},
    )
    out = seestar.action_set_exposure({"exp": 1200, "dark_frames": True})
    assert out["set_response"]["method"] == "set_setting"
    assert out["dark_response"]["method"] == "start_create_dark"
```

- [ ] **Step 2: Run tests to verify the new/changed assertions fail**

Run: `pytest tests/test_seestar_device.py -k "action_set_exposure or scheduler_pause_continue_skip_and_actions" -v`
Expected: `test_scheduler_pause_continue_skip_and_actions` FAILS at
`assert out["dark_response"] is None` (today it's always the dict);
`test_action_set_exposure_runs_dark_frame_when_requested` currently PASSES
by coincidence (today's code always calls it) — that's fine, it'll still
pass after the fix since it explicitly opts in.

- [ ] **Step 3: Gate the dark-frame call**

Replace `device/seestar_device.py:1771-1780`:

```python
    def action_set_exposure(self, params):
        set_response = self.send_message_param_sync(
            {"method": "set_setting", "params": {"exp_ms": {"stack_l": params["exp"]}}}
        )
        dark_response = None
        if params.get("dark_frames", False):
            self.logger.info(
                "action_set_exposure: dark_frames requested, running start_create_dark"
            )
            dark_response = self.send_message_param_sync(
                {"method": "start_create_dark"}
            )
        response = {
            "set_response": set_response,
            "dark_response": dark_response,
        }
        return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_seestar_device.py -k "action_set_exposure or scheduler_pause_continue_skip_and_actions" -v`
Expected: both PASS.

- [ ] **Step 5: Run the full device test file to confirm no regression**

Run: `pytest tests/test_seestar_device.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add device/seestar_device.py tests/test_seestar_device.py
git commit -m "fix: only run dark-frame calibration when explicitly requested

action_set_exposure (the scheduler's per-item exposure-set action)
unconditionally fired start_create_dark after every exposure change, with
no gating -- so nearly every scheduled imaging item triggered a full dark
run regardless of the user's own dark-frames choice elsewhere. Adds an
opt-in 'action_set_exposure: dark_frames requested' log line so this is
observable in an emulator-matrix test (see next task)."
```

---

### Task 4: Fix Live View zoom-below-1x letterbox

**Files:**
- Modify: `front_v2/ui/src/pages/Live.svelte:491,815-848` (`.feed-wrap`)
- Test: `front_v2/ui/src/pages/Live.test.ts`

**Interfaces:**
- Produces: no change to any exported function — this is a template/CSS-only fix. `zoom`, `imgTransform`, `isQuarterTurn` (all already defined in `Live.svelte`) are read as before; a new reactive `feedWrapStyle` string is added and bound to `.feed-wrap`'s `style` attribute.

- [ ] **Step 1: Write the failing test**

Add to `front_v2/ui/src/pages/Live.test.ts` (find the existing zoom-related
`describe` block, or add a new one at the end of the file):

```typescript
describe("Live — zoom below 1x", () => {
  it("shrinks the feed-wrap container width instead of only the image", async () => {
    mockStatus.mockResolvedValue({
      device_num: 1, is_connected: true, view_state: "working", mode: "star",
    });
    const { container } = render(Live);
    await waitFor(() => screen.getByText("Live Feed"));

    const zoomOutBtn = screen.getByLabelText("Zoom out");
    // ZOOM_STEP is 0.25 starting from 1.0 -- one click reaches 0.75.
    await fireEvent.click(zoomOutBtn);

    const feedWrap = container.querySelector(".feed-wrap") as HTMLElement;
    expect(feedWrap.style.width).toBe("75%");
  });

  it("leaves feed-wrap at full width at 1x and above", async () => {
    mockStatus.mockResolvedValue({
      device_num: 1, is_connected: true, view_state: "working", mode: "star",
    });
    const { container } = render(Live);
    await waitFor(() => screen.getByText("Live Feed"));

    const feedWrap = container.querySelector(".feed-wrap") as HTMLElement;
    expect(feedWrap.style.width).toBe("");

    await fireEvent.click(screen.getByLabelText("Zoom in"));
    expect(feedWrap.style.width).toBe("");
  });
});
```

Check the top of `Live.test.ts` already imports `fireEvent` from
`@testing-library/svelte` — if not, add it to the existing import line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/pages/Live.test.ts -t "zoom below 1x"`
(from `front_v2/ui/`)
Expected: first test FAILS — `feedWrap.style.width` is `""`, not `"75%"`,
since today zoom only scales the `<img>`.

- [ ] **Step 3: Shrink the container below 1x**

In `front_v2/ui/src/pages/Live.svelte`, add a reactive style string near
the existing `imgTransform` block (around line 369-376):

```svelte
  $: feedWrapStyle = zoom < 1 ? `width:${zoom * 100}%;margin:0 auto;` : '';
```

Then update the `.feed-wrap` element at line 491 to bind it:

```svelte
          <div
            class="feed-wrap"
            class:feed-wrap-quarter={isQuarterTurn}
            class:feed-wrap-fs={isFullscreen}
            style={feedWrapStyle}
          >
```

No CSS rule changes needed — `.feed-wrap` is already `width: 100%` by
default (line 818), and this inline style only overrides it below 1x; the
existing `transform: scale()` + pan/clip behavior above 1x is untouched
since `feedWrapStyle` is empty in that case.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/Live.test.ts` (from `front_v2/ui/`)
Expected: all PASS, including the two new zoom tests and every
pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add front_v2/ui/src/pages/Live.svelte front_v2/ui/src/pages/Live.test.ts
git commit -m "fix: shrink the whole Live View box below 1x zoom, not just the image

Zoom was implemented purely as transform:scale() on the <img> inside a
fixed-size .feed-wrap, so zooming below 1.0 visually shrank the picture
but left the surrounding box (and its background) full-size -- producing
a border around the image. Below 1x, .feed-wrap's own width now shrinks
to match; at/above 1x the existing scale+pan+clip behavior is unchanged."
```

---

### Task 5: Fix Settings page Manual Exposure defaults and add range validation

**Files:**
- Modify: `front_v2/ui/src/pages/Settings.svelte:152-157,296-320`
- Test: `front_v2/ui/src/pages/Settings.test.ts`

**Interfaces:**
- Produces: new `enableManualExposure()` function (local to `Settings.svelte`, not exported — called only from the `manual_exp` radio's `Enable` input).

- [ ] **Step 1: Write the failing tests**

Add to `front_v2/ui/src/pages/Settings.test.ts` (after the existing
`describe` blocks; check the file for whether `fireEvent` is already
imported from `@testing-library/svelte` — add it if not):

```typescript
describe("Settings — Manual Exposure", () => {
  it("seeds a real value instead of the auto sentinel when enabled", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: {
        manual_exp: false,
        isp_exp_ms: -999000,
        isp_gain: -9990,
      },
      firmware_ver_int: 2582,
    });
    const { container } = render(Settings);
    await waitFor(() => screen.getByText(/Manual Exposure/));

    const enableRadio = container.querySelector(
      'input[name="manual_exp"][value="true"]',
    ) as HTMLInputElement;
    await fireEvent.click(enableRadio);

    const ispExpInput = container.querySelector(
      'input[type="number"]',
    ) as HTMLInputElement;
    expect(Number(ispExpInput.value)).not.toBe(-999000);
  });

  it("rejects an isp_exp_ms value above the device's real range", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: { manual_exp: true, isp_exp_ms: 10, isp_gain: 80 },
      firmware_ver_int: 2582,
    });
    const { container } = render(Settings);
    await waitFor(() => screen.getByText(/Manual Exposure/));

    const ispExpInput = container.querySelector(
      'input[type="number"]',
    ) as HTMLInputElement;
    expect(ispExpInput.max).toBe("1000");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/pages/Settings.test.ts -t "Manual Exposure"`
(from `front_v2/ui/`)
Expected: both FAIL — no `max` constraint exists today, and enabling
Manual Exposure leaves `isp_exp_ms` at `-999000`.

- [ ] **Step 3: Add constraints and the seed-on-enable behavior**

In `front_v2/ui/src/pages/Settings.svelte`, update `CONSTRAINTS` at lines
152-157:

```typescript
  // Known per-field constraints (min/max) matching the classic UI. The
  // isp_exp_ms/isp_gain ranges (isp_range_exp_us: [30, 1000000] -- note
  // MICROseconds -- and isp_range_gain: [0, 400]) come from the device's
  // own settings but aren't currently forwarded by the backend merge
  // (device_client.py filters out list-typed values), so they're hardcoded
  // here to match the observed device-reported values, same as the other
  // static entries below.
  const CONSTRAINTS: Record<string, { min?: number; max?: number }> = {
    exp_ms_stack_l:        { min: 5,    max: 90000 },
    exp_ms_continuous:     { min: 5,    max: 90000 },
    stack_dither_pix:      { min: 10,   max: 200   },
    stack_dither_interval: { min: 1                },
    isp_exp_ms:            { min: 0.03, max: 1000  },
    isp_gain:              { min: 0,    max: 400   },
  };
```

Add near the other functions (after `setVal`, around line 226):

```typescript
  // Device-reported "auto" sentinels (see REQUIRES_MANUAL_EXP below) --
  // seeded away from these the moment the user turns Manual Exposure on,
  // so the field never shows a nonsense starting value.
  const SENTINEL_ISP_EXP_MS = -999000;
  const SENTINEL_ISP_GAIN = -9990;
  const DEFAULT_ISP_EXP_MS = 10;
  const DEFAULT_ISP_GAIN = 80;

  function enableManualExposure() {
    const next = { ...merged, manual_exp: true };
    if (next.isp_exp_ms === SENTINEL_ISP_EXP_MS) next.isp_exp_ms = DEFAULT_ISP_EXP_MS;
    if (next.isp_gain === SENTINEL_ISP_GAIN) next.isp_gain = DEFAULT_ISP_GAIN;
    merged = next;
  }
```

Update the boolean radio group template (around line 306-320) so the
`manual_exp` field's Enable radio calls the new function instead of the
generic `setVal`:

```svelte
                {:else if val === true || val === false}
                  <div class="radio-group">
                    <label class="radio-label">
                      <input type="radio" name={key} value="true"
                        checked={val === true}
                        on:change={() => key === "manual_exp" ? enableManualExposure() : setVal(key, true)} />
                      Enable
                    </label>
                    <label class="radio-label">
                      <input type="radio" name={key} value="false"
                        checked={val === false}
                        on:change={() => setVal(key, false)} />
                      Disable
                    </label>
                  </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/Settings.test.ts` (from `front_v2/ui/`)
Expected: all PASS, including both new tests and every pre-existing test.

- [ ] **Step 5: Commit**

```bash
git add front_v2/ui/src/pages/Settings.svelte front_v2/ui/src/pages/Settings.test.ts
git commit -m "fix: seed a real value and enforce device ranges for Manual Exposure

isp_exp_ms/isp_gain are real device-reported 'auto' sentinels (-999000/
-9990) when Manual Exposure is off -- correct, but toggling it on left
those same nonsense numbers as the editable starting point, and there was
no client-side range check against the device's real ~1-second/0-400
limits, so an out-of-range value could be silently dropped by the
firmware. Enabling now seeds a sane default; CONSTRAINTS now covers both
fields."
```

---

### Task 6: Add "Goto Moon" / "Goto Sun" shortcuts to Live View

**Files:**
- Modify: `front_v2/ui/src/pages/Live.svelte`
- Test: `front_v2/ui/src/pages/Live.test.ts`

**Interfaces:**
- Consumes: `api.devices.search(devNum, q, catalog)` and `api.devices.goto(devNum, ra, dec, targetName, isJ2000)`, both already defined in `front_v2/ui/src/lib/api.ts:161-162,210-211` — no backend changes.

- [ ] **Step 1: Write the failing test**

Add to the hoisted mocks at the top of `Live.test.ts` (extend the existing
`vi.hoisted`/`vi.mock("../lib/api", ...)` blocks with `mockSearch` and
`mockGoto` alongside the existing `mockStartMode` etc., and add
`search: mockSearch, goto: mockGoto` to the mocked `api.devices` object).
Then add:

```typescript
describe("Live — lunar/solar goto shortcuts", () => {
  it("resolves and gotos the Moon", async () => {
    mockStatus.mockResolvedValue({
      device_num: 1, is_connected: true, view_state: "working", mode: "moon",
    });
    mockSearch.mockResolvedValue({
      query: "moon",
      result: { ra: "10h00m00.0s", dec: "+10d00m00.0s", name: "Moon" },
    });
    mockGoto.mockResolvedValue({});

    render(Live);
    await waitFor(() => screen.getByText("Live Feed"));

    await fireEvent.click(screen.getByRole("button", { name: /Goto Moon/i }));

    await waitFor(() => expect(mockGoto).toHaveBeenCalledWith(
      1, "10h00m00.0s", "+10d00m00.0s", "Moon", true,
    ));
    expect(mockSearch).toHaveBeenCalledWith(1, "moon", "planet");
  });

  it("shows an error if the Sun can't be resolved", async () => {
    mockStatus.mockResolvedValue({
      device_num: 1, is_connected: true, view_state: "working", mode: "sun",
    });
    mockSearch.mockResolvedValue({ query: "sun", result: null });

    render(Live);
    await waitFor(() => screen.getByText("Live Feed"));

    await fireEvent.click(screen.getByRole("button", { name: /Goto Sun/i }));

    await waitFor(() =>
      expect(screen.getByText(/could not resolve/i)).toBeInTheDocument(),
    );
    expect(mockGoto).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/pages/Live.test.ts -t "lunar/solar"` (from `front_v2/ui/`)
Expected: both FAIL — no "Goto Moon"/"Goto Sun" buttons exist yet.

- [ ] **Step 3: Add the buttons and handler**

In `front_v2/ui/src/pages/Live.svelte`, add state and a handler near
`modeError` (around line 58):

```typescript
  let gotoError = "";
  let gotoing = false;

  async function gotoBody(body: "moon" | "sun") {
    gotoError = "";
    gotoing = true;
    try {
      const { result } = await api.devices.search($activeDevNum, body, "planet") as {
        result: { ra: string; dec: string; name: string } | null;
      };
      if (!result) {
        gotoError = `Could not resolve the ${body === "moon" ? "Moon" : "Sun"}'s position.`;
        return;
      }
      await api.devices.goto($activeDevNum, result.ra, result.dec, result.name, true);
    } catch (e) {
      gotoError = String(e);
    } finally {
      gotoing = false;
    }
  }
```

Add the buttons to the mode-strip card, right after the existing
`{#if modeError}` block (around line 443-445):

```svelte
        {#if modeError}
          <div class="alert alert-error" style="margin-top:0.5rem;margin-bottom:0">{modeError}</div>
        {/if}
        {#if gotoError}
          <div class="alert alert-error" style="margin-top:0.5rem;margin-bottom:0">{gotoError}</div>
        {/if}
        <div class="mode-strip" style="margin-top:0.5rem">
          <button class="mode-chip" on:click={() => gotoBody("moon")} disabled={gotoing}>
            🌙 Goto Moon
          </button>
          <button class="mode-chip" on:click={() => gotoBody("sun")} disabled={gotoing}>
            ☀ Goto Sun
          </button>
        </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/Live.test.ts` (from `front_v2/ui/`)
Expected: all PASS, including the two new tests and every pre-existing test.

- [ ] **Step 5: Commit**

```bash
git add front_v2/ui/src/pages/Live.svelte front_v2/ui/src/pages/Live.test.ts
git commit -m "feat: add one-tap Goto Moon / Goto Sun buttons to Live View

Wires two existing pieces together -- the planet-ephemeris search
(_search_planet, already implemented) and the existing goto endpoint --
no backend changes needed. Manual exposure/gain tweaking for sun/moon/
planet modes is already covered by the Task 2 exposure fix."
```

---

### Task 7: Verify firmware assumptions against the emulator (spike)

**Files:** none changed — this task's deliverable is a short findings note
appended to the design spec's Open Items, informing Task 8, 9, and 10.

**Interfaces:** none — investigation only.

- [ ] **Step 1: Confirm firmware is extracted for at least one matrix version**

Follow `emulator/README.md`'s "Firmware extraction" section, or use the
pinned-version automated path:

```bash
python3 -m emulator.firmware.provision --version 2.6.4 --out ~/dev/firmware/unpacked/2.6.4
```

- [ ] **Step 2: Launch the emulator against that firmware**

```bash
FIRMWARE_DIR=~/dev/firmware/unpacked/2.6.4 ./emulator/run.sh
```

Expected: container starts, ports 4700/4701/4800/4801/8080/4720 forwarded
(per `emulator/README.md`'s Quick Start).

- [ ] **Step 3: Confirm `get_setting` reports nested `exp_ms`**

In a second terminal:

```bash
docker exec -i seestar-emulator bash << 'EOF'
exec 3<>/dev/tcp/127.0.0.1/4700
echo '{"id":1,"method":"get_setting","params":{}}' >&3
sleep 2; cat <&3
exec 3>&-
EOF
```

Expected: the response JSON contains `"exp_ms":{"stack_l":...,"continuous":...}`
(nested), matching the real-device log capture used in Task 2 — not a flat
`exp_ms_continuous` key. Record pass/fail.

- [ ] **Step 4: Confirm gain appears on `View`/`Exposure` events**

Still inside the container, start a live view and watch the socket for a
few seconds:

```bash
docker exec -i seestar-emulator bash << 'EOF'
exec 3<>/dev/tcp/127.0.0.1/4700
echo '{"id":2,"method":"iscope_start_view","params":{"mode":"star"}}' >&3
sleep 5; cat <&3
exec 3>&-
EOF
```

Expected: among the streamed responses/events, at least one `"Event":"View"`
or `"Event":"Exposure"` line contains a `"gain"` field. This confirms the
`self.event_state["View"]`/`self.event_state["Exposure"]` population this
plan's Task 8 reads from (`device/seestar_device.py:708`) will actually
have a gain value to serve, on this firmware version.

- [ ] **Step 5: Repeat Steps 1-4 for the other two matrix versions**

```bash
python3 -m emulator.firmware.provision --version 3.2.0 --out ~/dev/firmware/unpacked/3.2.0
python3 -m emulator.firmware.provision --version 3.3.0 --out ~/dev/firmware/unpacked/3.3.0
```

Re-run Steps 2-4 with `FIRMWARE_DIR` pointed at each.

- [ ] **Step 6: Record findings**

Append a dated note under the "Open items" section of
`docs/superpowers/specs/2026-07-25-front-v2-bugfix-batch-design.md`,
e.g.:

```markdown
### Verification results (2026-07-25, emulator spike)

- exp_ms nested shape: confirmed on 2.6.4 / 3.2.0 / 3.3.0.
- gain present on View/Exposure events: confirmed on 2.6.4 / 3.2.0 / 3.3.0.
```

(If any version diverges, record exactly what it returned instead — that
finding changes Task 8/9/10's scope, and should be raised before continuing.)

- [ ] **Step 7: Commit the findings note**

```bash
git add docs/superpowers/specs/2026-07-25-front-v2-bugfix-batch-design.md
git commit -m "docs: record emulator verification of exp_ms shape and gain events"
```

---

### Task 8: Add a device-layer gain accessor and wire Live View to it

**Files:**
- Modify: `device/abstract_device.py:111-117` (add abstract method)
- Modify: `device/seestar_device.py` (add `get_last_gain`, near `action_set_exposure`)
- Modify: `device/seestar_remote.py:149-150` (add passthrough implementation)
- Modify: `device/seestar_federation.py:158-163` (add passthrough implementation)
- Modify: `device/telescope.py:278-280` (register the action)
- Modify: `front_v2/api/router_live.py` (`get_exposure`, `set_gain`)
- Test: `tests/test_seestar_device.py`, `tests/test_router_live.py`

**Note:** `AbstractDevice` (`device/abstract_device.py:38`) is a real `ABC`
— adding an `@abstractmethod` without implementing it in every subclass
would make `SeestarRemote`/`SeestarFederation` fail to instantiate, so both
need a matching implementation, not just `SeestarDevice`.

**Interfaces:**
- Produces: `SeestarDevice.get_last_gain(self) -> int | None` — reads the
  most recently seen `gain` value out of `self.event_state["View"]` or
  `self.event_state["Exposure"]` (whichever is newer; both already carry a
  `gain` field per the Task 7 spike). Registered as device action
  `"get_last_gain"` (no params) in `device/telescope.py`, callable via
  `do_action("get_last_gain", dev_num, {})`.

- [ ] **Step 1: Write the failing test for `get_last_gain`**

Add to `tests/test_seestar_device.py`, near the other `action_set_exposure`
tests:

```python
def test_get_last_gain_reads_from_view_event(seestar):
    seestar.event_state["View"] = {"Event": "View", "state": "working", "gain": 80}
    assert seestar.get_last_gain() == 80


def test_get_last_gain_falls_back_to_exposure_event(seestar):
    seestar.event_state.pop("View", None)
    seestar.event_state["Exposure"] = {"Event": "Exposure", "exp_us": 2000000, "gain": 0}
    assert seestar.get_last_gain() == 0


def test_get_last_gain_returns_none_when_no_event_seen(seestar):
    seestar.event_state.pop("View", None)
    seestar.event_state.pop("Exposure", None)
    assert seestar.get_last_gain() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_seestar_device.py -k "get_last_gain" -v`
Expected: all 3 FAIL with `AttributeError: 'SeestarDevice' object has no
attribute 'get_last_gain'`.

- [ ] **Step 3: Implement `get_last_gain`**

Add to `device/seestar_device.py`, directly after `action_set_exposure`
(after the block edited in Task 3):

```python
    def get_last_gain(self) -> int | None:
        """Most recently observed live-view gain, from whichever of the
        View/Exposure push events was seen more recently -- gain has no
        queryable get_setting field of its own (confirmed against a real
        device log and the emulator, see docs/superpowers/specs/
        2026-07-25-front-v2-bugfix-batch-design.md)."""
        view_gain = self.event_state.get("View", {}).get("gain")
        exposure_gain = self.event_state.get("Exposure", {}).get("gain")
        if view_gain is not None:
            return view_gain
        return exposure_gain
```

Add the abstract declaration to `device/abstract_device.py`, after
`action_set_exposure` (line 117):

```python
    @abstractmethod
    def get_last_gain(self) -> int | None:
        pass
```

Add matching passthrough implementations so the two other `AbstractDevice`
subclasses stay instantiable. In `device/seestar_remote.py`, after
`action_set_exposure` (line 149-150):

```python
    def get_last_gain(self):
        return self._do_action_device("get_last_gain", {})
```

In `device/seestar_federation.py`, after `action_set_exposure` (line 158-163):

```python
    def get_last_gain(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].get_last_gain()
        return result
```

Register the action in `device/telescope.py`, after the
`action_set_exposure` dispatch (line 278-280):

```python
            elif action_name == "get_last_gain":
                result = cur_dev.get_last_gain()
                resp.text = MethodResponse(req, value=result).json
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_seestar_device.py -k "get_last_gain" -v`
Expected: all 3 PASS.

- [ ] **Step 5: Write the failing router_live.py tests for gain**

Add to `tests/test_router_live.py`:

```python
def test_get_exposure_reads_gain_from_get_last_gain_action(client, monkeypatch):
    monkeypatch.setattr(
        router_live,
        "method_sync",
        _fake_method_sync("Idle", {"stack_l": 20000, "continuous": 2000}),
    )
    monkeypatch.setattr(
        router_live,
        "do_action",
        lambda action, dev_num, params: {"Value": 42} if action == "get_last_gain" else None,
    )
    r = client.get("/api/v1/devices/1/live/exposure")
    assert r.status_code == 200
    assert r.json()["gain"] == 42


def test_set_gain_uses_set_control_value(client, monkeypatch):
    captured = {}

    def fake_do_action(action, dev_num, params):
        captured["action"] = action
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(router_live, "do_action", fake_do_action)

    r = client.post("/api/v1/devices/1/live/gain", json={"gain": 120})
    assert r.status_code == 200
    assert captured["action"] == "method_sync"
    assert captured["params"]["method"] == "set_control_value"
    assert captured["params"]["params"] == ["gain", 120]
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_router_live.py -k "gain" -v`
Expected: both FAIL — `get_exposure` still returns the `get_setting`
result's nonexistent flat `gain` key (falls back to `80`), and `set_gain`
still calls `set_setting`.

- [ ] **Step 7: Wire `get_exposure`/`set_gain` to the new accessor**

Update `get_exposure` in `front_v2/api/router_live.py` (from Task 2's
version) to read gain via the new action instead of `get_setting`:

```python
@router.get("/devices/{dev_num}/live/exposure")
def get_exposure(dev_num: int):
    _require_connected(dev_num)
    result = method_sync("get_setting", dev_num) or {}
    exp_ms = result.get("exp_ms") or {}
    key = "stack_l" if _current_stage(dev_num) == "Stack" else "continuous"
    exp = exp_ms.get(key, 10000)
    gain_result = do_action("get_last_gain", dev_num, {}) or {}
    gain = gain_result.get("Value")
    if gain is None:
        gain = 80
    return {"exp_ms": exp, "gain": gain}
```

Replace `set_gain` (`router_live.py:107-111`):

```python
@router.post("/devices/{dev_num}/live/gain")
def set_gain(dev_num: int, body: GainRequest):
    _require_connected(dev_num)
    do_action(
        "method_sync",
        dev_num,
        {"method": "set_control_value", "params": ["gain", body.gain]},
    )
    return {"status": "ok", "gain": body.gain}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_router_live.py -v`
Expected: all PASS, including every test from Task 2.

- [ ] **Step 9: Commit**

```bash
git add device/abstract_device.py device/seestar_device.py device/seestar_remote.py \
        device/seestar_federation.py device/telescope.py \
        front_v2/api/router_live.py tests/test_seestar_device.py tests/test_router_live.py
git commit -m "fix: read/write Live View gain via tracked events + set_control_value

Gain has no field in get_setting at all (confirmed from a real device log
and the emulator spike) -- it only arrives via View/Exposure push events,
which the device object already tracks in self.event_state. Adds
get_last_gain to read that, and switches set_gain to set_control_value
['gain', N] (the same command already used for stack gain elsewhere),
since set_setting {gain: N} was a silent no-op."
```

---

### Task 9: Emulator-matrix test — exposure change is reflected by the firmware

**Files:**
- Create: `tests/system/test_exposure_and_dark_frames.py`

**Interfaces:**
- Consumes: `running_app` and `target` fixtures from `tests/system/conftest.py` (unchanged); `requests` (already a project dependency) for direct HTTP calls to the running app, bypassing Playwright since this checks an API contract, not UI behavior.

- [ ] **Step 1: Write the test**

Create `tests/system/test_exposure_and_dark_frames.py`:

```python
"""Emulator-matrix regression coverage for the exposure key-mismatch and
dark-frame-on-every-exposure-set bugs (see docs/superpowers/specs/
2026-07-25-front-v2-bugfix-batch-design.md). Runs against the real firmware
binary via the QEMU emulator, across the pinned version matrix
(emulator/firmware/versions.yaml) in the full/nightly CI lane -- see
tests/system/README.md for --target usage.
"""

import time

import pytest
import requests

pytestmark = pytest.mark.system


@pytest.fixture
def app(running_app):
    return running_app("v2")


@pytest.fixture
def base_url(app):
    return app.base_url


@pytest.mark.full
def test_live_exposure_change_is_reflected_by_firmware(base_url):
    requests.post(f"{base_url}/api/v1/devices/1/live/mode", json={"mode": "star"})
    time.sleep(3)  # let iscope_start_view settle before touching settings

    set_resp = requests.post(
        f"{base_url}/api/v1/devices/1/live/exposure", json={"exp_ms": 3000}
    )
    assert set_resp.status_code == 200

    get_resp = requests.get(f"{base_url}/api/v1/devices/1/live/exposure")
    assert get_resp.status_code == 200
    assert get_resp.json()["exp_ms"] == 3000

    requests.delete(f"{base_url}/api/v1/devices/1/live/mode")
```

- [ ] **Step 2: Run against the emulator to verify it fails on the pre-fix code**

(Confirms this test would have caught the bug — skip if Tasks 2/8 are
already committed ahead of this task; otherwise temporarily `git stash`
those commits, run, then `git stash pop`.)

Run: `pytest tests/system/test_exposure_and_dark_frames.py --target emulator -v`
Expected (pre-fix): FAIL — `exp_ms` comes back as the hardcoded `10000`
default instead of `3000`.

- [ ] **Step 3: Run against the fixed code to verify it passes**

Run: `pytest tests/system/test_exposure_and_dark_frames.py --target emulator -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/system/test_exposure_and_dark_frames.py
git commit -m "test: emulator-matrix regression for Live View exposure round-trip

Runs against the real firmware binary (2.6.4/3.2.0/3.3.0 via the
emulator-full.yml matrix), not a fixture -- catches the exp_ms flat-vs-
nested key mismatch directly against firmware behavior."
```

---

### Task 10: Emulator-matrix test — dark frames only run when requested

**Files:**
- Modify: `tests/system/test_exposure_and_dark_frames.py`

**Interfaces:** none new — extends Task 9's file.

- [ ] **Step 1: Write the test**

Append to `tests/system/test_exposure_and_dark_frames.py`:

```python
def _add_and_run_exposure_item(base_url, dark_frames: bool) -> None:
    requests.delete(f"{base_url}/api/v1/devices/1/schedule")
    requests.post(
        f"{base_url}/api/v1/devices/1/schedule/item",
        json={
            "action": "action_set_exposure",
            "params": {"exp": 1200, "dark_frames": dark_frames},
        },
    )
    requests.post(f"{base_url}/api/v1/devices/1/schedule/state?state=start")

    deadline = time.time() + 30
    while time.time() < deadline:
        state = requests.get(f"{base_url}/api/v1/devices/1/schedule").json()
        if state.get("state") in ("stopped", "complete"):
            break
        time.sleep(1)


@pytest.mark.full
def test_dark_frames_not_run_when_not_requested(app, base_url):
    _add_and_run_exposure_item(base_url, dark_frames=False)
    log_text = app.log_file.read_text()
    assert "action_set_exposure: dark_frames requested" not in log_text


@pytest.mark.full
def test_dark_frames_run_when_requested(app, base_url):
    _add_and_run_exposure_item(base_url, dark_frames=True)
    log_text = app.log_file.read_text()
    assert "action_set_exposure: dark_frames requested" in log_text
```

`AppProcess.log_file` (`tests/system/app_process.py:29`) already stores the
exact `Path` passed in by `conftest.py:191` (`config_dir / "app.log"`), so
`app.log_file` is usable directly — no changes needed to `app_process.py`.

- [ ] **Step 2: Run against the emulator to verify it fails on the pre-fix code**

(Same caveat as Task 9 Step 2 — verify against the pre-Task-3 code if it's
convenient to check out, otherwise skip straight to Step 3 since Task 3's
own unit tests already prove the gating logic.)

Run: `pytest tests/system/test_exposure_and_dark_frames.py --target emulator -k dark_frames -v`

- [ ] **Step 3: Run against the fixed code to verify it passes**

Run: `pytest tests/system/test_exposure_and_dark_frames.py --target emulator -v`
Expected: all 3 tests in the file PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/system/test_exposure_and_dark_frames.py
git commit -m "test: emulator-matrix regression for dark-frame gating

Confirms against the real firmware binary that action_set_exposure only
triggers start_create_dark when dark_frames is explicitly requested,
across the full firmware matrix."
```

---

## Post-implementation

After Task 10, all five bugs and the lunar/solar feature from
`docs/superpowers/specs/2026-07-25-front-v2-bugfix-batch-design.md` are
implemented and covered by tests. Run the full test suite once more before
opening a PR:

```bash
pytest tests/ -v --ignore=tests/system
cd front_v2/ui && npx vitest run
```

The emulator-matrix tests (Tasks 9-10) only run with `--target emulator`
and are gated by the `full` marker in CI (label/nightly) — they are not
part of the default `pytest` invocation above.
