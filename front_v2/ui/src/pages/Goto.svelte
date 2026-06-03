<script lang="ts">
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let ra = "";
  let dec = "";
  let targetName = "";
  let status = "";
  let error = "";

  async function doGoto() {
    error = "";
    status = "Slewing…";
    try {
      await api.devices.goto($activeDevNum, ra, dec, targetName);
      status = "Goto command sent.";
    } catch (e) {
      error = String(e);
      status = "";
    }
  }

  async function stopGoto() {
    try {
      await fetch(`/api/v1/devices/${$activeDevNum}/goto`, { method: "DELETE" });
      status = "Goto cancelled.";
    } catch (e) {
      error = String(e);
    }
  }
</script>

<h1>Goto</h1>

{#if !$isConnected}
  <p class="offline">Device {$activeDevNum} is offline.</p>
{:else}
  {#if error}<p class="error">{error}</p>{/if}
  {#if status}<p class="info">{status}</p>{/if}

  <form on:submit|preventDefault={doGoto}>
    <div class="field">
      <label for="target">Target name</label>
      <input id="target" bind:value={targetName} placeholder="M31, NGC 224, …" />
    </div>
    <div class="row">
      <div class="field">
        <label for="ra">RA (J2000)</label>
        <input id="ra" bind:value={ra} placeholder="10h 45m 3.6s" required />
      </div>
      <div class="field">
        <label for="dec">Dec (J2000)</label>
        <input id="dec" bind:value={dec} placeholder="+41° 16′" required />
      </div>
    </div>
    <div class="actions">
      <button type="submit">Goto</button>
      <button type="button" class="secondary" on:click={stopGoto}>Stop</button>
    </div>
  </form>
{/if}

<style>
  h1 { margin-top: 0; }
  .offline, .error { color: #e94560; }
  .info { color: #68d391; }
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
