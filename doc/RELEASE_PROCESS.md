# Seestar ALP Release Process

This doc aims to document how we release software from this project.

- From the main repo's [github page](https://github.com/smart-underworld/seestar_alp), click on [Releases](https://github.com/smart-underworld/seestar_alp/releases) on the right of the page

- Click the ["Draft new release"](https://github.com/smart-underworld/seestar_alp/releases/new) button
- Click the "Select Tag" dropdown
- Type the new tag (Eg, v3.1.1)
- Click "Create new tag: v3.1.1 on publish"
- Name the "release title" the same as the tag
- Write some release notes.

  I usually start by indicating whether it is a mostly bugfix, or feature release
- Click "Publish Release"
- Monitor "Actions" tab for any failed builds
- Announce on:
   + #⁠seestar_alp-user-channel on Discord
   + Facebook "Smart Telescope Underworld"

## Actions tests in personal fork

Occasionally, the need arises to test/debug builds on your personal fork, to avoid a lot of builds in a publicly facing repo.

To do so:
- Go to your fork on github.com
- Click "Actions" in the top menu bar
- In the "Actions" column on the left part of the page, click "Python package"
- Click the "Run workflow" button
- Pick the branch where your test modifications to the `.github/workflows/build_seestar_alp.yaml` are.
- Monitor the build results

Once this build passes, open up a PR to the main repo with your changes.