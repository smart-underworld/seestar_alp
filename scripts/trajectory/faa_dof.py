"""FAA Digital Obstruction File (DOF) access + landmark catalog.

Provides the two default calibration landmarks for the Dockweiler Beach
observing site (Hyperion stack + Culver City tower) and a fetcher that
parses the full DOF DAT file to produce a short list of visible
landmarks when the defaults aren't suitable.

The DAT file is fixed-width ASCII, one record per line. Positions
below are 0-indexed half-open slices, derived from a real 2026-vintage
DOF.DAT record:

    [0:2]   OAS state code            ("06" for California)
    [2]     "-"                       (state/obstacle separator)
    [3:9]   obstacle number           (6 chars, zero-padded)
    [10]    verification status       ("O" verified, "U" unverified)
    [12:14] country                   ("US")
    [15:17] state                     ("CA")
    [18:34] city                      (16 chars, space-padded)
    [35:37] lat degrees
    [38:40] lat minutes
    [41:46] lat seconds.hundredths    ("SS.SS")
    [46]    lat hemisphere            ("N"/"S", packed — no leading space)
    [48:51] lon degrees               (3 chars)
    [52:54] lon minutes
    [55:60] lon seconds.hundredths
    [60]    lon hemisphere            ("E"/"W", packed)
    [62:75] obstacle type             (13 chars, space-padded)
    [77:82] quantity                  (5 chars, right-aligned)
    [83:88] AGL height (ft)           (right-aligned)
    [89:94] AMSL height (ft)
    [95]    lighting character        ("R"/"W"/"D"/"N"/...)
    [97]    horizontal accuracy code
    [99]    vertical accuracy code
    [101]   marking indicator

The lat/lon fields are double-checked with regex so rows with slight
column drift between FAA revisions still parse. Rows that fail
anything are silently skipped; the two hardcoded defaults bypass the
parser entirely.
"""

from __future__ import annotations

import io
import os
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scripts.trajectory.observer import (
    ObserverSite,
    ecef_array_to_topo,
    lla_to_ecef,
)


DOF_ZIP_URL = "https://aeronav.faa.gov/Obst_Data/DAILY_DOF_DAT.ZIP"


@dataclass(frozen=True)
class Landmark:
    """A single calibration-candidate obstruction.

    ``oas`` is the FAA obstruction identifier (e.g. "06-000301"). ``lit``
    captures whether the beacon is on at night (L-864 red, L-810 side,
    white strobe). Unlit landmarks (``lit=False``) work for daytime
    calibration only.
    """
    oas: str
    name: str
    lat_deg: float
    lon_deg: float
    height_amsl_m: float
    lit: bool
    accuracy_class: str
    obstacle_type: str = ""
    city: str = ""

    def ecef(self) -> tuple[float, float, float]:
        return lla_to_ecef(self.lat_deg, self.lon_deg, self.height_amsl_m)


# ---------- hardcoded defaults ----------------------------------------

HYPERION_06_000301 = Landmark(
    oas="06-000301",
    name="Hyperion primary beacon stack",
    lat_deg=33.918889,
    lon_deg=-118.427223,
    height_amsl_m=339.0 * 0.3048,  # 339 ft AMSL → 103.33 m
    lit=True,                       # L-864 red obstruction + L-810 sides
    accuracy_class="1A",
    obstacle_type="STACK",
    city="El Segundo / Playa del Rey",
)

LA_BROADCAST_06_000177 = Landmark(
    oas="06-000177",
    name="LA broadcast tower (Baldwin Hills cluster)",
    lat_deg=34.027767,            # 34° 01' 39.96" N
    lon_deg=-118.373250,           # 118° 22' 23.70" W
    height_amsl_m=568.0 * 0.3048,  # 568 ft AMSL → 173.13 m (473 ft AGL)
    lit=True,                      # L-864 red beacon per DOF record
    accuracy_class="1B",           # 1 = ±50 ft horiz, B = ±10 ft vert
    obstacle_type="TOWER",
    city="Los Angeles",
)

# Kept for downstream tools that reference the original unlit Culver
# City obstruction by name. Not a default — see LA_BROADCAST_06_000177
# above, which sits 2.1° west on the same Baldwin Hills ridge and is
# actually lit (usable at night).
CULVER_CITY_06_001087 = Landmark(
    oas="06-001087",
    name="Culver City tower (Baldwin Hills, unlit)",
    lat_deg=34.015863,
    lon_deg=-118.383156,
    height_amsl_m=649.0 * 0.3048,
    lit=False,
    accuracy_class="1E",
    obstacle_type="TOWER",
    city="Culver City",
)

DEFAULT_LANDMARKS: tuple[Landmark, ...] = (
    HYPERION_06_000301, LA_BROADCAST_06_000177,
)


# ---------- visibility filter -----------------------------------------


def _compute_topo(site: ObserverSite, landmarks: list[Landmark]) -> np.ndarray:
    """Return an (N, 3) array of (az_deg, el_deg, slant_m) per landmark."""
    if not landmarks:
        return np.zeros((0, 3))
    ecef = np.asarray(
        [list(lla_to_ecef(lm.lat_deg, lm.lon_deg, lm.height_amsl_m))
         for lm in landmarks],
        dtype=float,
    )
    az, el, slant = ecef_array_to_topo(ecef, site)
    return np.stack([az, el, slant], axis=-1)


def filter_visible(
    landmarks: list[Landmark],
    site: ObserverSite,
    *,
    min_el_deg: float = 0.3,
    max_slant_km: float = 20.0,
    top_n: int = 10,
) -> list[tuple[Landmark, float, float, float]]:
    """Return the top-N landmarks visible from ``site``.

    Visible = above ``min_el_deg`` and within ``max_slant_km`` of the
    observer. Ranked by ``(lit desc, height_amsl_m desc, slant asc)``
    so lit, tall, close obstructions bubble up first.

    Each result tuple is ``(landmark, az_deg, el_deg, slant_m)``.
    """
    if not landmarks:
        return []
    topo = _compute_topo(site, landmarks)
    out: list[tuple[Landmark, float, float, float]] = []
    for lm, (az, el, slant) in zip(landmarks, topo):
        if el < min_el_deg:
            continue
        if slant > max_slant_km * 1000.0:
            continue
        out.append((lm, float(az), float(el), float(slant)))
    out.sort(key=lambda t: (not t[0].lit, -t[0].height_amsl_m, t[3]))
    return out[:top_n]


# ---------- DAT fetch + parse -----------------------------------------


def default_cache_path() -> Path:
    """~/.cache/seestar_alp/dof_dat.zip — respects XDG_CACHE_HOME."""
    root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "seestar_alp" / "dof_dat.zip"


def fetch_dof_zip(
    cache_path: Path | None = None,
    *,
    max_age_s: float = 30 * 24 * 3600,
    url: str = DOF_ZIP_URL,
) -> Path:
    """Return the path to a cached copy of the FAA DOF DAT zip.

    Downloads from ``url`` if the cache file is missing or older than
    ``max_age_s``. The file is ~20 MB; callers should not call this
    more than once per session.
    """
    import requests

    p = cache_path or default_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and (time.time() - p.stat().st_mtime) < max_age_s:
        return p
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        tmp = p.with_suffix(p.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
        tmp.replace(p)
    return p


# DOF lines have a leading bulk header / legend that we skip by requiring
# the first two chars to be a 2-digit state code followed by a dash.
_STATE_CODE_RE = re.compile(r"^\d{2}-")
# Inside each record, lat/lon blocks have a stable pattern we can
# regex-match regardless of minor column drift. Hemisphere letter is
# packed directly against the seconds field — no intervening space.
_LAT_RE = re.compile(r"(\d{2}) (\d{2}) (\d{2}\.\d{2})([NS])")
_LON_RE = re.compile(r"(\d{3}) (\d{2}) (\d{2}\.\d{2})([EW])")


def _parse_dms(d: str, m: str, s: str, hemi: str) -> float:
    val = float(d) + float(m) / 60.0 + float(s) / 3600.0
    if hemi in ("S", "W"):
        val = -val
    return val


def parse_dof_line(line: str) -> Landmark | None:
    """Parse one line of FAA DOF DAT. Returns None if the row is
    malformed, a header, or missing required fields."""
    if not line or not _STATE_CODE_RE.match(line):
        return None
    # Require at least 96 chars so lat/lon/AMSL/lighting are present.
    if len(line) < 96:
        return None
    try:
        state_code = line[0:2]
        obs_num = line[3:9].strip()
        oas = f"{state_code}-{obs_num}"
        city = line[18:34].strip()
        # Lat at [35:47] ("DD MM SS.SSH"); lon at [48:61] ("DDD MM SS.SSH").
        lat_m = _LAT_RE.search(line[35:47])
        lon_m = _LON_RE.search(line[48:61])
        if lat_m is None or lon_m is None:
            return None
        lat = _parse_dms(*lat_m.groups())
        lon = _parse_dms(*lon_m.groups())
        obstacle_type = line[62:75].strip()
        # AGL [83:88] + AMSL [89:94] are right-aligned 5-char integer
        # fields. If the canonical slice doesn't parse, scan the [82:95]
        # window for integer tokens and take the last (AMSL).
        amsl_str = line[89:94].strip()
        if not amsl_str.isdigit():
            ints = [t for t in line[82:95].split() if t.isdigit()]
            if not ints:
                return None
            amsl_str = ints[-1]
        amsl_ft = float(amsl_str)
        lighting = line[95] if len(line) > 95 else " "
        # Horizontal accuracy at [97], vertical at [99]; concatenated
        # (e.g. "1A", "4D", "5 ") matches the user-visible FAA convention.
        h_acc = line[97] if len(line) > 97 else " "
        v_acc = line[99] if len(line) > 99 else " "
        accuracy = (h_acc + v_acc).strip()
        # Lighting codes: "R" L-864 red obstruction, "D" L-810 red side,
        # "W" white strobe, "H" high-intensity white, "M" medium-intensity,
        # "S" dual red/white. "N" = not lit per FAA record.
        lit = lighting.upper() in {"R", "D", "W", "H", "M", "S"}
        return Landmark(
            oas=oas,
            name=(f"{obstacle_type} {oas}" if obstacle_type else oas),
            lat_deg=lat,
            lon_deg=lon,
            height_amsl_m=amsl_ft * 0.3048,
            lit=lit,
            accuracy_class=accuracy,
            obstacle_type=obstacle_type,
            city=city,
        )
    except (ValueError, IndexError):
        return None


def iter_dof_records(zip_path: Path, *, state: str = "06"):
    """Yield Landmark records from the DOF DAT zip, filtered to
    ``state`` (2-digit OAS code, default ``06`` = California)."""
    with zipfile.ZipFile(zip_path) as zf:
        # DAT archives typically contain a single DOF.DAT file; scan
        # members rather than assume a name.
        members = [n for n in zf.namelist()
                   if n.upper().endswith(".DAT")]
        if not members:
            return
        with zf.open(members[0]) as raw:
            wrapped = io.TextIOWrapper(raw, encoding="latin-1", errors="replace")
            prefix = state + "-"
            for line in wrapped:
                if not line.startswith(prefix):
                    continue
                lm = parse_dof_line(line.rstrip("\r\n"))
                if lm is not None:
                    yield lm


def fetch_nearby_landmarks(
    site: ObserverSite,
    *,
    state: str = "06",
    radius_km: float = 20.0,
    cache_path: Path | None = None,
) -> list[Landmark]:
    """Download (if needed) and parse the FAA DOF DAT, returning every
    landmark from ``state`` within ``radius_km`` of ``site``.

    Combines network I/O (``fetch_dof_zip``) with filtering. Callers
    that want to plug in a pre-downloaded zip can pass ``cache_path``.
    """
    zip_path = fetch_dof_zip(cache_path=cache_path)
    candidates = list(iter_dof_records(zip_path, state=state))
    # Pre-filter by slant distance so we don't carry thousands of
    # landmarks into visibility ranking.
    topo = _compute_topo(site, candidates)
    if topo.size == 0:
        return []
    slant = topo[:, 2]
    mask = slant <= radius_km * 1000.0
    return [c for c, keep in zip(candidates, mask) if keep]


# ---------- FAA accuracy decoding + aiming hints ---------------------


# FAA DOF accuracy code → (horizontal_ft, vertical_ft) tolerances.
# Source: FAA DOF User Guide rev. 2023. "5" horizontal and "H"/"I"
# vertical are explicitly "unknown / unverified" so we surface NaN.
_FAA_H_FT: dict[str, float] = {
    "1":   50.0,
    "2":  250.0,
    "3":  500.0,
    "4": 1000.0,
    "5": float("nan"),
    "6": float("nan"),
    "7": float("nan"),
    "8": float("nan"),
    "9": float("nan"),
}
_FAA_V_FT: dict[str, float] = {
    "A":   3.0,
    "B":  10.0,
    "C":  20.0,
    "D":  50.0,
    "E": 125.0,
    "F": 250.0,
    "G": 500.0,
    "H": float("nan"),
    "I": float("nan"),
}


def faa_accuracy_ft(accuracy_class: str) -> tuple[float, float]:
    """Decode a two-character FAA DOF accuracy code into
    ``(horizontal_ft, vertical_ft)`` tolerances.

    - Digit encodes horizontal accuracy (``1`` = ±50 ft best;
      ``4`` = ±1000 ft worst; ``5``–``9`` = unknown).
    - Letter encodes vertical accuracy (``A`` = ±3 ft best;
      ``E`` = ±125 ft; ``H``/``I`` = unknown).
    Returns ``(nan, nan)`` when the code is missing or malformed;
    callers display those as "unknown" in the UI.
    """
    if not isinstance(accuracy_class, str) or len(accuracy_class) < 2:
        return (float("nan"), float("nan"))
    h = _FAA_H_FT.get(accuracy_class[0].upper(), float("nan"))
    v = _FAA_V_FT.get(accuracy_class[1].upper(), float("nan"))
    return (h, v)


# Aiming-hint table keyed by (normalised obstacle_type, lighting
# letter). The DOF User Guide states the published lat/lon/AMSL
# refer to "the top of the tallest obstruction element", so picking
# a consistent top-of-structure aim point avoids a systematic offset.
_LIT_WHITE = {"W", "H", "M", "S"}


def aiming_hint(landmark: "Landmark") -> str:
    """Short sentence describing where to point the scope on this
    landmark. Uses ``obstacle_type`` + ``lighting`` (inferred from
    ``accuracy_class`` via ``lit`` — the record-level lighting letter
    is encoded in ``Landmark.lit`` + ``obstacle_type``) to pick a
    specific feature: L-864 red beacon, L-810 side lights, white
    strobe, or silhouette top.

    The DOF position is by convention the top of the tallest element,
    so the hint always biases toward the highest identifiable point.
    """
    t = (landmark.obstacle_type or "").upper().strip()
    # The `lit` boolean in our Landmark collapses multiple lighting
    # codes; we can't recover the exact letter from it. But since the
    # DOF record surfaces distinct codes, callers that care about
    # "R vs D vs W" can pass them down another day. For the shipped
    # data (HYPERION_06_000301=R, LA_BROADCAST_06_000177=R, Culver City=N)
    # the distinction between L-864, L-810, and strobes is captured
    # well enough by type + lit for the phrasing here to be useful.
    if not landmark.lit:
        return (
            "Unlit — daytime only. Aim at the top-centre silhouette "
            "against the sky."
        )
    if "STACK" in t:
        return (
            "Red L-864 beacon at the top of the taller stack "
            "(FAA position is the top of the tallest element)."
        )
    if "T-L" in t or "ANT" in t:
        return "Top of the antenna / T-L tower."
    if "TOWER" in t:
        return "Red L-864 flashing beacon at the very top of the tower."
    if "BLDG" in t:
        return (
            "Top-edge marker light; aim at the highest lit point on "
            "the roofline."
        )
    return "Top of the structure."
