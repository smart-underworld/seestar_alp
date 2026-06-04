<script lang="ts">
  import { activeDevNum } from "../lib/stores/deviceStore";

  let description = `Please describe your problem in as much detail as you can provide.

Reproduction steps and the times issues occurred are helpful.`;
  let includeSeestarLogs = false;
  let generating = false;
  let error = "";

  async function downloadBundle() {
    generating = true;
    error = "";
    try {
      const res = await fetch("/api/v1/support-bundle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description,
          dev_num: $activeDevNum,
          include_seestar_logs: includeSeestarLogs,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `HTTP ${res.status}`);
      }
      // Trigger browser download
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") ?? "";
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : "seestar_alp_support.zip";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      error = String(e);
    } finally {
      generating = false;
    }
  }
</script>

<div class="page-hero">
  <p class="page-kicker">Help</p>
  <h1 class="page-title">Support</h1>
  <p class="page-subtitle">Documentation, community, and bug reporting.</p>
</div>

<div class="support-grid">

  <div class="panel-card">
    <p class="panel-title">Documentation</p>
    <p class="section-body">Seestar ALP documentation can be found on GitHub:</p>
    <ul class="link-list">
      <li>
        <a href="https://github.com/smart-underworld/seestar_alp/blob/main/README.md" target="_blank" rel="noopener">README.md</a>
        — quick-start guide and overview
      </li>
      <li>
        <a href="https://github.com/smart-underworld/seestar_alp/wiki" target="_blank" rel="noopener">GitHub Wiki</a>
        — full documentation (contributions welcome!)
      </li>
    </ul>
  </div>

  <div class="panel-card">
    <p class="panel-title">Community</p>
    <p class="section-body">
      The primary collaboration space is Discord. Join for help, advice, and discussion with other users and developers.
    </p>
    <a href="https://discord.gg/B3zDCAMP4V" target="_blank" rel="noopener" class="btn btn-primary discord-btn">
      Join Discord Server
    </a>
    <p class="channel-hint">
      Useful channels: <code>#seestar_alp-user-channel</code> · <code>#seestar_alp-ask-developers</code>
    </p>
  </div>

  <div class="panel-card">
    <p class="panel-title">Bug Reports &amp; Feature Requests</p>
    <p class="section-body">
      Issues are tracked on GitHub. Search before opening — a thumbs-up or comment helps prioritise work.
    </p>
    <ul class="link-list">
      <li><a href="https://github.com/smart-underworld/seestar_alp/issues" target="_blank" rel="noopener">Browse existing issues</a></li>
      <li><a href="https://github.com/smart-underworld/seestar_alp/issues/new" target="_blank" rel="noopener">Open a new issue</a></li>
    </ul>
  </div>

  <div class="panel-card bundle-card">
    <p class="panel-title">Support Bundle</p>
    <p class="section-body">
      Generate a zip file containing SSC logs, config.toml, system info, and your problem description. Attach it to a GitHub issue to help developers debug.
    </p>

    {#if error}<div class="alert alert-error" style="margin-bottom:0.75rem">{error}</div>{/if}

    <div class="form-field" style="margin-bottom:0.75rem">
      <label class="form-label" for="bundle-desc">Problem Description</label>
      <textarea
        id="bundle-desc"
        class="form-input"
        rows="8"
        bind:value={description}
      ></textarea>
    </div>

    <label class="checkbox-label">
      <input type="checkbox" bind:checked={includeSeestarLogs} />
      Collect embedded logs from the Seestar device
    </label>

    <button
      class="btn btn-primary bundle-btn"
      on:click={downloadBundle}
      disabled={generating}
    >
      {generating ? "Generating…" : "⬇ Download Support Bundle"}
    </button>
  </div>

</div>

<style>
  .support-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 1rem;
    align-items: start;
  }

  .bundle-card {
    grid-column: 1 / -1;
  }

  .section-body {
    font-size: 0.85rem;
    color: var(--ui-muted);
    line-height: 1.6;
    margin: 0 0 0.75rem;
  }

  .link-list {
    margin: 0;
    padding-left: 1.2rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.85rem;
    color: var(--ui-muted);
  }
  .link-list a { color: var(--ui-primary); text-decoration: none; }
  .link-list a:hover { text-decoration: underline; }

  .discord-btn { display: inline-flex; margin-bottom: 0.75rem; }

  .channel-hint {
    font-size: 0.75rem;
    color: var(--ui-muted);
    margin: 0;
  }
  .channel-hint code {
    font-family: "SF Mono","Fira Code",monospace;
    font-size: 0.8em;
    background: rgba(255,255,255,0.07);
    padding: 0.1em 0.35em;
    border-radius: 3px;
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.83rem;
    color: var(--ui-body);
    cursor: pointer;
    margin-bottom: 1rem;
  }
  .checkbox-label input[type="checkbox"] {
    accent-color: var(--ui-primary);
    width: 15px;
    height: 15px;
    cursor: pointer;
  }

  .bundle-btn { width: 100%; justify-content: center; }
</style>
