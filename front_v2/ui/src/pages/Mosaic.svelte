<script lang="ts">
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";
  import EventStatusPanel from "../lib/components/EventStatusPanel.svelte";

  const EVENTS = ["WheelMove", "AutoGoto", "PlateSolve", "DarkLibrary", "AutoFocus", "Stack"];

  let targetName = "";
  let ra = "";
  let dec = "";
  let isJ2000 = true;
  let raPanels = 2;
  let decPanels = 2;
  let panelOverlap = 10;
  let panelTimeSec = 3600;
  let gain = 80;
  let useLpFilter = false;
  let useAutoFocus = false;
  let numTries = 1;
  let retryWaitS = 300;
  let stackType = "DeepSky";

  let status = "";
  let error = "";
  let submitting = false;

  $: isFederation = $activeDevNum === 0;
  let federationMode = "duplicate";
  let maxDevices = 1;

  function panelTimeDisplay(sec: number): string {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (h > 0 && m > 0) return `${h}h ${m}m`;
    if (h > 0) return `${h}h`;
    return `${m}m`;
  }

  function parsePanelTime(val: string): number {
    val = val.trim();
    let total = 0;
    const hMatch = val.match(/(\d+)\s*h/i);
    const mMatch = val.match(/(\d+)\s*m/i);
    const sMatch = val.match(/^(\d+)$/);
    if (hMatch) total += parseInt(hMatch[1]) * 3600;
    if (mMatch) total += parseInt(mMatch[1]) * 60;
    if (sMatch) total = parseInt(sMatch[1]);
    return total || 3600;
  }

  let panelTimeRaw = "1h";

  async function submit() {
    error = "";
    status = "";
    submitting = true;
    try {
      const body: Record<string, unknown> = {
        target_name: targetName,
        ra,
        dec,
        is_j2000: isJ2000,
        ra_num: raPanels,
        dec_num: decPanels,
        panel_overlap_percent: panelOverlap,
        panel_time_sec: parsePanelTime(panelTimeRaw),
        gain,
        is_use_lp_filter: useLpFilter,
        is_use_autofocus: useAutoFocus,
        num_tries: numTries,
        retry_wait_s: retryWaitS,
        stack_type: stackType,
      };
      if (isFederation) {
        body.federation_mode = federationMode;
        body.max_devices = maxDevices;
      }
      await api.devices.mosaic.start($activeDevNum, body as any);
      status = "Mosaic started successfully.";
    } catch (e) {
      error = String(e);
    } finally {
      submitting = false;
    }
  }
</script>

<div class="page-hero">
  <div>
    <p class="page-kicker">Imaging</p>
    <h1 class="page-title">Mosaic</h1>
    <p class="page-subtitle">Create and run a multi-panel mosaic. For scheduling, use the Schedule page.</p>
  </div>
</div>

<EventStatusPanel events={EVENTS} />

{#if !$isConnected}
  <div class="panel-card offline-msg">Device {$activeDevNum} is offline.</div>
{:else}
  {#if status}
    <div class="alert alert-success">{status}</div>
  {/if}
  {#if error}
    <div class="alert alert-error">{error}</div>
  {/if}

  <form on:submit|preventDefault={submit} class="mosaic-form">

    <!-- Target -->
    <div class="panel-card">
      <p class="panel-title">Target</p>
      <div class="field-row">
        <div class="form-field">
          <label class="form-label" for="targetName">Target Name</label>
          <input id="targetName" class="form-input" bind:value={targetName} required placeholder="e.g. Andromeda Galaxy" />
        </div>
      </div>
      <div class="field-row two-col">
        <div class="form-field">
          <label class="form-label" for="ra">Right Ascension</label>
          <input id="ra" class="form-input" bind:value={ra} required placeholder="e.g. 0h42m44s or 0.7122" />
        </div>
        <div class="form-field">
          <label class="form-label" for="dec">Declination</label>
          <input id="dec" class="form-input" bind:value={dec} required placeholder="e.g. +41d16m9s or 41.27" />
        </div>
      </div>
      <label class="check-label">
        <input type="checkbox" bind:checked={isJ2000} />
        Use J2000 coordinates
      </label>
    </div>

    <!-- Panels -->
    <div class="panel-card">
      <p class="panel-title">Panels</p>
      <div class="field-row three-col">
        <div class="form-field">
          <label class="form-label" for="raPanels">RA Panels</label>
          <input id="raPanels" class="form-input" type="number" min="1" bind:value={raPanels} required />
        </div>
        <div class="form-field">
          <label class="form-label" for="decPanels">Dec Panels</label>
          <input id="decPanels" class="form-input" type="number" min="1" bind:value={decPanels} required />
        </div>
        <div class="form-field">
          <label class="form-label" for="panelOverlap">Overlap (%)</label>
          <input id="panelOverlap" class="form-input" type="number" min="0" max="50" bind:value={panelOverlap} required />
        </div>
      </div>
      <div class="panel-summary">
        {raPanels} × {decPanels} = {raPanels * decPanels} panel{raPanels * decPanels !== 1 ? "s" : ""}
      </div>
    </div>

    <!-- Exposure -->
    <div class="panel-card">
      <p class="panel-title">Exposure</p>
      <div class="field-row three-col">
        <div class="form-field">
          <label class="form-label" for="panelTime">Time per Panel</label>
          <input id="panelTime" class="form-input" bind:value={panelTimeRaw} placeholder="e.g. 1h 30m or 5400" required />
          <span class="field-hint">Hours/minutes or seconds</span>
        </div>
        <div class="form-field">
          <label class="form-label" for="gain">Gain</label>
          <input id="gain" class="form-input" type="number" min="0" max="150" bind:value={gain} required />
        </div>
        <div class="form-field">
          <label class="form-label" for="stackType">Stack Mode</label>
          <select id="stackType" class="form-input" bind:value={stackType}>
            <option value="DeepSky">Deep Sky</option>
            <option value="SolarSystem">Planetary</option>
            <option value="MilkyWay">Milky Way</option>
          </select>
        </div>
      </div>
      <div class="check-row">
        <label class="check-label">
          <input type="checkbox" bind:checked={useLpFilter} />
          Use Light Pollution Filter
        </label>
        <label class="check-label">
          <input type="checkbox" bind:checked={useAutoFocus} />
          Auto-focus each panel
        </label>
      </div>
    </div>

    <!-- Retry -->
    <div class="panel-card">
      <p class="panel-title">Retry</p>
      <div class="field-row two-col">
        <div class="form-field">
          <label class="form-label" for="numTries">Retries</label>
          <input id="numTries" class="form-input" type="number" min="0" bind:value={numTries} />
          <span class="field-hint">Times to retry a failed GoTo (default 1)</span>
        </div>
        <div class="form-field">
          <label class="form-label" for="retryWait">Retry Delay (s)</label>
          <input id="retryWait" class="form-input" type="number" min="0" bind:value={retryWaitS} />
          <span class="field-hint">Seconds between retries (default 300)</span>
        </div>
      </div>
    </div>

    {#if isFederation}
      <div class="panel-card">
        <p class="panel-title">Federation</p>
        <div class="field-row two-col">
          <div class="form-field">
            <label class="form-label" for="fedMode">Mode</label>
            <select id="fedMode" class="form-input" bind:value={federationMode}>
              <option value="duplicate">Duplicate</option>
              <option value="by_time">Split By Time</option>
              <option value="by_panel">Split By Panel</option>
            </select>
          </div>
          <div class="form-field">
            <label class="form-label" for="maxDev">Max Devices</label>
            <input id="maxDev" class="form-input" type="number" min="1" bind:value={maxDevices} />
          </div>
        </div>
      </div>
    {/if}

    <div class="submit-row">
      <button type="submit" class="btn btn-primary" disabled={submitting}>
        {submitting ? "Starting…" : "Start Mosaic"}
      </button>
    </div>

  </form>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); }

  .mosaic-form { display: flex; flex-direction: column; gap: 1rem; }

  .field-row { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 0.75rem; }
  .field-row.two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  .field-row.three-col {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 1rem;
  }
  @media (max-width: 640px) {
    .field-row.two-col,
    .field-row.three-col { grid-template-columns: 1fr; }
  }

  .field-hint {
    font-size: 0.75rem;
    color: var(--ui-muted);
    margin-top: 0.2rem;
    display: block;
  }

  .panel-summary {
    font-size: 0.82rem;
    color: var(--ui-muted);
    margin-top: 0.25rem;
  }

  .check-row {
    display: flex;
    gap: 1.5rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
  }

  .check-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: var(--ui-body);
    cursor: pointer;
  }
  .check-label input[type="checkbox"] { accent-color: var(--ui-primary); }

  .submit-row { display: flex; justify-content: flex-end; }
</style>
