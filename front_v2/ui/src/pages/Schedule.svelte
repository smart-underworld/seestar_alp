<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { dndzone } from "svelte-dnd-action";
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";
  import type { ScheduleItem } from "../lib/api";

  // ---- Action definitions -----------------------------------------------

  type ActionGroup = "observation" | "setup" | "timing" | "control";
  type FieldType = "bool" | "int" | "float" | "text" | "time" | "range" | "select";

  interface FieldDef {
    key: string;
    label: string;
    type: FieldType;
    default: unknown;
    min?: number;
    max?: number;
    step?: number;
    placeholder?: string;
    options?: string[];
  }

  interface ActionDef {
    key: string;
    label: string;
    group: ActionGroup;
    fields: FieldDef[];
    apiAction?: string;  // device-side action name when different from key
  }

  // Fields shared by both Mosaic and Image actions
  const MOSAIC_BASE_FIELDS: FieldDef[] = [
    { key: "target_name",      label: "Target Name",        type: "text",   default: "",      placeholder: "e.g. M42" },
    { key: "ra",               label: "RA",                 type: "text",   default: "",      placeholder: "e.g. 05h35m17.3s" },
    { key: "dec",              label: "Dec",                type: "text",   default: "",      placeholder: "e.g. -05d23m28s" },
    { key: "is_j2000",         label: "J2000 Coords",       type: "bool",   default: true },
    { key: "panel_time_sec",   label: "Panel Time (s)",     type: "int",    default: 3600,    min: 60, max: 86400, placeholder: "e.g. 3600 = 1h" },
    { key: "end_local_time",   label: "— or — End Time (local)", type: "time",  default: "",      placeholder: "Stop at this local time (handles midnight)" },
    { key: "gain",             label: "Gain",               type: "int",    default: 80,      min: 0, max: 100 },
    { key: "is_use_lp_filter", label: "LP Filter",          type: "bool",   default: false },
    { key: "is_use_autofocus", label: "Auto Focus",         type: "bool",   default: true },
    { key: "num_tries",        label: "Number of Retries",  type: "int",    default: 1,       min: 1, max: 10 },
    { key: "retry_wait_s",     label: "Retry Delay (s)",    type: "int",    default: 300,     min: 0, max: 3600 },
    { key: "stack_type",       label: "Stack Type (exp.)",  type: "select", default: "DeepSky", options: ["DeepSky", "SolarSystem", "MilkyWay"] },
  ];

  const ACTION_DEFS: ActionDef[] = [
    {
      key: "startup",
      label: "Startup",
      group: "setup",
      apiAction: "start_up_sequence",
      fields: [
        { key: "3ppa",        label: "Polar Align (3PPA)", type: "bool", default: true },
        { key: "auto_focus",  label: "Auto Focus",          type: "bool", default: true },
        { key: "dark_frames", label: "Dark Frames",          type: "bool", default: false },
      ],
    },
    {
      key: "auto_focus",
      label: "Auto Focus",
      group: "setup",
      fields: [
        { key: "try_count", label: "Rounds", type: "int", default: 1, min: 1, max: 10 },
      ],
    },
    {
      key: "adjust_focus",
      label: "Focus Steps",
      group: "setup",
      fields: [
        { key: "steps", label: "Focus Step", type: "int", default: 0, min: -5000, max: 5000 },
      ],
    },
    {
      key: "action_set_exposure",
      label: "Exposure",
      group: "setup",
      fields: [
        { key: "exp", label: "Exposure (ms)", type: "int", default: 10000, min: 100, max: 60000 },
      ],
    },
    {
      key: "action_set_dew_heater",
      label: "Dew Heater",
      group: "setup",
      fields: [
        { key: "heater", label: "Heater Power (0–100)", type: "range", default: 0, min: 0, max: 100, step: 1 },
      ],
    },
    {
      key: "lpf",
      label: "LP Filter",
      group: "setup",
      apiAction: "set_wheel_position",
      fields: [
        { key: "enable", label: "Enable LP Filter", type: "bool", default: true },
      ],
    },
    {
      key: "start_mosaic",
      label: "Mosaic",
      group: "observation",
      fields: [
        ...MOSAIC_BASE_FIELDS,
        { key: "ra_num",                label: "RA Panels",         type: "int",  default: 1,  min: 1, max: 10 },
        { key: "dec_num",               label: "Dec Panels",        type: "int",  default: 1,  min: 1, max: 10 },
        { key: "panel_overlap_percent", label: "Panel Overlap %",   type: "int",  default: 30, min: 0, max: 60 },
        { key: "selected_panels",       label: "Selected Panels",   type: "text", default: "",  placeholder: "e.g. 1;2;4 (empty = all)" },
      ],
    },
    {
      key: "image",
      label: "Image (1×1)",
      group: "observation",
      apiAction: "start_mosaic",
      fields: MOSAIC_BASE_FIELDS,
    },
    {
      key: "wait_for",
      label: "Wait For",
      group: "timing",
      fields: [
        { key: "timer_sec", label: "Seconds", type: "int", default: 60, min: 1, max: 86400 },
      ],
    },
    {
      key: "wait_until",
      label: "Wait Until",
      group: "timing",
      fields: [
        { key: "local_time", label: "Time (local)", type: "time", default: "23:00" },
      ],
    },
    {
      key: "scope_park",
      label: "Park",
      group: "control",
      fields: [],
    },
    {
      key: "shutdown",
      label: "Shutdown",
      group: "control",
      fields: [],
    },
  ];

  // Covers both frontend keys and device action names so the queue renders readable labels
  const ACTION_LABELS: Record<string, string> = {
    ...Object.fromEntries(ACTION_DEFS.map((a) => [a.key, a.label])),
    start_up_sequence:    "Startup",
    auto_focus:           "Auto Focus",
    adjust_focus:         "Focus Steps",
    action_set_exposure:  "Exposure",
    action_set_dew_heater:"Dew Heater",
    set_wheel_position:   "LP Filter",
    scope_park:           "Park",
    start_mosaic:         "Mosaic",
  };

  const GROUPS: { key: ActionGroup; label: string }[] = [
    { key: "observation", label: "Observation" },
    { key: "setup",       label: "Setup" },
    { key: "timing",      label: "Timing" },
    { key: "control",     label: "Control" },
  ];

  const FEDERATION_MODES = ["by_time", "by_panel", "duplicate"];

  // ---- Component state --------------------------------------------------

  type DndItem = ScheduleItem & { id: string };

  let items: DndItem[] = [];
  let schedState = "";
  let error = "";
  let loading = false;
  let adding = false;
  let reordering = false;
  let confirmClear = false;

  let selectedAction = "";
  let formValues: Record<string, unknown> = {};

  // Object search (mosaic / image forms only)
  let searchQuery = "";
  let searching = false;
  let searchError = "";
  let searchResult: Record<string, unknown> | null = null;

  // Federation settings (device 0 only, mosaic / image)
  let federationMode = "by_time";
  let maxDevices = 4;

  let refreshInterval: ReturnType<typeof setInterval> | null = null;

  // Edit mode state
  let editMode = false;
  let editingItemId = "";
  let saving = false;

  // ---- Helpers ----------------------------------------------------------

  function getActionDef(key: string): ActionDef | undefined {
    return ACTION_DEFS.find((a) => a.key === key);
  }

  function initFormDefaults(actionKey: string) {
    const def = getActionDef(actionKey);
    if (!def) return;
    formValues = Object.fromEntries(def.fields.map((f) => [f.key, f.default]));
    searchQuery = "";
    searchResult = null;
    searchError = "";
  }

  function selectAction(key: string) {
    if (selectedAction === key) {
      selectedAction = "";
      formValues = {};
    } else {
      selectedAction = key;
      initFormDefaults(key);
    }
  }

  function setField(key: string, value: unknown) {
    formValues = { ...formValues, [key]: value };
  }

  function isMosaicLike(key: string) {
    return key === "start_mosaic" || key === "image";
  }

  function toDndItems(raw: ScheduleItem[]): DndItem[] {
    return raw.map((item) => ({ ...item, id: item.schedule_item_id }));
  }

  function isActive(st: string) {
    return st === "running" || st === "working";
  }

  function stateColorClass(st: string): string {
    if (st === "running" || st === "working") return "state-success";
    if (st === "stopped" || st === "stopping") return "state-danger";
    return "state-muted";
  }

  function hasParams(item: ScheduleItem): boolean {
    const p = item.params;
    if (Array.isArray(p)) return (p as unknown[]).length > 0;
    if (!p || typeof p !== "object") return false;
    return Object.keys(p as object).length > 0;
  }

  function paramSummary(item: ScheduleItem): string {
    const p = item.params;
    if (Array.isArray(p)) return `[${(p as unknown[]).join(", ")}]`;
    if (!p || typeof p !== "object") return "";
    const entries = Object.entries(p as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .slice(0, 4);
    return entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join("  ·  ");
  }

  // ---- Object search ---------------------------------------------------

  async function doSearch() {
    if (!searchQuery.trim() || searching) return;
    searching = true;
    searchError = "";
    searchResult = null;
    try {
      const data = await api.devices.search($activeDevNum, searchQuery.trim());
      const r = data.result;
      if (!r || typeof r !== "object") {
        searchError = "No result found.";
      } else {
        searchResult = r as Record<string, unknown>;
      }
    } catch (e) {
      searchError = String(e);
    } finally {
      searching = false;
    }
  }

  function applySearchResult() {
    if (!searchResult) return;
    if (searchResult.ra)  setField("ra",  String(searchResult.ra));
    if (searchResult.dec) setField("dec", String(searchResult.dec));
    const name = searchResult.name ?? searchResult.objectName ?? searchQuery;
    setField("target_name", String(name));
    searchResult = null;
    searchQuery = "";
  }

  // ---- API actions -------------------------------------------------------

  async function load() {
    loading = true;
    error = "";
    try {
      const sched = await api.devices.schedule.get($activeDevNum);
      schedState = (sched.state as string) ?? "";
      items = toDndItems((sched.list as ScheduleItem[]) ?? []);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function addItem() {
    if (!selectedAction || adding) return;
    adding = true;
    error = "";
    try {
      const def = getActionDef(selectedAction);
      const action = def?.apiAction ?? selectedAction;
      let params: Record<string, unknown> | unknown[];

      if (selectedAction === "lpf") {
        // set_wheel_position expects a list: [2] = LP filter, [1] = IR cut
        params = formValues.enable ? [2] : [1];
      } else if (selectedAction === "image") {
        // Image is a 1×1 mosaic with fixed grid
        params = {
          ...formValues,
          ra_num: 1,
          dec_num: 1,
          panel_overlap_percent: 100,
          selected_panels: "",
        };
      } else {
        params = { ...formValues } as Record<string, unknown>;
      }

      // Append federation settings for mosaic-like actions when targeting all devices
      if (isMosaicLike(selectedAction) && $activeDevNum === 0) {
        (params as Record<string, unknown>).federation_mode = federationMode;
        (params as Record<string, unknown>).max_devices = maxDevices;
      }

      await api.devices.schedule.addItem($activeDevNum, action, params);
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      adding = false;
    }
  }

  async function deleteItem(itemId: string) {
    error = "";
    if (editingItemId === itemId) cancelEdit();
    try {
      await api.devices.schedule.deleteItem($activeDevNum, itemId);
      items = items.filter((i) => i.id !== itemId);
    } catch (e) {
      error = String(e);
    }
  }

  // ---- Edit helpers ------------------------------------------------------

  function findDefForItem(item: DndItem): ActionDef | undefined {
    if (item.action === "start_mosaic") {
      const p = item.params as Record<string, unknown>;
      if (p && Number(p.ra_num) === 1 && Number(p.dec_num) === 1)
        return getActionDef("image");
      return getActionDef("start_mosaic");
    }
    if (item.action === "set_wheel_position") return getActionDef("lpf");
    if (item.action === "start_up_sequence")  return getActionDef("startup");
    return ACTION_DEFS.find((d) => (d.apiAction ?? d.key) === item.action)
        ?? ACTION_DEFS.find((d) => d.key === item.action);
  }

  function paramsToFormValues(def: ActionDef, params: unknown): Record<string, unknown> {
    const defaults = Object.fromEntries(def.fields.map((f) => [f.key, f.default]));
    if (def.key === "lpf" && Array.isArray(params)) {
      return { ...defaults, enable: (params as number[])[0] === 2 };
    }
    if (params && typeof params === "object" && !Array.isArray(params)) {
      return { ...defaults, ...(params as Record<string, unknown>) };
    }
    return defaults;
  }

  function startEdit(item: DndItem) {
    const def = findDefForItem(item);
    if (!def) return;
    editingItemId = item.id;
    editMode = true;
    selectedAction = def.key;
    formValues = paramsToFormValues(def, item.params);
    if (isMosaicLike(def.key) && $activeDevNum === 0) {
      const p = item.params as Record<string, unknown>;
      if (p?.federation_mode) federationMode = String(p.federation_mode);
      if (p?.max_devices)     maxDevices = Number(p.max_devices);
    }
    searchQuery = "";
    searchResult = null;
    searchError = "";
  }

  function cancelEdit() {
    editMode = false;
    editingItemId = "";
    selectedAction = "";
    formValues = {};
  }

  async function saveEdit() {
    if (!editingItemId || saving) return;
    saving = true;
    error = "";
    try {
      const def = getActionDef(selectedAction);
      const action = def?.apiAction ?? selectedAction;
      let params: Record<string, unknown> | unknown[];

      if (selectedAction === "lpf") {
        params = formValues.enable ? [2] : [1];
      } else if (selectedAction === "image") {
        params = { ...formValues, ra_num: 1, dec_num: 1, panel_overlap_percent: 100, selected_panels: "" };
      } else {
        params = { ...formValues } as Record<string, unknown>;
      }

      if (isMosaicLike(selectedAction) && $activeDevNum === 0) {
        (params as Record<string, unknown>).federation_mode = federationMode;
        (params as Record<string, unknown>).max_devices = maxDevices;
      }

      const idx = items.findIndex((i) => i.id === editingItemId);
      const nextItem = items[idx + 1];

      await api.devices.schedule.deleteItem($activeDevNum, editingItemId);
      if (nextItem) {
        await api.devices.schedule.insertItem($activeDevNum, action, params as Record<string, unknown>, nextItem.id);
      } else {
        await api.devices.schedule.addItem($activeDevNum, action, params);
      }

      cancelEdit();
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }

  async function setState(state: "start" | "stop" | "pause") {
    error = "";
    try {
      await api.devices.schedule.setState($activeDevNum, state);
      await load();
    } catch (e) {
      error = String(e);
    }
  }

  async function clearSchedule() {
    confirmClear = false;
    error = "";
    try {
      await api.devices.schedule.clear($activeDevNum);
      items = [];
      schedState = "";
    } catch (e) {
      error = String(e);
    }
  }

  // Drag-and-drop reorder: clear then re-add in new order.
  async function reorderItems(newOrder: DndItem[]) {
    if (reordering || isActive(schedState)) return;
    reordering = true;
    error = "";
    items = newOrder;
    try {
      await api.devices.schedule.clear($activeDevNum);
      for (const item of newOrder) {
        await api.devices.schedule.addItem(
          $activeDevNum,
          item.action,
          (item.params ?? {}) as Record<string, unknown> | unknown[]
        );
      }
      await load();
    } catch (e) {
      error = String(e);
      await load();
    } finally {
      reordering = false;
    }
  }

  // ---- DnD event handlers -----------------------------------------------

  function handleConsider(e: CustomEvent<{ items: DndItem[] }>) {
    items = e.detail.items;
  }

  function handleFinalize(e: CustomEvent<{ items: DndItem[] }>) {
    reorderItems(e.detail.items);
  }

  // ---- Auto-refresh ------------------------------------------------------

  function startAutoRefresh() {
    stopAutoRefresh();
    refreshInterval = setInterval(async () => {
      if (isActive(schedState)) await load();
    }, 10000);
  }

  function stopAutoRefresh() {
    if (refreshInterval !== null) {
      clearInterval(refreshInterval);
      refreshInterval = null;
    }
  }

  $: if (isActive(schedState)) {
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }

  // ---- Lifecycle ---------------------------------------------------------

  onMount(load);
  $: if ($activeDevNum) load();
  onDestroy(stopAutoRefresh);
</script>

<div class="page-hero">
  <p class="page-kicker">Automation</p>
  <h1 class="page-title">Schedule</h1>
  <p class="page-subtitle">Build and manage the observation schedule queue.</p>
</div>

{#if !$isConnected}
  <div class="panel-card offline-msg">Device {$activeDevNum} is offline.</div>
{:else}
  {#if error}<div class="alert alert-error">{error}</div>{/if}

  <div class="builder-layout">
    <!-- ================================================================
         LEFT PANEL — Action Library
    ================================================================ -->
    <div class="library-panel panel-card">
      <p class="panel-title">{editMode ? "Edit Item" : "Action Library"}</p>

      {#if editMode}
        <div class="edit-banner">
          <span class="edit-banner-text">Editing existing item</span>
          <button class="btn-link" on:click={cancelEdit} type="button">← Cancel</button>
        </div>
      {/if}

      {#if !editMode}
        {#each GROUPS as group}
          <div class="action-group">
            <div class="group-label">{group.label}</div>
            <div class="chip-row">
              {#each ACTION_DEFS.filter((a) => a.group === group.key) as act}
                <button
                  class="chip"
                  class:active={selectedAction === act.key}
                  on:click={() => selectAction(act.key)}
                  type="button"
                  aria-pressed={selectedAction === act.key}
                >
                  {act.label}
                </button>
              {/each}
            </div>
          </div>
        {/each}
      {/if}

      <!-- Inline add-item form -->
      {#if selectedAction}
        {@const def = getActionDef(selectedAction)}
        {#if def}
          <div class="add-form">
            <div class="add-form-title">{editMode ? "Edit" : "Configure"}: {def.label}</div>

            <!-- Object search (mosaic / image only) -->
            {#if isMosaicLike(selectedAction)}
              <div class="search-section">
                <div class="search-label">Object Search</div>
                <div class="search-row">
                  <input
                    type="text"
                    class="form-input search-input"
                    placeholder="e.g. M31, Orion Nebula"
                    bind:value={searchQuery}
                    on:keydown={(e) => e.key === "Enter" && doSearch()}
                  />
                  <button
                    class="btn btn-secondary btn-sm search-btn"
                    on:click={doSearch}
                    disabled={searching || !searchQuery.trim()}
                    type="button"
                  >
                    {searching ? "…" : "Search"}
                  </button>
                </div>
                {#if searchError}
                  <div class="search-error">{searchError}</div>
                {/if}
                {#if searchResult}
                  <div class="search-result">
                    <span class="search-result-coords">
                      RA: {searchResult.ra ?? "?"} · Dec: {searchResult.dec ?? "?"}
                    </span>
                    <button class="btn btn-primary btn-sm" type="button" on:click={applySearchResult}>
                      Use
                    </button>
                  </div>
                {/if}
              </div>
            {/if}

            {#if def.fields.length === 0}
              <p class="no-params">No parameters required.</p>
            {:else}
              <div class="fields-grid">
                {#each def.fields as field}
                  <div class="form-field">
                    <label class="form-label" for="field-{field.key}">{field.label}</label>

                    {#if field.type === "bool"}
                      <div class="toggle-row">
                        <label class="toggle-label">
                          <input
                            type="radio"
                            name="field-{field.key}"
                            value="true"
                            checked={formValues[field.key] === true}
                            on:change={() => setField(field.key, true)}
                          /> On
                        </label>
                        <label class="toggle-label">
                          <input
                            type="radio"
                            name="field-{field.key}"
                            value="false"
                            checked={formValues[field.key] === false}
                            on:change={() => setField(field.key, false)}
                          /> Off
                        </label>
                      </div>

                    {:else if field.type === "select"}
                      <select
                        id="field-{field.key}"
                        class="form-input"
                        value={String(formValues[field.key] ?? field.default)}
                        on:change={(e) => setField(field.key, e.currentTarget.value)}
                      >
                        {#each (field.options ?? []) as opt}
                          <option value={opt}>{opt}</option>
                        {/each}
                      </select>

                    {:else if field.type === "range"}
                      <div class="range-row">
                        <input
                          id="field-{field.key}"
                          type="range"
                          min={field.min ?? 0}
                          max={field.max ?? 100}
                          step={field.step ?? 1}
                          value={Number(formValues[field.key])}
                          on:input={(e) => setField(field.key, +e.currentTarget.value)}
                          class="range-input"
                        />
                        <span class="range-val">{formValues[field.key]}</span>
                      </div>

                    {:else if field.type === "time"}
                      <input
                        id="field-{field.key}"
                        type="time"
                        class="form-input"
                        value={String(formValues[field.key] ?? "")}
                        on:input={(e) => setField(field.key, e.currentTarget.value)}
                      />

                    {:else if field.type === "int" || field.type === "float"}
                      {@const isPanelTimeDisabled = field.key === "panel_time_sec" && !!formValues.end_local_time}
                      <input
                        id="field-{field.key}"
                        type="number"
                        class="form-input"
                        class:input-disabled={isPanelTimeDisabled}
                        disabled={isPanelTimeDisabled}
                        min={field.min}
                        max={field.max}
                        step={field.type === "float" ? 0.001 : 1}
                        value={Number(formValues[field.key])}
                        on:input={(e) => setField(field.key, +e.currentTarget.value)}
                      />

                    {:else}
                      <input
                        id="field-{field.key}"
                        type="text"
                        class="form-input"
                        placeholder={field.placeholder ?? ""}
                        value={String(formValues[field.key] ?? "")}
                        on:input={(e) => setField(field.key, e.currentTarget.value)}
                      />
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}

            <!-- Federation settings (all-device target only, mosaic/image) -->
            {#if isMosaicLike(selectedAction) && $activeDevNum === 0}
              <div class="federation-section">
                <div class="federation-label">Federation Settings</div>
                <div class="form-field">
                  <label class="form-label" for="fed-mode">Mode</label>
                  <select
                    id="fed-mode"
                    class="form-input"
                    bind:value={federationMode}
                  >
                    {#each FEDERATION_MODES as m}
                      <option value={m}>{m}</option>
                    {/each}
                  </select>
                </div>
                <div class="form-field">
                  <label class="form-label" for="fed-max">Max Devices</label>
                  <input
                    id="fed-max"
                    type="number"
                    class="form-input"
                    min="1"
                    max="20"
                    bind:value={maxDevices}
                  />
                </div>
              </div>
            {/if}

            {#if editMode}
              <button class="btn btn-primary add-btn" on:click={saveEdit} disabled={saving}>
                {saving ? "Saving…" : "Save Changes"}
              </button>
              <button class="btn btn-secondary add-btn" on:click={cancelEdit} type="button" style="margin-top:0.5rem">
                Cancel
              </button>
            {:else}
              <button class="btn btn-primary add-btn" on:click={addItem} disabled={adding}>
                {adding ? "Adding…" : "+ Add to Schedule"}
              </button>
            {/if}
          </div>
        {/if}
      {/if}
    </div>

    <!-- ================================================================
         RIGHT PANEL — Queue
    ================================================================ -->
    <div class="queue-panel panel-card">
      <!-- Queue header -->
      <div class="queue-header">
        <div class="queue-header-left">
          <p class="panel-title" style="margin:0">Queue</p>
          {#if schedState}
            <span class="sched-state-badge {stateColorClass(schedState)}">{schedState}</span>
          {/if}
        </div>
        <div class="queue-actions">
          <button
            class="btn btn-secondary btn-sm"
            on:click={load}
            disabled={loading || reordering}
            title="Refresh"
          >
            {loading ? "…" : "↻"}
          </button>
          {#if !isActive(schedState)}
            <button
              class="btn btn-primary btn-sm"
              on:click={() => setState("start")}
              disabled={items.length === 0}
            >
              ▶ Start
            </button>
          {:else}
            <button class="btn btn-secondary btn-sm" on:click={() => setState("pause")}>
              ⏸ Pause
            </button>
            <button class="btn btn-danger btn-sm" on:click={() => setState("stop")}>
              ⏹ Stop
            </button>
          {/if}
          {#if items.length > 0 && !isActive(schedState)}
            <button class="btn btn-danger btn-sm" on:click={() => (confirmClear = true)}>
              ⊘ Clear
            </button>
          {/if}
        </div>
      </div>

      {#if confirmClear}
        <div class="confirm-bar">
          <span>Clear all {items.length} item{items.length !== 1 ? "s" : ""}?</span>
          <button class="btn btn-danger btn-sm" on:click={clearSchedule}>Yes, clear</button>
          <button class="btn btn-secondary btn-sm" on:click={() => (confirmClear = false)}>Cancel</button>
        </div>
      {/if}

      {#if reordering}
        <div class="alert alert-info reorder-notice">
          Reordering — clearing and re-adding items…
        </div>
      {/if}

      {#if isActive(schedState)}
        <div class="alert alert-info reorder-notice">
          Schedule is running. Drag reorder is disabled while active.
        </div>
      {/if}

      <!-- Queue list -->
      {#if loading && items.length === 0}
        <div class="loading">Loading schedule…</div>
      {:else if items.length === 0}
        <div class="empty-queue">
          <div class="empty-icon">📋</div>
          <div class="empty-text">Queue is empty</div>
          <div class="empty-sub">Select an action from the library and click "Add to Schedule".</div>
        </div>
      {:else}
        <div class="queue-count">
          {items.length} item{items.length !== 1 ? "s" : ""} in queue
        </div>

        <div
          class="dnd-list"
          use:dndzone={{ items, dragDisabled: isActive(schedState) || reordering }}
          on:consider={handleConsider}
          on:finalize={handleFinalize}
        >
          {#each items as item (item.id)}
            <div
              class="queue-item"
              class:done={item.state === "done"}
              class:working={item.state === "working"}
              class:editing={item.id === editingItemId}
            >
              <div
                class="drag-handle"
                title={isActive(schedState) ? "Disabled while running" : "Drag to reorder"}
                aria-label="Drag to reorder"
              >⠿</div>

              <div class="item-content">
                <div class="item-action">
                  {ACTION_LABELS[item.action] ?? item.action}
                  {#if item.state}
                    <span
                      class="item-state-badge"
                      class:state-success={item.state === "working"}
                      class:state-muted={item.state !== "working"}
                    >{item.state}</span>
                  {/if}
                </div>
                {#if hasParams(item)}
                  <div class="item-params">{paramSummary(item)}</div>
                {/if}
              </div>

              <button
                class="btn-icon edit-btn"
                on:click={() => startEdit(item)}
                disabled={isActive(schedState)}
                title="Edit item"
                aria-label="Edit {ACTION_LABELS[item.action] ?? item.action}"
              >✏</button>
              <button
                class="btn-icon delete-btn"
                on:click={() => deleteItem(item.id)}
                disabled={isActive(schedState)}
                title="Remove item"
                aria-label="Remove {ACTION_LABELS[item.action] ?? item.action}"
              >🗑</button>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }
  .loading     { color: var(--ui-muted); font-size: 0.9rem; padding: 1.5rem 0; }

  /* ---- Two-panel layout ---- */
  .builder-layout {
    display: grid;
    grid-template-columns: 38% 1fr;
    gap: 1.25rem;
    align-items: start;
  }
  @media (max-width: 768px) {
    .builder-layout { grid-template-columns: 1fr; }
  }

  /* ---- Library Panel ---- */
  .library-panel { display: flex; flex-direction: column; gap: 0.75rem; }

  .action-group { margin-bottom: 0.25rem; }
  .group-label {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ui-muted);
    margin-bottom: 0.4rem;
  }
  .chip-row { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .chip {
    padding: 0.28rem 0.75rem;
    border-radius: 99px;
    font-size: 0.78rem;
    font-weight: 500;
    cursor: pointer;
    border: 1px solid var(--ui-border);
    background: rgba(255,255,255,0.04);
    color: var(--ui-body);
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }
  .chip:hover { background: rgba(44,177,255,0.1); border-color: rgba(44,177,255,0.3); color: var(--ui-primary); }
  .chip.active { background: rgba(44,177,255,0.15); border-color: rgba(44,177,255,0.5); color: var(--ui-primary); }

  /* ---- Add Form ---- */
  .add-form {
    margin-top: 0.75rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--ui-border);
  }
  .add-form-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--ui-primary);
    margin-bottom: 0.75rem;
  }
  .no-params { font-size: 0.8rem; color: var(--ui-muted); margin: 0 0 0.75rem; }
  .fields-grid { display: flex; flex-direction: column; gap: 0.65rem; margin-bottom: 0.75rem; }

  .toggle-row { display: flex; gap: 1rem; }
  .toggle-label {
    display: flex; align-items: center; gap: 0.35rem;
    font-size: 0.82rem; color: var(--ui-body); cursor: pointer;
  }
  .toggle-label input[type="radio"] { accent-color: var(--ui-primary); cursor: pointer; }

  .range-row { display: flex; align-items: center; gap: 0.6rem; }
  .range-input { flex: 1; accent-color: var(--ui-primary); }
  .range-val { font-size: 0.82rem; color: var(--ui-body); min-width: 32px; text-align: right; }

  .add-btn { width: 100%; justify-content: center; margin-top: 0.5rem; }

  /* ---- Object search ---- */
  .search-section {
    margin-bottom: 0.75rem;
    padding: 0.6rem 0.75rem;
    background: rgba(44,177,255,0.04);
    border: 1px solid rgba(44,177,255,0.12);
    border-radius: var(--ui-radius-sm);
  }
  .search-label {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ui-primary);
    margin-bottom: 0.4rem;
    opacity: 0.8;
  }
  .search-row { display: flex; gap: 0.4rem; }
  .search-input { flex: 1; }
  .search-btn { flex-shrink: 0; }
  .search-error { font-size: 0.75rem; color: var(--ui-danger); margin-top: 0.35rem; }
  .search-result {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-top: 0.4rem;
    padding: 0.35rem 0.5rem;
    background: rgba(104,211,145,0.06);
    border: 1px solid rgba(104,211,145,0.2);
    border-radius: var(--ui-radius-sm);
  }
  .search-result-coords { font-size: 0.75rem; color: var(--ui-muted); }

  /* ---- Edit banner ---- */
  .edit-banner {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.4rem 0.65rem;
    background: rgba(98,126,234,0.1);
    border: 1px solid rgba(98,126,234,0.25);
    border-radius: var(--ui-radius-sm);
    font-size: 0.8rem;
  }
  .edit-banner-text { color: var(--ui-primary); font-weight: 500; }
  .btn-link {
    background: none;
    border: none;
    color: var(--ui-muted);
    cursor: pointer;
    font-size: 0.8rem;
    padding: 0;
    text-decoration: underline;
    text-decoration-color: transparent;
    transition: color 0.15s, text-decoration-color 0.15s;
  }
  .btn-link:hover { color: var(--ui-body); text-decoration-color: var(--ui-muted); }

  /* ---- Federation section ---- */
  .federation-section {
    margin: 0.75rem 0;
    padding: 0.6rem 0.75rem;
    background: rgba(255,200,50,0.04);
    border: 1px solid rgba(255,200,50,0.15);
    border-radius: var(--ui-radius-sm);
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .federation-label {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: rgba(255,200,50,0.8);
    margin-bottom: 0.1rem;
  }

  /* ---- Queue Panel ---- */
  .queue-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .queue-header-left { display: flex; align-items: center; gap: 0.6rem; }
  .queue-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }

  .sched-state-badge {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.15rem 0.55rem;
    border-radius: 99px;
  }
  .state-success { background: rgba(104,211,145,0.12); color: var(--ui-success); border: 1px solid rgba(104,211,145,0.3); }
  .state-danger  { background: rgba(233,69,96,0.12);  color: var(--ui-danger);  border: 1px solid rgba(233,69,96,0.25); }
  .state-muted   { background: rgba(255,255,255,0.06); color: var(--ui-muted);  border: 1px solid rgba(255,255,255,0.12); }

  .confirm-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: rgba(233,69,96,0.1);
    border: 1px solid rgba(233,69,96,0.25);
    border-radius: var(--ui-radius-sm);
    padding: 0.5rem 0.75rem;
    font-size: 0.82rem;
    color: var(--ui-danger);
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }

  .reorder-notice { margin-bottom: 0.75rem; font-size: 0.8rem; }

  .queue-count {
    font-size: 0.72rem;
    color: var(--ui-muted);
    margin-bottom: 0.5rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  /* ---- DnD list ---- */
  .dnd-list {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .queue-item {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.6rem 0.75rem;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--ui-border);
    border-radius: var(--ui-radius-sm);
    transition: opacity 0.2s, background 0.15s;
  }
  .queue-item:hover { background: rgba(255,255,255,0.055); }
  .queue-item.done    { opacity: 0.45; }
  .queue-item.working { border-color: rgba(104,211,145,0.3); background: rgba(104,211,145,0.04); }
  .queue-item.editing { border-color: rgba(98,126,234,0.5); background: rgba(98,126,234,0.07); }

  .drag-handle {
    font-size: 1.1rem;
    color: var(--ui-muted);
    cursor: grab;
    user-select: none;
    line-height: 1;
    flex-shrink: 0;
    opacity: 0.55;
    padding: 0 0.1rem;
  }
  .drag-handle:hover { opacity: 1; color: var(--ui-body); }

  .item-content { flex: 1; min-width: 0; }
  .item-action {
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--ui-body);
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .item-params {
    font-size: 0.72rem;
    color: var(--ui-muted);
    margin-top: 0.15rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
  }

  .item-state-badge {
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 0.1rem 0.4rem;
    border-radius: 99px;
  }

  .btn-icon {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.9rem;
    opacity: 0.45;
    transition: opacity 0.15s;
    padding: 0.2rem;
    flex-shrink: 0;
    line-height: 1;
    border-radius: var(--ui-radius-sm);
  }
  .btn-icon:hover:not(:disabled) { opacity: 1; }
  .btn-icon:disabled { opacity: 0.2; cursor: not-allowed; }
  .delete-btn:hover:not(:disabled) { color: var(--ui-danger); }
  .edit-btn:hover:not(:disabled) { color: var(--ui-primary); }

  .empty-queue {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2.5rem 1rem;
    text-align: center;
    gap: 0.4rem;
  }
  .empty-icon { font-size: 2rem; }
  .empty-text { font-weight: 600; color: var(--ui-body); font-size: 0.9rem; }
  .empty-sub  { font-size: 0.78rem; color: var(--ui-muted); line-height: 1.5; max-width: 260px; }

  :global(.btn-sm) {
    padding: 0.35rem 0.75rem !important;
    font-size: 0.8rem !important;
  }

  .input-disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
