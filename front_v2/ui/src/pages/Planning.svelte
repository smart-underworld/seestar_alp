<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  interface PlanningData {
    lat: number;
    lon: number;
    utc_offset: number;
    twilight: Record<string, string>;
    clear_dark_sky: { name?: string; dist_km?: number; href?: string; img?: string };
  }

  let data: PlanningData | null = null;
  let error = "";

  // Collapsible state for each card
  let open = { astroMosaic: true, twilight: true, clearDarkSky: true, astrospheric: true, clearOutside: true };

  // AstroMosaic "Send to Schedule" modal state
  let schedModal = false;
  let schedTarget = "";
  let schedRa = "";
  let schedDec = "";
  let schedExp = 10000;
  let schedGain = 80;
  let schedCount = 0;
  let schedLp = false;
  let schedGridX = 1;
  let schedGridY = 1;
  let schedOverlap = 20;
  let schedAdding = false;
  let schedError = "";

  // Whether the AstroMosaic scripts are loaded
  let mosaicReady = false;

  async function load() {
    try {
      const res = await fetch("/api/v1/planning");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (e) {
      error = String(e);
    }
  }

  function loadScript(src: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
      const s = document.createElement("script");
      s.src = src; s.async = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(s);
    });
  }

  function loadCss(href: string) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = href;
    document.head.appendChild(l);
  }

  async function initAstroMosaic(lat: number, lon: number, utcOffset: number) {
    loadCss("https://aladin.u-strasbg.fr/AladinLite/api/v2/latest/aladin.min.css");
    await loadScript("https://code.jquery.com/jquery-1.12.1.min.js");
    await loadScript("https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js");
    await loadScript("https://www.gstatic.com/charts/loader.js");
    await loadScript("/AstroMosaicEngine.js");

    // Replicate the classic template's inline <script> — AstroMosaicEngine.js
    // only provides StartAstroMosaicViewerEngine; the caller glue lives here.
    const w = window as Record<string, unknown>;

    let isProgrammaticUpdate = false;
    const viewer_params: Record<string, unknown> = {
      fov_x: 43.8, fov_y: 77.4,
      grid_type: "fov", grid_size_x: 1, grid_size_y: 1, grid_overlap: 20,
      location_lat: lat, location_lng: lon,
      horizonSoft: null, horizonHard: [30], meridian_transit: null,
      UTCdate_ms: null, timezoneOffset: utcOffset,
      isCustomMode: true,
      chartTextColor: "white", gridlinesColor: "gray", backgroundColor: "black",
      isRepositionModeFunc: () => {
        const cb = document.getElementById("repositionCheckbox") as HTMLInputElement;
        return cb?.checked ?? false;
      },
      repositionTargetFunc: (target_str: string) => {
        isProgrammaticUpdate = true;
        const el = document.getElementById("astro_mosaic_search_text") as HTMLInputElement;
        if (el) el.value = target_str;
        setTimeout(() => { isProgrammaticUpdate = false; }, 100);
      },
    };

    const runUpdate = () => {
      if (isProgrammaticUpdate) return;
      const get = (id: string) => (document.getElementById(id) as HTMLInputElement)?.value ?? "";
      const num = (id: string, def = 0) => Number(get(id)) || def;

      const seestar = get("seestar");
      if (seestar === "S50")    { viewer_params.fov_x = 43.8;  viewer_params.fov_y = 77.4;  }
      else if (seestar === "S30")     { viewer_params.fov_x = 73.2;  viewer_params.fov_y = 130.2; }
      else if (seestar === "S30 Pro") { viewer_params.fov_x = 144.4; viewer_params.fov_y = 256.7; }

      const gx = num("astro_mosaic_grid_x", 1);
      const gy = num("astro_mosaic_grid_y", 1);
      const ov = num("astro_mosaic_overlap", 20);
      if (gx === 1 && gy === 1) {
        viewer_params.grid_type = "fov"; viewer_params.grid_size_x = 1;
        viewer_params.grid_size_y = 1;  viewer_params.grid_overlap = 100;
      } else {
        viewer_params.grid_type = "mosaic"; viewer_params.grid_size_x = gx;
        viewer_params.grid_size_y = gy;     viewer_params.grid_overlap = ov;
      }
      viewer_params.am_fov_x = (viewer_params.fov_x as number * 60) / 3600;
      viewer_params.am_fov_y = (viewer_params.fov_y as number * 60) / 3600;

      if (viewer_params.UTCdate_ms == null) {
        const d = new Date();
        viewer_params.UTCdate_ms = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
      }

      const StartEngine = w["StartAstroMosaicViewerEngine"] as (
        type: string, target: string, params: unknown, panels: unknown,
        catalogs: unknown, overlap: unknown, resources: unknown
      ) => unknown;

      if (typeof StartEngine === "function") {
        StartEngine(
          "all", get("astro_mosaic_search_text"), viewer_params,
          {
            aladin_panel: "aladin-div", aladin_panel_text: "radec-div",
            dayvisibility_panel: "day-div",
            dayvisibility_panel_text: "dayvisibility-panel-text",
            yearvisibility_panel: "year-div",
            yearvisibility_panel_text: "yearvisibility-panel-text",
            status_text: "status-text", error_text: "error-text",
            panel_view_x: null, panel_view_y: null,
            panel_view_div: null, panel_view_text: null,
          },
          null,
          viewer_params.grid_overlap ?? 20,
          {
            isRepositionModeFunc: viewer_params.isRepositionModeFunc,
            repositionTargetFunc: viewer_params.repositionTargetFunc,
            sun_rise_set: () => ({ sunset: 0, sunrise: 0 }),
            object_altitude_init: () => ({}),
            object_altaz: () => ({ alt: 0, az: 0 }),
            object_altitude_get: () => 0,
            moon_position: () => ({ ra: 0, dec: 0 }),
            moon_topocentric_correction: () => 0,
            moon_distance: () => 0,
            getTargetAboveRightNow: () => [0, 0],
          }
        );
      }
    };

    // Expose as global so the search/select onchange handlers can call it
    w["update_astro_mosaic"] = runUpdate;

    // Google Charts triggers the initial render
    const google = w["google"] as { charts: { load: (v: string, o: unknown) => void; setOnLoadCallback: (fn: () => void) => void } };
    if (google?.charts) {
      google.charts.load("current", { packages: ["corechart"] });
      google.charts.setOnLoadCallback(runUpdate);
    } else {
      // Fallback if Google Charts not yet ready
      setTimeout(runUpdate, 500);
    }

    // Wire the "Send to Schedule" button
    const btn = document.getElementById("open_send_to_schedule_modal_btn");
    if (btn) btn.addEventListener("click", openSchedModal);

    mosaicReady = true;
  }

  function callUpdateMosaic() {
    const w = window as unknown as Record<string, unknown>;
    if (typeof w["update_astro_mosaic"] === "function") {
      (w["update_astro_mosaic"] as () => void)();
    }
  }

  async function initAstrospheric(lat: number, lon: number) {
    await loadScript("https://astrosphericcloudstorage.blob.core.windows.net/embed/astrosphericembed.js");
    const w = window as unknown as Record<string, unknown>;
    if (typeof w["m_AstrosphericEmbed"] === "object" && w["m_AstrosphericEmbed"] !== null) {
      const embed = w["m_AstrosphericEmbed"] as { Create: (id: string, lat: number, lon: number) => void };
      embed.Create("AstrosphericEmbedContainer", lat, lon);
    }
  }

  function openSchedModal() {
    // Read current values from the AstroMosaic form fields
    schedRa  = (document.getElementById("ra")  as HTMLInputElement)?.value ?? "";
    schedDec = (document.getElementById("dec") as HTMLInputElement)?.value ?? "";
    schedGridX  = parseInt((document.getElementById("astro_mosaic_grid_x")  as HTMLInputElement)?.value ?? "1") || 1;
    schedGridY  = parseInt((document.getElementById("astro_mosaic_grid_y")  as HTMLInputElement)?.value ?? "1") || 1;
    schedOverlap = parseInt((document.getElementById("astro_mosaic_overlap") as HTMLInputElement)?.value ?? "20") || 20;
    schedError = "";
    schedModal = true;
  }

  async function sendToSchedule() {
    schedAdding = true;
    schedError = "";
    try {
      await api.devices.schedule.addItem($activeDevNum, "start_mosaic", {
        target_name:           schedTarget,
        ra:                    schedRa,
        dec:                   schedDec,
        is_j2000:              true,
        exp_ms:                schedExp,
        gain:                  schedGain,
        count:                 schedCount,
        lp_filter:             schedLp,
        panel_overlap_percent: schedOverlap,
        panel_x:               schedGridX,
        panel_y:               schedGridY,
      });
      schedModal = false;
    } catch (e) {
      schedError = String(e);
    } finally {
      schedAdding = false;
    }
  }

  onMount(async () => {
    await load();
    if (data) {
      await initAstroMosaic(data.lat, data.lon, data.utc_offset);
      await initAstrospheric(data.lat, data.lon);
    }
  });
</script>

<div class="page-hero">
  <p class="page-kicker">Observation</p>
  <h1 class="page-title">Planning</h1>
  <p class="page-subtitle">Sky atlas, weather forecasts, and twilight times for your location.</p>
</div>

{#if error}<div class="alert alert-error">{error}</div>{/if}

<!-- ── AstroMosaic ───────────────────────────────────────────────────── -->
<div class="panel-card section-card">
  <div class="section-header" on:click={() => (open.astroMosaic = !open.astroMosaic)} role="button" tabindex="0" on:keydown={(e) => e.key === "Enter" && (open.astroMosaic = !open.astroMosaic)}>
    <p class="group-title">AstroMosaic</p>
    <span class="chevron" class:open={open.astroMosaic}>▼</span>
  </div>

  {#if open.astroMosaic}
    {#if !mosaicReady}
      <div class="loading">Loading sky atlas…</div>
    {/if}

    <!-- Controls -->
    <div class="mosaic-controls" class:hidden={!mosaicReady}>
      <div class="ctrl-grid">
        <div class="ctrl-cell">
          <label class="ctrl-label" for="astro_mosaic_search_text">Search</label>
          <div class="ctrl-row">
            <input type="text" class="form-input" id="astro_mosaic_search_text" value="M33" />
            <button class="btn btn-primary" type="button" id="astro_mosaic_search_button"
              on:click={callUpdateMosaic}>
              🔍
            </button>
          </div>
        </div>

        <div class="ctrl-cell">
          <label class="ctrl-label" for="seestar">Seestar Model</label>
          <select class="form-input" id="seestar" name="seestar"
            on:change={callUpdateMosaic}>
            <option value="S50">S50</option>
            <option value="S30">S30</option>
            <option value="S30 Pro">S30 Pro</option>
          </select>
        </div>

        <div class="ctrl-cell">
          <label class="ctrl-label">Grid (X × Y)</label>
          <div class="ctrl-row">
            <input type="number" class="form-input" id="astro_mosaic_grid_x" min="1" max="100" value="1"
              on:change={callUpdateMosaic} />
            <span style="color:var(--ui-muted);padding:0 0.25rem">×</span>
            <input type="number" class="form-input" id="astro_mosaic_grid_y" min="1" max="100" value="1"
              on:change={callUpdateMosaic} />
          </div>
        </div>

        <div class="ctrl-cell">
          <label class="ctrl-label" for="astro_mosaic_overlap">Overlap %</label>
          <input type="number" class="form-input" id="astro_mosaic_overlap" min="1" max="100" value="20"
            on:change={callUpdateMosaic} />
        </div>

        <div class="ctrl-cell">
          <label class="ctrl-label">Send to Schedule</label>
          <button class="btn btn-secondary" type="button" id="open_send_to_schedule_modal_btn"
            disabled={!$isConnected}>
            📅 Send
          </button>
        </div>
      </div>
    </div>

    <!-- Hidden inputs AstroMosaicEngine reads/writes -->
    <input type="hidden" id="ra" />
    <input type="hidden" id="dec" />
    <input type="hidden" id="repositionCheckbox" />

    <!-- Aladin viewer -->
    <div id="aladin-div" style="height:500px;width:100%;margin-top:0.75rem;border-radius:0.5rem;overflow:hidden;"></div>
    <!-- Visibility charts -->
    <div id="radec-div" style="width:300px;"></div>
    <div id="day-div"  style="height:300px;width:100%;margin-top:0.5rem;"></div>
    <div id="year-div" style="height:300px;width:100%;margin-top:0.5rem;"></div>
    <!-- Engine internals (hidden) -->
    <div id="dayvisibility-panel-text"  style="display:none;"></div>
    <div id="yearvisibility-panel-text" style="display:none;"></div>
    <div id="status-text" style="display:none;"></div>
    <div id="error-text"  style="display:none;"></div>
  {/if}
</div>

<!-- ── "Send to Schedule" modal ─────────────────────────────────────── -->
{#if schedModal}
  <div class="modal-backdrop" on:click={() => (schedModal = false)} role="presentation">
    <div class="modal-card" on:click|stopPropagation role="dialog" aria-modal="true" aria-label="Send to Schedule">
      <div class="modal-header">
        <span class="modal-title">Send Mosaic to Schedule</span>
        <button class="btn-close" on:click={() => (schedModal = false)} aria-label="Close">✕</button>
      </div>

      {#if schedError}<div class="alert alert-error" style="margin-bottom:0.75rem">{schedError}</div>{/if}

      <div class="modal-body">
        <div class="form-field">
          <label class="form-label" for="sched-target">Target Name</label>
          <input id="sched-target" class="form-input" type="text" bind:value={schedTarget} placeholder="e.g. M42" />
        </div>
        <div class="modal-row">
          <div class="form-field">
            <label class="form-label" for="sched-ra">Right Ascension</label>
            <input id="sched-ra" class="form-input" type="text" bind:value={schedRa} />
          </div>
          <div class="form-field">
            <label class="form-label" for="sched-dec">Declination</label>
            <input id="sched-dec" class="form-input" type="text" bind:value={schedDec} />
          </div>
        </div>
        <div class="modal-row">
          <div class="form-field">
            <label class="form-label" for="sched-exp">Exposure (ms)</label>
            <input id="sched-exp" class="form-input" type="number" min="100" max="60000" bind:value={schedExp} />
          </div>
          <div class="form-field">
            <label class="form-label" for="sched-gain">Gain</label>
            <input id="sched-gain" class="form-input" type="number" min="0" max="100" bind:value={schedGain} />
          </div>
          <div class="form-field">
            <label class="form-label" for="sched-count">Count (0=∞)</label>
            <input id="sched-count" class="form-input" type="number" min="0" bind:value={schedCount} />
          </div>
        </div>
        <div class="modal-row">
          <div class="form-field">
            <label class="form-label" for="sched-grid-x">Grid X</label>
            <input id="sched-grid-x" class="form-input" type="number" min="1" max="100" bind:value={schedGridX} />
          </div>
          <div class="form-field">
            <label class="form-label" for="sched-grid-y">Grid Y</label>
            <input id="sched-grid-y" class="form-input" type="number" min="1" max="100" bind:value={schedGridY} />
          </div>
          <div class="form-field">
            <label class="form-label" for="sched-ov">Overlap %</label>
            <input id="sched-ov" class="form-input" type="number" min="0" max="60" bind:value={schedOverlap} />
          </div>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={schedLp} /> LP Filter
        </label>
      </div>

      <div class="modal-footer">
        <button class="btn btn-secondary" on:click={() => (schedModal = false)}>Cancel</button>
        <button class="btn btn-primary" on:click={sendToSchedule} disabled={schedAdding || !schedRa || !schedDec}>
          {schedAdding ? "Adding…" : "Add to Schedule"}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- ── Twilight Times ────────────────────────────────────────────────── -->
<div class="panel-card section-card">
  <div class="section-header" on:click={() => (open.twilight = !open.twilight)} role="button" tabindex="0" on:keydown={(e) => e.key === "Enter" && (open.twilight = !open.twilight)}>
    <p class="group-title">Twilight Times</p>
    <span class="chevron" class:open={open.twilight}>▼</span>
  </div>
  {#if open.twilight}
    {#if data && Object.keys(data.twilight).length > 0}
      <div class="twilight-info">
        <span class="loc-tag">
          {data.lat.toFixed(3)}°, {data.lon.toFixed(3)}°
        </span>
      </div>
      <div class="tw-table">
        {#each Object.entries(data.twilight) as [label, time]}
          <div class="stat-row">
            <div class="stat-key">{label}</div>
            <div class="stat-value">{time}</div>
          </div>
        {/each}
      </div>
    {:else if data}
      <p class="muted-note">Set your latitude/longitude in Config → Seestar Init Defaults to enable twilight times.</p>
    {:else}
      <div class="loading">Loading…</div>
    {/if}
  {/if}
</div>

<!-- ── Clear Dark Sky ────────────────────────────────────────────────── -->
<div class="panel-card section-card">
  <div class="section-header" on:click={() => (open.clearDarkSky = !open.clearDarkSky)} role="button" tabindex="0" on:keydown={(e) => e.key === "Enter" && (open.clearDarkSky = !open.clearDarkSky)}>
    <p class="group-title">Clear Dark Sky</p>
    <span class="chevron" class:open={open.clearDarkSky}>▼</span>
  </div>
  {#if open.clearDarkSky}
    {#if data?.clear_dark_sky?.img}
      <p class="cds-meta">
        Nearest site: <strong>{data.clear_dark_sky.name}</strong>
        ({data.clear_dark_sky.dist_km} km away)
      </p>
      <a href={data.clear_dark_sky.href} target="_blank" rel="noopener">
        <img src={data.clear_dark_sky.img} alt="Clear Dark Sky chart" class="cds-img" />
      </a>
    {:else if data}
      <p class="muted-note">No Clear Dark Sky site found near your configured location. Set lat/lon in Config → Seestar Init Defaults.</p>
    {:else}
      <div class="loading">Loading…</div>
    {/if}
  {/if}
</div>

<!-- ── Astrospheric ──────────────────────────────────────────────────── -->
<div class="panel-card section-card">
  <div class="section-header" on:click={() => (open.astrospheric = !open.astrospheric)} role="button" tabindex="0" on:keydown={(e) => e.key === "Enter" && (open.astrospheric = !open.astrospheric)}>
    <p class="group-title">Astrospheric</p>
    <span class="chevron" class:open={open.astrospheric}>▼</span>
  </div>
  {#if open.astrospheric && data}
    <div id="AstrosphericEmbedContainer" style="width:100%;min-height:200px;"></div>
  {/if}
</div>

<!-- ── Clear Outside ─────────────────────────────────────────────────── -->
<div class="panel-card section-card">
  <div class="section-header" on:click={() => (open.clearOutside = !open.clearOutside)} role="button" tabindex="0" on:keydown={(e) => e.key === "Enter" && (open.clearOutside = !open.clearOutside)}>
    <p class="group-title">Clear Outside</p>
    <span class="chevron" class:open={open.clearOutside}>▼</span>
  </div>
  {#if open.clearOutside && data}
    {@const coUrl = `https://clearoutside.com/forecast/${data.lat}/${data.lon}`}
    {@const coImg = `https://clearoutside.com/forecast_image_large/${data.lat}/${data.lon}/forecast.png`}
    <a href={coUrl} target="_blank" rel="noopener">
      <img src={coImg} alt="Clear Outside forecast" class="co-img" />
    </a>
  {/if}
</div>

<style>
  .section-card { margin-bottom: 1rem; }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    user-select: none;
    margin-bottom: 0;
  }
  .section-header:focus-visible { outline: 2px solid var(--ui-primary); border-radius: 4px; }

  .group-title {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ui-primary);
    margin: 0;
  }

  .chevron {
    font-size: 0.65rem;
    color: var(--ui-muted);
    transition: transform 0.2s;
    transform: rotate(-90deg);
  }
  .chevron.open { transform: rotate(0deg); }

  .loading { color: var(--ui-muted); font-size: 0.88rem; padding: 1rem 0; }
  .muted-note { font-size: 0.85rem; color: var(--ui-muted); padding: 0.5rem 0; margin: 0; }
  .hidden { display: none; }

  /* AstroMosaic controls */
  .mosaic-controls { margin-top: 0.75rem; }
  .ctrl-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.6rem 0.75rem;
    align-items: end;
  }
  .ctrl-cell { display: flex; flex-direction: column; gap: 0.25rem; }
  .ctrl-label { font-size: 0.75rem; font-weight: 600; color: var(--ui-muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .ctrl-row { display: flex; align-items: center; gap: 0.35rem; }
  .ctrl-row .form-input { flex: 1; }

  /* Twilight */
  .twilight-info { margin-bottom: 0.5rem; }
  .loc-tag {
    font-size: 0.75rem;
    color: var(--ui-muted);
    font-family: "SF Mono","Fira Code",monospace;
  }
  .tw-table { max-width: 420px; }

  /* Clear Dark Sky */
  .cds-meta { font-size: 0.82rem; color: var(--ui-muted); margin: 0.4rem 0 0.6rem; }
  .cds-img { width: 100%; border-radius: 6px; }

  /* Clear Outside */
  .co-img { width: 100%; border-radius: 6px; }

  /* "Send to Schedule" modal */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.65);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 999;
    padding: 1rem;
  }
  .modal-card {
    background: var(--ui-surface-raised);
    border: 1px solid var(--ui-border);
    border-radius: var(--ui-radius);
    width: 100%;
    max-width: 560px;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: var(--ui-shadow);
  }
  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 1.25rem 0.75rem;
    border-bottom: 1px solid var(--ui-border);
  }
  .modal-title { font-weight: 600; font-size: 0.95rem; color: var(--ui-body); }
  .btn-close {
    background: none; border: none; cursor: pointer;
    color: var(--ui-muted); font-size: 1rem; line-height: 1;
    padding: 0.2rem;
  }
  .btn-close:hover { color: var(--ui-body); }
  .modal-body {
    padding: 1rem 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .modal-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.6rem; }
  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding: 0.75rem 1.25rem 1rem;
    border-top: 1px solid var(--ui-border);
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.83rem;
    color: var(--ui-body);
    cursor: pointer;
  }
  .checkbox-label input[type="checkbox"] {
    accent-color: var(--ui-primary);
    cursor: pointer;
  }
</style>
