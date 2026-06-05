<script lang="ts">
  import { link, location } from "svelte-spa-router";
  import { onMount } from "svelte";
  import { deviceList, activeDevNum, deviceStatuses } from "../stores/deviceStore";
  import { isNavActive } from "../utils";

  let menuOpen = false;
  let moreOpen = false;

  $: $location, (menuOpen = false), (moreOpen = false);

  function devState(devNum: number): "loading" | "offline" | "online" {
    const s = $deviceStatuses[devNum];
    if (!s || !s.backend_ready) return "loading";
    return s.is_connected ? "online" : "offline";
  }

  // Priority 1 = always visible, 4 = collapses into "More" first.
  // Order is preserved — priority only controls which items survive at narrow widths.
  const navLinks = [
    { href: "/",          label: "Home",       priority: 1 },
    { href: "/startup",   label: "Startup",    priority: 1 },
    { href: "/command",   label: "Commands",   priority: 2 },
    { href: "/guestmode", label: "Guest Mode", priority: 4 },
    { href: "/goto",      label: "Goto",       priority: 3 },
    { href: "/image",     label: "Image",      priority: 3 },
    { href: "/live",      label: "Live",       priority: 2 },
    { href: "/mosaic",    label: "Mosaic",     priority: 3 },
    { href: "/planning",  label: "Planning",   priority: 2 },
    { href: "/schedule",  label: "Schedule",   priority: 2 },
    { href: "/settings",  label: "Settings",   priority: 3 },
    { href: "/config",    label: "SSC Config", priority: 3 },
    { href: "/stats",     label: "Stats",      priority: 4 },
    { href: "/support",   label: "Support",    priority: 1 },
  ];

  // Hidden ghost spans measure each link's rendered width once on mount.
  let linkWidths: number[] = navLinks.map(() => 80);
  let ghostEls: (HTMLElement | null)[] = new Array(navLinks.length).fill(null);

  onMount(() => {
    const measured = ghostEls.map(el => (el ? Math.ceil(el.getBoundingClientRect().width) : 0));
    if (measured.every(w => w > 0)) linkWidths = measured;
  });

  const MORE_BTN_W = 74; // approximate "More ▾" button width in px

  // .links has flex:1 — bind:clientWidth gives exact available px for links,
  // automatically accounting for brand width, device area width, and nav padding.
  let linksWidth = 0;

  $: visiblePriority = (() => {
    if (linksWidth === 0) return 4; // not yet measured — show all
    for (let maxP = 4; maxP >= 1; maxP--) {
      const shown = navLinks.filter(l => l.priority <= maxP);
      const hasOverflow = shown.length < navLinks.length;
      const total =
        shown.reduce((sum, l) => sum + (linkWidths[navLinks.indexOf(l)] || 80), 0) +
        (hasOverflow ? MORE_BTN_W : 0);
      if (total <= linksWidth) return maxP;
    }
    return 0; // nothing fits → full hamburger
  })();

  $: useHamburger = linksWidth > 0 && visiblePriority === 0;
  $: primaryLinks = useHamburger ? [] : navLinks.filter(l => l.priority <= visiblePriority);
  $: overflowLinks = useHamburger ? [] : navLinks.filter(l => l.priority > visiblePriority);
  $: hasMore = !useHamburger && overflowLinks.length > 0;
</script>

<nav>
  <!-- Ghost spans: invisible, used only to measure each link's natural width on mount -->
  <div class="link-ghost" aria-hidden="true">
    {#each navLinks as { label }, i}
      <span bind:this={ghostEls[i]}>{label}</span>
    {/each}
  </div>

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

  <!-- Links container: flex:1 fills space between brand and device area -->
  <div class="links" bind:clientWidth={linksWidth}>
    {#if !useHamburger}
      {#each primaryLinks as { href, label }}
        <a {href} use:link class:active={isNavActive(href, $location)}>{label}</a>
      {/each}

      {#if hasMore}
        <div class="more-wrap">
          <button
            class="more-btn"
            on:click={() => (moreOpen = !moreOpen)}
            aria-expanded={moreOpen}
            aria-haspopup="true"
          >
            More <span class="caret" class:flipped={moreOpen}>▾</span>
          </button>
          <div class="more-menu" class:open={moreOpen} role="menu">
            {#each overflowLinks as { href, label }}
              <a
                {href}
                use:link
                role="menuitem"
                class:active={isNavActive(href, $location)}
                on:click={() => (moreOpen = false)}
              >{label}</a>
            {/each}
          </div>
        </div>
      {/if}
    {/if}
  </div>

  <!-- Device area — always visible -->
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

  <!-- Hamburger: only when the bar is too narrow even for P1 + More -->
  {#if useHamburger}
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
  {/if}
</nav>

<!-- "More" click-outside backdrop (transparent, below nav) -->
{#if moreOpen}
  <div class="more-backdrop" on:click={() => (moreOpen = false)} role="presentation" />
{/if}

<!-- Full hamburger menu (very small screens only) -->
{#if menuOpen}
  <div class="mobile-backdrop" on:click={() => (menuOpen = false)} role="presentation" />
{/if}
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
    >{label}</a>
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

  /* Invisible measurement container — same font/padding as real links */
  .link-ghost {
    position: absolute;
    top: 0;
    left: 0;
    visibility: hidden;
    pointer-events: none;
    display: flex;
    font-size: 0.81rem;
    font-weight: 500;
    letter-spacing: 0.02em;
  }
  .link-ghost span {
    padding: 0 0.75rem;
    white-space: nowrap;
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

  /* Links fill available space; overflow visible so the More dropdown escapes */
  .links {
    display: flex;
    flex: 1;
    height: 100%;
    align-items: stretch;
    min-width: 0;
    overflow: visible;
  }

  .links > a {
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
  .links > a:hover { color: var(--ui-body); }
  .links > a.active {
    color: var(--ui-primary);
    border-bottom-color: var(--ui-primary);
  }

  /* "More" overflow control */
  .more-wrap {
    display: flex;
    align-items: center;
    position: relative; /* anchor for .more-menu */
  }

  .more-btn {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.3rem 0.65rem;
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    color: rgba(231, 237, 247, 0.55);
    font-size: 0.81rem;
    font-weight: 500;
    letter-spacing: 0.02em;
    cursor: pointer;
    white-space: nowrap;
    transition: color 0.15s, border-color 0.15s, background 0.15s;
  }
  .more-btn:hover {
    color: var(--ui-body);
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.22);
  }

  .caret {
    font-size: 0.7rem;
    display: inline-block;
    transition: transform 0.15s;
  }
  .caret.flipped { transform: rotate(180deg); }

  .more-menu {
    display: none;
    position: absolute;
    top: 52px; /* pin to nav bottom edge */
    left: 0;
    min-width: 140px;
    background: rgba(4, 8, 20, 0.97);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
    z-index: 102;
    overflow: hidden;
  }
  .more-menu.open { display: block; }

  .more-menu a {
    display: block;
    padding: 0.6rem 1rem;
    font-size: 0.84rem;
    font-weight: 500;
    color: rgba(231, 237, 247, 0.55);
    text-decoration: none;
    transition: color 0.12s, background 0.12s;
    white-space: nowrap;
  }
  .more-menu a + a { border-top: 1px solid rgba(255, 255, 255, 0.05); }
  .more-menu a:hover {
    color: var(--ui-body);
    background: rgba(255, 255, 255, 0.05);
  }
  .more-menu a.active {
    color: var(--ui-primary);
    background: rgba(44, 177, 255, 0.08);
    border-left: 2px solid var(--ui-primary);
    padding-left: calc(1rem - 2px);
  }

  /* Click-outside layer for the More dropdown */
  .more-backdrop {
    position: fixed;
    inset: 0;
    z-index: 99;
  }

  /* Device area */
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

  /* Hamburger: only rendered when priority+ can't fit P1 + More */
  .hamburger {
    display: flex;
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

  /* Full-screen dropdown: only used at very small widths */
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

  @media (max-width: 480px) {
    nav { padding: 0 0.75rem; }
    .brand svg { display: none; }
    .brand { padding-right: 0.75rem; font-size: 0.88rem; }
  }
</style>
