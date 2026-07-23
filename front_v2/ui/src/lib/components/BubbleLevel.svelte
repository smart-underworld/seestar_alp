<script lang="ts">
  import { onDestroy } from "svelte";
  import { activeDevNum } from "../stores/deviceStore";
  import { api } from "../api";

  let open = false;
  let x = 0;
  let y = 0;
  let interval: ReturnType<typeof setInterval> | null = null;

  // .panel-card uses backdrop-filter, which creates a containing block for
  // position:fixed descendants — move the modal to <body> so it centers on
  // the viewport instead of the (small) card it's declared inside.
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return {
      destroy() {
        node.parentNode?.removeChild(node);
      },
    };
  }

  const LEVEL_SIZE = 220;
  const BALL_SIZE = 20;

  async function poll() {
    try {
      const data = await api.devices.balanceSensor($activeDevNum);
      x = data.x ?? 0;
      y = data.y ?? 0;
    } catch {
      // keep last known reading on transient errors
    }
  }

  function show() {
    open = true;
    if (interval === null) {
      poll();
      interval = setInterval(poll, 250);
    }
  }

  function hide() {
    open = false;
    if (interval !== null) {
      clearInterval(interval);
      interval = null;
    }
  }

  onDestroy(() => {
    if (interval !== null) clearInterval(interval);
  });

  $: maxOffset = LEVEL_SIZE - BALL_SIZE;
  $: scaledX = x * 100 + 100;
  $: scaledY = y * 100 + 100;
  $: ballTop = (maxOffset * scaledX) / 180 - 10;
  $: ballLeft = (maxOffset * scaledY) / 180 - 10;
</script>

<button type="button" class="btn btn-secondary" on:click={show}>
  Show Bubble Level
</button>

{#if open}
  <div class="modal-backdrop" use:portal on:click={(e) => { if (e.target === e.currentTarget) hide(); }} role="presentation">
    <div class="modal-card" role="dialog" aria-modal="true" aria-label="Bubble Level">
      <div class="modal-header">
        <span class="modal-title">Bubble Level</span>
        <button class="btn-close" on:click={hide} aria-label="Close">✕</button>
      </div>
      <div class="modal-body">
        <div class="bubble-level" style="width:{LEVEL_SIZE}px; height:{LEVEL_SIZE}px;">
          <div
            class="bubble-ball"
            style="width:{BALL_SIZE}px; height:{BALL_SIZE}px; top:{ballTop}px; left:{ballLeft}px;"
          ></div>
        </div>
        <div class="bubble-readout">
          X: <span class="value">{(x * 100).toFixed(2)}</span>
          &nbsp;|&nbsp;
          Y: <span class="value">{(y * 100).toFixed(2)}</span>
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.65);
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
    max-width: 360px;
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
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
  }

  .bubble-level {
    position: relative;
    border: 2px solid var(--ui-border);
    border-radius: 14px;
    background: rgba(3, 8, 18, 0.68);
  }
  .bubble-level::after,
  .bubble-level::before {
    content: "";
    position: absolute;
    background: rgba(255, 255, 255, 0.32);
    border-radius: 2px;
    pointer-events: none;
  }
  .bubble-level::after {
    left: calc(50% - 1px);
    width: 2px;
    height: 100%;
  }
  .bubble-level::before {
    top: calc(50% - 1px);
    width: 100%;
    height: 2px;
  }
  .bubble-ball {
    position: absolute;
    border-radius: 50%;
    background: radial-gradient(circle at 30% 30%, #78f8bd, #16a085 68%);
    border: 1px solid rgba(255, 255, 255, 0.35);
    box-shadow: 0 0 16px rgba(22, 160, 133, 0.55);
    z-index: 10;
  }

  .bubble-readout {
    font-size: 0.9rem;
    color: var(--ui-body);
    opacity: 0.9;
  }
  .bubble-readout .value {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }
</style>
