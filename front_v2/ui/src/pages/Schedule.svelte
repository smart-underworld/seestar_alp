<script lang="ts">
  import { onMount } from "svelte";
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let schedule: unknown = null;
  let error = "";

  async function load() {
    error = "";
    try {
      schedule = await api.devices.schedule.get($activeDevNum);
    } catch (e) {
      error = String(e);
    }
  }

  async function clearSchedule() {
    try {
      await api.devices.schedule.clear($activeDevNum);
      schedule = null;
    } catch (e) {
      error = String(e);
    }
  }

  onMount(load);
  $: if ($activeDevNum) load();
</script>

<h1>Schedule</h1>

{#if !$isConnected}
  <p class="offline">Device {$activeDevNum} is offline.</p>
{:else}
  {#if error}<p class="error">{error}</p>{/if}
  <div class="actions">
    <button on:click={load}>Refresh</button>
    <button class="secondary" on:click={clearSchedule}>Clear</button>
  </div>

  {#if schedule}
    <pre class="schedule-json">{JSON.stringify(schedule, null, 2)}</pre>
  {:else}
    <p>No schedule data.</p>
  {/if}
{/if}

<style>
  h1 { margin-top: 0; }
  .offline, .error { color: #e94560; }
  .actions { display: flex; gap: 0.75rem; margin-bottom: 1rem; }
  button {
    background: #e94560; color: white; border: none;
    padding: 0.5rem 1.5rem; border-radius: 4px; cursor: pointer;
  }
  button.secondary { background: #0f3460; }
  .schedule-json {
    background: #16213e; border: 1px solid #0f3460;
    padding: 1rem; border-radius: 4px;
    overflow: auto; font-size: 0.8rem; color: #a0aec0;
  }
</style>
