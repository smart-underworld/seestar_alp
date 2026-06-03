<script lang="ts">
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let method = "";
  let paramsJson = "{}";
  let result: unknown = null;
  let error = "";
  let loading = false;

  const PRESETS = [
    { label: "Get Device State",  method: "get_device_state",  params: "{}" },
    { label: "Get View State",    method: "get_view_state",    params: "{}" },
    { label: "Get Setting",       method: "get_setting",       params: "{}" },
    { label: "Get Stack Setting", method: "get_stack_setting", params: "{}" },
    { label: "Get Focus Pos",     method: "get_focuser_position", params: "{}" },
    { label: "Auto Focus",        method: "start_auto_focus",  params: "{}" },
    { label: "Stop View",         method: "iscope_stop_view",  params: "{}" },
  ];

  function applyPreset(p: { method: string; params: string }) {
    method = p.method;
    paramsJson = p.params;
  }

  async function send() {
    error = "";
    result = null;
    loading = true;
    try {
      const params = JSON.parse(paramsJson);
      result = await api.devices.command($activeDevNum, method, params);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function formatResult(r: unknown): string {
    return JSON.stringify(r, null, 2);
  }
</script>

<div class="page-hero">
  <p class="page-kicker">Developer</p>
  <h1 class="page-title">Command</h1>
  <p class="page-subtitle">Send raw method calls directly to the telescope firmware.</p>
</div>

{#if !$isConnected}
  <div class="panel-card offline-msg">
    Device {$activeDevNum} is offline.
  </div>
{:else}
  <div class="cmd-layout">

    <div class="panel-card form-card">
      <p class="panel-title">Quick Presets</p>
      <div class="preset-grid">
        {#each PRESETS as p}
          <button class="preset-btn" on:click={() => applyPreset(p)}>{p.label}</button>
        {/each}
      </div>

      <div class="divider"></div>

      <form on:submit|preventDefault={send}>
        <div class="form-field" style="margin-bottom:0.75rem">
          <label class="form-label" for="cmd-method">Method</label>
          <input id="cmd-method" class="form-input" bind:value={method} placeholder="get_device_state" required />
        </div>
        <div class="form-field" style="margin-bottom:1rem">
          <label class="form-label" for="cmd-params">Parameters (JSON)</label>
          <textarea id="cmd-params" class="form-input" bind:value={paramsJson} rows="5"></textarea>
        </div>
        <button type="submit" class="btn btn-primary" disabled={loading || !method}>
          {loading ? "Sending…" : "▶ Send Command"}
        </button>
      </form>
    </div>

    <div class="result-col">
      {#if error}
        <div class="alert alert-error">{error}</div>
      {/if}
      {#if result !== null}
        <div class="panel-card result-card">
          <p class="panel-title">Response</p>
          <pre class="result-pre">{formatResult(result)}</pre>
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
  .form-card { width: 380px; flex-shrink: 0; }
  .result-col { flex: 1; min-width: 0; }

  .preset-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.25rem;
  }
  .preset-btn {
    padding: 0.3rem 0.7rem;
    font-size: 0.75rem;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    color: var(--ui-muted);
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
    white-space: nowrap;
  }
  .preset-btn:hover {
    background: rgba(44,177,255,0.1);
    border-color: rgba(44,177,255,0.25);
    color: var(--ui-primary);
  }

  .divider {
    height: 1px;
    background: rgba(255,255,255,0.07);
    margin: 1rem 0;
  }

  .result-card {}
  .result-pre {
    margin: 0;
    padding: 0.75rem;
    background: rgba(0,0,0,0.25);
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.06);
    font-size: 0.78rem;
    color: var(--ui-muted);
    overflow: auto;
    max-height: 60vh;
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

  @media (max-width: 700px) {
    .cmd-layout { flex-direction: column; }
    .form-card  { width: 100%; }
  }
</style>
