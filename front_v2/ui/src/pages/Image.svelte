<script lang="ts">
  import { activeDevNum, activeDeviceStatus, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";
  import EventStatusPanel from "../lib/components/EventStatusPanel.svelte";

  const EVENTS = ["WheelMove", "AutoGoto", "PlateSolve", "DarkLibrary", "AutoFocus", "Stack"];

  // Target
  let targetName = "";
  let ra = "";
  let dec = "";
  let isJ2000 = true;

  // Session
  let panelTimeSec = 3600;
  let endLocalTime = "";
  let gain = 80;
  let isUseLpFilter = false;
  let isUseAutofocus = true;

  // Retries
  let numTries = 1;
  let retryWaitS = 300;

  let status = "";
  let error = "";
  let imaging = false;

  // ── Object search ─────────────────────────────────────────────────────────
  const CATALOGS = [
    { value: "auto",     label: "Auto (Local → Simbad)" },
    { value: "local",    label: "Local DB" },
    { value: "simbad",   label: "Simbad (Online)" },
    { value: "planet",   label: "Planet / Moon" },
    { value: "asteroid", label: "Minor Planet / Asteroid" },
    { value: "comet",    label: "Comet" },
    { value: "variable", label: "Variable Star (AAVSO)" },
  ];
  let searchQuery = "";
  let searchCatalog = "auto";
  let searching = false;
  let searchError = "";
  let searchResult: Record<string, unknown> | null = null;

  async function doSearch() {
    if (!searchQuery.trim() || searching) return;
    searching = true; searchError = ""; searchResult = null;
    try {
      const data = await api.devices.search($activeDevNum, searchQuery.trim(), searchCatalog);
      const r = data.result;
      if (!r || typeof r !== "object") { searchError = "No result found."; }
      else { searchResult = r as Record<string, unknown>; }
    } catch (e) { searchError = String(e); }
    finally { searching = false; }
  }

  function applySearch() {
    if (!searchResult) return;
    if (searchResult.ra)  ra  = String(searchResult.ra);
    if (searchResult.dec) dec = String(searchResult.dec);
    const name = searchResult.name ?? searchResult.objectName ?? searchQuery;
    if (!targetName) targetName = String(name);
    searchResult = null;
    searchQuery = "";
  }

  async function startImaging() {
    error = "";
    status = "";
    imaging = true;
    try {
      const body: Record<string, unknown> = {
        target_name: targetName,
        ra,
        dec,
        is_j2000: isJ2000,
        ra_num: 1,
        dec_num: 1,
        panel_overlap_percent: 100,
        panel_time_sec: panelTimeSec,
        gain,
        is_use_lp_filter: isUseLpFilter,
        is_use_autofocus: isUseAutofocus,
        num_tries: numTries,
        retry_wait_s: retryWaitS,
      };
      if (endLocalTime) body.end_local_time = endLocalTime;
      await api.devices.mosaic.start($activeDevNum, body as Parameters<typeof api.devices.mosaic.start>[1]);
      status = "Imaging session started.";
    } catch (e) {
      error = String(e);
    } finally {
      imaging = false;
    }
  }

  async function stopImaging() {
    error = "";
    try {
      await api.devices.image.stop($activeDevNum);
      status = "Imaging stopped.";
    } catch (e) {
      error = String(e);
    }
  }

  $: s = $activeDeviceStatus;
  $: stacked = s?.stacked;
  $: failed  = s?.failed;
  $: isActive = stacked !== "" && stacked != null;
  $: panelTimeDisabled = !!endLocalTime;
</script>

<div class="page-hero">
  <p class="page-kicker">Capture</p>
  <h1 class="page-title">Image</h1>
  <p class="page-subtitle">Configure and start an imaging session.</p>
</div>

<EventStatusPanel events={EVENTS} />

{#if $activeDevNum === 0}
  <div class="panel-card offline-msg">
    Imaging requires a single telescope. Select a specific device from the dropdown above.
  </div>
{:else if !$isConnected}
  <div class="panel-card offline-msg">
    Device {$activeDevNum} is offline. Connect to start imaging.
  </div>
{:else}
  <div class="image-layout">

    <!-- Progress / live status -->
    {#if isActive}
      <div class="panel-card progress-card">
        <p class="panel-title">Session Progress</p>
        <div class="progress-nums">
          <div class="prog-val success">
            {stacked}
            <span class="prog-unit">stacked</span>
          </div>
          {#if failed !== "" && failed != null && +failed > 0}
            <div class="prog-val danger">
              {failed}
              <span class="prog-unit">failed</span>
            </div>
          {/if}
        </div>
        {#if s?.target}
          <div class="target-line">⌖ {s.target}</div>
        {/if}
      </div>
    {/if}

    <!-- Controls -->
    <div class="panel-card form-card">
      {#if error}<div class="alert alert-error">{error}</div>{/if}
      {#if status}<div class="alert alert-success">{status}</div>{/if}

      <!-- ── Object search ────────────────────────────────────────────── -->
      <div class="search-section">
        <div class="search-row">
          <select class="form-input search-catalog" bind:value={searchCatalog}>
            {#each CATALOGS as cat}<option value={cat.value}>{cat.label}</option>{/each}
          </select>
          <div class="search-input-row">
            <input class="form-input search-input" bind:value={searchQuery}
              placeholder="Object name…" on:keydown={(e) => e.key === "Enter" && doSearch()} />
            <button type="button" class="btn btn-secondary search-btn"
              on:click={doSearch} disabled={searching || !searchQuery.trim()}
            >{searching ? "…" : "🔍"}</button>
          </div>
        </div>
        {#if searchError}<p class="search-error">{searchError}</p>{/if}
        {#if searchResult}
          <div class="search-result">
            <span class="search-coords">RA {searchResult.ra} · Dec {searchResult.dec}</span>
            <button type="button" class="btn btn-primary btn-sm" on:click={applySearch}>Use</button>
          </div>
        {/if}
      </div>

      <form on:submit|preventDefault={startImaging}>

        <!-- ── Target ────────────────────────────────────────────────── -->
        <div class="section-label">Target</div>
        <div class="form-field" style="margin-bottom:0.75rem">
          <label class="form-label" for="iname">Target Name</label>
          <input id="iname" class="form-input" bind:value={targetName} placeholder="e.g. M42, Orion Nebula" />
        </div>

        <div class="coord-grid">
          <div class="form-field">
            <label class="form-label" for="ira">RA</label>
            <input id="ira" class="form-input" bind:value={ra} placeholder="e.g. 05h35m17.3s" />
          </div>
          <div class="form-field">
            <label class="form-label" for="idec">Dec</label>
            <input id="idec" class="form-input" bind:value={dec} placeholder="e.g. -05d23m28s" />
          </div>
        </div>

        <div class="form-field j2000-row">
          <span class="form-label">Coordinates</span>
          <div class="radio-row">
            <label class="radio-label"><input type="radio" bind:group={isJ2000} value={true} /> J2000</label>
            <label class="radio-label"><input type="radio" bind:group={isJ2000} value={false} /> JNow</label>
          </div>
        </div>

        <!-- ── Session ───────────────────────────────────────────────── -->
        <div class="section-label" style="margin-top:1rem">Session</div>

        <div class="param-grid">
          <div class="form-field">
            <label class="form-label" for="iptime">Panel Time (s)</label>
            <input id="iptime" type="number" class="form-input" class:input-dim={panelTimeDisabled}
              bind:value={panelTimeSec} min="60" max="86400" disabled={panelTimeDisabled} />
            <span class="field-hint">{panelTimeDisabled ? "— overridden by end time" : "e.g. 3600 = 1 h"}</span>
          </div>
          <div class="form-field">
            <label class="form-label" for="ietime">— or — End Time (local)</label>
            <input id="ietime" type="time" class="form-input" bind:value={endLocalTime} />
            <span class="field-hint">Leave blank to use panel time</span>
          </div>
          <div class="form-field">
            <label class="form-label" for="igain">Gain</label>
            <input id="igain" type="number" class="form-input" bind:value={gain} min="0" max="300" />
          </div>
        </div>

        <div class="toggle-grid">
          <div class="toggle-field">
            <span class="form-label">LP Filter</span>
            <div class="radio-row">
              <label class="radio-label"><input type="radio" bind:group={isUseLpFilter} value={true} /> On</label>
              <label class="radio-label"><input type="radio" bind:group={isUseLpFilter} value={false} /> Off</label>
            </div>
          </div>
          <div class="toggle-field">
            <span class="form-label">Auto Focus</span>
            <div class="radio-row">
              <label class="radio-label"><input type="radio" bind:group={isUseAutofocus} value={true} /> On</label>
              <label class="radio-label"><input type="radio" bind:group={isUseAutofocus} value={false} /> Off</label>
            </div>
          </div>
        </div>

        <!-- ── Retries ───────────────────────────────────────────────── -->
        <div class="section-label" style="margin-top:1rem">Retries</div>
        <div class="param-grid-2">
          <div class="form-field">
            <label class="form-label" for="itries">Number of Retries</label>
            <input id="itries" type="number" class="form-input" bind:value={numTries} min="1" max="10" />
          </div>
          <div class="form-field">
            <label class="form-label" for="iretry">Retry Delay (s)</label>
            <input id="iretry" type="number" class="form-input" bind:value={retryWaitS} min="0" max="3600" />
          </div>
        </div>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary" disabled={imaging}>
            {imaging ? "Starting…" : "▶ Start"}
          </button>
          <button type="button" class="btn btn-danger" on:click={stopImaging}>
            ⏹ Stop
          </button>
        </div>
      </form>
    </div>

  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }

  .search-section { margin-bottom: 1rem; padding-bottom: 1rem; border-bottom: 1px solid rgba(255,255,255,0.06); }
  .search-row { display: flex; flex-direction: row; gap: 0.4rem; align-items: center; }
  .search-catalog { width: auto; font-size: 0.85rem; flex-shrink: 0; }
  .search-input-row { display: flex; gap: 0.4rem; align-items: center; flex: 1; }
  .search-input { flex: 1; }
  .search-btn { flex-shrink: 0; padding: 0.3rem 0.65rem; }
  .search-error { font-size: 0.8rem; color: var(--ui-danger); margin: 0.3rem 0 0; }
  .search-result {
    display: flex; align-items: center; gap: 0.75rem; margin-top: 0.5rem;
    padding: 0.45rem 0.65rem; background: rgba(44,177,255,0.07);
    border: 1px solid rgba(44,177,255,0.2); border-radius: 6px; font-size: 0.82rem;
  }
  .search-coords { flex: 1; color: var(--ui-muted); font-family: "SF Mono","Fira Code",monospace; font-size: 0.78rem; }
  .btn-sm { padding: 0.2rem 0.6rem; font-size: 0.8rem; }

  .section-label {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ui-muted);
    margin: 0 0 0.65rem;
  }

  .image-layout {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .progress-card {}
  .progress-nums {
    display: flex;
    gap: 2rem;
    margin: 0.25rem 0;
  }
  .prog-val {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
    color: var(--ui-body);
  }
  .prog-val.success { color: var(--ui-success); }
  .prog-val.danger  { color: var(--ui-danger); }
  .prog-unit {
    font-size: 0.75rem;
    font-weight: 400;
    color: var(--ui-muted);
    display: block;
    margin-top: 0.2rem;
  }
  .target-line {
    font-size: 0.82rem;
    color: var(--ui-primary);
    margin-top: 0.5rem;
  }

  .coord-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }

  .j2000-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
  }

  .radio-row { display: flex; gap: 1rem; }
  .radio-label {
    display: flex; align-items: center; gap: 0.3rem;
    font-size: 0.83rem; color: var(--ui-body); cursor: pointer;
  }
  .radio-label input[type="radio"] { accent-color: var(--ui-primary); }

  .param-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }

  .toggle-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  .toggle-field {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .param-grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }

  .field-hint { font-size: 0.72rem; color: var(--ui-muted); margin-top: 0.15rem; }
  .input-dim { opacity: 0.4; cursor: not-allowed; }

  .form-actions { display: flex; gap: 0.6rem; margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid rgba(255,255,255,0.06); }

  @media (max-width: 600px) {
    .param-grid { grid-template-columns: 1fr; }
    .coord-grid { grid-template-columns: 1fr; }
    .toggle-grid { grid-template-columns: 1fr; }
    .param-grid-2 { grid-template-columns: 1fr; }
  }
</style>
