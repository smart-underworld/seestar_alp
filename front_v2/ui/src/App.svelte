<script lang="ts">
  import { onMount } from "svelte";
  import Router from "svelte-spa-router";
  import { initDevices } from "./lib/stores/deviceStore";
  import Nav from "./lib/components/Nav.svelte";
  import Home from "./pages/Home.svelte";
  import Startup from "./pages/Startup.svelte";
  import Live from "./pages/Live.svelte";
  import Settings from "./pages/Settings.svelte";
  import Schedule from "./pages/Schedule.svelte";
  import Goto from "./pages/Goto.svelte";
  import Image from "./pages/Image.svelte";
  import Command from "./pages/Command.svelte";
  import Config from "./pages/Config.svelte";
  import Support from "./pages/Support.svelte";
  import Planning from "./pages/Planning.svelte";

  const routes = {
    "/": Home,
    "/startup": Startup,
    "/live": Live,
    "/goto": Goto,
    "/image": Image,
    "/schedule": Schedule,
    "/planning": Planning,
    "/settings": Settings,
    "/config": Config,
    "/command": Command,
    "/support": Support,
  };

  onMount(() => {
    initDevices();
  });
</script>

<Nav />
<main>
  <Router {routes} />
</main>

<style>
  :global(:root) {
    --ui-primary: #2cb1ff;
    --ui-primary-hover: #5ec8ff;
    --ui-accent: #e94560;
    --ui-body: #e7edf7;
    --ui-muted: #718096;
    --ui-success: #68d391;
    --ui-warning: #f6c90e;
    --ui-danger: #e94560;
    --ui-radius: 0.85rem;
    --ui-radius-sm: 0.5rem;
    --ui-shadow: 0 20px 50px rgba(0, 0, 0, 0.35);
    --ui-border: rgba(255, 255, 255, 0.1);
    --ui-surface: rgba(9, 16, 34, 0.72);
    --ui-surface-raised: rgba(12, 22, 46, 0.88);
    --ui-nav-bg: rgba(4, 8, 20, 0.92);
  }

  :global(*, *::before, *::after) {
    box-sizing: border-box;
  }

  :global(body) {
    margin: 0;
    font-family: "Avenir Next", "Segoe UI Variable", "Inter", system-ui, -apple-system, sans-serif;
    background:
      radial-gradient(140% 80% at 12% -5%, #0b2a50 0%, transparent 55%),
      radial-gradient(120% 80% at 92% 6%, #2a150f 0%, transparent 50%),
      linear-gradient(160deg, #050910 0%, #0c1928 55%, #0f1f35 100%);
    background-attachment: fixed;
    color: var(--ui-body);
    min-height: 100vh;
  }

  :global(h1, h2, h3, h4) {
    margin: 0 0 0.5rem;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  :global(a) {
    color: var(--ui-primary);
    text-decoration: none;
  }

  :global(.panel-card) {
    background: var(--ui-surface);
    border: 1px solid var(--ui-border);
    border-radius: var(--ui-radius);
    padding: 1.25rem 1.5rem;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: var(--ui-shadow);
  }

  :global(.panel-title) {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ui-muted);
    margin: 0 0 0.75rem;
  }

  :global(.page-kicker) {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--ui-primary);
    margin: 0 0 0.2rem;
  }

  :global(.page-title) {
    font-size: 1.7rem;
    font-weight: 700;
    margin: 0 0 0.2rem;
    color: var(--ui-body);
  }

  :global(.page-subtitle) {
    font-size: 0.85rem;
    color: var(--ui-muted);
    margin: 0 0 1.25rem;
  }

  :global(.page-hero) {
    margin-bottom: 1.5rem;
  }

  :global(.btn) {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.5rem 1.25rem;
    border: none;
    border-radius: var(--ui-radius-sm);
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
    white-space: nowrap;
  }
  :global(.btn:disabled) {
    opacity: 0.45;
    cursor: not-allowed;
  }
  :global(.btn-primary) {
    background: var(--ui-primary);
    color: #05090e;
  }
  :global(.btn-primary:hover:not(:disabled)) {
    background: var(--ui-primary-hover);
  }
  :global(.btn-secondary) {
    background: rgba(44, 177, 255, 0.12);
    color: var(--ui-primary);
    border: 1px solid rgba(44, 177, 255, 0.25);
  }
  :global(.btn-secondary:hover:not(:disabled)) {
    background: rgba(44, 177, 255, 0.22);
  }
  :global(.btn-danger) {
    background: rgba(233, 69, 96, 0.15);
    color: var(--ui-danger);
    border: 1px solid rgba(233, 69, 96, 0.3);
  }
  :global(.btn-danger:hover:not(:disabled)) {
    background: rgba(233, 69, 96, 0.28);
  }

  :global(.form-field) {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  :global(.form-label) {
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--ui-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  :global(.form-input) {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--ui-border);
    color: var(--ui-body);
    padding: 0.5rem 0.75rem;
    border-radius: var(--ui-radius-sm);
    font-size: 0.9rem;
    font-family: inherit;
    width: 100%;
    transition: border-color 0.15s;
  }
  :global(.form-input:focus) {
    outline: none;
    border-color: var(--ui-primary);
  }
  :global(textarea.form-input) {
    resize: vertical;
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 0.8rem;
  }

  :global(.stat-row) {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.55rem 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }
  :global(.stat-row:last-child) {
    border-bottom: none;
  }
  :global(.stat-key) {
    font-size: 0.82rem;
    color: var(--ui-muted);
    min-width: 130px;
    flex-shrink: 0;
  }
  :global(.stat-value) {
    font-size: 0.85rem;
    color: var(--ui-body);
    text-align: right;
    flex: 1;
    min-width: 0;
    overflow-wrap: break-word;
  }
  :global(.stat-value.success) { color: var(--ui-success); }
  :global(.stat-value.warning) { color: var(--ui-warning); }
  :global(.stat-value.danger)  { color: var(--ui-danger); }

  :global(.metric-bar) {
    width: 100%;
    height: 3px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
    margin-top: 4px;
    overflow: hidden;
  }
  :global(.metric-bar-fill) {
    height: 100%;
    border-radius: 2px;
    transition: width 0.5s ease;
  }
  :global(.metric-bar-fill.success) { background: var(--ui-success); }
  :global(.metric-bar-fill.warning) { background: var(--ui-warning); }
  :global(.metric-bar-fill.danger)  { background: var(--ui-danger); }
  :global(.metric-bar-fill.primary) { background: var(--ui-primary); }

  :global(.badge) {
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 99px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  :global(.badge-connected) {
    background: rgba(104, 211, 145, 0.15);
    color: var(--ui-success);
    border: 1px solid rgba(104, 211, 145, 0.3);
  }
  :global(.badge-offline) {
    background: rgba(233, 69, 96, 0.12);
    color: var(--ui-danger);
    border: 1px solid rgba(233, 69, 96, 0.25);
  }

  :global(.alert) {
    padding: 0.6rem 1rem;
    border-radius: var(--ui-radius-sm);
    font-size: 0.85rem;
    margin-bottom: 1rem;
  }
  :global(.alert-error) {
    background: rgba(233, 69, 96, 0.12);
    border: 1px solid rgba(233, 69, 96, 0.3);
    color: #ff7a92;
  }
  :global(.alert-success) {
    background: rgba(104, 211, 145, 0.1);
    border: 1px solid rgba(104, 211, 145, 0.25);
    color: var(--ui-success);
  }
  :global(.alert-info) {
    background: rgba(44, 177, 255, 0.08);
    border: 1px solid rgba(44, 177, 255, 0.2);
    color: var(--ui-primary);
  }

  main {
    padding: 1.5rem 2rem;
    max-width: 1200px;
    margin: 0 auto;
  }

  @media (max-width: 768px) {
    main { padding: 1rem; }
  }
</style>
