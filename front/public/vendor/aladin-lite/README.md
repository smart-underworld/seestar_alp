# Aladin Lite (vendored)

`aladin.js` is Aladin Lite 3.9.2-beta (LGPL-3.0-or-later, see `LICENSE` and
`COPYING`). Upstream: https://github.com/cds-astro/aladin-lite

It is served from this directory so the planner pages do not depend on
`aladin.cds.unistra.fr` being reachable. Sky tiles still come from a HiPS
server; see `../../dss_survey.js` for how the DSS2 colour survey source is
chosen.

## This is not the raw npm file

The `aladin-lite` npm package ships `dist/aladin.js` as an ES module (it ends
with `export{f as default};`). The planner pages load it with a plain
`<script src>` tag, where `export` is a SyntaxError and `window.A` is never
defined, which leaves the sky map blank. `scripts/vendor_aladin_lite.py` wraps
the module body in a function and assigns the default export to `window.A`,
which is how CDS's hosted `latest/aladin.js` behaves. Nothing else is changed.

To update:

```
npm pack aladin-lite
tar -xzf aladin-lite-*.tgz
python scripts/vendor_aladin_lite.py package/dist/aladin.js <version>
```

Then bump the `?v=` value on the script tag in
`templates/partials/astro_mosaic.html` and
`templates/partials/framed_mosaic_planning.html`. `front/tests/aladin_vendored.test.js`
fails if the file stops being loadable as a classic script.
