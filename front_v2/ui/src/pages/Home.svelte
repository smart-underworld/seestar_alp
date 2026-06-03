<script lang="ts">
  import { activeDeviceStatus, isConnected, activeDevNum, deviceList } from "../lib/stores/deviceStore";
  import { batteryColor, storagePct, storageColor } from "../lib/utils";

  $: s = $activeDeviceStatus;
  $: device = $deviceList.find((d) => d.device_num === $activeDevNum);
</script>

<div class="page-hero">
  <p class="page-kicker">Dashboard</p>
  <h1 class="page-title">{device?.name ?? "Telescope"}</h1>
  {#if device}
    <p class="page-subtitle">{device.ip_address}</p>
  {/if}
</div>

{#if !$isConnected}
  <div class="panel-card offline-card">
    <div class="offline-icon">📡</div>
    <div>
      <div class="offline-title">Device Offline</div>
      <div class="offline-sub">
        {device?.name ?? `Device ${$activeDevNum}`} is not reachable.
        Check that the telescope is powered on and connected to your network.
      </div>
    </div>
  </div>
{:else if s}
  <div class="stat-grid">

    <div class="panel-card stat-card">
      <p class="panel-title">State</p>
      <div class="big-value">{s.view_state || "Idle"}</div>
      {#if s.mode}
        <div class="sub-line">{s.mode}{s.stage ? ` · ${s.stage}` : ""}</div>
      {/if}
      {#if s.target}
        <div class="sub-line target">⌖ {s.target}</div>
      {/if}
    </div>

    <div class="panel-card stat-card">
      <p class="panel-title">Mount</p>
      <div class="big-value">{s.mount_mode}</div>
      {#if s.ra != null}
        <div class="sub-line coord">RA &nbsp;{s.ra.toFixed(5)}°</div>
      {/if}
      {#if s.dec != null}
        <div class="sub-line coord">Dec {s.dec >= 0 ? "+" : ""}{s.dec.toFixed(5)}°</div>
      {/if}
    </div>

    <div class="panel-card stat-card">
      <p class="panel-title">Capture Progress</p>
      {#if s.stacked !== "" && s.stacked != null}
        <div class="big-value success">{s.stacked} <span class="unit">stacked</span></div>
        {#if s.failed !== "" && s.failed != null && +s.failed > 0}
          <div class="sub-line danger">{s.failed} failed</div>
        {/if}
      {:else}
        <div class="big-value muted">—</div>
        <div class="sub-line">No active imaging session</div>
      {/if}
    </div>

    <div class="panel-card stat-card">
      <p class="panel-title">System</p>
      {#if s.battery_capacity != null}
        <div class="stat-row">
          <div class="stat-key">Battery</div>
          <div class="stat-value {batteryColor(s.battery_capacity)}">
            {s.battery_capacity}%
            <div class="metric-bar">
              <div class="metric-bar-fill {batteryColor(s.battery_capacity)}" style="width:{Math.min(100,s.battery_capacity)}%"></div>
            </div>
          </div>
        </div>
      {/if}
      {#if s.temp != null}
        <div class="stat-row">
          <div class="stat-key">Temperature</div>
          <div class="stat-value">{s.temp.toFixed(1)}°C</div>
        </div>
      {/if}
      {#if s.free_storage && s.free_storage !== "Unknown"}
        <div class="stat-row">
          <div class="stat-key">Free Storage</div>
          <div class="stat-value {storageColor(s.free_storage)}">
            {s.free_storage}
            <div class="metric-bar">
              <div class="metric-bar-fill {storageColor(s.free_storage)}" style="width:{storagePct(s.free_storage)}%"></div>
            </div>
          </div>
        </div>
      {/if}
    </div>

  </div>
{:else}
  <div class="loading">Loading device status…</div>
{/if}

<style>
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 1rem;
  }
  .stat-card { display: flex; flex-direction: column; }

  .big-value {
    font-size: 1.35rem;
    font-weight: 600;
    color: var(--ui-body);
    margin: 0.1rem 0 0.25rem;
    line-height: 1.2;
  }
  .big-value.success { color: var(--ui-success); }
  .big-value.muted   { color: var(--ui-muted); }
  .big-value .unit   { font-size: 0.78rem; font-weight: 400; color: var(--ui-muted); }

  .sub-line { font-size: 0.82rem; color: var(--ui-muted); margin: 0.1rem 0; }
  .sub-line.target { color: var(--ui-primary); }
  .sub-line.danger { color: var(--ui-danger); }
  .sub-line.coord  { font-variant-numeric: tabular-nums; font-family: "SF Mono", monospace; font-size: 0.78rem; }

  .offline-card {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    max-width: 540px;
  }
  .offline-icon  { font-size: 2rem; flex-shrink: 0; }
  .offline-title { font-weight: 600; color: var(--ui-danger); margin-bottom: 0.25rem; }
  .offline-sub   { font-size: 0.85rem; color: var(--ui-muted); line-height: 1.5; }

  .loading { color: var(--ui-muted); font-size: 0.9rem; padding: 2rem 0; }
</style>
