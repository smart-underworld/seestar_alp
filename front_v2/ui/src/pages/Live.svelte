<script lang="ts">
  import { activeDevNum, activeDeviceStatus, isConnected } from "../lib/stores/deviceStore";

  // The MJPEG stream is served by the Flask imaging server on imgport.
  // We read it directly via an <img> tag — no changes to that server needed.
  // The port is baked at build time via the API; for now we default to 7556.
  const imgPort = 7556;

  $: vidUrl = `http://${location.hostname}:${imgPort}/${$activeDevNum}/vid`;
  $: overlayState = $activeDeviceStatus;
</script>

<h1>Live View</h1>

{#if !$isConnected}
  <p class="offline">Device {$activeDevNum} is offline.</p>
{:else}
  <div class="live-container">
    <img src={vidUrl} alt="Live telescope feed" class="live-feed" />

    {#if overlayState}
      <div class="overlay">
        <span>{overlayState.view_state}</span>
        {#if overlayState.ra != null}
          <span>RA {overlayState.ra.toFixed(3)}° / Dec {overlayState.dec?.toFixed(3)}°</span>
        {/if}
        {#if overlayState.stacked !== ""}
          <span>{overlayState.stacked} frames</span>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  h1 { margin-top: 0; }
  .offline { color: #e94560; }
  .live-container {
    position: relative;
    display: inline-block;
    max-width: 100%;
  }
  .live-feed {
    max-width: 100%;
    border: 1px solid #0f3460;
    border-radius: 4px;
    display: block;
  }
  .overlay {
    position: absolute;
    bottom: 0.5rem;
    left: 0.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .overlay span {
    background: rgba(0,0,0,0.7);
    color: #e0e0e0;
    font-size: 0.75rem;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }
</style>
