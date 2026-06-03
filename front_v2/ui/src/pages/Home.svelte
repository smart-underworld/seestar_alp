<script lang="ts">
  import { activeDeviceStatus, isConnected, activeDevNum } from "../lib/stores/deviceStore";
</script>

<h1>Dashboard</h1>

{#if !$isConnected}
  <p class="offline">Device {$activeDevNum} is offline or not connected.</p>
{:else if $activeDeviceStatus}
  {@const s = $activeDeviceStatus}
  <div class="grid">
    <div class="card">
      <h3>State</h3>
      <p class="value">{s.view_state || "—"}</p>
      {#if s.mode}<p class="sub">{s.mode}{s.stage ? ` · ${s.stage}` : ""}</p>{/if}
      {#if s.target}<p class="sub">Target: {s.target}</p>{/if}
    </div>

    <div class="card">
      <h3>Mount</h3>
      <p class="value">{s.mount_mode}</p>
      {#if s.ra != null}<p class="sub">RA {s.ra.toFixed(4)}°</p>{/if}
      {#if s.dec != null}<p class="sub">Dec {s.dec.toFixed(4)}°</p>{/if}
    </div>

    <div class="card">
      <h3>Progress</h3>
      <p class="value">{s.stacked !== "" ? `${s.stacked} stacked` : "—"}</p>
      {#if s.failed !== ""}<p class="sub">{s.failed} failed</p>{/if}
    </div>

    <div class="card">
      <h3>System</h3>
      {#if s.battery_capacity != null}
        <p class="sub">Battery {s.battery_capacity}%</p>
      {/if}
      {#if s.temp != null}
        <p class="sub">Temp {s.temp}°C</p>
      {/if}
      <p class="sub">Storage {s.free_storage}</p>
    </div>
  </div>
{:else}
  <p>Loading…</p>
{/if}

<style>
  h1 { margin-top: 0; }
  .offline { color: #e94560; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1rem;
  }
  .card {
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 1rem;
  }
  .card h3 {
    margin: 0 0 0.5rem;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #718096;
  }
  .value {
    margin: 0;
    font-size: 1.4rem;
    font-weight: 600;
    color: #e94560;
  }
  .sub {
    margin: 0.25rem 0 0;
    font-size: 0.85rem;
    color: #a0aec0;
  }
</style>
