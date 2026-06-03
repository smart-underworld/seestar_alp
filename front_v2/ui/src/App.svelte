<script lang="ts">
  import { onMount } from "svelte";
  import Router from "svelte-spa-router";
  import { initDevices } from "./lib/stores/deviceStore";
  import Nav from "./lib/components/Nav.svelte";
  import Home from "./pages/Home.svelte";
  import Live from "./pages/Live.svelte";
  import Settings from "./pages/Settings.svelte";
  import Schedule from "./pages/Schedule.svelte";
  import Goto from "./pages/Goto.svelte";
  import Image from "./pages/Image.svelte";
  import Command from "./pages/Command.svelte";

  const routes = {
    "/": Home,
    "/live": Live,
    "/settings": Settings,
    "/schedule": Schedule,
    "/goto": Goto,
    "/image": Image,
    "/command": Command,
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
  :global(body) {
    margin: 0;
    font-family: system-ui, -apple-system, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
  }
  main {
    padding: 1rem 1.5rem;
  }
</style>
