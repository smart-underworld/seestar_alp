<script lang="ts">
  import { activeDevNum, activeDeviceStatus, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let expMs = 10000;
  let gain = 80;
  let count = 0;
  let targetName = "";
  let status = "";
  let error = "";

  async function startImaging() {
    error = "";
    status = "Starting…";
    try {
      await api.devices.image.start($activeDevNum, {
        exp_ms: expMs,
        gain,
        count,
        target_name: targetName,
      });
      status = "Imaging started.";
    } catch (e) {
      error = String(e);
      status = "";
    }
  }

  async function stopImaging() {
    try {
      await api.devices.image.stop($activeDevNum);
      status = "Imaging stopped.";
    } catch (e) {
      error = String(e);
    }
  }

  $: stacked = $activeDeviceStatus?.stacked;
  $: failed = $activeDeviceStatus?.failed;
</script>

<h1>Image</h1>

{#if !$isConnected}
  <p class="offline">Device {$activeDevNum} is offline.</p>
{:else}
  {#if error}<p class="error">{error}</p>{/if}
  {#if status}<p class="info">{status}</p>{/if}

  {#if stacked !== ""}
    <div class="progress">
      <span>{stacked} stacked</span>
      {#if failed !== ""}<span class="failed">{failed} failed</span>{/if}
    </div>
  {/if}

  <form on:submit|preventDefault={startImaging}>
    <div class="field">
      <label for="tname">Target name</label>
      <input id="tname" bind:value={targetName} />
    </div>
    <div class="row">
      <div class="field">
        <label for="exp">Exposure (ms)</label>
        <input id="exp" type="number" bind:value={expMs} min="100" max="60000" />
      </div>
      <div class="field">
        <label for="gain">Gain</label>
        <input id="gain" type="number" bind:value={gain} min="0" max="100" />
      </div>
      <div class="field">
        <label for="count">Count (0=∞)</label>
        <input id="count" type="number" bind:value={count} min="0" />
      </div>
    </div>
    <div class="actions">
      <button type="submit">Start</button>
      <button type="button" class="secondary" on:click={stopImaging}>Stop</button>
    </div>
  </form>
{/if}

<style>
  h1 { margin-top: 0; }
  .offline, .error { color: #e94560; }
  .info { color: #68d391; }
  .progress { margin-bottom: 1rem; display: flex; gap: 1rem; font-size: 1.1rem; }
  .failed { color: #e94560; }
  form { display: flex; flex-direction: column; gap: 0.75rem; max-width: 480px; }
  .row { display: flex; gap: 0.75rem; }
  .row .field { flex: 1; }
  .field { display: flex; flex-direction: column; gap: 0.2rem; }
  label { font-size: 0.8rem; color: #a0aec0; }
  input {
    background: #16213e; border: 1px solid #0f3460;
    color: #e0e0e0; padding: 0.4rem 0.6rem; border-radius: 4px; width: 100%;
    box-sizing: border-box;
  }
  .actions { display: flex; gap: 0.75rem; }
  button {
    background: #e94560; color: white; border: none;
    padding: 0.5rem 1.5rem; border-radius: 4px; cursor: pointer;
  }
  button.secondary { background: #0f3460; }
</style>
