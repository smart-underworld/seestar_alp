"""Unit tests for scripts.trajectory.faa_dof (no network)."""

from __future__ import annotations

import zipfile

import pytest

import math

from scripts.trajectory.faa_dof import (
    CULVER_CITY_06_001087,
    DEFAULT_LANDMARKS,
    HYPERION_06_000301,
    LA_BROADCAST_06_000177,
    Landmark,
    aiming_hint,
    faa_accuracy_ft,
    filter_visible,
    iter_dof_records,
    parse_dof_line,
)
from scripts.trajectory.observer import build_site


# ---------- default landmarks ----------------------------------------

def test_default_landmarks_have_expected_oas():
    assert HYPERION_06_000301.oas == "06-000301"
    assert LA_BROADCAST_06_000177.oas == "06-000177"
    assert CULVER_CITY_06_001087.oas == "06-001087"  # kept, not default
    assert len(DEFAULT_LANDMARKS) == 2
    assert DEFAULT_LANDMARKS == (HYPERION_06_000301, LA_BROADCAST_06_000177)
    # Both defaults must be lit; otherwise a night run starts with
    # at least one target the user can't see.
    assert all(lm.lit for lm in DEFAULT_LANDMARKS)


def test_default_landmarks_geometry_from_dockweiler():
    """Cross-check each default against its FAA-datasheet bearing from
    the Dockweiler site. Catches dtype / sign / unit regressions in
    the ECEF → topocentric pipeline."""
    site = build_site(lat_deg=33.9615051, lon_deg=-118.4581361, alt_m=2.0)
    hits = filter_visible(list(DEFAULT_LANDMARKS), site, min_el_deg=0.0)
    lm_by_oas = {h[0].oas: h for h in hits}
    # Hyperion primary beacon stack — FAA datasheet values.
    assert "06-000301" in lm_by_oas
    _, az, el, slant = lm_by_oas["06-000301"]
    assert az == pytest.approx(148.87, abs=0.5)
    assert el == pytest.approx(1.03, abs=0.2)
    assert slant == pytest.approx(5523.0, rel=0.02)
    # LA broadcast tower — looked up from DOF in this repo.
    assert "06-000177" in lm_by_oas
    _, az, el, slant = lm_by_oas["06-000177"]
    assert az == pytest.approx(46.83, abs=0.3)
    assert el == pytest.approx(0.86, abs=0.2)
    assert slant == pytest.approx(10_750.0, rel=0.02)


# ---------- filter_visible -------------------------------------------


def test_filter_visible_excludes_below_horizon():
    """A landmark placed below the observer (negative height) cannot be
    above 0° el. filter_visible must drop it."""
    site = build_site(lat_deg=0.0, lon_deg=0.0, alt_m=1000.0)
    buried = Landmark(
        oas="00-000000", name="sunk",
        lat_deg=0.0, lon_deg=0.01, height_amsl_m=-500.0,
        lit=False, accuracy_class="",
    )
    assert filter_visible([buried], site) == []


def test_filter_visible_excludes_beyond_radius():
    # Observer at 500 m AMSL so a far-away target can still be above
    # the horizon once Earth-curvature drop is applied.
    site = build_site(lat_deg=0.0, lon_deg=0.0, alt_m=500.0)
    # ~111 km north, tall enough (15 km) to stay well above horizon.
    far = Landmark(
        oas="00-000001", name="far",
        lat_deg=1.0, lon_deg=0.0, height_amsl_m=15000.0,
        lit=True, accuracy_class="",
    )
    assert filter_visible([far], site, max_slant_km=20.0) == []
    # But visible with a large radius.
    assert len(filter_visible([far], site, max_slant_km=500.0)) == 1


def test_filter_visible_ranks_lit_then_height_then_slant():
    site = build_site(lat_deg=0.0, lon_deg=0.0, alt_m=0.0)
    # Three candidates at various positions, all visible.
    lm_close_unlit = Landmark(
        oas="00-000A", name="A", lat_deg=0.01, lon_deg=0.0,
        height_amsl_m=200.0, lit=False, accuracy_class="",
    )
    lm_tall_lit = Landmark(
        oas="00-000B", name="B", lat_deg=0.03, lon_deg=0.0,
        height_amsl_m=500.0, lit=True, accuracy_class="",
    )
    lm_short_lit = Landmark(
        oas="00-000C", name="C", lat_deg=0.02, lon_deg=0.0,
        height_amsl_m=150.0, lit=True, accuracy_class="",
    )
    hits = filter_visible(
        [lm_close_unlit, lm_tall_lit, lm_short_lit], site,
        min_el_deg=0.05,
    )
    names = [h[0].name for h in hits]
    # Lit first, tall before short within lit, unlit last.
    assert names == ["B", "C", "A"]


# ---------- parse_dof_line -------------------------------------------


def _build_dof_line(
    *,
    oas_state: str,
    obs_num: str,
    city: str,
    lat_deg: int, lat_min: int, lat_sec: float, lat_hemi: str,
    lon_deg: int, lon_min: int, lon_sec: float, lon_hemi: str,
    obstacle_type: str,
    quantity: int,
    agl_ft: int,
    amsl_ft: int,
    lighting: str,
    h_acc: str,
    v_acc: str,
    marking: str,
) -> str:
    """Build a byte-aligned FAA DOF DAT line matching the real 2026
    format. Layout comes from a CA ("06-") record pulled from the
    live DAT zip."""
    return (
        f"{oas_state:>2}"                       # [0:2]  OAS state
        "-"                                      # [2]    separator
        f"{obs_num:>6}"                         # [3:9]  obs number
        " "
        "O"                                      # [10]   verified
        " "
        "US"                                     # [12:14]
        " "
        "CA"                                     # [15:17]
        " "
        f"{city:<16}"                           # [18:34]
        " "
        f"{lat_deg:02d}"                        # [35:37]
        " "
        f"{lat_min:02d}"                        # [38:40]
        " "
        f"{lat_sec:05.2f}"                      # [41:46]
        f"{lat_hemi}"                           # [46]
        " "
        f"{lon_deg:03d}"                        # [48:51]
        " "
        f"{lon_min:02d}"                        # [52:54]
        " "
        f"{lon_sec:05.2f}"                      # [55:60]
        f"{lon_hemi}"                           # [60]
        " "
        f"{obstacle_type:<13}"                  # [62:75]
        "  "
        f"{quantity:5d}"                        # [77:82]
        " "
        f"{agl_ft:05d}"                         # [83:88]
        " "
        f"{amsl_ft:05d}"                        # [89:94]
        " "
        f"{lighting}"                           # [95]
        " "
        f"{h_acc}"                              # [97]
        " "
        f"{v_acc}"                              # [99]
        " "
        f"{marking}"                            # [101]
    )


_HYPERION_LINE = _build_dof_line(
    oas_state="06", obs_num="000301", city="EL SEGUNDO",
    lat_deg=33, lat_min=55, lat_sec=8.00, lat_hemi="N",
    lon_deg=118, lon_min=25, lon_sec=38.00, lon_hemi="W",
    obstacle_type="STACK", quantity=2, agl_ft=292, amsl_ft=339,
    lighting="R", h_acc="1", v_acc="A", marking="M",
)

_CULVER_LINE = _build_dof_line(
    oas_state="06", obs_num="001087", city="CULVER CITY",
    lat_deg=34, lat_min=0, lat_sec=57.10, lat_hemi="N",
    lon_deg=118, lon_min=22, lon_sec=59.36, lon_hemi="W",
    obstacle_type="TOWER", quantity=1, agl_ft=280, amsl_ft=649,
    lighting="N", h_acc="1", v_acc="E", marking="N",
)


def test_parse_dof_line_hyperion():
    lm = parse_dof_line(_HYPERION_LINE)
    assert lm is not None
    assert lm.oas == "06-000301"
    assert lm.lat_deg == pytest.approx(33.918889, abs=1e-4)
    assert lm.lon_deg == pytest.approx(-118.427223, abs=1e-4)
    assert lm.height_amsl_m == pytest.approx(339 * 0.3048, abs=0.01)
    assert lm.lit is True  # "R" = red obstruction
    assert "STACK" in lm.obstacle_type


def test_parse_dof_line_culver_city_unlit():
    lm = parse_dof_line(_CULVER_LINE)
    assert lm is not None
    assert lm.oas == "06-001087"
    assert lm.lit is False  # "N" = not lit
    assert "TOWER" in lm.obstacle_type


def test_parse_dof_line_rejects_header():
    assert parse_dof_line("DIGITAL OBSTACLE FILE") is None
    assert parse_dof_line("") is None
    assert parse_dof_line("a short line") is None


# ---------- iter_dof_records -----------------------------------------


def test_iter_dof_records_reads_zip(tmp_path):
    """Write a minimal ZIP containing the two synthetic lines and
    verify the iterator yields both with a matching state prefix."""
    dat_bytes = (_HYPERION_LINE + "\n" + _CULVER_LINE + "\n").encode("latin-1")
    zip_path = tmp_path / "dof.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("DOF.DAT", dat_bytes)
    records = list(iter_dof_records(zip_path, state="06"))
    assert len(records) == 2
    oas = {r.oas for r in records}
    assert oas == {"06-000301", "06-001087"}


# ---------- faa_accuracy_ft --------------------------------------------


def test_faa_accuracy_ft_known_classes():
    """Canonical FAA DOF codes map to the published tolerances."""
    assert faa_accuracy_ft("1A") == (50.0, 3.0)    # Hyperion
    assert faa_accuracy_ft("1B") == (50.0, 10.0)   # LA broadcast
    assert faa_accuracy_ft("1E") == (50.0, 125.0)  # Culver City
    assert faa_accuracy_ft("4D") == (1000.0, 50.0)
    assert faa_accuracy_ft("2C") == (250.0, 20.0)


def test_faa_accuracy_ft_lowercase_accepted():
    assert faa_accuracy_ft("1a") == (50.0, 3.0)


def test_faa_accuracy_ft_unknown_horizontal():
    """Horizontal digits 5-9 are 'unverified / unknown' per FAA."""
    h, v = faa_accuracy_ft("5A")
    assert math.isnan(h)
    assert v == 3.0


def test_faa_accuracy_ft_unknown_vertical():
    h, v = faa_accuracy_ft("1H")
    assert h == 50.0
    assert math.isnan(v)


def test_faa_accuracy_ft_empty_or_malformed_returns_nan():
    for bad in ("", " ", "1", "XY", None):
        h, v = faa_accuracy_ft(bad)  # type: ignore[arg-type]
        assert math.isnan(h)
        assert math.isnan(v)


# ---------- aiming_hint ------------------------------------------------


def test_aiming_hint_lit_stack_calls_out_taller():
    """STACK landmarks (Hyperion pair) should note the 'top of the
    taller stack' convention — the paired-stack case is the one
    place the aim point isn't the top-centre of a single structure."""
    hint = aiming_hint(HYPERION_06_000301)
    assert "L-864" in hint
    assert "taller" in hint.lower()


def test_aiming_hint_lit_tower_points_at_top_beacon():
    hint = aiming_hint(LA_BROADCAST_06_000177)
    assert "top" in hint.lower()
    assert "L-864" in hint


def test_aiming_hint_unlit_says_daytime_only():
    hint = aiming_hint(CULVER_CITY_06_001087)
    assert "daytime" in hint.lower() or "silhouette" in hint.lower()


def test_aiming_hint_unknown_type_falls_back():
    lm = Landmark(
        oas="00-000000", name="mystery",
        lat_deg=0, lon_deg=0, height_amsl_m=100.0,
        lit=True, accuracy_class="1A",
        obstacle_type="UFO",
    )
    assert "top" in aiming_hint(lm).lower()


def test_aiming_hint_bldg_lit():
    lm = Landmark(
        oas="00-000001", name="roof",
        lat_deg=0, lon_deg=0, height_amsl_m=100.0,
        lit=True, accuracy_class="1A",
        obstacle_type="BLDG",
    )
    hint = aiming_hint(lm)
    assert "roof" in hint.lower() or "marker" in hint.lower()


def test_aiming_hint_antenna():
    lm = Landmark(
        oas="00-000002", name="tl",
        lat_deg=0, lon_deg=0, height_amsl_m=100.0,
        lit=True, accuracy_class="1A",
        obstacle_type="T-L TWR",
    )
    hint = aiming_hint(lm)
    assert "antenna" in hint.lower() or "T-L" in hint
