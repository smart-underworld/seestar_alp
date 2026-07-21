<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { activeDevNum } from "../stores/deviceStore";
  import { api, type EventState } from "../api";
  import { humanizeEventState } from "../utils";

  export let events: string[] = [];

  let byDevice: Record<string, Record<string, EventState>> | null = null;
  let flat: Record<string, EventState> | null = null;
  let interval: ReturnType<typeof setInterval>;

  const DISPLAY_NAME: Record<string, string> = {
    "3PPA": "PolarAlign",
    WheelMove: "FilterWheel",
  };

  function stateClass(ev: EventState | undefined): string {
    if (!ev?.state || ev.state === "idle") return "card-idle";
    switch (ev.state) {
      case "complete":
        return "card-success";
      case "fail":
      case "cancel":
        return "card-fail";
      default:
        // Any other present state is an active sub-state — 3PPA in
        // particular cycles through firmware-internal values like
        // "delay1"/"delay2"/"calc3" (and PlateSolve through "solving")
        // that aren't literally "in progress". Treat any non-terminal,
        // non-idle state as progress so the tile visibly lights up
        // instead of looking identical to an untouched Idle tile.
        return "card-progress";
    }
  }

  function filterName(position: number | undefined): string | null {
    if (position === 0) return "DARK";
    if (position === 1) return "IRCUT";
    if (position === 2) return "LP";
    return null;
  }

  async function load() {
    try {
      const result = await api.devices.events($activeDevNum);
      const entries = Object.entries(result || {});
      const hasDeviceGrouping = entries.some(
        ([, v]) => v && typeof v === "object" && "DeviceID" in (v as Record<string, unknown>)
      );
      if (hasDeviceGrouping) {
        const grouped: Record<string, Record<string, EventState>> = {};
        for (const [name, ev] of entries) {
          const devId = String((ev as Record<string, unknown>).DeviceID ?? "unknown");
          if (!grouped[devId]) grouped[devId] = {};
          grouped[devId][name] = ev as EventState;
        }
        byDevice = grouped;
        flat = null;
      } else {
        flat = result as Record<string, EventState>;
        byDevice = null;
      }
    } catch {
      // keep last known state on transient errors
    }
  }

  onMount(() => {
    load();
    interval = setInterval(load, 2000);
  });

  onDestroy(() => clearInterval(interval));

  $: $activeDevNum, load();
</script>

<div class="panel-card event-status-panel">
  <p class="panel-title">Current Status of Devices</p>

  {#if byDevice}
    {#each Object.entries(byDevice) as [deviceId, deviceEvents]}
      <p class="device-id-label">Device ID: {deviceId}</p>
      <div class="event-grid">
        {#each events as eventName}
          {@const ev = deviceEvents[eventName]}
          <div class="event-card {stateClass(ev)}">
            <div class="event-card-header">{DISPLAY_NAME[eventName] ?? eventName}</div>
            <div class="event-card-body">
              <p><strong>State:</strong> {humanizeEventState(ev?.state)}</p>
              {#if ev?.error}
                <p><strong>Error:</strong> {ev.error}</p>
              {/if}
              {#if eventName === "3PPA"}
                {#if ev?.percent}
                  <p><strong>% Complete:</strong> {ev.percent}</p>
                {/if}
                {#if ev?.eq_offset_alt != null && ev?.eq_offset_az != null}
                  <p><strong>Alt Error:</strong> {ev.eq_offset_alt.toFixed(3)}</p>
                  <p><strong>Az Error:</strong> {ev.eq_offset_az.toFixed(3)}</p>
                {/if}
              {/if}
              {#if eventName === "AutoFocus" && ev?.position != null}
                <p><strong>Position:</strong> {ev.position}</p>
              {/if}
              {#if eventName === "DarkLibrary" && ev?.percent != null}
                <p><strong>% Complete:</strong> {ev.percent.toFixed(2)}</p>
              {/if}
              {#if eventName === "Stack" && ev}
                {@const stacked = ev.stacked_frame ?? 0}
                {@const dropped = ev.dropped_frame ?? 0}
                {@const total = stacked + dropped}
                {@const failRate = total > 0 ? (dropped / total) * 100 : 0}
                <p><strong>Stacked:</strong> {stacked}</p>
                <p><strong>Dropped:</strong> {dropped}</p>
                <p><strong>Fail Rate:</strong> {failRate.toFixed(2)}%</p>
              {/if}
              {#if eventName === "WheelMove" && filterName(ev?.position)}
                <p><strong>Filter:</strong> {filterName(ev?.position)}</p>
              {/if}
              {#if eventName === "Scheduler" && ev?.cur_scheduler_item?.type}
                <p><strong>Action:</strong> {ev.cur_scheduler_item.type}</p>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/each}
  {:else if flat}
    <div class="event-grid">
      {#each events as eventName}
        {@const ev = flat[eventName]}
        <div class="event-card {stateClass(ev)}">
          <div class="event-card-header">{DISPLAY_NAME[eventName] ?? eventName}</div>
          <div class="event-card-body">
            <p><strong>State:</strong> {humanizeEventState(ev?.state)}</p>
            {#if ev?.error}
              <p><strong>Error:</strong> {ev.error}</p>
            {/if}
            {#if eventName === "3PPA"}
              {#if ev?.percent}
                <p><strong>% Complete:</strong> {ev.percent}</p>
              {/if}
              {#if ev?.eq_offset_alt != null && ev?.eq_offset_az != null}
                <p><strong>Alt Error:</strong> {ev.eq_offset_alt.toFixed(3)}</p>
                <p><strong>Az Error:</strong> {ev.eq_offset_az.toFixed(3)}</p>
              {/if}
            {/if}
            {#if eventName === "AutoFocus" && ev?.position != null}
              <p><strong>Position:</strong> {ev.position}</p>
            {/if}
            {#if eventName === "DarkLibrary" && ev?.percent != null}
              <p><strong>% Complete:</strong> {ev.percent.toFixed(2)}</p>
            {/if}
            {#if eventName === "Stack" && ev}
              {@const stacked = ev.stacked_frame ?? 0}
              {@const dropped = ev.dropped_frame ?? 0}
              {@const total = stacked + dropped}
              {@const failRate = total > 0 ? (dropped / total) * 100 : 0}
              <p><strong>Stacked:</strong> {stacked}</p>
              <p><strong>Dropped:</strong> {dropped}</p>
              <p><strong>Fail Rate:</strong> {failRate.toFixed(2)}%</p>
            {/if}
            {#if eventName === "WheelMove" && filterName(ev?.position)}
              <p><strong>Filter:</strong> {filterName(ev?.position)}</p>
            {/if}
            {#if eventName === "Scheduler" && ev?.cur_scheduler_item?.type}
              <p><strong>Action:</strong> {ev.cur_scheduler_item.type}</p>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <p class="event-status-empty">No results available.</p>
  {/if}
</div>

<style>
  .event-status-panel {
    margin-bottom: 1rem;
  }

  .device-id-label {
    font-weight: 600;
    margin: 0.75rem 0 0.5rem;
    color: var(--ui-body);
  }
  .device-id-label:first-of-type { margin-top: 0; }

  .event-status-empty { color: var(--ui-muted); font-size: 0.9rem; }

  .event-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 0.75rem;
  }

  .event-card {
    border-radius: var(--ui-radius-sm);
    overflow: hidden;
    border: 1px solid var(--ui-border);
    background: var(--ui-surface-raised);
  }

  .event-card-header {
    padding: 0.4rem 0.6rem;
    font-weight: 600;
    font-size: 0.85rem;
    border-bottom: 1px solid var(--ui-border);
  }

  .event-card-body {
    padding: 0.5rem 0.6rem;
    font-size: 0.78rem;
    line-height: 1.4;
  }
  .event-card-body p { margin: 0; }
  .event-card-body strong { font-weight: 600; }

  .card-idle { color: var(--ui-body); }
  .card-idle .event-card-header { background: rgba(255, 255, 255, 0.04); }

  .card-success { color: var(--ui-body); }
  .card-success .event-card-header { background: rgba(104, 211, 145, 0.28); color: var(--ui-success); }

  .card-fail { color: var(--ui-body); }
  .card-fail .event-card-header { background: rgba(233, 69, 96, 0.28); color: var(--ui-danger); }

  .card-progress { color: var(--ui-body); }
  .card-progress .event-card-header { background: rgba(246, 201, 14, 0.28); color: var(--ui-warning); }
</style>
