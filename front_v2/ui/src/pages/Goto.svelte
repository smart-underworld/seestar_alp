<script lang="ts">
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let ra = "";
  let dec = "";
  let targetName = "";
  let status = "";
  let error = "";
  let slewing = false;

  async function doGoto() {
    error = "";
    status = "";
    slewing = true;
    try {
      await api.devices.goto($activeDevNum, ra, dec, targetName);
      status = "GoTo command sent — telescope is slewing.";
    } catch (e) {
      error = String(e);
    } finally {
      slewing = false;
    }
  }

  async function stopGoto() {
    error = "";
    try {
      await fetch(`/api/v1/devices/${$activeDevNum}/goto`, { method: "DELETE" });
      status = "GoTo cancelled.";
    } catch (e) {
      error = String(e);
    }
  }

  $: s = $activeDeviceStatus;
</script>

<div class="page-hero">
  <p class="page-kicker">Navigation</p>
  <h1 class="page-title">GoTo Target</h1>
  <p class="page-subtitle">Slew the telescope to a sky coordinate or named object.</p>
</div>

{#if !$isConnected}
  <div class="panel-card offline-msg">
    Device {$activeDevNum} is offline. Connect to use GoTo.
  </div>
{:else}
  <div class="goto-layout">

    <div class="panel-card goto-form-card">
      {#if error}<div class="alert alert-error">{error}</div>{/if}
      {#if status}<div class="alert alert-success">{status}</div>{/if}

      <form on:submit|preventDefault={doGoto}>
        <div class="form-field" style="margin-bottom:1rem">
          <label class="form-label" for="tname">Target Name</label>
          <input id="tname" class="form-input" bind:value={targetName} placeholder="M31, NGC 224, Andromeda…" />
          <span class="field-hint">Optional — for display purposes only.</span>
        </div>

        <div class="coord-row">
          <div class="form-field">
            <label class="form-label" for="ra">Right Ascension (J2000)</label>
            <input id="ra" class="form-input" bind:value={ra} placeholder="10h 45m 3.6s" required />
          </div>
          <div class="form-field">
            <label class="form-label" for="dec">Declination (J2000)</label>
            <input id="dec" class="form-input" bind:value={dec} placeholder="+41° 16′ 9″" required />
          </div>
        </div>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary" disabled={slewing}>
            {#if slewing}⏳ Slewing…{:else}⌖ GoTo{/if}
          </button>
          <button type="button" class="btn btn-danger" on:click={stopGoto}>
            ⏹ Stop
          </button>
        </div>
      </form>
    </div>

    {#if s && (s.ra != null || s.mount_mode)}
      <div class="panel-card position-card">
        <p class="panel-title">Current Position</p>
        {#if s.mount_mode}
          <div class="stat-row">
            <div class="stat-key">Mount</div>
            <div class="stat-value">{s.mount_mode}</div>
          </div>
        {/if}
        {#if s.ra != null}
          <div class="stat-row">
            <div class="stat-key">RA (J2000)</div>
            <div class="stat-value coord">{s.ra.toFixed(6)}°</div>
          </div>
        {/if}
        {#if s.dec != null}
          <div class="stat-row">
            <div class="stat-key">Dec (J2000)</div>
            <div class="stat-value coord">{s.dec >= 0 ? "+" : ""}{s.dec.toFixed(6)}°</div>
          </div>
        {/if}
        {#if s.target}
          <div class="stat-row">
            <div class="stat-key">Last Target</div>
            <div class="stat-value">{s.target}</div>
          </div>
        {/if}
        {#if s.view_state && s.view_state !== "Idle"}
          <div class="stat-row">
            <div class="stat-key">State</div>
            <div class="stat-value">{s.view_state}</div>
          </div>
        {/if}
      </div>
    {/if}

  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }

  .goto-layout {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .goto-form-card { flex: 1; min-width: 320px; }
  .position-card  { width: 260px; flex-shrink: 0; }

  .coord-row {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }
  .coord-row .form-field { flex: 1; }

  .field-hint {
    font-size: 0.72rem;
    color: var(--ui-muted);
    margin-top: 0.15rem;
  }

  .form-actions {
    display: flex;
    gap: 0.6rem;
    margin-top: 0.25rem;
  }

  .coord {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.82rem;
    font-variant-numeric: tabular-nums;
  }

  @media (max-width: 600px) {
    .coord-row { flex-direction: column; }
    .position-card { width: 100%; }
  }
</style>
