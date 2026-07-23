<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { navGuardMessage } from "../lib/stores/navGuard";

  interface ConfigData {
    networking: Record<string, unknown>;
    webui: Record<string, unknown>;
    logging: Record<string, unknown>;
    init: Record<string, unknown>;
    devices: Array<{ device_num: number; name: string; ip_address: string }>;
  }

  let config: ConfigData | null = null;
  let baseline = "";
  let loading = true;
  let saving = false;
  let saved = false;
  let error = "";
  let submitted = false;

  $: isDirty = config !== null && JSON.stringify(config) !== baseline;
  $: baselineObj = baseline ? (JSON.parse(baseline) as ConfigData) : null;

  function isFieldDirty(section: keyof ConfigData, key: string, current: unknown): boolean {
    if (!baselineObj) return false;
    const sec = baselineObj[section];
    if (!sec || typeof sec !== "object" || Array.isArray(sec)) return false;
    return (sec as Record<string, unknown>)[key] !== current;
  }

  const NETWORKING_LABELS: Record<string, string> = {
    ip_address: "Bind IP Address",
    port:       "Alpaca Port",
    imgport:    "Image Port",
    stport:     "Stellarium Port",
    sthost:     "Stellarium Host",
    timeout:    "Timeout (s)",
    rtsp_udp:   "RTSP UDP",
  };

  const WEBUI_LABELS: Record<string, string> = {
    uiport:          "UI Port",
    ui_theme:        "UI Theme",
    experimental:    "Experimental Features",
    confirm:         "Confirmation Dialogs",
    save_frames:     "Save Preview Frames",
    save_frames_dir: "Save Frames Directory",
    frontend:        "Frontend",
  };

  const LOGGING_LABELS: Record<string, string> = {
    log_level:       "Log Level",
    log_to_stdout:   "Log to Stdout",
    max_log_size_mb: "Max Log Size (MB)",
    log_num_keep:    "Logs to Keep",
    log_prefix:      "Log Prefix",
  };

  const INIT_LABELS: Record<string, string> = {
    latitude:            "Latitude",
    longitude:           "Longitude",
    gain:                "Gain",
    exp_ms_preview:      "Exposure Preview (ms)",
    exp_ms_stack_l:      "Exposure Stack (ms)",
    dither_enabled:      "Dither",
    dither_length_pixel: "Dither Length (px)",
    dither_frequency:    "Dither Frequency",
    lp_filter:           "LP Filter",
    heater_power:        "Dew Heater Power (0-100)",
    save_good_frames:    "Save Good Frames",
    save_all_frames:     "Save All Frames",
    dec_pos_index:       "Dec Offset Index (1-5)",
    battery_low_limit:   "Battery Low Limit (%)",
    guest_mode:          "Claim Guest Mode",
  };

  // Which fields are numbers vs strings (booleans are detected automatically)
  const NUMBER_FIELDS = new Set([
    "port", "imgport", "stport", "timeout",
    "uiport",
    "max_log_size_mb", "log_num_keep",
    "latitude", "longitude", "gain", "exp_ms_preview", "exp_ms_stack_l",
    "dither_length_pixel", "dither_frequency", "heater_power",
    "dec_pos_index", "battery_low_limit",
  ]);

  const SELECT_OPTIONS: Record<string, string[]> = {
    log_level: ["DEBUG", "INFO", "WARNING", "ERROR"],
    ui_theme:  ["dark", "light"],
    frontend:  ["classic", "v2"],
  };

  // Restart-required fields (networking + ports)
  const RESTART_FIELDS = new Set([
    "ip_address", "port", "imgport", "stport", "sthost", "rtsp_udp",
    "uiport", "frontend",
  ]);

  function setField(section: keyof ConfigData, key: string, value: unknown) {
    if (!config) return;
    config = {
      ...config,
      [section]: { ...(config[section] as Record<string, unknown>), [key]: value },
    };
  }

  function needsRestart(key: string): boolean {
    return RESTART_FIELDS.has(key);
  }

  async function load() {
    loading = true;
    error = "";
    try {
      const res = await fetch("/api/v1/config");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      config = await res.json();
      baseline = JSON.stringify(config);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function save() {
    if (!config) return;
    submitted = true;
    saving = true;
    error = "";
    try {
      const res = await fetch("/api/v1/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          networking: config.networking,
          webui:      config.webui,
          logging:    config.logging,
          init:       config.init,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `HTTP ${res.status}`);
      }
      baseline = JSON.stringify(config);
      saved = true;
      setTimeout(() => (saved = false), 2500);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }

  function reset() {
    config = JSON.parse(baseline);
  }

  type DeviceEntry = { device_num: number; name: string; ip_address: string };

  let devices: DeviceEntry[] = [];
  let devicesBaseline = "";
  let devicesSaving = false;
  let devicesSaved = false;
  let devicesError = "";

  $: devicesDirty = JSON.stringify(devices) !== devicesBaseline;

  function addDevice() {
    devices = [...devices, { device_num: devices.length + 1, name: "", ip_address: "" }];
  }

  function removeDevice(index: number) {
    devices = devices.filter((_, i) => i !== index).map((d, i) => ({ ...d, device_num: i + 1 }));
  }

  function setDeviceField(index: number, key: "name" | "ip_address", value: string) {
    devices = devices.map((d, i) => (i === index ? { ...d, [key]: value } : d));
  }

  function resetDevices() {
    devices = JSON.parse(devicesBaseline);
  }

  async function saveDevices() {
    devicesSaving = true;
    devicesError = "";
    try {
      const res = await fetch("/api/v1/config/devices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          devices: devices.map((d) => ({ name: d.name, ip_address: d.ip_address })),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `HTTP ${res.status}`);
      }
      const data = await res.json();
      devices = data.devices ?? devices;
      devicesBaseline = JSON.stringify(devices);
      if (config) config = { ...config, devices };
      devicesSaved = true;
      setTimeout(() => (devicesSaved = false), 2500);
    } catch (e) {
      devicesError = String(e);
    } finally {
      devicesSaving = false;
    }
  }

  $: if (config && devicesBaseline === "") {
    devices = config.devices.map((d) => ({ ...d }));
    devicesBaseline = JSON.stringify(devices);
  }

  $: navGuardMessage.set(
    (isDirty || devicesDirty) ? "You have unsaved changes. Leave this page?" : null
  );
  onDestroy(() => navGuardMessage.set(null));

  function beforeUnload(e: BeforeUnloadEvent) {
    if (isDirty || devicesDirty) e.preventDefault();
  }

  onMount(() => window.addEventListener("beforeunload", beforeUnload));
  onDestroy(() => window.removeEventListener("beforeunload", beforeUnload));

  let started = false;
  if (!started) {
    started = true;
    load();
  }
</script>

<div class="page-hero">
  <p class="page-kicker">Application</p>
  <h1 class="page-title">Config</h1>
  <p class="page-subtitle">SSC application configuration — saved to config.toml.</p>
</div>

{#if loading}
  <div class="loading">Loading configuration…</div>
{:else if error && !config}
  <div class="alert alert-error">{error}</div>
{:else if config}

  <div class="config-header">
    {#if isDirty}
      <span class="unsaved-pill">● Unsaved Changes</span>
    {/if}
    <div class="header-actions">
      {#if isDirty}
        <button class="btn btn-secondary" on:click={reset}>Reset</button>
      {/if}
      <button class="btn btn-primary" on:click={save} disabled={saving || !isDirty}>
        {saving ? "Saving…" : "Save to config.toml"}
      </button>
    </div>
  </div>

  {#if error}<div class="alert alert-error">{error}</div>{/if}
  {#if saved}<div class="alert alert-success">Saved. Fields marked ↺ require a service restart.</div>{/if}

  <div class:was-validated={submitted}>

  <!-- Networking -->
  <div class="panel-card section-card">
    <p class="group-title">Networking</p>
    {#each Object.entries(config.networking) as [key, val]}
      <div class="setting-row" class:row--dirty={isFieldDirty("networking", key, val)}>
        <div class="setting-meta">
          <div class="setting-name">
            {NETWORKING_LABELS[key] ?? key}
            {#if needsRestart(key)}<span class="restart-tag" title="Requires restart">↺</span>{/if}
          </div>
        </div>
        <div class="setting-control">
          {#if typeof val === "boolean"}
            <div class="radio-group">
              <label class="radio-label">
                <input type="radio" name="net-{key}" checked={val === true}
                  on:change={() => setField("networking", key, true)} /> On
              </label>
              <label class="radio-label">
                <input type="radio" name="net-{key}" checked={val === false}
                  on:change={() => setField("networking", key, false)} /> Off
              </label>
            </div>
          {:else if NUMBER_FIELDS.has(key)}
            <input type="number" class="form-input narrow" required
              value={Number(val)}
              on:input={(e) => setField("networking", key, +e.currentTarget.value)} />
          {:else}
            <input type="text" class="form-input narrow" required
              value={String(val ?? "")}
              on:input={(e) => setField("networking", key, e.currentTarget.value)} />
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <!-- Web UI -->
  <div class="panel-card section-card">
    <p class="group-title">Web UI</p>
    {#each Object.entries(config.webui) as [key, val]}
      <div class="setting-row" class:row--dirty={isFieldDirty("webui", key, val)}>
        <div class="setting-meta">
          <div class="setting-name">
            {WEBUI_LABELS[key] ?? key}
            {#if needsRestart(key)}<span class="restart-tag" title="Requires restart">↺</span>{/if}
          </div>
        </div>
        <div class="setting-control">
          {#if typeof val === "boolean"}
            <div class="radio-group">
              <label class="radio-label">
                <input type="radio" name="webui-{key}" checked={val === true}
                  on:change={() => setField("webui", key, true)} /> On
              </label>
              <label class="radio-label">
                <input type="radio" name="webui-{key}" checked={val === false}
                  on:change={() => setField("webui", key, false)} /> Off
              </label>
            </div>
          {:else if key in SELECT_OPTIONS}
            <select class="form-input narrow"
              value={String(val)}
              on:change={(e) => setField("webui", key, e.currentTarget.value)}>
              {#each SELECT_OPTIONS[key] as opt}
                <option value={opt}>{opt}</option>
              {/each}
            </select>
          {:else if NUMBER_FIELDS.has(key)}
            <input type="number" class="form-input narrow" required
              value={Number(val)}
              on:input={(e) => setField("webui", key, +e.currentTarget.value)} />
          {:else}
            <input type="text" class="form-input narrow" required
              value={String(val ?? "")}
              on:input={(e) => setField("webui", key, e.currentTarget.value)} />
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <!-- Logging -->
  <div class="panel-card section-card">
    <p class="group-title">Logging</p>
    {#each Object.entries(config.logging) as [key, val]}
      <div class="setting-row" class:row--dirty={isFieldDirty("logging", key, val)}>
        <div class="setting-meta">
          <div class="setting-name">{LOGGING_LABELS[key] ?? key}</div>
        </div>
        <div class="setting-control">
          {#if typeof val === "boolean"}
            <div class="radio-group">
              <label class="radio-label">
                <input type="radio" name="log-{key}" checked={val === true}
                  on:change={() => setField("logging", key, true)} /> On
              </label>
              <label class="radio-label">
                <input type="radio" name="log-{key}" checked={val === false}
                  on:change={() => setField("logging", key, false)} /> Off
              </label>
            </div>
          {:else if key in SELECT_OPTIONS}
            <select class="form-input narrow"
              value={String(val)}
              on:change={(e) => setField("logging", key, e.currentTarget.value)}>
              {#each SELECT_OPTIONS[key] as opt}
                <option value={opt}>{opt}</option>
              {/each}
            </select>
          {:else if NUMBER_FIELDS.has(key)}
            <input type="number" class="form-input narrow" required
              value={Number(val)}
              on:input={(e) => setField("logging", key, +e.currentTarget.value)} />
          {:else}
            <input type="text" class="form-input narrow" required
              value={String(val ?? "")}
              on:input={(e) => setField("logging", key, e.currentTarget.value)} />
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <!-- Seestar Init Defaults -->
  <div class="panel-card section-card">
    <p class="group-title">Seestar Init Defaults</p>
    <p class="section-note">Applied when a new telescope session starts.</p>
    {#each Object.entries(config.init) as [key, val]}
      <div class="setting-row" class:row--dirty={isFieldDirty("init", key, val)}>
        <div class="setting-meta">
          <div class="setting-name">{INIT_LABELS[key] ?? key}</div>
        </div>
        <div class="setting-control">
          {#if typeof val === "boolean"}
            <div class="radio-group">
              <label class="radio-label">
                <input type="radio" name="init-{key}" checked={val === true}
                  on:change={() => setField("init", key, true)} /> On
              </label>
              <label class="radio-label">
                <input type="radio" name="init-{key}" checked={val === false}
                  on:change={() => setField("init", key, false)} /> Off
              </label>
            </div>
          {:else if NUMBER_FIELDS.has(key)}
            <input type="number" class="form-input narrow" required
              value={Number(val)}
              on:input={(e) => setField("init", key, +e.currentTarget.value)} />
          {:else}
            <input type="text" class="form-input narrow" required
              value={String(val ?? "")}
              on:input={(e) => setField("init", key, e.currentTarget.value)} />
          {/if}
        </div>
      </div>
    {/each}
  </div>

  </div> <!-- end was-validated wrapper -->

  <!-- Devices -->
  <div class="panel-card section-card">
    <p class="group-title">Devices</p>
    <p class="section-note">Add, edit, or remove Seestar devices. Device numbers are reassigned sequentially on save.</p>
    {#if devicesError}<div class="alert alert-error">{devicesError}</div>{/if}
    {#if devicesSaved}<div class="alert alert-success">Devices saved. Restart required for changes to take effect.</div>{/if}
    {#if devices.length === 0}
      <div class="no-devices">No devices configured.</div>
    {:else}
      <div class="devices-table">
        <div class="devices-header devices-header--edit">
          <span>#</span><span>Name</span><span>IP Address</span><span></span>
        </div>
        {#each devices as d, i}
          <div class="devices-row devices-row--edit">
            <span class="device-num">{d.device_num}</span>
            <input type="text" class="form-input narrow" placeholder="Name" required
              value={d.name}
              on:input={(e) => setDeviceField(i, "name", e.currentTarget.value)} />
            <input type="text" class="form-input narrow device-ip-input" placeholder="192.168.1.100" required
              value={d.ip_address}
              on:input={(e) => setDeviceField(i, "ip_address", e.currentTarget.value)} />
            <button type="button" class="btn btn-secondary btn-remove-device" title="Remove device"
              on:click={() => removeDevice(i)}>
              Remove
            </button>
          </div>
        {/each}
      </div>
    {/if}
    <div class="devices-actions">
      <button type="button" class="btn btn-secondary" on:click={addDevice}>Add Device</button>
      <div class="devices-save-actions">
        {#if devicesDirty}
          <button type="button" class="btn btn-secondary" on:click={resetDevices}>Reset</button>
        {/if}
        <button type="button" class="btn btn-primary" on:click={saveDevices} disabled={devicesSaving || !devicesDirty}>
          {devicesSaving ? "Saving…" : "Save Devices"}
        </button>
      </div>
    </div>
  </div>

  <div class="save-footer">
    <button class="btn btn-primary" on:click={save} disabled={saving || !isDirty}>
      {saving ? "Saving…" : "Save to config.toml"}
    </button>
    {#if isDirty}
      <button class="btn btn-secondary" on:click={reset}>Reset</button>
    {/if}
  </div>

{/if}

<style>
  .loading { color: var(--ui-muted); font-size: 0.9rem; padding: 2rem 0; }

  .config-header {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }
  .header-actions { display: flex; gap: 0.5rem; }

  .unsaved-pill {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--ui-warning);
    background: rgba(246, 201, 14, 0.1);
    border: 1px solid rgba(246, 201, 14, 0.25);
    padding: 0.2rem 0.7rem;
    border-radius: 99px;
    margin-right: auto;
  }

  .section-card { margin-bottom: 1rem; }

  .group-title {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ui-primary);
    margin: 0 0 0.5rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(44, 177, 255, 0.15);
  }

  .section-note {
    font-size: 0.78rem;
    color: var(--ui-muted);
    margin: 0 0 0.75rem;
  }

  .setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.6rem 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    border-left: 2px solid transparent;
    margin: 0 -0.5rem;
    border-radius: 2px;
    transition: border-color 0.15s, background 0.15s;
  }
  .setting-row:last-child { border-bottom: none; }
  .row--dirty {
    border-left-color: var(--ui-warning);
    background: rgba(246, 201, 14, 0.05);
  }
  .was-validated .form-input:invalid {
    border-color: var(--ui-danger);
    box-shadow: 0 0 0 2px rgba(233, 69, 96, 0.15);
  }

  .setting-meta { flex: 1; min-width: 0; }
  .setting-name {
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--ui-body);
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .restart-tag {
    font-size: 0.72rem;
    color: var(--ui-warning);
    font-weight: 700;
    cursor: help;
  }

  .setting-control { flex-shrink: 0; }

  .form-input.narrow {
    width: 160px;
    text-align: right;
  }

  select.form-input.narrow {
    text-align: left;
    padding-right: 0.5rem;
  }

  .radio-group { display: flex; gap: 1rem; }
  .radio-label {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.83rem;
    color: var(--ui-body);
    cursor: pointer;
  }
  .radio-label input[type="radio"] {
    accent-color: var(--ui-primary);
    cursor: pointer;
  }

  .save-footer {
    display: flex;
    gap: 0.5rem;
    padding-top: 0.5rem;
  }

  .no-devices { color: var(--ui-muted); font-size: 0.85rem; padding: 0.5rem 0; }

  .devices-table { display: flex; flex-direction: column; }
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
  .device-num { color: var(--ui-muted); font-variant-numeric: tabular-nums; }

  .devices-header--edit, .devices-row--edit {
    grid-template-columns: 2.5rem 1fr 1fr auto;
    align-items: center;
  }
  .device-ip-input { font-family: "SF Mono", "Fira Code", monospace; font-size: 0.8rem; }
  .btn-remove-device { font-size: 0.8rem; padding: 0.35rem 0.75rem; }
  .devices-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin-top: 1rem;
  }
  .devices-save-actions { display: flex; gap: 0.5rem; }

  @media (max-width: 600px) {
    .setting-row { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
    .form-input.narrow { width: 100%; text-align: left; }
  }
</style>
