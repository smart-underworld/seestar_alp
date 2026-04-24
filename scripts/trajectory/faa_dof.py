"""FAA Digital Obstruction File (DOF) access + landmark catalog.

Provides the two default calibration landmarks for the Dockweiler Beach
observing site (Hyperion stack + Culver City tower) and a fetcher that
parses the full DOF DAT file to produce a short list of visible
landmarks when the defaults aren't suitable.

The DAT file is fixed-width ASCII, one record per line. Column positions
(1-indexed) from the FAA DOF User Guide, 0-indexed slice in brackets:

    1-2    [0:2]    OAS state code           (e.g. "06" for California)
    4-9    [3:9]    obstacle number          (6 chars, zero-padded)
    11     [10]     verification status      ("O"=verified, "U"=unverified)
    13-14  [12:14]  country                  ("US")
    16-17  [15:17]  state                    ("CA")
    19-34  [18:34]  city                     (16 chars, space-padded)
    36-37  [35:37]  lat degrees
    39-40  [38:40]  lat minutes
    42-46  [41:46]  lat seconds.hundredths   (SS.SS)
    48     [47]     lat hemisphere           ("N"/"S")
    50-52  [49:52]  lon degrees
    54-55  [53:55]  lon minutes
    57-61  [56:61]  lon seconds.hundredths
    63     [62]     lon hemisphere           ("E"/"W")
    65-74  [64:74]  obstacle type            (10 chars)
    76-80  [75:80]  quantity
    82-86  [81:86]  AGL height (ft, right-aligned)
    88-92  [87:92]  AMSL height (ft, right-aligned)
    94     [93]     lighting character       ("R"/"W"/"D"/"N"/...)
    96     [95]     marking
    100-101 [99:101] accuracy code           ("1A", "1E", ...)

The lat/lon fields are cross-checked with regex so minor column drift
between FAA revisions doesn't break the parser. Rows that fail to
parse cleanly are silently skipped — defaults bypass the parser.
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

CULVER_CITY_06_001087 = Landmark(
    oas="06-001087",
    name="Culver City tower (Baldwin Hills)",
    lat_deg=34.015863,
    lon_deg=-118.383156,
    height_amsl_m=649.0 * 0.3048,  # 649 ft AMSL → 197.79 m
    lit=False,                      # unlit per FAA record
    accuracy_class="1E",
    obstacle_type="TOWER",
    city="Culver City",
)

DEFAULT_LANDMARKS: tuple[Landmark, ...] = (
    HYPERION_06_000301, CULVER_CITY_06_001087,
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
# the first two chars to be a 2-digit state code followed by a space.
_STATE_CODE_RE = re.compile(r"^\d{2} ")
# Inside each record, lat/lon blocks have a stable pattern we can
# regex-match regardless of minor column drift.
_LAT_RE = re.compile(r"\b(\d{2}) (\d{2}) (\d{2}\.\d{2}) ([NS])\b")
_LON_RE = re.compile(r"\b(\d{3}) (\d{2}) (\d{2}\.\d{2}) ([EW])\b")


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
    # Require at least 94 chars so lat/lon/AMSL/lighting are present.
    if len(line) < 94:
        return None
    try:
        state_code = line[0:2]
        obs_num = line[3:9].strip()
        oas = f"{state_code}-{obs_num}"
        city = line[18:34].strip()
        lat_m = _LAT_RE.search(line[35:48])
        lon_m = _LON_RE.search(line[49:63])
        if lat_m is None or lon_m is None:
            return None
        lat = _parse_dms(*lat_m.groups())
        lon = _parse_dms(*lon_m.groups())
        obstacle_type = line[64:74].strip()
        # AGL (cols 82-86) + AMSL (cols 88-92) are both right-aligned
        # 5-char integer fields. Be tolerant of drift: if the canonical
        # slices don't parse, fall back to scanning the 81:94 window
        # for the two largest integer tokens (AMSL is the last one).
        amsl_str = line[87:92].strip()
        if not amsl_str.isdigit():
            ints = [t for t in line[81:94].split() if t.isdigit()]
            if not ints:
                return None
            amsl_str = ints[-1]
        amsl_ft = float(amsl_str)
        lighting = line[93] if len(line) > 93 else " "
        accuracy = line[99:101].strip() if len(line) >= 101 else ""
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
            prefix = state + " "
            for line in wrapped:
                if not line.startswith(prefix):
                    continue
                lm = parse_dof_line(line.rstrip("\n"))
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
