<script lang="ts">
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let polarAlign = true;
  let autoFocus = true;
  let darkFrames = false;
  let lat = "";
  let lon = "";
  let decOffset = 3;

  let running = false;
  let stopping = false;
  let result: unknown = null;
  let error = "";

  $: s = $activeDeviceStatus;
  $: schedState = (s as { schedule_state?: string })?.schedule_state ?? "";
  $: isRunning = schedState === "running" || schedState === "working";

  async function start() {
    running = true;
    error = "";
    result = null;
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
      result = await api.devices.startup($activeDevNum, params);
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

  {#if isRunning}
    <div class="alert alert-info running-banner">
      Startup sequence is running — scheduler state: <strong>{schedState}</strong>
    </div>
  {/if}

  <div class="startup-layout">
    <div class="panel-card options-card">
      <p class="panel-title">Startup Options</p>

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Polar Align</div>
          <div class="option-help">Run 3-point polar alignment at session start</div>
        </div>
        <div class="radio-group">
          <label class="radio-label">
            <input type="radio" bind:group={polarAlign} value={true} /> On
          </label>
          <label class="radio-label">
            <input type="radio" bind:group={polarAlign} value={false} /> Off
          </label>
        </div>
      </div>

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Auto Focus</div>
          <div class="option-help">Run auto-focus routine before imaging</div>
        </div>
        <div class="radio-group">
          <label class="radio-label">
            <input type="radio" bind:group={autoFocus} value={true} /> On
          </label>
          <label class="radio-label">
            <input type="radio" bind:group={autoFocus} value={false} /> Off
          </label>
        </div>
      </div>

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Dark Frames</div>
          <div class="option-help">Capture dark calibration frames</div>
        </div>
        <div class="radio-group">
          <label class="radio-label">
            <input type="radio" bind:group={darkFrames} value={true} /> On
          </label>
          <label class="radio-label">
            <input type="radio" bind:group={darkFrames} value={false} /> Off
          </label>
        </div>
      </div>

      <div class="option-row">
        <div class="option-meta">
          <div class="option-label">Dec Offset (1–5)</div>
          <div class="option-help">Declination offset index for EQ polar alignment</div>
        </div>
        <input
          type="number"
          class="form-input dec-input"
          min="1" max="5" step="1"
          bind:value={decOffset}
        />
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
        <button
          class="btn btn-primary"
          on:click={start}
          disabled={running || isRunning}
        >
          {running ? "Starting…" : "▶ Run Startup Sequence"}
        </button>
        {#if isRunning}
          <button class="btn btn-danger" on:click={stop} disabled={stopping}>
            {stopping ? "Stopping…" : "⏹ Stop"}
          </button>
        {/if}
      </div>
    </div>

    {#if result !== null}
      <div class="panel-card result-card">
        <p class="panel-title">Response</p>
        <pre class="result-pre">{JSON.stringify(result, null, 2)}</pre>
      </div>
    {/if}
  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }
  .running-banner { margin-bottom: 1rem; }

  .startup-layout {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    max-width: 600px;
  }

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

  .result-card {}
  .result-pre {
    margin: 0;
    padding: 0.75rem;
    background: rgba(0,0,0,0.25);
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.06);
    font-size: 0.78rem;
    color: var(--ui-muted);
    overflow: auto;
    max-height: 300px;
    font-family: "SF Mono","Fira Code",monospace;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
