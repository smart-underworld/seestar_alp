<script lang="ts">
  import { link } from "svelte-spa-router";
  import { deviceList, activeDevNum } from "../stores/deviceStore";
</script>

<nav>
  <a href="/" use:link class="brand">Seestar ALP</a>

  <div class="links">
    <a href="/" use:link>Home</a>
    <a href="/live" use:link>Live</a>
    <a href="/goto" use:link>Goto</a>
    <a href="/image" use:link>Image</a>
    <a href="/schedule" use:link>Schedule</a>
    <a href="/settings" use:link>Settings</a>
    <a href="/command" use:link>Command</a>
  </div>

  {#if $deviceList.length > 1}
    <select bind:value={$activeDevNum}>
      {#each $deviceList as d}
        <option value={d.device_num}>{d.name} {d.is_connected ? "✓" : "✗"}</option>
      {/each}
    </select>
  {:else if $deviceList.length === 1}
    <span class="device-name">{$deviceList[0].name}</span>
  {/if}
</nav>

<style>
  nav {
    display: flex;
    align-items: center;
    gap: 1.5rem;
    padding: 0.75rem 1.5rem;
    background: #16213e;
    border-bottom: 1px solid #0f3460;
  }
  .brand {
    font-weight: 700;
    font-size: 1.1rem;
    text-decoration: none;
    color: #e94560;
  }
  .links {
    display: flex;
    gap: 1rem;
    flex: 1;
  }
  a {
    color: #a0aec0;
    text-decoration: none;
  }
  a:hover {
    color: #e0e0e0;
  }
  select {
    background: #0f3460;
    color: #e0e0e0;
    border: 1px solid #e94560;
    border-radius: 4px;
    padding: 0.25rem 0.5rem;
  }
  .device-name {
    color: #a0aec0;
    font-size: 0.9rem;
  }
</style>
