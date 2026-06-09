<script lang="ts">
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";
  import EventStatusPanel from "../lib/components/EventStatusPanel.svelte";

  const EVENTS = ["WheelMove", "AutoFocus", "DarkLibrary", "3PPA", "PlateSolve", "Scheduler"];

  let result: unknown = null;
  let error = "";
  let loading = false;
  let loadingKey = "";

  $: mountMode = $activeDeviceStatus?.mount_mode ?? "";

  // ── Quick Actions ──────────────────────────────────────────────────────────
  const QUICK_ACTIONS = [
    { label: "Stop View",        icon: "⏹", cmd: "iscope_stop_view",       params: {} },
    { label: "Park Scope",       icon: "🏠", cmd: "scope_park",             params: {} },
    { label: "Auto Focus",       icon: "🔭", cmd: "start_auto_focus",       params: {} },
    { label: "Stop Scheduler",   icon: "⏸", cmd: null,                      params: {} }, // handled specially
    { label: "Open to Horizon",  icon: "↔", cmd: "scope_move_to_horizon",  params: {} },
  ];

  async function runQuick(qa: typeof QUICK_ACTIONS[0]) {
    loadingKey = qa.label;
    error = "";
    try {
      if (qa.label === "Stop Scheduler") {
        result = await api.devices.schedule.setState($activeDevNum, "stop");
      } else if (qa.cmd) {
        result = await api.devices.command($activeDevNum, qa.cmd, qa.params);
      }
    } catch (e) {
      error = String(e);
    } finally {
      loadingKey = "";
    }
  }

  async function switchMountMode() {
    const cmd = mountMode === "Equatorial" ? "set_alt_az_mode" : "set_eq_mode";
    loadingKey = "mountmode";
    error = "";
    try {
      result = await api.devices.command($activeDevNum, cmd, {});
    } catch (e) {
      error = String(e);
    } finally {
      loadingKey = "";
    }
  }

  // ── Command Groups ─────────────────────────────────────────────────────────
  interface CmdEntry { label: string; value: string; confirm?: string }
  interface CmdGroup { label: string; commands: CmdEntry[] }

  const CMD_GROUPS: CmdGroup[] = [
    {
      label: "Startup / Shutdown",
      commands: [
        { label: "Move to Horizon",  value: "scope_move_to_horizon" },
        { label: "Park Scope",       value: "scope_park" },
        { label: "Reboot",           value: "pi_reboot",   confirm: "Reboot the Seestar? This will disconnect all clients." },
        { label: "Shutdown",         value: "pi_shutdown", confirm: "Shut down the Seestar?" },
        { label: "Grab Control",     value: "grab_control" },
        { label: "Release Control",  value: "release_control" },
      ],
    },
    {
      label: "AutoFocus",
      commands: [
        { label: "Start AutoFocus",            value: "start_auto_focus" },
        { label: "Stop AutoFocus",             value: "stop_auto_focus" },
        { label: "Get Focuser Position",       value: "get_focuser_position" },
        { label: "Get Last Focuser Position",  value: "get_last_focuser_position" },
      ],
    },
    {
      label: "Calibration",
      commands: [
        { label: "Create Dark Frames",  value: "start_create_dark" },
        { label: "Hot Pixel Correction",value: "start_create_hpc" },
        { label: "Create Flat Frames",  value: "start_create_calib_frame",
          confirm: "Ensure your Seestar is open and pointing at a white light source." },
      ],
    },
    {
      label: "Filter / Wheel",
      commands: [
        { label: "Use LP Filter",      value: "set_wheel_position_LP" },
        { label: "Use IR Cut Filter",  value: "set_wheel_position_IR_Cut" },
        { label: "Use Dark Filter",    value: "set_wheel_position_Dark" },
        { label: "Get Wheel State",    value: "get_wheel_state" },
        { label: "Get Wheel Setting",  value: "get_wheel_setting" },
      ],
    },
    {
      label: "Plate Solve",
      commands: [
        { label: "Start Plate Solve",       value: "start_solve" },
        { label: "Get Current Result",      value: "get_solve_result" },
        { label: "Get Last Result",         value: "get_last_solve_result" },
      ],
    },
    {
      label: "Imaging",
      commands: [
        { label: "Start Imaging",             value: "iscope_start_stack" },
        { label: "Stop Imaging",              value: "iscope_stop_view" },
        { label: "Get View State",            value: "get_view_state" },
        { label: "Get Stack Info",            value: "get_stack_info" },
        { label: "Get Image Name Field",      value: "get_img_name_field" },
        { label: "Get Image Save Path",       value: "get_image_save_path" },
        { label: "Get Camera State",          value: "get_camera_state" },
        { label: "Get Camera Exp & Bin",      value: "get_camera_exp_and_bin" },
      ],
    },
    {
      label: "Get Information",
      commands: [
        { label: "Get Device State",       value: "get_device_state" },
        { label: "Get App State",          value: "iscope_get_app_state" },
        { label: "Get Event State",        value: "get_event_state" },
        { label: "Get WiFi Info",          value: "pi_get_ap" },
        { label: "Get App Setting",        value: "get_app_setting" },
        { label: "Get Controls",           value: "get_controls" },
        { label: "Get Disk Volume",        value: "get_disk_volume" },
        { label: "Get Settings",           value: "get_setting" },
        { label: "Get Stack Setting",      value: "get_stack_setting" },
        { label: "Get Test Settings",      value: "get_test_setting" },
        { label: "Get User Location",      value: "get_user_location" },
        { label: "Get Equatorial Coord",   value: "scope_get_equ_coord" },
        { label: "Get Horizon Coord",      value: "scope_get_horiz_coord" },
        { label: "Get RA/Dec",             value: "scope_get_ra_dec" },
      ],
    },
    {
      label: "Set Mount Mode",
      commands: [
        { label: "Equatorial",   value: "set_eq_mode" },
        { label: "Alt Azimuth",  value: "set_alt_az_mode" },
      ],
    },
  ];

  // Per-group selected value
  let groupSelections: Record<string, string> = {};
  for (const g of CMD_GROUPS) groupSelections[g.label] = "";

  async function execGroup(group: CmdGroup) {
    const sel = groupSelections[group.label];
    if (!sel) return;
    const entry = group.commands.find(c => c.value === sel);
    if (!entry) return;
    if (entry.confirm && !window.confirm(entry.confirm)) return;
    loadingKey = group.label;
    error = "";
    try {
      result = await api.devices.command($activeDevNum, sel, {});
    } catch (e) {
      error = String(e);
    } finally {
      loadingKey = "";
    }
  }

  // ── Magnetic Declination ───────────────────────────────────────────────────
  let magDecAdjust = false;
  let magDecOffset = 0;

  async function execMagDec() {
    loadingKey = "magdec";
    error = "";
    try {
      result = await api.devices.command($activeDevNum, "adjust_mag_declination", {
        adjust_mag_dec: magDecAdjust,
        fudge_angle: magDecOffset,
      });
    } catch (e) {
      error = String(e);
    } finally {
      loadingKey = "";
    }
  }

  // ── Raw Command ───────────────────────────────────────────────────────────
  let rawMethod = "";
  let rawParams = "{}";

  async function execRaw() {
    loading = true;
    error = "";
    result = null;
    try {
      const params = JSON.parse(rawParams);
      result = await api.devices.command($activeDevNum, rawMethod, params);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function fmt(r: unknown): string {
    return JSON.stringify(r, null, 2);
  }
</script>

<div class="page-hero">
  <p class="page-kicker">Developer</p>
  <h1 class="page-title">Command</h1>
  <p class="page-subtitle">Send commands directly to the telescope firmware.</p>
</div>

<EventStatusPanel events={EVENTS} />

{#if !$isConnected}
  <div class="panel-card offline-msg">Device {$activeDevNum} is offline.</div>
{:else}
  <div class="cmd-layout">

    <!-- ── Left column ────────────────────────────────────────────────── -->
    <div class="left-col">

      <!-- Quick Actions -->
      <div class="panel-card">
        <p class="panel-title">Quick Actions</p>
        <div class="action-grid">
          {#each QUICK_ACTIONS as qa}
            <button
              class="action-btn"
              on:click={() => runQuick(qa)}
              disabled={loadingKey === qa.label}
            >
              <span class="action-icon">{qa.icon}</span>
              <span>{loadingKey === qa.label ? "…" : qa.label}</span>
            </button>
          {/each}
          <button
            class="action-btn"
            on:click={switchMountMode}
            disabled={loadingKey === "mountmode"}
          >
            <span class="action-icon">⇄</span>
            <span>
              {#if loadingKey === "mountmode"}…
              {:else if mountMode === "Equatorial"}→ Alt-Az
              {:else if mountMode === "Alt Azimuth"}→ Equatorial
              {:else}Switch Mount Mode
              {/if}
            </span>
          </button>
        </div>
      </div>

      <!-- Command Groups -->
      <div class="panel-card">
        <p class="panel-title">Commands</p>
        <div class="groups-grid">
          {#each CMD_GROUPS as group}
            <div class="group-panel">
              <label class="group-label" for="grp-{group.label}">{group.label}</label>
              <div class="group-row">
                <select
                  id="grp-{group.label}"
                  class="form-input"
                  bind:value={groupSelections[group.label]}
                >
                  <option value="">Select…</option>
                  {#each group.commands as cmd}
                    <option value={cmd.value}>{cmd.label}</option>
                  {/each}
                </select>
                <button
                  class="btn btn-primary exec-btn"
                  on:click={() => execGroup(group)}
                  disabled={!groupSelections[group.label] || loadingKey === group.label}
                >
                  {loadingKey === group.label ? "…" : "▶"}
                </button>
              </div>
            </div>
          {/each}
        </div>
      </div>

      <!-- Magnetic Declination -->
      <div class="panel-card">
        <p class="panel-title">Magnetic Declination Adjustment</p>
        <p class="mag-note">Only use after a compass calibration at your current location.</p>
        <div class="mag-form">
          <label class="mag-check-label">
            <input type="checkbox" bind:checked={magDecAdjust} />
            Adjust Mag Dec to current location
          </label>
          <div class="form-field">
            <label class="form-label" for="fudge">Add Offset (degrees)</label>
            <input id="fudge" type="number" class="form-input" bind:value={magDecOffset} step="0.1" />
          </div>
          <button
            class="btn btn-primary"
            on:click={execMagDec}
            disabled={loadingKey === "magdec"}
          >
            {loadingKey === "magdec" ? "…" : "Execute"}
          </button>
        </div>
      </div>

      <!-- Raw Command -->
      <div class="panel-card">
        <p class="panel-title">Raw Command</p>
        <form on:submit|preventDefault={execRaw}>
          <div class="form-field" style="margin-bottom:0.75rem">
            <label class="form-label" for="raw-method">Method</label>
            <input id="raw-method" class="form-input" bind:value={rawMethod} placeholder="get_device_state" required />
          </div>
          <div class="form-field" style="margin-bottom:1rem">
            <label class="form-label" for="raw-params">Parameters (JSON)</label>
            <textarea id="raw-params" class="form-input" bind:value={rawParams} rows="4"></textarea>
          </div>
          <button type="submit" class="btn btn-primary" disabled={loading || !rawMethod}>
            {loading ? "Sending…" : "▶ Send"}
          </button>
        </form>
      </div>

    </div>

    <!-- ── Right column: result ───────────────────────────────────────── -->
    <div class="result-col">
      {#if error}
        <div class="alert alert-error">{error}</div>
      {/if}
      {#if result !== null}
        <div class="panel-card result-card">
          <p class="panel-title">Response</p>
          <pre class="result-pre">{fmt(result)}</pre>
        </div>
      {:else if !error}
        <div class="panel-card placeholder-card">
          <div class="placeholder-icon">⌨</div>
          <div class="placeholder-text">Response will appear here</div>
        </div>
      {/if}
    </div>

  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }

  .cmd-layout {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
  }

  .left-col {
    width: 480px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .result-col { flex: 1; min-width: 0; position: sticky; top: 68px; }

  /* Quick Actions */
  .action-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 0.5rem;
  }
  .action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 0.6rem 0.5rem;
    font-size: 0.8rem;
    font-weight: 600;
    background: rgba(44,177,255,0.08);
    border: 1px solid rgba(44,177,255,0.2);
    color: var(--ui-primary);
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    white-space: nowrap;
  }
  .action-btn:hover:not(:disabled) {
    background: rgba(44,177,255,0.16);
    border-color: rgba(44,177,255,0.4);
  }
  .action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .action-icon { font-size: 1rem; line-height: 1; }

  /* Command Groups */
  .groups-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }
  .group-panel {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .group-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--ui-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .group-row {
    display: flex;
    gap: 0.4rem;
  }
  .group-row .form-input { flex: 1; font-size: 0.8rem; padding: 0.3rem 0.5rem; }
  .exec-btn { padding: 0.3rem 0.6rem; font-size: 0.8rem; flex-shrink: 0; }

  /* Magnetic Declination */
  .mag-note {
    font-size: 0.8rem;
    color: var(--ui-muted);
    margin-bottom: 0.75rem;
  }
  .mag-form {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .mag-check-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    cursor: pointer;
  }
  .mag-check-label input { accent-color: var(--ui-primary); width: 14px; height: 14px; }

  /* Result */
  .result-pre {
    margin: 0;
    padding: 0.75rem;
    background: rgba(0,0,0,0.25);
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.06);
    font-size: 0.78rem;
    color: var(--ui-muted);
    overflow: auto;
    max-height: 70vh;
    font-family: "SF Mono", "Fira Code", monospace;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .placeholder-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2.5rem;
    text-align: center;
    gap: 0.5rem;
  }
  .placeholder-icon { font-size: 2rem; color: var(--ui-muted); }
  .placeholder-text { font-size: 0.85rem; color: var(--ui-muted); }

  @media (max-width: 800px) {
    .cmd-layout { flex-direction: column; }
    .left-col { width: 100%; }
    .result-col { position: static; }
    .action-grid { grid-template-columns: 1fr 1fr; }
  }
</style>
