<script lang="ts">
  import { api } from "../lib/api";

  interface ActionEntry {
    command: string;
    label: string;
    confirm?: string;
  }

  const ACTIONS: ActionEntry[] = [
    { command: "restart_alp", label: "Restart SSC/Alp service" },
    { command: "restart_indi", label: "Restart INDI service" },
    { command: "reboot_rpi", label: "Reboot Rpi", confirm: "Reboot the Raspberry Pi? This will disconnect all clients." },
    { command: "shutdown_rpi", label: "Shutdown Rpi", confirm: "Shut down the Raspberry Pi?" },
  ];

  let platform = "";
  let loading = true;
  let runningCommand = "";
  let message = "";
  let error = "";
  let loaded = false;

  async function load() {
    try {
      const r = await api.platform.get();
      platform = r.platform;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  if (!loaded) {
    loaded = true;
    load();
  }

  async function runAction(entry: ActionEntry) {
    if (entry.confirm && !window.confirm(entry.confirm)) return;
    error = "";
    message = "";
    runningCommand = entry.command;
    try {
      const r = await api.platform.action(entry.command);
      message = r.message;
    } catch (e) {
      error = String(e);
    } finally {
      runningCommand = "";
    }
  }

</script>

<div class="page-hero">
  <p class="page-kicker">System</p>
  <h1 class="page-title">Platform</h1>
  <p class="page-subtitle">Manage the host system services and power state.</p>
</div>

{#if loading}
  <div class="panel-card"><p>Loading…</p></div>
{:else if platform !== "raspberry_pi"}
  <div class="panel-card offline-msg">This page is not available for your platform.</div>
{:else}
  <div class="panel-card">
    <p class="panel-title">Raspberry Pi System</p>
    {#if error}<div class="alert alert-error" style="margin-bottom:0.75rem">{error}</div>{/if}
    {#if message}<div class="alert alert-success" style="margin-bottom:0.75rem">{message}</div>{/if}
    <div class="action-list">
      {#each ACTIONS as entry}
        <button
          class="btn btn-primary platform-btn"
          on:click={() => runAction(entry)}
          disabled={runningCommand !== ""}
        >
          {runningCommand === entry.command ? "…" : entry.label}
        </button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }
  .action-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    align-items: flex-start;
  }
  .platform-btn { width: 250px; justify-content: center; }
</style>
