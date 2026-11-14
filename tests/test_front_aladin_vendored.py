"""The planner pages must not depend on CDS Strasbourg for the Aladin Lite script.

When aladin.cds.unistra.fr is unreachable a CDN-hosted script leaves the sky map
blank (and a blocking stylesheet from a dead host delays the page). The script is
vendored under front/public, and the DSS2 survey source is chosen by
front/public/dss_survey.js.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "front"
PARTIALS = [
    FRONT / "templates" / "partials" / "astro_mosaic.html",
    FRONT / "templates" / "partials" / "framed_mosaic_planning.html",
]
VENDORED = "public/vendor/aladin-lite/aladin.js"
SURVEY_JS = "public/dss_survey.js"


def _live_markup(path):
    """Template text with HTML comments removed."""
    return re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)


def test_vendored_aladin_bundle_is_present():
    bundle = FRONT / VENDORED
    assert bundle.is_file()
    assert bundle.stat().st_size > 1_000_000, "vendored aladin.js looks truncated"
    assert (bundle.parent / "LICENSE").is_file()


def test_vendored_aladin_bundle_is_a_classic_script_that_sets_window_a():
    """The raw npm dist file is an ES module: `export` in a <script src> is a
    SyntaxError and the sky map stays blank. See vendor/aladin-lite/README.md."""
    source = (FRONT / VENDORED).read_text(encoding="utf-8")
    assert "window.A=" in source[-300:]
    assert not re.search(r"export\s*\{", source[-300:])


def test_planner_partials_load_aladin_locally_and_not_from_cds():
    for partial in PARTIALS:
        markup = _live_markup(partial)
        assert VENDORED in markup, partial.name
        assert "aladin.cds.unistra.fr" not in markup, partial.name
        assert "u-strasbg.fr/AladinLite" not in markup, partial.name


def test_survey_script_loads_between_aladin_and_the_page_scripts():
    expected_after = {
        "astro_mosaic.html": "public/AstroMosaicEngine.js",
        "framed_mosaic_planning.html": "public/framed_mosaic.js",
    }
    for partial in PARTIALS:
        markup = _live_markup(partial)
        aladin = markup.index(VENDORED)
        survey = markup.index(SURVEY_JS)
        page_script = markup.index(expected_after[partial.name])
        assert aladin < survey < page_script, partial.name


def test_no_view_hardcodes_the_cds_survey_id():
    for name in ("AstroMosaicEngine.js", "framed_mosaic.js"):
        source = (FRONT / "public" / name).read_text(encoding="utf-8")
        assert not re.search(r"survey:\s*[\"']P/DSS2/color[\"']", source), name
