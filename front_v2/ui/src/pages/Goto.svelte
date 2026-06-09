<script lang="ts">
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";
  import EventStatusPanel from "../lib/components/EventStatusPanel.svelte";

  const EVENTS = ["WheelMove", "AutoGoto", "PlateSolve"];

  let ra = "";
  let dec = "";
  let targetName = "";
  let status = "";
  let error = "";
  let slewing = false;

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
    searching = true;
    searchError = "";
    searchResult = null;
    try {
      const data = await api.devices.search($activeDevNum, searchQuery.trim(), searchCatalog);
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

  function applySearch() {
    if (!searchResult) return;
    if (searchResult.ra)  ra  = String(searchResult.ra);
    if (searchResult.dec) dec = String(searchResult.dec);
    const name = searchResult.name ?? searchResult.objectName ?? searchQuery;
    if (!targetName) targetName = String(name);
    searchResult = null;
    searchQuery = "";
  }

  async function doGoto() {
    error = "";
    status = "";
    slewing = true;
    try {
      await api.devices.goto($activeDevNum, ra, dec, targetName);
      status = "GoTo command sent — telescope is slewing.";
    } catch (e) {
      error = String(e);
    } finally {
      slewing = false;
    }
  }

  async function stopGoto() {
    error = "";
    try {
      await fetch(`/api/v1/devices/${$activeDevNum}/goto`, { method: "DELETE" });
      status = "GoTo cancelled.";
    } catch (e) {
      error = String(e);
    }
  }

  $: s = $activeDeviceStatus;
</script>

<div class="page-hero">
  <p class="page-kicker">Navigation</p>
  <h1 class="page-title">GoTo Target</h1>
  <p class="page-subtitle">Slew the telescope to a sky coordinate or named object.</p>
</div>

<EventStatusPanel events={EVENTS} />

{#if !$isConnected}
  <div class="panel-card offline-msg">
    Device {$activeDevNum} is offline. Connect to use GoTo.
  </div>
{:else}
  <div class="goto-layout">

    <div class="panel-card goto-form-card">
      {#if error}<div class="alert alert-error">{error}</div>{/if}
      {#if status}<div class="alert alert-success">{status}</div>{/if}

      <!-- ── Object search ──────────────────────────────────────────────── -->
      <div class="search-section">
        <div class="search-row">
          <select class="form-input search-catalog" bind:value={searchCatalog}>
            {#each CATALOGS as cat}
              <option value={cat.value}>{cat.label}</option>
            {/each}
          </select>
          <input
            class="form-input search-input"
            bind:value={searchQuery}
            placeholder="Object name…"
            on:keydown={(e) => e.key === "Enter" && doSearch()}
          />
          <button
            type="button"
            class="btn btn-secondary search-btn"
            on:click={doSearch}
            disabled={searching || !searchQuery.trim()}
          >{searching ? "…" : "🔍"}</button>
        </div>
        {#if searchError}<p class="search-error">{searchError}</p>{/if}
        {#if searchResult}
          <div class="search-result">
            <span class="search-coords">RA {searchResult.ra} · Dec {searchResult.dec}</span>
            <button type="button" class="btn btn-primary btn-sm" on:click={applySearch}>Use</button>
          </div>
        {/if}
      </div>

      <form on:submit|preventDefault={doGoto}>
        <div class="form-field" style="margin-bottom:1rem">
          <label class="form-label" for="tname">Target Name</label>
          <input id="tname" class="form-input" bind:value={targetName} placeholder="M31, NGC 224, Andromeda…" />
          <span class="field-hint">Optional — for display purposes only.</span>
        </div>

        <div class="coord-row">
          <div class="form-field">
            <label class="form-label" for="ra">Right Ascension (J2000)</label>
            <input id="ra" class="form-input" bind:value={ra} placeholder="10h 45m 3.6s" required />
          </div>
          <div class="form-field">
            <label class="form-label" for="dec">Declination (J2000)</label>
            <input id="dec" class="form-input" bind:value={dec} placeholder="+41° 16′ 9″" required />
          </div>
        </div>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary" disabled={slewing}>
            {#if slewing}⏳ Slewing…{:else}⌖ GoTo{/if}
          </button>
          <button type="button" class="btn btn-danger" on:click={stopGoto}>
            ⏹ Stop
          </button>
        </div>
      </form>
    </div>

    {#if s && (s.ra != null || s.mount_mode)}
      <div class="panel-card position-card">
        <p class="panel-title">Current Position</p>
        {#if s.mount_mode}
          <div class="stat-row">
            <div class="stat-key">Mount</div>
            <div class="stat-value">{s.mount_mode}</div>
          </div>
        {/if}
        {#if s.ra != null}
          <div class="stat-row">
            <div class="stat-key">RA (J2000)</div>
            <div class="stat-value coord">{s.ra.toFixed(6)}°</div>
          </div>
        {/if}
        {#if s.dec != null}
          <div class="stat-row">
            <div class="stat-key">Dec (J2000)</div>
            <div class="stat-value coord">{s.dec >= 0 ? "+" : ""}{s.dec.toFixed(6)}°</div>
          </div>
        {/if}
        {#if s.target}
          <div class="stat-row">
            <div class="stat-key">Last Target</div>
            <div class="stat-value">{s.target}</div>
          </div>
        {/if}
        {#if s.view_state && s.view_state !== "Idle"}
          <div class="stat-row">
            <div class="stat-key">State</div>
            <div class="stat-value">{s.view_state}</div>
          </div>
        {/if}
      </div>
    {/if}

  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }

  /* ── Object search ─────────────────────────────────────────────────── */
  .search-section {
    margin-bottom: 1rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }
  .search-row {
    display: flex;
    gap: 0.4rem;
    align-items: center;
  }
  .search-catalog { flex: 0 0 auto; font-size: 0.8rem; padding: 0.3rem 0.5rem; }
  .search-input   { flex: 1; }
  .search-btn     { flex-shrink: 0; padding: 0.3rem 0.65rem; }
  .search-error   { font-size: 0.8rem; color: var(--ui-danger); margin: 0.3rem 0 0; }
  .search-result  {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.5rem;
    padding: 0.45rem 0.65rem;
    background: rgba(44,177,255,0.07);
    border: 1px solid rgba(44,177,255,0.2);
    border-radius: 6px;
    font-size: 0.82rem;
  }
  .search-coords  { flex: 1; color: var(--ui-muted); font-family: "SF Mono","Fira Code",monospace; font-size: 0.78rem; }
  .btn-sm { padding: 0.2rem 0.6rem; font-size: 0.8rem; }

  .goto-layout {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .goto-form-card { flex: 1; min-width: 320px; }
  .position-card  { width: 260px; flex-shrink: 0; }

  .coord-row {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }
  .coord-row .form-field { flex: 1; }

  .field-hint {
    font-size: 0.72rem;
    color: var(--ui-muted);
    margin-top: 0.15rem;
  }

  .form-actions {
    display: flex;
    gap: 0.6rem;
    margin-top: 0.25rem;
  }

  .coord {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.82rem;
    font-variant-numeric: tabular-nums;
  }

  @media (max-width: 600px) {
    .coord-row { flex-direction: column; }
    .position-card { width: 100%; }
  }
</style>
