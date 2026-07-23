<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { navGuardMessage } from "../lib/stores/navGuard";
  import { api } from "../lib/api";

  const FRIENDLY: Record<string, string> = {
    stack_dither_pix:        "Stack Dither Pixels",
    stack_dither_interval:   "Stack Dither Interval",
    stack_dither_enable:     "Stack Dither",
    exp_ms_stack_l:          "Stacking Exposure (ms)",
    exp_ms_continuous:       "Preview Exposure (ms)",
    save_discrete_ok_frame:  "Save Sub Frames",
    save_discrete_frame:     "Save Failed Sub Frames",
    light_duration_min:      "Light Duration Min",
    stack_capt_type:         "Stack Capture Type",
    stack_capt_num:          "Stack Capture Count",
    stack_brightness:        "Stack Brightness",
    stack_contrast:          "Stack Contrast",
    stack_saturation:        "Stack Saturation",
    capt_type:               "Stack Capture Type",
    capt_num:                "Stack Capture Count",
    brightness:              "Stack Brightness",
    contrast:                "Stack Contrast",
    saturation:              "Stack Saturation",
    goto:                    "Stack Goto",
    move_sleep_sec:          "Mount Move Settle Time (s)",
    dbe:                     "Stack DBE",
    dbe_enable:              "Stack DBE (Enable)",
    plan_target_af:          "Plan Target AF",
    viewplan_gohome:         "Viewplan Go Home",
    stack_after_goto:        "Stack After Goto",
    expert_mode:             "Expert Mode",
    af_before_stack:         "AF Before Stack",
    auto_af:                 "Auto-Focus Before Capture",
    star_trails:             "Stack Star Trails",
    star_correction:         "Star Correction",
    airplane_line_removal:   "Airplane Line Removal",
    auto_3ppa_calib:         "Horizontal Calibration",
    frame_calib:             "Frame Calibration",
    stack_masic:             "Stack Mosaic",
    rec_stablzn:             "Record Stabilization",
    wide_cam:                "Wide Angle Camera",
    wide_4k:                 "Wide Camera 4K Mode",
    wide_denoise:            "Wide Camera Denoise",
    wide_focal_pos:          "Wide Camera Focal Position",
    temp_unit:               "Temperature Unit",
    focal_pos:               "Focal Position (User)",
    factory_focal_pos:       "Default Focal Position",
    heater_enable:           "Dew Heater",
    auto_power_off:          "Auto Power Off",
    stack_lenhance:          "Light Pollution Filter",
    auto_lenhance:           "Auto DSO Enhancement",
    dark_mode:               "Dark Mode",
    cont_capt:               "Continuous Capture Mode",
    drizzle2x:               "4K Live Stack (2× Drizzle)",
    beep_volume:             "Beep Volume",
    isp_exp_ms:              "ISP Exposure (ms)",
    isp_gain:                "ISP Gain",
    calib_location:          "Calibration Location",
    wifi_country:            "WiFi Country Code",
    manual_exp:              "Manual Exposure",
    remote_joined:           "Remote Joined",
    guest_mode:              "Guest Mode",
    user_stack_sim:          "Simulate Stacking",
    usb_en_eth:              "USB-to-Ethernet",
    ae_bri_percent:          "Auto-Exposure Brightness %",
    lang:                    "Language",
    expt_heater_enable:      "Heater Enable (Extended)",
  };

  const HELPER: Record<string, string> = {
    stack_dither_pix:        "Dither by N pixels. Resets on reboot.",
    stack_dither_interval:   "Dither every N sub frames. Resets on reboot.",
    stack_dither_enable:     "Enable or disable dithering.",
    exp_ms_stack_l:          "Stacking sub-frame exposure length in milliseconds.",
    exp_ms_continuous:       "Continuous preview exposure length in milliseconds.",
    save_discrete_ok_frame:  "Save successful sub frames to storage.",
    save_discrete_frame:     "Save failed sub frames (suffix '_failed').",
    light_duration_min:      "Minutes the built-in flat-field light panel stays on. -1 uses the device default.",
    stack_capt_type:         "Capture mode used when building the live stack.",
    stack_capt_num:          "Number of frames to capture for the stack.",
    stack_brightness:        "Brightness adjustment applied to the live stack preview.",
    stack_contrast:          "Contrast adjustment applied to the live stack preview.",
    stack_saturation:        "Saturation adjustment applied to the live stack preview.",
    capt_type:               "Capture mode used when building the live stack.",
    capt_num:                "Number of frames to capture for the stack.",
    brightness:              "Brightness adjustment applied to the live stack preview.",
    contrast:                "Contrast adjustment applied to the live stack preview.",
    saturation:              "Saturation adjustment applied to the live stack preview.",
    goto:                    "Whether this stacking session is tied to a Goto/slew command.",
    move_sleep_sec:          "Settle time after a mount move before resuming capture, in seconds.",
    dbe_enable:              "Enable Dynamic Background Extraction for this stack session.",
    plan_target_af:          "Auto-focus before each target in an observation plan.",
    viewplan_gohome:         "Return the mount home after a plan finishes.",
    stack_after_goto:        "Automatically begin stacking once a goto/slew completes.",
    expert_mode:             "Enable advanced, expert-only controls in the app.",
    af_before_stack:         "Auto-focus immediately before starting a stack.",
    auto_af:                 "Automatically run autofocus before each capture.",
    auto_3ppa_calib:         "In AltAz mode, auto-calibrate at session start.",
    frame_calib:             "Apply dark/flat frame calibration to captured frames.",
    stack_masic:             "Enable mosaic-mode stacking across multiple panels.",
    rec_stablzn:             "Enable video stabilization while recording.",
    wide_cam:                "Enable the wide-angle camera (S30/S30P only).",
    wide_4k:                 "Capture wide-angle camera frames at 4K resolution.",
    wide_focal_pos:          "User-defined focal position for the wide-angle camera.",
    temp_unit:               "Temperature display unit: Celsius (C) or Fahrenheit (F).",
    focal_pos:               "Current user-calibrated focal position.",
    factory_focal_pos:       "Factory-default focal position used on startup.",
    heater_enable:           "Enable or disable the dew heater.",
    auto_power_off:          "Auto power-off when idle.",
    stack_lenhance:          "Enable Light Pollution (LP) filter.",
    auto_lenhance:           "Auto DSO enhancement during stacking (firmware 7.75+).",
    dark_mode:               "Disable LEDs during imaging.",
    cont_capt:               "Continuous capture disables live stacking.",
    drizzle2x:               "4K live stack with 2× drizzle.",
    beep_volume:             "Beep volume preset: off, close (quiet), backyard, or outdoor (loud).",
    dbe:                     "Dynamic Background Extraction during stacking.",
    star_trails:             "Render trails instead of stacking point sources.",
    star_correction:         "Correct star shapes during stacking.",
    airplane_line_removal:   "Remove airplane/satellite trail streaks during stacking.",
    wide_denoise:            "Apply denoise processing to wide-camera frames.",
    isp_exp_ms:              "Manual exposure time in milliseconds. Only used when Manual Exposure is enabled.",
    isp_gain:                "Manual sensor gain. Only used when Manual Exposure is enabled.",
    calib_location:          "Internal frame-calibration reference index.",
    wifi_country:            "WiFi regulatory country code.",
    manual_exp:              "Override auto-exposure with a fixed exposure and gain (see ISP Exposure / ISP Gain).",
    remote_joined:           "Whether a remote client has joined this session.",
    guest_mode:              "Allow multiple app clients to connect at once; one acts as the master controller.",
    user_stack_sim:          "Simulate the stacking process without real frames (debug).",
    usb_en_eth:              "Enable USB-to-Ethernet adapter support (debug).",
    ae_bri_percent:          "Target brightness percentage for auto-exposure.",
    lang:                    "Device UI language code.",
    expt_heater_enable:      "Enable the extended/experimental dew heater control.",
  };

  import { settingGroupFor } from "../lib/utils";

  const groupFor = settingGroupFor;
  const GROUP_ORDER = ["Imaging", "Environment", "Mount & Focus", "General"];

  const ENUMS: Record<string, { value: string; label: string }[]> = {
    beep_volume: [
      { value: "off",      label: "Off" },
      { value: "close",    label: "Close (quiet)" },
      { value: "backyard", label: "Backyard" },
      { value: "outdoor",  label: "Outdoor (loud)" },
    ],
  };

  // Known per-field constraints (min/max) matching the classic UI
  const CONSTRAINTS: Record<string, { min?: number; max?: number }> = {
    exp_ms_stack_l:        { min: 5,  max: 90000 },
    exp_ms_continuous:     { min: 5,  max: 90000 },
    stack_dither_pix:      { min: 10, max: 200   },
    stack_dither_interval: { min: 1              },
  };

  // Minimum firmware_ver_int required for a field to be shown. Populate as
  // specific fields' introduction firmware becomes known — empty for now,
  // so nothing is hidden until thresholds are confirmed.
  const FIRMWARE_MIN: Record<string, number> = {};

  function hideIfBelowFirmware(key: string, firmwareVerInt: number): boolean {
    const min = FIRMWARE_MIN[key];
    return min !== undefined && firmwareVerInt < min;
  }

  // These fields are device-reported "auto" sentinels when Manual Exposure
  // is off (e.g. isp_exp_ms: -999000, isp_gain: -9990) and only mean
  // something once manual_exp is enabled.
  const REQUIRES_MANUAL_EXP = new Set(["isp_exp_ms", "isp_gain"]);

  let merged: Record<string, unknown> = {};
  let firmwareVerInt = 0;
  let baseline = "";
  let saving = false;
  let saved = false;
  let error = "";
  let loading = true;
  let submitted = false;

  $: isDirty = JSON.stringify(merged) !== baseline;
  $: baselineObj = baseline ? (JSON.parse(baseline) as Record<string, unknown>) : {};

  async function load() {
    loading = true;
    error = "";
    try {
      const result = await api.devices.settings.get($activeDevNum) as {
        merged?: Record<string, unknown>;
        firmware_ver_int?: number;
      };
      merged = result.merged ?? {};
      firmwareVerInt = result.firmware_ver_int ?? 0;
      baseline = JSON.stringify(merged);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function save() {
    submitted = true;
    saving = true;
    error = "";
    try {
      await api.devices.settings.save($activeDevNum, merged);
      baseline = JSON.stringify(merged);
      saved = true;
      setTimeout(() => (saved = false), 2500);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }

  function reset() {
    merged = JSON.parse(baseline);
  }

  function setVal(key: string, val: unknown) {
    merged = { ...merged, [key]: val };
  }

  $: navGuardMessage.set(isDirty ? "You have unsaved changes. Leave this page?" : null);
  onDestroy(() => navGuardMessage.set(null));

  function beforeUnload(e: BeforeUnloadEvent) {
    if (isDirty) e.preventDefault();
  }

  onMount(() => {
    load();
    window.addEventListener("beforeunload", beforeUnload);
  });
  onDestroy(() => window.removeEventListener("beforeunload", beforeUnload));
  $: if ($activeDevNum) load();
</script>

<div class="page-hero">
  <p class="page-kicker">Configuration</p>
  <h1 class="page-title">Settings</h1>
  <p class="page-subtitle">Device capture, processing, and behavior controls.</p>
</div>

{#if $activeDevNum === 0}
  <div class="panel-card offline-msg">
    Settings are per-device. Select a specific telescope from the dropdown above.
  </div>
{:else if !$isConnected}
  <div class="panel-card offline-msg">
    Device {$activeDevNum} is offline. Connect to configure settings.
  </div>
{:else if loading}
  <div class="loading">Loading settings…</div>
{:else}

  {#if error}<div class="alert alert-error">{error}</div>{/if}

  <div class="settings-header">
    {#if isDirty}
      <span class="unsaved-pill">● Unsaved Changes</span>
    {/if}
    <div class="header-actions">
      {#if isDirty}
        <button class="btn btn-secondary" on:click={reset}>Reset</button>
      {/if}
      <button class="btn btn-primary" on:click={save} disabled={saving || !isDirty}>
        {saving ? "Saving…" : "Save Changes"}
      </button>
    </div>
  </div>

  {#if saved}<div class="alert alert-success">Settings saved successfully.</div>{/if}

  <div class:was-validated={submitted}>
  {#each GROUP_ORDER as group}
    {@const entries = Object.entries(merged).filter(([k]) => groupFor(k) === group && !hideIfBelowFirmware(k, firmwareVerInt))}
    {#if entries.length > 0}
      <div class="panel-card settings-group">
        <p class="group-title">{group}</p>
        <div class="settings-table">
          {#each entries as [key, val]}
            {@const isDirtyRow = baselineObj[key] !== undefined && val !== baselineObj[key]}
            <div class="setting-row" class:row--dirty={isDirtyRow}>
              <div class="setting-meta">
                <div class="setting-name">{FRIENDLY[key] ?? key}</div>
                {#if HELPER[key]}
                  <div class="setting-help">{HELPER[key]}</div>
                {/if}
              </div>
              <div class="setting-control">
                {#if ENUMS[key]}
                  <select
                    class="form-input narrow"
                    value={String(val ?? "")}
                    on:change={(e) => setVal(key, e.currentTarget.value)}
                  >
                    {#each ENUMS[key] as opt}
                      <option value={opt.value}>{opt.label}</option>
                    {/each}
                  </select>
                {:else if val === true || val === false}
                  <div class="radio-group">
                    <label class="radio-label">
                      <input type="radio" name={key} value="true"
                        checked={val === true}
                        on:change={() => setVal(key, true)} />
                      Enable
                    </label>
                    <label class="radio-label">
                      <input type="radio" name={key} value="false"
                        checked={val === false}
                        on:change={() => setVal(key, false)} />
                      Disable
                    </label>
                  </div>
                {:else if typeof val === "number"}
                  {@const manualExpRequired = REQUIRES_MANUAL_EXP.has(key) && merged.manual_exp !== true}
                  <input
                    type="number"
                    class="form-input narrow"
                    value={manualExpRequired ? "" : val}
                    placeholder={manualExpRequired ? "Auto" : undefined}
                    required={!manualExpRequired}
                    disabled={manualExpRequired}
                    min={CONSTRAINTS[key]?.min}
                    max={CONSTRAINTS[key]?.max}
                    on:input={(e) => setVal(key, +e.currentTarget.value)}
                  />
                  {#if manualExpRequired}
                    <div class="setting-help">Enable Manual Exposure to edit.</div>
                  {/if}
                {:else}
                  <input
                    type="text"
                    class="form-input narrow"
                    value={String(val ?? "")}
                    required
                    on:input={(e) => setVal(key, e.currentTarget.value)}
                  />
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  {/each}
  </div>

  <div class="save-footer">
    <button class="btn btn-primary" on:click={save} disabled={saving || !isDirty}>
      {saving ? "Saving…" : "Save Changes"}
    </button>
    {#if isDirty}
      <button class="btn btn-secondary" on:click={reset}>Reset</button>
    {/if}
  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }
  .loading     { color: var(--ui-muted); font-size: 0.9rem; padding: 2rem 0; }

  .settings-header {
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

  .settings-group { margin-bottom: 1rem; padding-bottom: 0.5rem; }

  .group-title {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ui-primary);
    margin: 0 0 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(44, 177, 255, 0.15);
  }

  .settings-table { display: flex; flex-direction: column; gap: 0; }

  .setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.65rem 0.5rem 0.65rem 0.5rem;
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
  }
  .setting-help {
    font-size: 0.75rem;
    color: var(--ui-muted);
    margin-top: 0.15rem;
    line-height: 1.4;
  }

  .setting-control { flex-shrink: 0; }

  .form-input.narrow {
    width: 140px;
    text-align: right;
  }

  .radio-group {
    display: flex;
    gap: 1rem;
  }
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

  @media (max-width: 600px) {
    .setting-row { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
    .form-input.narrow { width: 100%; text-align: left; }
  }
</style>
