<script lang="ts">
  import { link, location } from "svelte-spa-router";
  import { deviceList, activeDevNum, deviceStatuses } from "../stores/deviceStore";
  import { isNavActive } from "../utils";

  let menuOpen = false;

  // Close menu on route change
  $: $location, (menuOpen = false);

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

  <!-- Desktop links (hidden on small screens) -->
  <div class="links">
    {#each navLinks as { href, label }}
      <a {href} use:link class:active={isNavActive(href, $location)}>{label}</a>
    {/each}
  </div>

  <!-- Device area — always visible in the bar -->
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

  <!-- Hamburger button (visible on small screens) -->
  <button
    class="hamburger"
    on:click={() => (menuOpen = !menuOpen)}
    aria-label="Toggle menu"
    aria-expanded={menuOpen}
    aria-controls="mobile-menu"
  >
    {#if menuOpen}
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
        <line x1="18" y1="6"  x2="6"  y2="18"/>
        <line x1="6"  y1="6"  x2="18" y2="18"/>
      </svg>
    {:else}
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
        <line x1="3" y1="6"  x2="21" y2="6"/>
        <line x1="3" y1="12" x2="21" y2="12"/>
        <line x1="3" y1="18" x2="21" y2="18"/>
      </svg>
    {/if}
  </button>
</nav>

<!-- Mobile menu backdrop -->
{#if menuOpen}
  <div
    class="mobile-backdrop"
    on:click={() => (menuOpen = false)}
    role="presentation"
  ></div>
{/if}

<!-- Mobile dropdown menu -->
<div
  id="mobile-menu"
  class="mobile-menu"
  class:open={menuOpen}
  aria-hidden={!menuOpen}
>
  {#each navLinks as { href, label }}
    <a
      {href}
      use:link
      class:active={isNavActive(href, $location)}
      on:click={() => (menuOpen = false)}
    >
      {label}
    </a>
  {/each}
</div>

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
    gap: 0.25rem;
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

  /* ── Desktop links ──────────────────────────────────────────────────── */
  .links {
    display: flex;
    flex: 1;
    height: 100%;
    align-items: stretch;
    overflow: hidden;
  }

  .links a {
    display: flex;
    align-items: center;
    padding: 0 0.75rem;
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

  /* ── Device area ────────────────────────────────────────────────────── */
  .device-area {
    margin-left: auto;
    display: flex;
    align-items: center;
    flex-shrink: 0;
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

  /* ── Hamburger button ───────────────────────────────────────────────── */
  .hamburger {
    display: none;
    align-items: center;
    justify-content: center;
    margin-left: 0.5rem;
    padding: 0.35rem;
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    color: var(--ui-body);
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.15s, border-color 0.15s;
  }
  .hamburger:hover {
    background: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.22);
  }

  /* ── Mobile menu ────────────────────────────────────────────────────── */
  .mobile-backdrop {
    position: fixed;
    inset: 52px 0 0 0;
    z-index: 98;
    background: rgba(0, 0, 0, 0.35);
  }

  .mobile-menu {
    position: fixed;
    top: 52px;
    left: 0;
    right: 0;
    z-index: 99;
    background: rgba(4, 8, 20, 0.97);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    max-height: 0;
    transition: max-height 0.22s ease, opacity 0.18s ease;
    opacity: 0;
    pointer-events: none;
  }
  .mobile-menu.open {
    max-height: calc(100dvh - 52px);
    opacity: 1;
    pointer-events: auto;
    overflow-y: auto;
  }

  .mobile-menu a {
    display: block;
    padding: 0.85rem 1.5rem;
    font-size: 0.9rem;
    font-weight: 500;
    color: rgba(231, 237, 247, 0.6);
    text-decoration: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    transition: color 0.12s, background 0.12s;
  }
  .mobile-menu a:hover {
    color: var(--ui-body);
    background: rgba(255, 255, 255, 0.04);
  }
  .mobile-menu a.active {
    color: var(--ui-primary);
    background: rgba(44, 177, 255, 0.07);
    border-left: 3px solid var(--ui-primary);
    padding-left: calc(1.5rem - 3px);
  }

  /* ── Responsive breakpoints ─────────────────────────────────────────── */
  @media (max-width: 1100px) {
    .links { display: none; }
    .hamburger { display: flex; }
  }

  @media (max-width: 480px) {
    nav { padding: 0 0.75rem; }
    .brand svg { display: none; }
    .brand { padding-right: 0.75rem; font-size: 0.88rem; }
  }
</style>
