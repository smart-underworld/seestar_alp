<script lang="ts">
  import { activeDevNum, activeDeviceStatus, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";
  import EventStatusPanel from "../lib/components/EventStatusPanel.svelte";

  const EVENTS = ["WheelMove", "AutoGoto", "PlateSolve", "DarkLibrary", "AutoFocus", "Stack"];

  let expMs = 10000;
  let gain = 80;
  let count = 0;
  let targetName = "";
  let status = "";
  let error = "";
  let imaging = false;

  async function startImaging() {
    error = "";
    status = "";
    imaging = true;
    try {
      await api.devices.image.start($activeDevNum, {
        exp_ms: expMs,
        gain,
        count,
        target_name: targetName,
      });
      status = "Imaging session started.";
    } catch (e) {
      error = String(e);
    } finally {
      imaging = false;
    }
  }

  async function stopImaging() {
    error = "";
    try {
      await api.devices.image.stop($activeDevNum);
      status = "Imaging stopped.";
    } catch (e) {
      error = String(e);
    }
  }

  $: s = $activeDeviceStatus;
  $: stacked = s?.stacked;
  $: failed  = s?.failed;
  $: isActive = stacked !== "" && stacked != null;
</script>

<div class="page-hero">
  <p class="page-kicker">Capture</p>
  <h1 class="page-title">Image</h1>
  <p class="page-subtitle">Configure and start an imaging session.</p>
</div>

<EventStatusPanel events={EVENTS} />

{#if !$isConnected}
  <div class="panel-card offline-msg">
    Device {$activeDevNum} is offline. Connect to start imaging.
  </div>
{:else}
  <div class="image-layout">

    <!-- Progress / live status -->
    {#if isActive}
      <div class="panel-card progress-card">
        <p class="panel-title">Session Progress</p>
        <div class="progress-nums">
          <div class="prog-val success">
            {stacked}
            <span class="prog-unit">stacked</span>
          </div>
          {#if failed !== "" && failed != null && +failed > 0}
            <div class="prog-val danger">
              {failed}
              <span class="prog-unit">failed</span>
            </div>
          {/if}
        </div>
        {#if s?.target}
          <div class="target-line">⌖ {s.target}</div>
        {/if}
      </div>
    {/if}

    <!-- Controls -->
    <div class="panel-card form-card">
      {#if error}<div class="alert alert-error">{error}</div>{/if}
      {#if status}<div class="alert alert-success">{status}</div>{/if}

      <form on:submit|preventDefault={startImaging}>
        <div class="form-field" style="margin-bottom:1rem">
          <label class="form-label" for="iname">Target Name</label>
          <input id="iname" class="form-input" bind:value={targetName} placeholder="e.g. M42, Orion Nebula" />
        </div>

        <div class="param-grid">
          <div class="form-field">
            <label class="form-label" for="iexp">Exposure (ms)</label>
            <input id="iexp" type="number" class="form-input" bind:value={expMs} min="100" max="60000" step="100" />
          </div>
          <div class="form-field">
            <label class="form-label" for="igain">Gain</label>
            <input id="igain" type="number" class="form-input" bind:value={gain} min="0" max="300" />
          </div>
          <div class="form-field">
            <label class="form-label" for="icount">Frame Count</label>
            <input id="icount" type="number" class="form-input" bind:value={count} min="0" />
            <span class="field-hint">0 = unlimited</span>
          </div>
        </div>

        <div class="param-summary">
          Exposure <strong>{expMs} ms</strong> · Gain <strong>{gain}</strong>
          {#if count > 0} · <strong>{count}</strong> frames{:else} · Continuous{/if}
        </div>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary" disabled={imaging}>
            {imaging ? "Starting…" : "▶ Start"}
          </button>
          <button type="button" class="btn btn-danger" on:click={stopImaging}>
            ⏹ Stop
          </button>
        </div>
      </form>
    </div>

  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }

  .image-layout {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .progress-card {}
  .progress-nums {
    display: flex;
    gap: 2rem;
    margin: 0.25rem 0;
  }
  .prog-val {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
    color: var(--ui-body);
  }
  .prog-val.success { color: var(--ui-success); }
  .prog-val.danger  { color: var(--ui-danger); }
  .prog-unit {
    font-size: 0.75rem;
    font-weight: 400;
    color: var(--ui-muted);
    display: block;
    margin-top: 0.2rem;
  }
  .target-line {
    font-size: 0.82rem;
    color: var(--ui-primary);
    margin-top: 0.5rem;
  }

  .param-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  .field-hint { font-size: 0.72rem; color: var(--ui-muted); margin-top: 0.15rem; }

  .param-summary {
    font-size: 0.8rem;
    color: var(--ui-muted);
    margin-bottom: 1rem;
    padding: 0.5rem 0.75rem;
    background: rgba(255,255,255,0.03);
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.06);
  }
  .param-summary strong { color: var(--ui-body); }

  .form-actions { display: flex; gap: 0.6rem; }

  @media (max-width: 500px) {
    .param-grid { grid-template-columns: 1fr; }
  }
</style>
