<script lang="ts">
  import { onDestroy } from "svelte";
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api, type EventState } from "../lib/api";
  import { humanizeEventState } from "../lib/utils";

  let polarAlign = true;
  let autoFocus = true;
  let darkFrames = false;
  let lat = "";
  let lon = "";
  let decOffset = 3;

  let running = false;
  let stopping = false;
  let error = "";

  // ── PA Refinement ─────────────────────────────────────────────────────────
  let paOpen = false;
  let paRunning = false;
  let paStopping = false;
  let paError = "";
  let paAltErr = 0.0;
  let paAzErr  = 0.0;
  let paMaxDeg = 5.0;          // slider value
  let paGardenEl: HTMLDivElement | null = null;
  let paPollTimer: ReturnType<typeof setTimeout> | null = null;

  function paBallPos(errAlt: number, errAz: number, max: number, size: number) {
    const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);
    const x = Math.round(size / 2 * (1 + clamp(errAz, -max, max) / max));
    const y = Math.round(size / 2 * (1 - clamp(errAlt, -max, max) / max));
    return { x, y };
  }

  async function paPoll() {
    if (!$isConnected || !paRunning) return;
    try {
      const d = await api.devices.paRefine.data($activeDevNum);
      paAltErr = d.error_alt;
      paAzErr  = d.error_az;
    } catch { /* ignore */ }
    paPollTimer = setTimeout(paPoll, 1000);
  }

  async function paStart() {
    paError = "";
    try {
      const r = await api.devices.paRefine.start($activeDevNum);
      if ((r as { ok?: boolean }).ok === false) {
        paError = (r as { error?: string }).error ?? "Failed to start";
        return;
      }
      paRunning = true;
      paPoll();
    } catch (e) {
      paError = String(e);
    }
  }

  async function paStop() {
    paStopping = true;
    if (paPollTimer) { clearTimeout(paPollTimer); paPollTimer = null; }
    try {
      await api.devices.paRefine.stop($activeDevNum);
    } catch { /* ignore */ } finally {
      paRunning  = false;
      paStopping = false;
    }
  }

  onDestroy(() => {
    if (pollTimer)   clearTimeout(pollTimer);
    if (paPollTimer) clearTimeout(paPollTimer);
  });

  $: s = $activeDeviceStatus;
  $: schedState = (s as { schedule_state?: string })?.schedule_state ?? "";
  // events.scheduler is polled locally every 1-3s (see below), much faster
  // than $activeDeviceStatus's 15s poll — checking both means isRunning (and
  // so the disabled Run button / visible Stop button) reflects reality
  // quickly instead of lagging up to 15s behind the real backend state.
  // NB: the raw key is lowercase "scheduler" even though its own Event field
  // reads "Scheduler" (every other event uses its canonical capitalized name
  // as the dict key too — this one's the one legacy exception).
  $: isRunning =
    schedState === "running" ||
    schedState === "working" ||
    events["scheduler"]?.state === "working";

  // Once isRunning is confirmed by a poll, hand off to it entirely — clears
  // the transient `running` flag set by start() below so a later real
  // completion (isRunning -> false) correctly re-enables the button instead
  // of staying stuck disabled forever.
  $: if (isRunning && running) running = false;

  // ── Event status polling ───────────────────────────────────────────────────
  // Matches classic front/app.py's "command" eventlist order (WheelMove,
  // AutoFocus, DarkLibrary, 3PPA, PlateSolve), minus Scheduler — redundant on
  // this page (the Run/Stop button + label already show whether a sequence
  // is running) and, on top of that, was silently always blank anyway (see
  // the events["scheduler"] key-casing note above).
  const EVENT_NAMES = ["WheelMove", "AutoFocus", "DarkLibrary", "3PPA", "PlateSolve"] as const;
  type EventName = typeof EVENT_NAMES[number];

  const EVENT_LABELS: Record<EventName, string> = {
    "3PPA":        "Polar Align",
    "AutoFocus":   "Auto Focus",
    "DarkLibrary": "Dark Frames",
    "PlateSolve":  "Plate Solve",
    "WheelMove":   "Filter Wheel",
  };

  let events: Record<string, EventState> = {};
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollingActive = false;

  async function pollEvents() {
    if (!$isConnected) return;
    try {
      events = await api.devices.events($activeDevNum);
    } catch {
      // silently ignore poll errors
    }
    const interval = isRunning ? 1000 : 3000;
    pollTimer = setTimeout(pollEvents, interval);
  }

  function startPolling() {
    if (pollingActive) return;
    pollingActive = true;
    pollEvents();
  }

  function stopPolling() {
    pollingActive = false;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    events = {};
  }

  // Depend only on $isConnected — referencing pollTimer/pollingActive here
  // (even just to read them) would make this block re-fire on every
  // assignment to them, including the one pollEvents() makes every tick,
  // collapsing the polling interval into a tight back-to-back loop.
  $: $isConnected ? startPolling() : stopPolling();

  // Auto-expand PA Refinement when polar align finishes
  $: if (events["3PPA"]?.state === "complete" && !paOpen) paOpen = true;

  // onDestroy is defined below with PA cleanup included

  function stateClass(ev: EventState | undefined): string {
    if (!ev?.state || ev.state === "idle") return "state-idle";
    if (ev.state === "complete") return "state-complete";
    if (ev.state === "fail" || ev.state === "cancel") return "state-fail";
    // Anything else present is an active sub-state — 3PPA in particular
    // cycles through firmware-internal values like "delay1"/"delay2"/"calc3"
    // (and PlateSolve through "solving") that aren't literally "in progress"/
    // "working"/"start". Treat any non-terminal, non-idle state as progress
    // rather than enumerating every sub-state literal, so the tile visibly
    // lights up instead of looking identical to an untouched Idle tile.
    return "state-progress";
  }

  function stateLabel(ev: EventState | undefined): string {
    return humanizeEventState(ev?.state);
  }

  function filterName(pos: number | undefined): string {
    if (pos === 0) return "Dark";
    if (pos === 1) return "IR Cut";
    if (pos === 2) return "LP";
    return "—";
  }

  // ── Startup sequence ───────────────────────────────────────────────────────
  async function start() {
    running = true;
    error = "";
    try {
      const params: Record<string, unknown> = {
        auto_focus:    autoFocus,
        dark_frames:   darkFrames,
        "3ppa":        polarAlign,
        dec_pos_index: decOffset,
      };
      if (lat.trim() && lon.trim()) {
        params.lat = parseFloat(lat);
        params.lon = parseFloat(lon);
      }
      await api.devices.startup($activeDevNum, params);
      // Don't clear `running` here — the POST resolving just means the
      // request was accepted, not that the sequence is underway. Clearing it
      // now would briefly re-enable the button for however long it takes the
      // next poll to notice isRunning (see reactive statement above), which
      // is exactly the "not disabled long enough" gap this fixes. `running`
      // gets handed off to isRunning once a poll confirms it; the timeout
      // below is only a safety net in case the sequence never actually starts
      // (e.g. backend silently no-ops with "device busy") so the button
      // doesn't stay disabled forever.
      setTimeout(() => { running = false; }, 20_000);
    } catch (e) {
      error = String(e);
      running = false;
    }
  }

  async function stop() {
    stopping = true;
    error = "";
    try {
      await api.devices.schedule.setState($activeDevNum, "stop");
      schedState = "stopped";
    } catch (e) {
      error = String(e);
    } finally {
      stopping = false;
    }
  }
</script>

<div class="page-hero">
  <p class="page-kicker">Session</p>
  <h1 class="page-title">Startup</h1>
  <p class="page-subtitle">Run the telescope startup sequence — polar align, auto focus, dark frames.</p>
</div>

{#if $activeDevNum === 0}
  <div class="panel-card offline-msg">
    Startup requires a single telescope. Select a specific device from the dropdown above.
  </div>
{:else if !$isConnected}
  <div class="panel-card offline-msg">Device {$activeDevNum} is offline.</div>
{:else}
  {#if error}<div class="alert alert-error">{error}</div>{/if}

  <!-- ── Event Status ────────────────────────────────────────────────────── -->
  <div class="panel-card events-card">
    <p class="panel-title">Event Status</p>
    <div class="events-grid">
      {#each EVENT_NAMES as name}
        {@const ev = events[name]}
        <div class="event-tile {stateClass(ev)}">
          <div class="event-name">{EVENT_LABELS[name]}</div>
          <div class="event-state">{stateLabel(ev)}</div>
          {#if ev?.error}
            <div class="event-detail error-text">{ev.error}</div>
          {/if}
          {#if name === "3PPA"}
            {#if ev?.percent != null}
              <div class="event-detail">{ev.percent}%</div>
              <div class="progress-bar-wrap">
                <div class="progress-bar-fill" style="width:{Math.min(ev.percent, 100)}%"></div>
              </div>
            {/if}
            {#if ev?.eq_offset_alt != null && ev?.eq_offset_az != null}
              <div class="event-detail">Alt err: {ev.eq_offset_alt.toFixed(3)}°</div>
              <div class="event-detail">Az err: {ev.eq_offset_az.toFixed(3)}°</div>
            {/if}
          {/if}
          {#if name === "AutoFocus" && ev?.position != null}
            <div class="event-detail">Pos: {ev.position}</div>
          {/if}
          {#if name === "DarkLibrary" && ev?.percent != null}
            <div class="event-detail">{ev.percent.toFixed(1)}%</div>
            <div class="progress-bar-wrap">
              <div class="progress-bar-fill" style="width:{Math.min(ev.percent, 100)}%"></div>
            </div>
          {/if}
          {#if name === "WheelMove" && ev?.position != null}
            <div class="event-detail">{filterName(ev.position)}</div>
          {/if}
        </div>
      {/each}
    </div>
  </div>

  <!-- ── Options ────────────────────────────────────────────────────────── -->
  <div class="startup-layout">
    <div class="panel-card options-card">
      <p class="panel-title">Startup Options</p>

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Polar Align</div>
          <div class="option-help">Run 3-point polar alignment at session start</div>
        </div>
        <div class="radio-group">
          <label class="radio-label"><input type="radio" bind:group={polarAlign} value={true} /> On</label>
          <label class="radio-label"><input type="radio" bind:group={polarAlign} value={false} /> Off</label>
        </div>
      </div>

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Auto Focus</div>
          <div class="option-help">Run auto-focus routine before imaging</div>
        </div>
        <div class="radio-group">
          <label class="radio-label"><input type="radio" bind:group={autoFocus} value={true} /> On</label>
          <label class="radio-label"><input type="radio" bind:group={autoFocus} value={false} /> Off</label>
        </div>
      </div>

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Dark Frames</div>
          <div class="option-help">Capture dark calibration frames</div>
        </div>
        <div class="radio-group">
          <label class="radio-label"><input type="radio" bind:group={darkFrames} value={true} /> On</label>
          <label class="radio-label"><input type="radio" bind:group={darkFrames} value={false} /> Off</label>
        </div>
      </div>

      <div class="option-row option-row-dec">
        <div class="option-meta">
          <div class="option-label">Dec Offset</div>
          <div class="option-help">Declination arm position for EQ polar alignment</div>
        </div>
      </div>
      <div class="dec-picker">
        <div class="dec-arc-wrap">
          <img
            class="dec-scope"
            src="/S50.png"
            alt="telescope"
            style="transform: translateX(-50%) rotate({(decOffset - 1) * 30 - 60}deg)"
          />
          {#each [1,2,3,4,5] as pos}
            {@const angle = (pos - 1) * 30 - 60}
            {@const rad = angle * Math.PI / 180}
            {@const x = 50 + 45 * Math.sin(rad)}
            {@const y = 60 - 45 * Math.cos(rad)}
            <label
              class="dec-option"
              class:dec-option-selected={decOffset === pos}
              style="left:{x}%; top:{y}%"
            >
              <input type="radio" bind:group={decOffset} value={pos} />
              <span>{pos}</span>
            </label>
          {/each}
          <span class="dec-dir dec-dir-left">← S</span>
          <span class="dec-dir dec-dir-right">N →</span>
        </div>
      </div>

      <div class="coords-section">
        <p class="coords-title">Location Override <span class="coords-optional">(optional — uses saved config if blank)</span></p>
        <div class="coords-row">
          <div class="form-field">
            <label class="form-label" for="lat">Latitude</label>
            <input id="lat" type="text" class="form-input" placeholder="e.g. 37.7749" bind:value={lat} />
          </div>
          <div class="form-field">
            <label class="form-label" for="lon">Longitude</label>
            <input id="lon" type="text" class="form-input" placeholder="e.g. -122.4194" bind:value={lon} />
          </div>
        </div>
      </div>

      <div class="action-row">
        <button class="btn btn-primary" on:click={start} disabled={running || isRunning}>
          {running ? "Starting…" : isRunning ? "Running…" : "▶ Run Startup Sequence"}
        </button>
        {#if isRunning}
          <button class="btn btn-danger" on:click={stop} disabled={stopping}>
            {stopping ? "Stopping…" : "⏹ Stop"}
          </button>
        {/if}
      </div>
    </div>
  </div>

  <!-- ── PA Refinement ────────────────────────────────────────────────────── -->
  <div class="panel-card pa-card">
    <button class="pa-header" on:click={() => paOpen = !paOpen} aria-expanded={paOpen}>
      <span class="panel-title pa-title">PA Refinement</span>
      <span class="pa-chevron" class:pa-chevron-open={paOpen}>▶</span>
    </button>

    {#if paOpen}
      <p class="pa-desc">Use the plate-solve loop to measure and guide polar alignment corrections.</p>

      {#if paError}<div class="alert alert-error">{paError}</div>{/if}

      <div class="pa-body">
        <!-- garden -->
        <div class="pa-garden" bind:this={paGardenEl}>
          {#if paGardenEl}
            {@const sz = paGardenEl.clientWidth}
            {@const pos = paBallPos(paAltErr, paAzErr, paMaxDeg, sz)}
            <div class="pa-ball" style="left:{pos.x}px; top:{pos.y}px"></div>
          {:else}
            <div class="pa-ball" style="left:50%;top:50%"></div>
          {/if}
          <div class="pa-circle" style="width:10%;height:10%"></div>
          <div class="pa-circle" style="width:30%;height:30%"></div>
          <div class="pa-circle" style="width:80%;height:80%"></div>
          <div class="pa-crosshair-h"></div>
          <div class="pa-crosshair-v"></div>
        </div>

        <!-- readouts + controls -->
        <div class="pa-controls">
          <div class="pa-errors">
            <div class="pa-err-row"><span class="pa-err-label">Alt error</span><span class="pa-err-val">{paAltErr.toFixed(3)}°</span></div>
            <div class="pa-err-row"><span class="pa-err-label">Az error</span><span class="pa-err-val">{paAzErr.toFixed(3)}°</span></div>
          </div>

          <div class="pa-slider-row">
            <label class="pa-slider-label" for="pa-slider">Zoom (max ±{paMaxDeg.toFixed(1)}°)</label>
            <input id="pa-slider" type="range" min="0.1" max="10" step="0.1" bind:value={paMaxDeg} class="pa-slider" />
          </div>

          <div class="pa-actions">
            {#if !paRunning}
              <button class="btn btn-primary" on:click={paStart}>▶ Start</button>
            {:else}
              <button class="btn btn-danger" on:click={paStop} disabled={paStopping}>
                {paStopping ? "Stopping…" : "⏹ Stop"}
              </button>
            {/if}
          </div>

          <div class="pa-instructions">
            <ol>
              <li>Press Start to begin the plate-solve loop.</li>
              <li>Adjust zoom so the dot is visible within the garden.</li>
              <li>Gradually adjust alt/az on your wedge; wait for the dot to move between adjustments.</li>
              <li>When satisfied, press Stop.</li>
            </ol>
          </div>
        </div>
      </div>
    {/if}
  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }

  /* ── Event tiles ─────────────────────────────────────────────────────── */
  .events-card { margin-bottom: 1rem; }

  .events-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 0.6rem;
  }

  .event-tile {
    border-radius: 8px;
    padding: 0.65rem 0.75rem;
    border: 1px solid transparent;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    min-height: 80px;
  }

  .event-name {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.75;
  }
  .event-state {
    font-size: 0.82rem;
    font-weight: 600;
    text-transform: capitalize;
  }
  .event-detail {
    font-size: 0.72rem;
    opacity: 0.8;
  }
  .error-text { color: #fc8181; }

  /* State color variants */
  .state-idle {
    background: rgba(255,255,255,0.03);
    border-color: rgba(255,255,255,0.08);
    color: var(--ui-muted);
  }
  .state-progress {
    background: rgba(237,184,40,0.12);
    border-color: rgba(237,184,40,0.35);
    color: #edb828;
  }
  .state-complete {
    background: rgba(72,187,120,0.12);
    border-color: rgba(72,187,120,0.35);
    color: #48bb78;
  }
  .state-fail {
    background: rgba(245,101,101,0.12);
    border-color: rgba(245,101,101,0.35);
    color: #f56565;
  }

  /* Progress bar inside tiles */
  .progress-bar-wrap {
    height: 3px;
    background: rgba(255,255,255,0.12);
    border-radius: 2px;
    margin-top: 0.2rem;
    overflow: hidden;
  }
  .progress-bar-fill {
    height: 100%;
    background: currentColor;
    border-radius: 2px;
    transition: width 0.4s ease;
  }

  /* ── Options form ────────────────────────────────────────────────────── */
  .startup-layout { max-width: 600px; }
  .options-card { display: flex; flex-direction: column; gap: 0; }

  .option-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.7rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }
  .option-row:last-of-type { border-bottom: none; }
  .option-meta { flex: 1; }
  .option-label { font-size: 0.85rem; font-weight: 500; color: var(--ui-body); }
  .option-help  { font-size: 0.75rem; color: var(--ui-muted); margin-top: 0.1rem; }

  .radio-group { display: flex; gap: 1rem; flex-shrink: 0; }
  .radio-label {
    display: flex; align-items: center; gap: 0.35rem;
    font-size: 0.83rem; color: var(--ui-body); cursor: pointer;
  }
  .radio-label input { accent-color: var(--ui-primary); cursor: pointer; }

  /* Dec offset arc picker */
  .option-row-dec { border-bottom: none; padding-bottom: 0; }

  .dec-picker {
    padding: 0.5rem 0 0.75rem;
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }

  .dec-arc-wrap {
    position: relative;
    width: 280px;
    height: 200px;
  }

  .dec-scope {
    position: absolute;
    width: 36px;
    height: auto;
    left: 50%;
    top: 42%;
    transform-origin: 50% 90%;
    transform: translateX(-50%) rotate(-60deg);
    transition: transform 0.3s ease;
    pointer-events: none;
    filter: brightness(1.4);
  }

  .dec-option {
    position: absolute;
    transform: translate(-50%, -50%);
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
    user-select: none;
  }
  .dec-option input[type="radio"] { display: none; }
  .dec-option span {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 2px solid rgba(255,255,255,0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--ui-muted);
    background: rgba(255,255,255,0.05);
    transition: border-color 0.15s, background 0.15s, color 0.15s;
  }
  .dec-option-selected span {
    border-color: var(--ui-primary);
    background: var(--ui-primary);
    color: #fff;
  }

  .dec-dir {
    position: absolute;
    bottom: 8px;
    font-size: 0.72rem;
    color: var(--ui-muted);
    user-select: none;
  }
  .dec-dir-left  { left: 4px; }
  .dec-dir-right { right: 4px; }

  .coords-section {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(255,255,255,0.07);
  }
  .coords-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--ui-body);
    margin: 0 0 0.65rem;
  }
  .coords-optional {
    font-size: 0.72rem;
    color: var(--ui-muted);
    font-weight: 400;
  }
  .coords-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }

  .action-row {
    display: flex;
    gap: 0.75rem;
    margin-top: 1.25rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(255,255,255,0.07);
    flex-wrap: wrap;
  }

  @media (max-width: 900px) {
    .events-grid { grid-template-columns: repeat(3, 1fr); }
  }
  @media (max-width: 540px) {
    .events-grid { grid-template-columns: repeat(2, 1fr); }
  }

  /* ── PA Refinement ───────────────────────────────────────────────────── */
  .pa-card { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 1rem; }

  .pa-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: inherit;
  }
  .pa-title { margin: 0; }
  .pa-chevron {
    font-size: 0.65rem;
    color: var(--ui-muted);
    transition: transform 0.2s ease;
    transform: rotate(0deg);
  }
  .pa-chevron-open { transform: rotate(90deg); }

  .pa-desc { font-size: 0.8rem; color: var(--ui-muted); margin: 0; }

  .pa-body {
    display: flex;
    gap: 1.5rem;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .pa-garden {
    position: relative;
    width: 360px;
    height: 360px;
    flex-shrink: 0;
    border: 2px solid rgba(255,255,255,0.15);
    border-radius: 10px;
    overflow: visible;
  }
  .pa-crosshair-h {
    position: absolute;
    top: 50%; left: 0; width: 100%; height: 0;
    border-top: 1px solid rgba(255,255,255,0.25);
  }
  .pa-crosshair-v {
    position: absolute;
    top: 0; left: 50%; width: 0; height: 100%;
    border-left: 1px solid rgba(255,255,255,0.25);
  }
  .pa-circle {
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: 50%;
  }
  .pa-ball {
    position: absolute;
    width: 12px; height: 12px;
    background: #fc8181;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    z-index: 10;
    transition: left 0.3s ease, top 0.3s ease;
  }

  .pa-controls {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 200px;
  }

  .pa-errors {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .pa-err-row {
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
    font-size: 0.85rem;
  }
  .pa-err-label { color: var(--ui-muted); min-width: 5rem; }
  .pa-err-val   { font-weight: 600; color: var(--ui-body); font-variant-numeric: tabular-nums; }

  .pa-slider-row { display: flex; flex-direction: column; gap: 0.3rem; }
  .pa-slider-label { font-size: 0.75rem; color: var(--ui-muted); }
  .pa-slider { width: 100%; accent-color: var(--ui-primary); cursor: pointer; }

  .pa-actions { display: flex; gap: 0.75rem; }

  .pa-instructions {
    font-size: 0.75rem;
    color: var(--ui-muted);
    line-height: 1.5;
  }
  .pa-instructions ol { margin: 0; padding-left: 1.1rem; }
  .pa-instructions li { margin-bottom: 0.2rem; }
</style>
