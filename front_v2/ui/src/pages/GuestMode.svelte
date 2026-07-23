<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api, type GuestModeState } from "../lib/api";

  let state: GuestModeState | null = null;
  let error = "";
  let busy = false;
  let interval: ReturnType<typeof setInterval>;

  async function load() {
    try {
      state = await api.devices.guestmode.get($activeDevNum);
      error = "";
    } catch (e) {
      error = String(e);
    }
  }

  async function act(action: "grab" | "release") {
    busy = true;
    error = "";
    try {
      if (action === "grab") await api.devices.guestmode.grab($activeDevNum);
      else await api.devices.guestmode.release($activeDevNum);
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    load();
    interval = setInterval(load, 15000);
  });

  onDestroy(() => clearInterval(interval));

  $: $activeDevNum, load();

  $: canClaim  = state?.guest_mode && state?.master_index === -1 && !busy;
  $: canRelease = state?.guest_mode && state?.client_master && !busy;
</script>

<div class="page-hero">
  <div>
    <p class="page-kicker">Access</p>
    <h1 class="page-title">Guest Mode</h1>
    <p class="page-subtitle">Control ownership and active clients.</p>
  </div>
</div>

{#if $activeDevNum === 0}
  <div class="panel-card offline-msg">
    Guest mode is per-device. Select a specific telescope from the dropdown above.
  </div>
{:else if !$isConnected}
  <div class="panel-card offline-msg">Device {$activeDevNum} is offline.</div>
{:else if error}
  <div class="alert alert-error">{error}</div>
{:else if !state}
  <div class="panel-card"><p>Loading…</p></div>
{:else if !state.guest_mode}
  <div class="panel-card">
    <p class="mb-0">Guest mode is not available on this device (firmware {state.firmware_ver_int}).</p>
  </div>
{:else}
  <div class="panel-card clients-card">
    <p class="panel-title">Connected Clients</p>
    <div class="client-grid">
      {#each state.client_list as client, i}
        {@const isMaster = i === state.master_index}
        <div class="client-chip" class:master={isMaster} class:guest={!isMaster}>
          <span class="client-dot"></span>
          <span class="client-name">{client}</span>
          <span class="client-role">{isMaster ? "Controller" : "Guest"}</span>
        </div>
      {/each}
      {#if state.client_list.length === 0}
        <p class="no-clients">No clients connected.</p>
      {/if}
    </div>
  </div>

  <div class="panel-card actions-card">
    <p class="panel-title">Actions</p>
    <div class="action-row">
      <button
        class="btn btn-primary"
        disabled={!canClaim}
        on:click={() => act("grab")}
      >Claim Control</button>
      <button
        class="btn btn-secondary"
        disabled={!canRelease}
        on:click={() => act("release")}
      >Release Control</button>
    </div>
    {#if !state.client_master}
      <p class="hint">You are currently a guest. Claim control to operate the telescope.</p>
    {/if}
  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); }
  .mb-0 { margin: 0; }

  .clients-card { margin-bottom: 1rem; }

  .client-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-top: 0.5rem;
  }

  .client-chip {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.85rem;
    border-radius: var(--ui-radius-sm);
    border: 1px solid var(--ui-border);
    font-size: 0.85rem;
  }
  .client-chip.master {
    border-color: rgba(104, 211, 145, 0.35);
    background: rgba(104, 211, 145, 0.08);
  }
  .client-chip.guest {
    background: rgba(255, 255, 255, 0.03);
  }

  .client-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--ui-muted);
    flex-shrink: 0;
  }
  .master .client-dot { background: var(--ui-success); }

  .client-name { font-weight: 500; color: var(--ui-body); }
  .client-role {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--ui-muted);
  }
  .master .client-role { color: var(--ui-success); }

  .no-clients { color: var(--ui-muted); font-size: 0.85rem; margin: 0; }

  .action-row {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .hint {
    margin: 0.75rem 0 0;
    font-size: 0.82rem;
    color: var(--ui-muted);
  }
</style>
