<script lang="ts">
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let method = "";
  let paramsJson = "{}";
  let result: unknown = null;
  let error = "";
  let loading = false;

  async function send() {
    error = "";
    result = null;
    loading = true;
    try {
      const params = JSON.parse(paramsJson);
      result = await api.devices.command($activeDevNum, method, params);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }
</script>

<h1>Command</h1>

{#if !$isConnected}
  <p class="offline">Device {$activeDevNum} is offline.</p>
{:else}
  <form on:submit|preventDefault={send}>
    <div class="field">
      <label for="method">Method</label>
      <input id="method" bind:value={method} placeholder="get_device_state" required />
    </div>
    <div class="field">
      <label for="params">Params (JSON)</label>
      <textarea id="params" bind:value={paramsJson} rows="4"></textarea>
    </div>
    <button type="submit" disabled={loading}>{loading ? "Sending…" : "Send"}</button>
  </form>

  {#if error}<p class="error">{error}</p>{/if}
  {#if result}
    <pre class="result">{JSON.stringify(result, null, 2)}</pre>
  {/if}
{/if}

<style>
  h1 { margin-top: 0; }
  .offline, .error { color: #e94560; }
  form { display: flex; flex-direction: column; gap: 0.75rem; max-width: 480px; }
  .field { display: flex; flex-direction: column; gap: 0.2rem; }
  label { font-size: 0.8rem; color: #a0aec0; }
  input, textarea {
    background: #16213e; border: 1px solid #0f3460;
    color: #e0e0e0; padding: 0.4rem 0.6rem; border-radius: 4px;
    font-family: monospace; resize: vertical;
  }
  button {
    background: #e94560; color: white; border: none;
    padding: 0.5rem 1.5rem; border-radius: 4px; cursor: pointer;
    align-self: flex-start;
  }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  .result {
    margin-top: 1rem; background: #16213e; border: 1px solid #0f3460;
    padding: 1rem; border-radius: 4px; overflow: auto;
    font-size: 0.8rem; color: #a0aec0;
  }
</style>
