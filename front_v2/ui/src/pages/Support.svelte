<script lang="ts">
  // No script needed — purely informational page
</script>

<div class="page-hero">
  <p class="page-kicker">Help</p>
  <h1 class="page-title">Support</h1>
  <p class="page-subtitle">Documentation, community, and bug reporting.</p>
</div>

<div class="support-grid">

  <div class="panel-card">
    <p class="panel-title">Documentation</p>
    <p class="section-body">
      Seestar ALP documentation can be found on GitHub:
    </p>
    <ul class="link-list">
      <li>
        <a href="https://github.com/smart-underworld/seestar_alp/blob/main/README.md" target="_blank" rel="noopener">
          README.md
        </a>
        — quick-start guide and overview
      </li>
      <li>
        <a href="https://github.com/smart-underworld/seestar_alp/wiki" target="_blank" rel="noopener">
          GitHub Wiki
        </a>
        — full documentation (wiki contributions welcome!)
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
    <p class="channel-hint">Useful channels: <code>#seestar_alp-user-channel</code> · <code>#seestar_alp-ask-developers</code></p>
  </div>

  <div class="panel-card">
    <p class="panel-title">Bug Reports &amp; Feature Requests</p>
    <p class="section-body">
      Issues are tracked on GitHub. Please search existing issues before opening a new one — a thumbs-up or comment helps prioritise work.
    </p>
    <ul class="link-list">
      <li>
        <a href="https://github.com/smart-underworld/seestar_alp/issues" target="_blank" rel="noopener">
          Browse existing issues
        </a>
      </li>
      <li>
        <a href="https://github.com/smart-underworld/seestar_alp/issues/new" target="_blank" rel="noopener">
          Open a new issue
        </a>
      </li>
    </ul>
  </div>

  <div class="panel-card">
    <p class="panel-title">Support Bundle</p>
    <p class="section-body">
      A support bundle packages logs and system info into a zip file for sharing with developers when filing a bug report.
    </p>
    <p class="section-body muted">
      Support bundle generation is available in the <strong>classic UI</strong>. Switch to it temporarily via Config → Frontend → <code>classic</code>, generate the bundle, then switch back.
    </p>
  </div>

</div>

<style>
  .support-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 1rem;
  }

  .section-body {
    font-size: 0.85rem;
    color: var(--ui-muted);
    line-height: 1.6;
    margin: 0 0 0.75rem;
  }
  .section-body.muted { color: rgba(113,128,150,0.75); }

  .link-list {
    margin: 0;
    padding-left: 1.2rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.85rem;
    color: var(--ui-muted);
  }
  .link-list a {
    color: var(--ui-primary);
    text-decoration: none;
  }
  .link-list a:hover { text-decoration: underline; }

  .discord-btn {
    display: inline-flex;
    margin-bottom: 0.75rem;
  }

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
</style>
