<script lang="ts">
  import { onMount } from "svelte";
  import { activeDevNum, activeDeviceStatus, isConnected, deviceList } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  const imgPort = 7556;
  $: vidUrl = `http://${location.hostname}:${imgPort}/${$activeDevNum}/vid`;

  type LiveMode = "none" | "star" | "sun" | "moon" | "planet" | "scenery";

  const modes: { id: LiveMode; label: string; icon: string; desc: string }[] = [
    { id: "none",    label: "Stop",    icon: "⏹",  desc: "Stop live view" },
    { id: "star",    label: "Star",    icon: "✦",  desc: "Deep sky / star mode" },
    { id: "sun",     label: "Sun",     icon: "☀",  desc: "Solar imaging" },
    { id: "moon",    label: "Moon",    icon: "🌙", desc: "Lunar imaging" },
    { id: "planet",  label: "Planet",  icon: "🪐", desc: "Planetary imaging" },
    { id: "scenery", label: "Scenery", icon: "🌄", desc: "Landscape / wide field" },
  ];

  let activeMode: LiveMode | null = null;
  let focusPos: number | null = null;
  let expMs = 10000;
  let gain = 80;
  let modeError = "";
  let focusError = "";
  let focusing = false;
  let autoFocusing = false;

  async function setMode(mode: LiveMode) {
    modeError = "";
    try {
      if (mode === "none") {
        await api.devices.live.stopMode($activeDevNum);
        activeMode = null;
      } else {
        await api.devices.live.startMode($activeDevNum, mode);
        activeMode = mode;
        loadFocus();
        loadExposure();
      }
    } catch (e) {
      modeError = String(e);
    }
  }

  async function loadFocus() {
    try {
      const r = await api.devices.live.getFocus($activeDevNum);
      focusPos = r.position;
    } catch { /* offline */ }
  }

  async function loadExposure() {
    try {
      const r = await api.devices.live.getExposure($activeDevNum);
      expMs = r.exp_ms;
      gain = r.gain;
    } catch { /* offline */ }
  }

  async function moveFocus(inc: number) {
    focusError = "";
    focusing = true;
    try {
      const r = await api.devices.live.moveFocus($activeDevNum, inc);
      focusPos = r.position;
    } catch (e) {
      focusError = String(e);
    } finally {
      focusing = false;
    }
  }

  async function doAutoFocus() {
    autoFocusing = true;
    try {
      await api.devices.live.autoFocus($activeDevNum);
    } finally {
      autoFocusing = false;
    }
  }

  async function onExpChange() {
    try { await api.devices.live.setExposure($activeDevNum, expMs); } catch { /* best effort */ }
  }

  async function onGainChange() {
    try { await api.devices.live.setGain($activeDevNum, gain); } catch { /* best effort */ }
  }

  $: s = $activeDeviceStatus;
  $: if ($activeDevNum) { activeMode = null; focusPos = null; }
</script>

<div class="page-hero">
  <p class="page-kicker">Capture</p>
  <h1 class="page-title">Live View</h1>
  {#each $deviceList.filter(d => d.device_num === $activeDevNum) as dev}
    <p class="page-subtitle">{dev.name} · {dev.ip_address}</p>
  {/each}
</div>

{#if !$isConnected}
  <div class="panel-card offline-msg">
    <span class="offline-dot"></span>
    Device {$activeDevNum} is offline or not connected.
  </div>
{:else}
  <div class="live-layout">

    <!-- Main column -->
    <div class="live-main">

      <!-- Mode selection -->
      <div class="panel-card">
        <p class="panel-title">Select Live Mode</p>
        {#if modeError}
          <div class="alert alert-error">{modeError}</div>
        {/if}
        <div class="mode-grid">
          {#each modes as m}
            <button
              class="mode-btn"
              class:active={activeMode === m.id}
              class:stop-btn={m.id === "none"}
              on:click={() => setMode(m.id)}
              title={m.desc}
            >
              <span class="mode-icon">{m.icon}</span>
              <span class="mode-label">{m.label}</span>
            </button>
          {/each}
        </div>
      </div>

      <!-- Live feed (always visible once mode is set) -->
      {#if activeMode && activeMode !== "none"}
        <div class="panel-card feed-card">
          <p class="panel-title">Live Feed</p>
          <div class="feed-wrap">
            <img src={vidUrl} alt="Live telescope feed" class="live-feed" />
            {#if s}
              <div class="feed-overlay">
                {#if s.view_state}<span class="chip">{s.view_state}</span>{/if}
                {#if s.ra != null}
                  <span class="chip">RA {s.ra.toFixed(3)}° / Dec {s.dec?.toFixed(3)}°</span>
                {/if}
                {#if s.stacked !== ""}
                  <span class="chip">{s.stacked} frames</span>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      {/if}

    </div>

    <!-- Sidebar controls (only when a mode is active) -->
    {#if activeMode && activeMode !== "none"}
      <aside class="live-sidebar">

        <!-- Status -->
        {#if s}
          <div class="panel-card">
            <p class="panel-title">Status</p>
            <div class="sidebar-stats">
              {#if s.view_state}
                <div class="stat-row"><div class="stat-key">State</div><div class="stat-value">{s.view_state}</div></div>
              {/if}
              {#if s.mode}
                <div class="stat-row"><div class="stat-key">Mode</div><div class="stat-value">{s.mode}</div></div>
              {/if}
              {#if s.stage}
                <div class="stat-row"><div class="stat-key">Stage</div><div class="stat-value">{s.stage}</div></div>
              {/if}
              {#if s.target}
                <div class="stat-row"><div class="stat-key">Target</div><div class="stat-value">{s.target}</div></div>
              {/if}
              {#if s.stacked !== ""}
                <div class="stat-row"><div class="stat-key">Stacked</div><div class="stat-value success">{s.stacked}</div></div>
              {/if}
              {#if s.failed !== "" && +s.failed > 0}
                <div class="stat-row"><div class="stat-key">Failed</div><div class="stat-value danger">{s.failed}</div></div>
              {/if}
            </div>
          </div>
        {/if}

        <!-- Exposure controls -->
        <div class="panel-card">
          <p class="panel-title">Exposure</p>
          <div class="control-group">
            <label class="form-label">Exposure: <strong>{expMs} ms</strong></label>
            <input
              type="range" class="slider" min="100" max="60000" step="100"
              bind:value={expMs}
              on:change={onExpChange}
            />
            <div class="slider-ticks"><span>100</span><span>30 000</span><span>60 000</span></div>
          </div>
          <div class="control-group">
            <label class="form-label">Gain: <strong>{gain}</strong></label>
            <input
              type="range" class="slider" min="0" max="300" step="1"
              bind:value={gain}
              on:change={onGainChange}
            />
            <div class="slider-ticks"><span>0</span><span>150</span><span>300</span></div>
          </div>
        </div>

        <!-- Focus controls -->
        <div class="panel-card">
          <p class="panel-title">Focus</p>
          {#if focusError}<div class="alert alert-error" style="margin-bottom:0.5rem">{focusError}</div>{/if}
          <div class="focus-position">
            Position: <strong>{focusPos ?? "—"}</strong>
          </div>
          <div class="focus-buttons">
            <button class="btn btn-secondary focus-step" on:click={() => moveFocus(-50)} disabled={focusing} title="Step −50">
              ⏮ −50
            </button>
            <button class="btn btn-secondary focus-step" on:click={() => moveFocus(-10)} disabled={focusing} title="Step −10">
              ◀ −10
            </button>
            <button class="btn btn-secondary focus-step" on:click={() => moveFocus(10)} disabled={focusing} title="Step +10">
              +10 ▶
            </button>
            <button class="btn btn-secondary focus-step" on:click={() => moveFocus(50)} disabled={focusing} title="Step +50">
              +50 ⏭
            </button>
          </div>
          <button class="btn btn-secondary auto-focus-btn" on:click={doAutoFocus} disabled={autoFocusing}>
            {#if autoFocusing}⏳ Auto-focusing…{:else}⊕ Auto Focus{/if}
          </button>
        </div>

      </aside>
    {/if}

  </div>
{/if}

<style>
  .offline-msg {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ui-danger);
    font-size: 0.9rem;
  }
  .offline-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--ui-danger);
    flex-shrink: 0;
  }

  .live-layout {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
  }
  .live-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 0;
  }
  .live-sidebar {
    width: 280px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .mode-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.6rem;
  }
  .mode-btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.3rem;
    padding: 0.85rem 0.5rem;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: var(--ui-radius-sm);
    color: var(--ui-body);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    font-size: 0.82rem;
  }
  .mode-btn:hover {
    background: rgba(44, 177, 255, 0.1);
    border-color: rgba(44, 177, 255, 0.3);
  }
  .mode-btn.active {
    background: rgba(44, 177, 255, 0.15);
    border-color: var(--ui-primary);
    color: var(--ui-primary);
  }
  .mode-btn.stop-btn:hover {
    background: rgba(233, 69, 96, 0.1);
    border-color: rgba(233, 69, 96, 0.35);
    color: var(--ui-danger);
  }
  .mode-icon { font-size: 1.4rem; line-height: 1; }
  .mode-label { font-weight: 500; }

  .feed-card {}
  .feed-wrap {
    position: relative;
    display: inline-block;
    width: 100%;
  }
  .live-feed {
    width: 100%;
    max-width: 100%;
    border-radius: 6px;
    display: block;
    background: #000;
    min-height: 200px;
    object-fit: contain;
  }
  .feed-overlay {
    position: absolute;
    bottom: 0.6rem;
    left: 0.6rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .chip {
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(4px);
    color: var(--ui-body);
    font-size: 0.72rem;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.08);
  }

  .sidebar-stats { display: flex; flex-direction: column; }
  .stat-value.success { color: var(--ui-success); }
  .stat-value.danger  { color: var(--ui-danger); }

  .control-group { margin-bottom: 0.75rem; }
  .control-group:last-child { margin-bottom: 0; }
  .slider {
    width: 100%;
    margin: 0.3rem 0 0.1rem;
    accent-color: var(--ui-primary);
    cursor: pointer;
  }
  .slider-ticks {
    display: flex;
    justify-content: space-between;
    font-size: 0.68rem;
    color: var(--ui-muted);
  }

  .focus-position {
    font-size: 0.85rem;
    color: var(--ui-muted);
    margin-bottom: 0.6rem;
  }
  .focus-position strong { color: var(--ui-body); }

  .focus-buttons {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
    gap: 0.4rem;
    margin-bottom: 0.6rem;
  }
  .focus-step {
    padding: 0.4rem 0.2rem;
    font-size: 0.72rem;
    justify-content: center;
  }
  .auto-focus-btn { width: 100%; justify-content: center; }

  @media (max-width: 900px) {
    .live-layout { flex-direction: column; }
    .live-sidebar { width: 100%; }
    .mode-grid { grid-template-columns: repeat(3, 1fr); }
  }
</style>
