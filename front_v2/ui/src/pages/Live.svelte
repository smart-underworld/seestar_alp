<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { activeDevNum, activeDeviceStatus, isConnected, deviceList, deviceStatuses } from "../lib/stores/deviceStore";
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

  // "idle"    – no mode selected yet
  // "loading" – mode started but device not yet streaming (covers loading.gif phase)
  // "live"    – device reports view_state === "working", show the MJPEG feed
  $: feedState = !activeMode || activeMode === "none" ? "idle"
               : $activeDeviceStatus?.view_state === "working" ? "live"
               : "loading";

  let focusPos: number | null = null;
  let expMs = 10000;
  let gain = 80;
  let modeError = "";
  let focusError = "";
  let focusing = false;
  let autoFocusing = false;

  // One-shot status refresh 2 s after starting a live mode — catches the initial
  // state transition without overlapping the 15 s global poll.  Ongoing updates
  // arrive via the "View" WebSocket event handled in deviceStore.
  let liveRefreshTimer: ReturnType<typeof setTimeout> | null = null;

  function startLiveRefresh() {
    stopLiveRefresh();
    liveRefreshTimer = setTimeout(async () => {
      liveRefreshTimer = null;
      try {
        const status = await api.devices.status($activeDevNum);
        deviceStatuses.update(prev => ({ ...prev, [$activeDevNum]: status }));
      } catch { /* best effort */ }
    }, 2000);
  }

  function stopLiveRefresh() {
    if (liveRefreshTimer !== null) {
      clearTimeout(liveRefreshTimer);
      liveRefreshTimer = null;
    }
  }

  async function setMode(mode: LiveMode) {
    modeError = "";
    try {
      if (mode === "none") {
        await api.devices.live.stopMode($activeDevNum);
        activeMode = null;
        stopLiveRefresh();
      } else {
        await api.devices.live.startMode($activeDevNum, mode);
        activeMode = mode;
        startLiveRefresh();
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

  // Recording
  let recording = false;
  let recordError = "";
  async function toggleRecord() {
    recordError = "";
    recording = true;
    try {
      await api.devices.live.record($activeDevNum);
    } catch (e) {
      recordError = String(e);
    } finally {
      recording = false;
    }
  }

  // Movement joystick — pointer-based control sending {angle, distance, force}
  // to /live/move every 250ms while dragging, mirroring the classic nipplejs control.
  let joystickZoneEl: HTMLDivElement;
  let joystickKnobEl: HTMLDivElement;
  let joystickDragging = false;
  let joystickKnobX = 0;
  let joystickKnobY = 0;
  const JOYSTICK_RADIUS = 100;
  const ZERO_VECTOR = { angle: 0, distance: 0, force: 0 };
  let joystickVector = ZERO_VECTOR;
  let joystickTimer: ReturnType<typeof setInterval> | null = null;
  let joystickSending = false;

  function sendJoystickMove(force = false) {
    if (joystickSending && !force) return;
    joystickSending = true;
    const { angle, distance, force: f } = joystickVector;
    api.devices.live.move($activeDevNum, angle, distance, f)
      .catch(() => { /* best effort */ })
      .finally(() => { joystickSending = false; });
  }

  function joystickPointerDown(evt: PointerEvent) {
    joystickDragging = true;
    joystickZoneEl.setPointerCapture(evt.pointerId);
    joystickPointerMove(evt);
  }

  function joystickPointerMove(evt: PointerEvent) {
    if (!joystickDragging) return;
    const rect = joystickZoneEl.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    let dx = evt.clientX - cx;
    let dy = evt.clientY - cy;
    const rawDist = Math.sqrt(dx * dx + dy * dy);
    const clamped = Math.min(rawDist, JOYSTICK_RADIUS);
    const ratio = rawDist > 0 ? clamped / rawDist : 0;
    dx *= ratio;
    dy *= ratio;
    joystickKnobX = dx;
    joystickKnobY = dy;

    const distance = clamped / JOYSTICK_RADIUS;
    // Screen Y grows downward; convert to a standard math angle (CCW from East).
    let degrees = Math.atan2(-dy, dx) * (180 / Math.PI);
    if (degrees < 0) degrees += 360;
    joystickVector = { angle: degrees, distance, force: distance };

    if (joystickTimer === null) {
      sendJoystickMove();
      joystickTimer = setInterval(() => sendJoystickMove(), 250);
    }
  }

  function joystickPointerUp(evt: PointerEvent) {
    if (!joystickDragging) return;
    joystickDragging = false;
    joystickZoneEl.releasePointerCapture(evt.pointerId);
    joystickKnobX = 0;
    joystickKnobY = 0;
    if (joystickTimer !== null) {
      clearInterval(joystickTimer);
      joystickTimer = null;
    }
    joystickVector = ZERO_VECTOR;
    sendJoystickMove(true);
  }

  // Rotation — persisted to localStorage, same key as classic UI
  let rotation = 0; // 0 | 90 | 180 | 270
  const ROTATION_KEY = 'ssc.live.rotation';

  // Zoom (digital, CSS scale)
  let zoom = 1.0;
  const ZOOM_STEP = 0.25;
  const ZOOM_MIN = 0.25;
  const ZOOM_MAX = 4.0;
  function zoomIn()    { zoom = Math.min(+(zoom + ZOOM_STEP).toFixed(2), ZOOM_MAX); }
  function zoomOut()   { zoom = Math.max(+(zoom - ZOOM_STEP).toFixed(2), ZOOM_MIN); }
  function zoomReset() { zoom = 1.0; }

  // Fullscreen — native API where available, fixed-overlay fallback for iOS Safari
  let feedCardEl: HTMLElement;
  let imgEl: HTMLImageElement;
  let isFullscreen = false;
  let isFakeFullscreen = false;

  onMount(() => {
    try {
      const r = parseInt(localStorage.getItem(ROTATION_KEY) || '0', 10);
      if ([0, 90, 180, 270].includes(r)) rotation = r;
    } catch { /* ignore */ }

    const onFsChange = () => {
      const el = document.fullscreenElement ?? (document as any).webkitFullscreenElement;
      isFullscreen = !!el;
      if (!el) { isFakeFullscreen = false; document.body.style.overflow = ''; }
    };
    document.addEventListener('fullscreenchange', onFsChange);
    document.addEventListener('webkitfullscreenchange', onFsChange);
    return () => {
      document.removeEventListener('fullscreenchange', onFsChange);
      document.removeEventListener('webkitfullscreenchange', onFsChange);
    };
  });

  onDestroy(() => {
    if (joystickTimer !== null) clearInterval(joystickTimer);
    stopLiveRefresh();
  });

  function rotateFeed() {
    rotation = (rotation + 90) % 360;
    try { localStorage.setItem(ROTATION_KEY, String(rotation)); } catch { /* ignore */ }
  }

  function toggleFullscreen() {
    if (isFullscreen) {
      if (isFakeFullscreen) {
        isFakeFullscreen = false;
        isFullscreen = false;
        document.body.style.overflow = '';
      } else {
        const exit = document.exitFullscreen ?? (document as any).webkitExitFullscreen;
        exit.call(document);
      }
      return;
    }
    zoom = 1.0;
    const req = feedCardEl.requestFullscreen ?? (feedCardEl as any).webkitRequestFullscreen;
    if (req) {
      req.call(feedCardEl);
    } else {
      // iOS Safari: no fullscreen API for non-video — use fixed viewport overlay
      isFakeFullscreen = true;
      isFullscreen = true;
      document.body.style.overflow = 'hidden';
    }
  }

  $: isQuarterTurn = rotation % 180 !== 0;
  $: imgTransform = [
    zoom !== 1 ? `scale(${zoom})` : '',
    rotation   ? `rotate(${rotation}deg)` : '',
  ].filter(Boolean).join(' ');

  $: s = $activeDeviceStatus;
  $: if ($activeDevNum) { activeMode = null; focusPos = null; zoom = 1.0; }
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
        <div class="panel-card feed-card" class:feed-fs={isFullscreen} bind:this={feedCardEl}>
          <div class="feed-title-row">
            <p class="panel-title">Live Feed</p>
            <div class="feed-controls">
              <button class="feed-btn" on:click={zoomOut} disabled={zoom <= ZOOM_MIN} aria-label="Zoom out">−</button>
              <button class="feed-btn zoom-label" on:click={zoomReset} title="Reset zoom to 1×" aria-label="Reset zoom to 1×">{zoom}×</button>
              <button class="feed-btn" on:click={zoomIn} disabled={zoom >= ZOOM_MAX} aria-label="Zoom in">+</button>
              <button
                class="feed-btn"
                on:click={rotateFeed}
                title="Rotate 90° (current: {rotation}°)"
                aria-label="Rotate live view 90 degrees, currently {rotation} degrees"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M21 2v6h-6"/>
                  <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
                  <path d="M3 22v-6h6"/>
                  <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
                </svg>
                {rotation}°
              </button>
              <button
                class="feed-btn"
                on:click={toggleFullscreen}
                title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
                aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
              >
                {#if isFullscreen}
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
                    <path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/>
                    <path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>
                  </svg>
                {:else}
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
                    <path d="M3 7V3h4"/><path d="M21 7V3h-4"/>
                    <path d="M3 17v4h4"/><path d="M21 17v4h-4"/>
                  </svg>
                {/if}
              </button>
            </div>
          </div>
          <div class="feed-wrap" class:feed-wrap-quarter={isQuarterTurn} class:feed-wrap-fs={isFullscreen}>
            <img
              bind:this={imgEl}
              src={vidUrl}
              alt="Live telescope feed"
              class="live-feed"
              class:live-feed-fs={isFullscreen}
              style={imgTransform ? `transform:${imgTransform}` : ''}
            />
            {#if feedState !== "live"}
              <div class="feed-placeholder">
                <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" class="scope-svg" aria-hidden="true">
                  <!-- Outer ring -->
                  <circle cx="100" cy="100" r="88" fill="none" stroke="currentColor" stroke-width="0.75" opacity="0.12"/>
                  <!-- Crosshairs -->
                  <line x1="100" y1="16" x2="100" y2="184" stroke="currentColor" stroke-width="0.75" opacity="0.18"/>
                  <line x1="16"  y1="100" x2="184" y2="100" stroke="currentColor" stroke-width="0.75" opacity="0.18"/>
                  <!-- Crosshair end ticks -->
                  <line x1="100" y1="16"  x2="100" y2="26"  stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.5"/>
                  <line x1="100" y1="174" x2="100" y2="184" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.5"/>
                  <line x1="16"  y1="100" x2="26"  y2="100" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.5"/>
                  <line x1="174" y1="100" x2="184" y2="100" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.5"/>
                  <!-- Inner focus ring -->
                  <circle cx="100" cy="100" r="38" fill="none" stroke="currentColor" stroke-width="1" opacity="0.2"/>
                  <!-- Rotating scan arc (only while actively connecting) -->
                  {#if feedState === "loading"}
                    <circle cx="100" cy="100" r="62" fill="none" stroke="currentColor" stroke-width="1.5"
                      stroke-dasharray="45 345" stroke-linecap="round" class="scan-arc"/>
                  {/if}
                  <!-- Corner brackets -->
                  <path d="M36 54 L36 36 L54 36"   fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.45"/>
                  <path d="M164 54 L164 36 L146 36" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.45"/>
                  <path d="M36 146 L36 164 L54 164" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.45"/>
                  <path d="M164 146 L164 164 L146 164" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.45"/>
                  <!-- Centre dot -->
                  <circle cx="100" cy="100" r="3.5" fill="currentColor" class="centre-dot"/>
                </svg>
                <div class="feed-placeholder-label">
                  {feedState === "idle" ? "Select a mode to begin" : "Connecting…"}
                </div>
              </div>
            {/if}
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

        <!-- Movement / joystick controls -->
        <div class="panel-card">
          <p class="panel-title">Movement</p>
          <div class="joystick-zone-wrap">
            <div
              class="joystick-zone"
              bind:this={joystickZoneEl}
              on:pointerdown={joystickPointerDown}
              on:pointermove={joystickPointerMove}
              on:pointerup={joystickPointerUp}
              on:pointercancel={joystickPointerUp}
              role="slider"
              aria-label="Telescope movement joystick"
              aria-valuenow={Math.round(joystickVector.distance * 100)}
              tabindex="0"
            >
              <div
                class="joystick-knob"
                bind:this={joystickKnobEl}
                style="transform: translate({joystickKnobX}px, {joystickKnobY}px)"
              ></div>
            </div>
          </div>
        </div>

        <!-- Recording -->
        <div class="panel-card">
          <p class="panel-title">Recording</p>
          {#if recordError}<div class="alert alert-error" style="margin-bottom:0.5rem">{recordError}</div>{/if}
          <button class="btn btn-secondary record-btn" on:click={toggleRecord} disabled={recording}>
            <span class="record-dot"></span>
            {recording ? "Starting…" : "Record"}
          </button>
        </div>

        <!-- Exposure controls -->
        <div class="panel-card">
          <p class="panel-title">Exposure</p>
          <div class="control-group">
            <label class="form-label" for="exp-slider">Exposure: <strong>{expMs} ms</strong></label>
            <input
              id="exp-slider"
              type="range" class="slider" min="100" max="60000" step="100"
              bind:value={expMs}
              on:change={onExpChange}
            />
            <div class="slider-ticks"><span>100</span><span>30 000</span><span>60 000</span></div>
          </div>
          <div class="control-group">
            <label class="form-label" for="gain-slider">Gain: <strong>{gain}</strong></label>
            <input
              id="gain-slider"
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

  .feed-title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.6rem;
  }
  .feed-title-row .panel-title { margin-bottom: 0; }

  .feed-controls {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .feed-btn {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.25rem 0.6rem;
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 6px;
    color: rgba(231, 237, 247, 0.6);
    font-size: 0.78rem;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s, background 0.15s;
    user-select: none;
  }
  .feed-btn:hover {
    color: var(--ui-body);
    border-color: rgba(255, 255, 255, 0.28);
    background: rgba(255, 255, 255, 0.06);
  }
  .feed-btn:disabled {
    opacity: 0.3;
    cursor: default;
  }
  .zoom-label {
    min-width: 2.8rem;
    text-align: center;
  }

  /* Fullscreen mode — driven by isFullscreen state, not :fullscreen pseudo-class
     (Svelte strips :fullscreen to a bare element selector, so it never applies) */
  .feed-fs {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: #000;
    border-radius: 0;
    border: none;
    padding: 0.5rem;
    display: flex;
    flex-direction: column;
  }
  .feed-wrap-fs {
    flex: 1;
    aspect-ratio: unset;
  }
  .live-feed-fs {
    height: 100%;
    min-height: 0;
  }

  /* Feed container */
  .feed-wrap {
    position: relative;
    overflow: hidden;
    width: 100%;
  }
  /* Square container for quarter turns — image fills it, object-fit:contain keeps full video visible */
  .feed-wrap-quarter {
    aspect-ratio: 1;
  }

  .live-feed {
    width: 100%;
    max-width: 100%;
    border-radius: 6px;
    display: block;
    background: #000;
    min-height: 200px;
    object-fit: contain;
    transform-origin: center center;
  }
  /* Fill the square container at quarter turns so rotate() acts on the full area */
  .feed-wrap-quarter .live-feed {
    height: 100%;
    min-height: 0;
  }
  /* Thematic placeholder that covers loading.gif and idle state */
  .feed-placeholder {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #0a0c10;
    border-radius: 6px;
    gap: 0.75rem;
    color: var(--ui-primary, #4da6ff);
  }
  .scope-svg {
    width: min(55%, 220px);
    height: auto;
    opacity: 0.9;
  }
  .feed-placeholder-label {
    font-size: 0.75rem;
    color: var(--ui-muted, #7a8a9a);
    letter-spacing: 0.06em;
  }
  .scan-arc {
    transform-origin: 100px 100px;
    animation: scan-rotate 2.4s linear infinite;
  }
  .centre-dot {
    animation: dot-pulse 2.4s ease-in-out infinite;
  }
  @keyframes scan-rotate {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }
  @keyframes dot-pulse {
    0%, 100% { opacity: 0.4; r: 3.5px; }
    50%       { opacity: 1;   r: 5px;   }
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

  .joystick-zone-wrap {
    display: flex;
    justify-content: center;
  }
  .joystick-zone {
    position: relative;
    width: 200px;
    height: 200px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--ui-border);
    touch-action: none;
    cursor: grab;
  }
  .joystick-zone:active { cursor: grabbing; }
  .joystick-knob {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 56px;
    height: 56px;
    margin: -28px 0 0 -28px;
    border-radius: 50%;
    background: var(--ui-accent);
    opacity: 0.85;
    pointer-events: none;
    transition: transform 0.05s linear;
  }

  .record-btn {
    width: 100%;
    justify-content: center;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .record-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--ui-danger);
    flex-shrink: 0;
  }

  @media (max-width: 900px) {
    .live-layout { flex-direction: column; }
    .live-sidebar { width: 100%; }
    .mode-grid { grid-template-columns: repeat(3, 1fr); }
  }
</style>
