<script lang="ts">
  import { onMount } from "svelte";

  interface ConfigData {
    networking: Record<string, unknown>;
    webui: Record<string, unknown>;
    logging: Record<string, unknown>;
    init: Record<string, unknown>;
    devices: Array<{ device_num: number; name: string; ip_address: string }>;
  }

  let config: ConfigData | null = null;
  let loading = true;
  let error = "";

  const NETWORKING_LABELS: Record<string, string> = {
    ip_address: "IP Address",
    port:       "Alpaca Port",
    imgport:    "Image Port",
    stport:     "Stellarium Port",
    sthost:     "Stellarium Host",
    timeout:    "Timeout (s)",
    rtsp_udp:   "RTSP UDP",
  };

  const WEBUI_LABELS: Record<string, string> = {
    uiport:        "UI Port",
    ui_theme:      "UI Theme",
    experimental:  "Experimental Features",
    confirm:       "Confirmation Dialog",
    save_frames:   "Save Preview Frames",
    save_frames_dir: "Save Frames Directory",
    frontend:      "Frontend Version",
  };

  const LOGGING_LABELS: Record<string, string> = {
    log_level:      "Log Level",
    log_to_stdout:  "Log to Stdout",
    max_log_size_mb: "Max Log Size (MB)",
    log_num_keep:   "Logs to Keep",
    log_prefix:     "Log Prefix",
  };

  const INIT_LABELS: Record<string, string> = {
    latitude:          "Latitude",
    longitude:         "Longitude",
    gain:              "Gain",
    exp_ms_preview:    "Exposure Preview (ms)",
    exp_ms_stack_l:    "Exposure Stack (ms)",
    dither_enabled:    "Dither",
    dither_length_pixel: "Dither Length (px)",
    dither_frequency:  "Dither Frequency",
    lp_filter:         "LP Filter",
    heater_power:      "Dew Heater Power",
    save_good_frames:  "Save Good Frames",
    save_all_frames:   "Save All Frames",
    dec_pos_index:     "Dec Offset",
    battery_low_limit: "Battery Low Limit (%)",
    guest_mode:        "Claim Guest Mode",
  };

  function formatValue(val: unknown): string {
    if (val === true)  return "Enabled";
    if (val === false) return "Disabled";
    if (val === "" || val === null || val === undefined) return "—";
    return String(val);
  }

  function boolClass(val: unknown): string {
    if (val === true)  return "success";
    if (val === false) return "warning";
    return "";
  }

  async function load() {
    loading = true;
    error = "";
    try {
      const res = await fetch("/api/v1/config");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      config = await res.json();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);
</script>

<div class="page-hero">
  <p class="page-kicker">Application</p>
  <h1 class="page-title">Config</h1>
  <p class="page-subtitle">SSC application configuration loaded from config.toml.</p>
</div>

<div class="alert alert-info readonly-notice">
  Configuration is read-only. Edit <code>config.toml</code> and restart SSC to apply changes.
</div>

{#if loading}
  <div class="loading">Loading configuration…</div>
{:else if error}
  <div class="alert alert-error">{error}</div>
{:else if config}

  <!-- Networking -->
  <div class="panel-card section-card">
    <p class="panel-title">Networking</p>
    {#each Object.entries(config.networking) as [key, val]}
      <div class="stat-row">
        <div class="stat-key">{NETWORKING_LABELS[key] ?? key}</div>
        <div class="stat-value {boolClass(val)}">{formatValue(val)}</div>
      </div>
    {/each}
  </div>

  <!-- Web UI -->
  <div class="panel-card section-card">
    <p class="panel-title">Web UI</p>
    {#each Object.entries(config.webui) as [key, val]}
      <div class="stat-row">
        <div class="stat-key">{WEBUI_LABELS[key] ?? key}</div>
        <div class="stat-value {boolClass(val)}">{formatValue(val)}</div>
      </div>
    {/each}
  </div>

  <!-- Logging -->
  <div class="panel-card section-card">
    <p class="panel-title">Logging</p>
    {#each Object.entries(config.logging) as [key, val]}
      <div class="stat-row">
        <div class="stat-key">{LOGGING_LABELS[key] ?? key}</div>
        <div class="stat-value {boolClass(val)}">{formatValue(val)}</div>
      </div>
    {/each}
  </div>

  <!-- Seestar Init Defaults -->
  <div class="panel-card section-card">
    <p class="panel-title">Seestar Init Defaults</p>
    {#each Object.entries(config.init) as [key, val]}
      <div class="stat-row">
        <div class="stat-key">{INIT_LABELS[key] ?? key}</div>
        <div class="stat-value {boolClass(val)}">{formatValue(val)}</div>
      </div>
    {/each}
  </div>

  <!-- Devices -->
  <div class="panel-card section-card">
    <p class="panel-title">Devices</p>
    {#if config.devices.length === 0}
      <div class="no-devices">No devices configured.</div>
    {:else}
      <div class="devices-table">
        <div class="devices-header">
          <span>#</span>
          <span>Name</span>
          <span>IP Address</span>
        </div>
        {#each config.devices as d}
          <div class="devices-row">
            <span class="device-num">{d.device_num}</span>
            <span>{d.name}</span>
            <span class="device-ip">{d.ip_address}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>

{/if}

<style>
  .loading { color: var(--ui-muted); font-size: 0.9rem; padding: 2rem 0; }

  .readonly-notice {
    margin-bottom: 1.25rem;
    font-size: 0.85rem;
  }
  .readonly-notice code {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.8em;
    background: rgba(44, 177, 255, 0.12);
    padding: 0.1em 0.35em;
    border-radius: 3px;
  }

  .section-card {
    margin-bottom: 1rem;
  }

  .no-devices {
    color: var(--ui-muted);
    font-size: 0.85rem;
    padding: 0.5rem 0;
  }

  .devices-table {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .devices-header {
    display: grid;
    grid-template-columns: 2.5rem 1fr 1fr;
    gap: 0.75rem;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--ui-muted);
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
    margin-bottom: 0.1rem;
  }

  .devices-row {
    display: grid;
    grid-template-columns: 2.5rem 1fr 1fr;
    gap: 0.75rem;
    font-size: 0.85rem;
    padding: 0.55rem 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    color: var(--ui-body);
  }
  .devices-row:last-child { border-bottom: none; }

  .device-num {
    color: var(--ui-muted);
    font-variant-numeric: tabular-nums;
  }

  .device-ip {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.8rem;
    color: var(--ui-primary);
  }

  @media (max-width: 600px) {
    .devices-header,
    .devices-row {
      grid-template-columns: 2rem 1fr;
    }
    .devices-header span:last-child,
    .devices-row .device-ip {
      display: none;
    }
  }
</style>
