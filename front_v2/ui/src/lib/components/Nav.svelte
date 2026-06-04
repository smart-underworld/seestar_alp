<script lang="ts">
  import { link, location } from "svelte-spa-router";
  import { deviceList, activeDevNum, deviceStatuses } from "../stores/deviceStore";
  import { isNavActive } from "../utils";

  function devState(devNum: number): "loading" | "offline" | "online" {
    const s = $deviceStatuses[devNum];
    if (!s || !s.backend_ready) return "loading";
    return s.is_connected ? "online" : "offline";
  }

  const navLinks = [
    { href: "/",         label: "Home"     },
    { href: "/startup",  label: "Startup"  },
    { href: "/live",     label: "Live"     },
    { href: "/goto",     label: "GoTo"     },
    { href: "/image",    label: "Image"    },
    { href: "/schedule", label: "Schedule" },
    { href: "/planning", label: "Planning" },
    { href: "/settings", label: "Settings" },
    { href: "/config",   label: "Config"   },
    { href: "/command",  label: "Command"  },
    { href: "/support",  label: "Support"  },
  ];
</script>

<nav>
  <a href="/" use:link class="brand">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10"/>
      <circle cx="12" cy="12" r="3"/>
      <line x1="12" y1="2"  x2="12" y2="6"/>
      <line x1="12" y1="18" x2="12" y2="22"/>
      <line x1="2"  y1="12" x2="6"  y2="12"/>
      <line x1="18" y1="12" x2="22" y2="12"/>
    </svg>
    Seestar ALP
  </a>

  <div class="links">
    {#each navLinks as { href, label }}
      <a {href} use:link class:active={isNavActive(href, $location)}>{label}</a>
    {/each}
  </div>

  <div class="device-area">
    {#if $deviceList.length > 1}
      <select bind:value={$activeDevNum} class="device-select">
        {#each $deviceList as d}
          {@const state = devState(d.device_num)}
          <option value={d.device_num}>
            {d.name}{state === "offline" ? " (offline)" : state === "loading" ? " …" : ""}
          </option>
        {/each}
      </select>
    {:else if $deviceList.length === 1}
      {@const state = devState($deviceList[0].device_num)}
      <span class="device-chip">
        <span class="dot" class:online={state === "online"} class:loading={state === "loading"}></span>
        {$deviceList[0].name}
      </span>
    {:else}
      <span class="device-chip muted">No devices</span>
    {/if}
  </div>
</nav>

<style>
  nav {
    display: flex;
    align-items: center;
    padding: 0 1.5rem;
    background: var(--ui-nav-bg, rgba(4, 8, 20, 0.94));
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    position: sticky;
    top: 0;
    z-index: 100;
    height: 52px;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 700;
    font-size: 0.95rem;
    color: var(--ui-primary);
    text-decoration: none;
    letter-spacing: -0.01em;
    padding-right: 1.25rem;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    margin-right: 0.25rem;
    flex-shrink: 0;
    white-space: nowrap;
  }
  .brand:hover { color: var(--ui-primary-hover); }

  .links {
    display: flex;
    flex: 1;
    height: 100%;
    align-items: stretch;
  }

  .links a {
    display: flex;
    align-items: center;
    padding: 0 0.85rem;
    font-size: 0.81rem;
    font-weight: 500;
    color: rgba(231, 237, 247, 0.45);
    text-decoration: none;
    letter-spacing: 0.02em;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s;
    white-space: nowrap;
  }
  .links a:hover { color: var(--ui-body); }
  .links a.active {
    color: var(--ui-primary);
    border-bottom-color: var(--ui-primary);
  }

  .device-area {
    margin-left: auto;
    display: flex;
    align-items: center;
  }

  .device-select {
    background: rgba(44, 177, 255, 0.08);
    border: 1px solid rgba(44, 177, 255, 0.2);
    color: var(--ui-body);
    padding: 0.28rem 0.6rem;
    border-radius: 6px;
    font-size: 0.78rem;
    cursor: pointer;
  }

  .device-chip {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.78rem;
    color: var(--ui-muted);
    padding: 0.22rem 0.7rem;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 99px;
  }
  .device-chip.muted { color: rgba(113, 128, 150, 0.5); }

  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ui-danger);
    flex-shrink: 0;
  }
  .dot.online { background: var(--ui-success); }
  .dot.loading {
    background: var(--ui-muted);
    animation: dot-pulse 1.2s ease-in-out infinite;
  }
  @keyframes dot-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.25; }
  }

  @media (max-width: 768px) {
    nav { padding: 0 0.75rem; }
    .links a { padding: 0 0.45rem; font-size: 0.72rem; }
    .brand { padding-right: 0.75rem; }
    .brand svg { display: none; }
  }
</style>
