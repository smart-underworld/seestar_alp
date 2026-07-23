<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api, type DeviceStatus } from "../lib/api";
  import BubbleLevel from "../lib/components/BubbleLevel.svelte";

  let status: DeviceStatus | null = null;
  let error = "";
  let interval: ReturnType<typeof setInterval>;

  async function load() {
    try {
      status = await api.devices.status($activeDevNum);
      error = "";
    } catch (e) {
      error = String(e);
    }
  }

  onMount(() => {
    load();
    interval = setInterval(load, 15000);
  });

  onDestroy(() => clearInterval(interval));

  $: $activeDevNum, load();

  function wifiPct(raw: string): number {
    const dbm = parseInt(raw.replace(/dBm/i, "").trim(), 10);
    if (isNaN(dbm)) return 0;
    return Math.max(0, Math.min(100, Math.round(((dbm + 90) * 100) / 40)));
  }

  function storagePct(raw: string): number {
    const m = raw.match(/^([\d.]+)\s*GB\s*\/\s*([\d.]+)\s*GB/i);
    if (!m) return 0;
    return Math.max(0, Math.min(100, Math.round((parseFloat(m[1]) / parseFloat(m[2])) * 100)));
  }

  type Row = { key: string; value: string; bar?: number };

  function barClass(key: string, pct: number): string {
    if (key === "Battery") return pct < 20 ? "danger" : pct < 50 ? "warning" : "success";
    // pct here is percent FREE (storagePct computes free/total), so low
    // free space is the danger case — not high, like the raw threshold
    // numbers might suggest.
    if (key === "Free Storage") return pct < 10 ? "danger" : pct < 30 ? "warning" : "success";
    if (key === "Wi-Fi Signal") return pct < 30 ? "danger" : pct < 60 ? "warning" : "success";
    return "primary";
  }

  $: rows = (() => {
    if (!status || !status.is_connected) return [] as Row[];
    const s = status;
    const list: Row[] = [];

    const push = (key: string, val: string | number | null | undefined, bar?: number) => {
      if (val === null || val === undefined || val === "") return;
      list.push({ key, value: String(val), bar });
    };

    push("View State", s.view_state);
    if (s.view_state && s.view_state !== "Idle") {
      push("Mode", s.mode);
      push("Stage", s.stage);
      push("Target", s.target);
      if (s.stacked !== "") push("Successful Frames", s.stacked);
      if (s.failed !== "") push("Failed Frames", s.failed);
    }
    push("Mount Mode", s.mount_mode);
    push("RA", s.ra !== null ? Number(s.ra).toFixed(4) + " h" : null);
    push("Dec", s.dec !== null ? Number(s.dec).toFixed(4) + "°" : null);
    if (s.battery_capacity !== null)
      push("Battery", s.battery_capacity + " %", Number(s.battery_capacity));
    push("Temp", s.temp !== null ? s.temp + " °C" : null);
    push("Battery Temp", s.battery_temp !== null ? s.battery_temp + " °C" : null);
    push("Charge Status", s.charge_status);
    if (s.free_storage && s.free_storage !== "Unknown")
      push("Free Storage", s.free_storage, storagePct(s.free_storage));
    if (s.wifi_signal) push("Wi-Fi Signal", s.wifi_signal, wifiPct(s.wifi_signal));
    push("Focal Position", s.focal_position);
    push("Balance Angle", s.balance_angle !== null ? s.balance_angle + "°" : null);
    push("Compass Direction", s.compass_direction !== null ? s.compass_direction + "°" : null);
    push("Firmware", s.firmware_ver);
    push("Schedule State", s.schedule_state);
    return list;
  })();
</script>

<div class="page-hero">
  <div>
    <p class="page-kicker">Telemetry</p>
    <h1 class="page-title">Stats</h1>
    <p class="page-subtitle">Current telescope measurements and health metrics.</p>
  </div>
  <span class="refresh-note">Auto-refresh every 15 s</span>
</div>

{#if $activeDevNum === 0}
  <div class="panel-card offline-msg">
    Stats are per-device. Select a specific telescope from the dropdown above.
  </div>
{:else if !$isConnected}
  <div class="panel-card offline-msg">Device {$activeDevNum} is offline.</div>
{:else if error}
  <div class="alert alert-error">{error}</div>
{:else if rows.length === 0}
  <div class="panel-card"><p>Loading…</p></div>
{:else}
  <div class="panel-card">
    <p class="panel-title">Device Status</p>
    <div class="stat-list">
      {#each rows as row}
        <div class="stat-row">
          <div class="stat-key">{row.key}</div>
          <div class="stat-value">
            {row.value}
            {#if row.bar !== undefined}
              <div class="metric-bar">
                <div
                  class="metric-bar-fill {barClass(row.key, row.bar)}"
                  style="width: {row.bar}%"
                ></div>
              </div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </div>

  <div class="panel-card bubble-level-card">
    <p class="panel-title">Orientation</p>
    <BubbleLevel />
  </div>
{/if}

<style>
  .page-hero {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 1.5rem;
  }
  .refresh-note {
    font-size: 0.75rem;
    color: var(--ui-muted);
    padding-top: 0.4rem;
  }
  .offline-msg { color: var(--ui-muted); }
  .stat-list { display: flex; flex-direction: column; }
  .bubble-level-card { margin-top: 1rem; }
</style>
