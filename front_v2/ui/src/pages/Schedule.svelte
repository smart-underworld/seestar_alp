<script lang="ts">
  import { onMount } from "svelte";
  import { activeDevNum, isConnected, activeDeviceStatus } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  interface ScheduleItem {
    action?: string;
    state?: string;
    [key: string]: unknown;
  }
  interface ScheduleData {
    state?: string;
    list?: ScheduleItem[];
    [key: string]: unknown;
  }

  let schedule: ScheduleData | null = null;
  let error = "";
  let loading = false;

  async function load() {
    loading = true;
    error = "";
    try {
      schedule = (await api.devices.schedule.get($activeDevNum)) as ScheduleData;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function clearSchedule() {
    try {
      await api.devices.schedule.clear($activeDevNum);
      schedule = null;
    } catch (e) {
      error = String(e);
    }
  }

  onMount(load);
  $: if ($activeDevNum) load();

  $: items = schedule?.list ?? [];
  $: schedState = schedule?.state ?? "";
</script>

<div class="page-hero">
  <p class="page-kicker">Automation</p>
  <h1 class="page-title">Schedule</h1>
  <p class="page-subtitle">View and manage the observation schedule queue.</p>
</div>

{#if !$isConnected}
  <div class="panel-card offline-msg">
    Device {$activeDevNum} is offline.
  </div>
{:else}
  {#if error}<div class="alert alert-error">{error}</div>{/if}

  <div class="schedule-header">
    <div class="sched-state-wrap">
      {#if schedState}
        <span class="sched-state" class:running={schedState === "running" || schedState === "working"}>
          {schedState}
        </span>
      {/if}
    </div>
    <div class="sched-actions">
      <button class="btn btn-secondary" on:click={load} disabled={loading}>
        {loading ? "Loading…" : "↻ Refresh"}
      </button>
      {#if items.length > 0}
        <button class="btn btn-danger" on:click={clearSchedule}>⊘ Clear Schedule</button>
      {/if}
    </div>
  </div>

  {#if loading}
    <div class="loading">Loading schedule…</div>
  {:else if items.length > 0}
    <div class="panel-card sched-table-card">
      <p class="panel-title">{items.length} item{items.length !== 1 ? "s" : ""} in queue</p>
      <div class="sched-list">
        {#each items as item, i}
          <div class="sched-item" class:done={item.state === "done"} class:working={item.state === "working"}>
            <div class="sched-idx">{i + 1}</div>
            <div class="sched-content">
              <div class="sched-action">{item.action ?? "Unknown action"}</div>
              {#if item.state}
                <span class="sched-item-state" class:done={item.state === "done"} class:working={item.state === "working"}>
                  {item.state}
                </span>
              {/if}
              {#each Object.entries(item).filter(([k]) => k !== "action" && k !== "state") as [k, v]}
                {#if v !== null && v !== undefined && v !== ""}
                  <span class="sched-param">{k}: <strong>{JSON.stringify(v)}</strong></span>
                {/if}
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>
  {:else if schedule !== null}
    <div class="panel-card empty-card">
      <div class="empty-icon">📋</div>
      <div class="empty-text">Schedule is empty</div>
      <div class="empty-sub">No items are queued. Use the classic UI to build a schedule.</div>
    </div>
  {/if}
{/if}

<style>
  .offline-msg { color: var(--ui-muted); font-size: 0.9rem; }
  .loading     { color: var(--ui-muted); font-size: 0.9rem; padding: 1.5rem 0; }

  .schedule-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  .sched-state-wrap { display: flex; align-items: center; gap: 0.5rem; }
  .sched-state {
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.2rem 0.7rem;
    border-radius: 99px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    color: var(--ui-muted);
  }
  .sched-state.running {
    background: rgba(104, 211, 145, 0.1);
    border-color: rgba(104, 211, 145, 0.25);
    color: var(--ui-success);
  }
  .sched-actions { display: flex; gap: 0.5rem; }

  .sched-table-card {}
  .sched-list {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .sched-item {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 0.7rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    opacity: 1;
    transition: opacity 0.2s;
  }
  .sched-item:last-child { border-bottom: none; }
  .sched-item.done { opacity: 0.45; }

  .sched-idx {
    width: 24px;
    height: 24px;
    background: rgba(44,177,255,0.1);
    border: 1px solid rgba(44,177,255,0.2);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: 700;
    color: var(--ui-primary);
    flex-shrink: 0;
  }
  .sched-item.done .sched-idx {
    background: rgba(255,255,255,0.05);
    border-color: rgba(255,255,255,0.1);
    color: var(--ui-muted);
  }

  .sched-content { flex: 1; display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 0.75rem; }
  .sched-action { font-size: 0.85rem; font-weight: 500; color: var(--ui-body); width: 100%; }

  .sched-item-state {
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.1rem 0.45rem;
    border-radius: 99px;
    background: rgba(255,255,255,0.06);
    color: var(--ui-muted);
  }
  .sched-item-state.done    { background: rgba(255,255,255,0.04); color: var(--ui-muted); }
  .sched-item-state.working { background: rgba(104,211,145,0.1); color: var(--ui-success); }

  .sched-param {
    font-size: 0.75rem;
    color: var(--ui-muted);
  }
  .sched-param strong { color: var(--ui-body); }

  .empty-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2.5rem;
    text-align: center;
    gap: 0.5rem;
    max-width: 400px;
  }
  .empty-icon { font-size: 2.5rem; }
  .empty-text { font-weight: 600; color: var(--ui-body); }
  .empty-sub  { font-size: 0.82rem; color: var(--ui-muted); line-height: 1.5; }
</style>
