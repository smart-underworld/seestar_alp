<script lang="ts">
  import { activeDeviceStatus, isConnected, activeDevNum, deviceList } from "../lib/stores/deviceStore";
  import { batteryColor, storagePct, storageColor } from "../lib/utils";

  $: s = $activeDeviceStatus;
  $: device = $deviceList.find((d) => d.device_num === $activeDevNum);

  function wifiColor(signal: string): "success" | "warning" | "danger" {
    if (!signal) return "danger";
    const m = signal.match(/-?\d+/);
    if (!m) return "danger";
    const dbm = parseInt(m[0], 10);
    if (dbm >= -69) return "success";
    if (dbm >= -80) return "warning";
    return "danger";
  }

  function fmt(v: unknown, unit = ""): string {
    if (v == null || v === "") return "—";
    return `${v}${unit}`;
  }
</script>

<div class="page-hero">
  <p class="page-kicker">Dashboard</p>
  <h1 class="page-title">{device?.name ?? "Telescope"}</h1>
  {#if device}
    <p class="page-subtitle">{device.ip_address}</p>
  {/if}
</div>

{#if !s || !s.backend_ready}
  <div class="panel-card init-card">
    <div class="init-spinner"></div>
    <div>
      <div class="init-title">Initializing…</div>
      <div class="init-sub">Seestar ALP is starting up. The telescope will connect automatically.</div>
    </div>
  </div>
{:else if !s.is_connected}
  <div class="panel-card offline-card">
    <div class="offline-icon">📡</div>
    <div>
      <div class="offline-title">Telescope Offline</div>
      <div class="offline-sub">
        {device?.name ?? `Device ${$activeDevNum}`} is not reachable.
        Check that the telescope is powered on and connected to your network.
      </div>
    </div>
  </div>
{:else}
  <div class="stat-grid">

    <!-- Card 1: State -->
    <div class="panel-card stat-card">
      <p class="panel-title">State</p>
      <div class="big-value">{s.view_state || "Idle"}</div>
      {#if s.mode}
        <div class="sub-line">{s.mode}{s.stage ? ` · ${s.stage}` : ""}</div>
      {/if}
      {#if s.target}
        <div class="sub-line target">&#x2316; {s.target}</div>
      {/if}
      {#if s.schedule_state}
        <div class="badge">{s.schedule_state}</div>
      {/if}
    </div>

    <!-- Card 2: Mount -->
    <div class="panel-card stat-card">
      <p class="panel-title">Mount</p>
      <div class="big-value">{s.mount_mode}</div>
      {#if s.ra != null}
        <div class="sub-line coord">RA &nbsp;&nbsp;{s.ra.toFixed(5)}&deg;</div>
      {/if}
      {#if s.dec != null}
        <div class="sub-line coord">Dec &nbsp;{s.dec >= 0 ? "+" : ""}{s.dec.toFixed(5)}&deg;</div>
      {/if}
    </div>

    <!-- Card 3: Capture -->
    <div class="panel-card stat-card">
      <p class="panel-title">Capture</p>
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

    <!-- Card 4: Power -->
    <div class="panel-card stat-card">
      <p class="panel-title">Power</p>
      {#if s.battery_capacity != null}
        <div class="stat-row">
          <div class="stat-key">Battery</div>
          <div class="stat-value {batteryColor(s.battery_capacity)}">
            {s.battery_capacity}%
            <div class="metric-bar">
              <div class="metric-bar-fill {batteryColor(s.battery_capacity)}" style="width:{Math.min(100, s.battery_capacity)}%"></div>
            </div>
          </div>
        </div>
      {/if}
      <div class="stat-row">
        <div class="stat-key">Charge</div>
        <div class="stat-value">{fmt(s.charge_status)}</div>
      </div>
      <div class="stat-row">
        <div class="stat-key">Batt Temp</div>
        <div class="stat-value">{s.battery_temp != null ? `${Number(s.battery_temp).toFixed(1)}°C` : "—"}</div>
      </div>
      {#if s.temp != null}
        <div class="stat-row">
          <div class="stat-key">CPU Temp</div>
          <div class="stat-value">{s.temp.toFixed(1)}°C</div>
        </div>
      {/if}
    </div>

    <!-- Card 5: Storage & Network -->
    <div class="panel-card stat-card">
      <p class="panel-title">Storage &amp; Network</p>
      {#if s.free_storage && s.free_storage !== "Unknown"}
        <div class="stat-row">
          <div class="stat-key">Free</div>
          <div class="stat-value {storageColor(s.free_storage)}">
            {s.free_storage}
            <div class="metric-bar">
              <div class="metric-bar-fill {storageColor(s.free_storage)}" style="width:{storagePct(s.free_storage)}%"></div>
            </div>
          </div>
        </div>
      {/if}
      <div class="stat-row">
        <div class="stat-key">Wi-Fi</div>
        <div class="stat-value {wifiColor(s.wifi_signal)}">{fmt(s.wifi_signal)}</div>
      </div>
    </div>

    <!-- Card 6: Telescope -->
    <div class="panel-card stat-card">
      <p class="panel-title">Telescope</p>
      <div class="stat-row">
        <div class="stat-key">Firmware</div>
        <div class="stat-value">{fmt(s.firmware_ver)}</div>
      </div>
      <div class="stat-row">
        <div class="stat-key">Focus</div>
        <div class="stat-value">{fmt(s.focal_position)}</div>
      </div>
      <div class="stat-row">
        <div class="stat-key">Balance</div>
        <div class="stat-value">{s.balance_angle != null ? s.balance_angle : "—"}</div>
      </div>
      <div class="stat-row">
        <div class="stat-key">Compass</div>
        <div class="stat-value">{s.compass_direction != null ? s.compass_direction : "—"}</div>
      </div>
      <div class="stat-row">
        <div class="stat-key">Auto Off</div>
        <div class="stat-value">{s.auto_power_off ? "On" : "Off"}</div>
      </div>
      <div class="stat-row">
        <div class="stat-key">Heater</div>
        <div class="stat-value">{s.heater_enable ? "On" : "Off"}</div>
      </div>
    </div>

  </div>
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

  .stat-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.5rem;
    margin: 0.2rem 0;
    font-size: 0.82rem;
  }
  .stat-key   { color: var(--ui-muted); white-space: nowrap; flex-shrink: 0; }
  .stat-value { color: var(--ui-body); text-align: right; word-break: break-word; }
  .stat-value.success { color: var(--ui-success); }
  .stat-value.warning { color: var(--ui-warning); }
  .stat-value.danger  { color: var(--ui-danger); }

  .metric-bar {
    height: 3px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
    margin-top: 3px;
    width: 100%;
    min-width: 60px;
  }
  .metric-bar-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.4s ease;
  }
  .metric-bar-fill.success { background: var(--ui-success); }
  .metric-bar-fill.warning { background: var(--ui-warning); }
  .metric-bar-fill.danger  { background: var(--ui-danger); }

  .badge {
    display: inline-block;
    margin-top: 0.4rem;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    background: rgba(255, 255, 255, 0.08);
    color: var(--ui-primary);
    text-transform: capitalize;
    letter-spacing: 0.03em;
  }

  .init-card, .offline-card {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    max-width: 540px;
  }
  .init-spinner {
    width: 2rem;
    height: 2rem;
    border-radius: 50%;
    border: 3px solid rgba(255, 255, 255, 0.1);
    border-top-color: var(--ui-primary);
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .init-title { font-weight: 600; color: var(--ui-muted); margin-bottom: 0.25rem; }
  .init-sub   { font-size: 0.85rem; color: var(--ui-muted); line-height: 1.5; opacity: 0.7; }

  .offline-icon  { font-size: 2rem; flex-shrink: 0; }
  .offline-title { font-weight: 600; color: var(--ui-danger); margin-bottom: 0.25rem; }
  .offline-sub   { font-size: 0.85rem; color: var(--ui-muted); line-height: 1.5; }
</style>
