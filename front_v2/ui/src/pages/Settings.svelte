<script lang="ts">
  import { onMount } from "svelte";
  import { activeDevNum, isConnected } from "../lib/stores/deviceStore";
  import { api } from "../lib/api";

  let settings: Record<string, unknown> = {};
  let merged: Record<string, unknown> = {};
  let saving = false;
  let saved = false;
  let error = "";

  async function load() {
    error = "";
    try {
      const result = await api.devices.settings.get($activeDevNum);
      settings = result as Record<string, unknown>;
      merged = (result as { merged?: Record<string, unknown> }).merged ?? {};
    } catch (e) {
      error = String(e);
    }
  }

  async function save() {
    saving = true;
    error = "";
    try {
      await api.devices.settings.save($activeDevNum, merged);
      saved = true;
      setTimeout(() => (saved = false), 2000);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }

  onMount(load);
  $: if ($activeDevNum) load();
</script>

<h1>Settings</h1>

{#if !$isConnected}
  <p class="offline">Device {$activeDevNum} is offline.</p>
{:else}
  {#if error}<p class="error">{error}</p>{/if}
  {#if saved}<p class="saved">Saved.</p>{/if}

  <form on:submit|preventDefault={save}>
    {#each Object.entries(merged) as [key, val]}
      <div class="field">
        <label for={key}>{key}</label>
        <input
          id={key}
          value={val ?? ""}
          on:input={(e) => { merged = { ...merged, [key]: e.currentTarget.value }; }}
        />
      </div>
    {/each}

    <button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
  </form>
{/if}

<style>
  h1 { margin-top: 0; }
  .offline, .error { color: #e94560; }
  .saved { color: #68d391; }
  form { display: flex; flex-direction: column; gap: 0.5rem; max-width: 480px; }
  .field { display: flex; flex-direction: column; gap: 0.2rem; }
  label { font-size: 0.8rem; color: #a0aec0; }
  input {
    background: #16213e;
    border: 1px solid #0f3460;
    color: #e0e0e0;
    padding: 0.4rem 0.6rem;
    border-radius: 4px;
  }
  button {
    margin-top: 0.5rem;
    background: #e94560;
    color: white;
    border: none;
    padding: 0.5rem 1.5rem;
    border-radius: 4px;
    cursor: pointer;
    align-self: flex-start;
  }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
