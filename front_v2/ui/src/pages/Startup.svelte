<script lang="ts">
  import { onDestroy } from "svelte";
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api, type EventState } from "../lib/api";

  let polarAlign = true;
  let autoFocus = true;
  let darkFrames = false;
  let lat = "";
  let lon = "";
  let decOffset = 3;

  let running = false;
  let stopping = false;
  let error = "";

  $: s = $activeDeviceStatus;
  $: schedState = (s as { schedule_state?: string })?.schedule_state ?? "";
  $: isRunning = schedState === "running" || schedState === "working";

  // ── Event status polling ───────────────────────────────────────────────────
  const EVENT_NAMES = ["3PPA", "AutoFocus", "DarkLibrary", "PlateSolve", "WheelMove", "Scheduler"] as const;
  type EventName = typeof EVENT_NAMES[number];

  const EVENT_LABELS: Record<EventName, string> = {
    "3PPA":        "Polar Align",
    "AutoFocus":   "Auto Focus",
    "DarkLibrary": "Dark Frames",
    "PlateSolve":  "Plate Solve",
    "WheelMove":   "Filter Wheel",
    "Scheduler":   "Scheduler",
  };

  let events: Record<string, EventState> = {};
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

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

  $: if ($isConnected) {
    if (pollTimer) clearTimeout(pollTimer);
    pollEvents();
  } else {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    events = {};
  }

  onDestroy(() => { if (pollTimer) clearTimeout(pollTimer); });

  function stateClass(ev: EventState | undefined): string {
    if (!ev?.state || ev.state === "idle") return "state-idle";
    if (ev.state === "in progress")        return "state-progress";
    if (ev.state === "complete")           return "state-complete";
    if (ev.state === "fail")              return "state-fail";
    return "state-idle";
  }

  function stateLabel(ev: EventState | undefined): string {
    return ev?.state || "Idle";
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
    } catch (e) {
      error = String(e);
    } finally {
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

{#if !$isConnected}
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
          {#if name === "Scheduler" && ev?.cur_scheduler_item?.type}
            <div class="event-detail">{ev.cur_scheduler_item.type}</div>
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

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Dec Offset (1–5)</div>
          <div class="option-help">Declination offset index for EQ polar alignment</div>
        </div>
        <input type="number" class="form-input dec-input" min="1" max="5" step="1" bind:value={decOffset} />
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
          {running ? "Starting…" : "▶ Run Startup Sequence"}
        </button>
        {#if isRunning}
          <button class="btn btn-danger" on:click={stop} disabled={stopping}>
            {stopping ? "Stopping…" : "⏹ Stop"}
          </button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }

  /* ── Event tiles ─────────────────────────────────────────────────────── */
  .events-card { margin-bottom: 1rem; }

  .events-grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
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

  .dec-input { width: 80px; text-align: center; flex-shrink: 0; }

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
</style>
