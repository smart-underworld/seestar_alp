import logging
import sqlite3
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from front_v2.device_client import check_api_state, do_action
from front_v2.schemas.models import GotoRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

_REPO_ROOT = Path(__file__).parent.parent.parent
_ALP_DAT = _REPO_ROOT / "data" / "alp.dat"
_DATA_DIR = _REPO_ROOT / "data"


# ── helpers ──────────────────────────────────────────────────────────────────


def _sky_loader():
    """Return a skyfield Loader pointed at the repo data directory."""
    from skyfield.api import Loader  # type: ignore

    return Loader(str(_DATA_DIR))


def _fmt_ra(ra_obj) -> str:
    return str(ra_obj).replace(" ", "")


def _fmt_dec(dec_obj) -> str:
    return (
        str(dec_obj)
        .replace(" ", "")
        .replace("deg", "d")
        .replace("'", "m")
        .replace('"', "s")
    )


# ── catalog search functions ─────────────────────────────────────────────────


def _search_local(query: str) -> dict | None:
    """Search the local object catalogue. Returns first match as {ra, dec, objectName} or None."""
    if not _ALP_DAT.exists():
        return None
    try:
        con = sqlite3.connect(str(_ALP_DAT))
        cur = con.cursor()
        q = f"%{query}%"
        cur.execute(
            "SELECT ra, dec, commonNames, identifiers FROM objects "
            "WHERE identifiers LIKE ? OR commonNames LIKE ? COLLATE NOCASE LIMIT 1",
            (q, q),
        )
        row = cur.fetchone()
        con.close()
        if row:
            name = row[2] or row[3] or query
            if isinstance(name, str) and "," in name:
                name = name.split(",")[0].strip()
            return {"ra": row[0], "dec": row[1], "objectName": name}
    except Exception as exc:
        logger.warning("local object search failed: %s", exc)
    return None


def _search_simbad(query: str) -> dict | None:
    """Query Simbad SESAME service. Returns {ra, dec, name} or None."""
    try:
        from astroquery.simbad import Simbad  # type: ignore

        table = Simbad.query_object(query)
        if table is None or len(table) == 0:
            return None
        row = table[0]
        main_id = str(row.get("MAIN_ID", row.get("main_id", query)))
        ra = str(row.get("RA", row.get("ra", "")))
        dec = str(row.get("DEC", row.get("dec", "")))
        if not ra:
            return None
        return {"ra": ra, "dec": dec, "name": main_id}
    except Exception as exc:
        logger.warning("Simbad search failed for %r: %s", query, exc)
    return None


def _search_planet(name: str) -> dict | None:
    """Look up a planet/moon using skyfield ephemeris (JNow coords)."""
    try:
        load = _sky_loader()
        eph = load("de440s.bsp")
        earth = eph["earth"]
        body = name.strip()
        if body.lower() != "moon":
            body = body + " BARYCENTER"
        planet = eph[body]
        ts = load.timescale()
        t = ts.now()
        astrometric = earth.at(t).observe(planet)
        ra_obj, dec_obj, _ = astrometric.radec("date")
        return {"ra": _fmt_ra(ra_obj), "dec": _fmt_dec(dec_obj), "name": name.title()}
    except Exception as exc:
        logger.warning("Planet search failed for %r: %s", name, exc)
    return None


def _search_comet(name: str) -> dict | None:
    """Look up a comet using the MPC comet database (downloads if needed)."""
    try:
        import re as _re
        from skyfield.data import mpc  # type: ignore

        load = _sky_loader()
        comet_file = _DATA_DIR / "CometEls.txt"
        stale = not comet_file.exists() or (
            comet_file.stat().st_mtime < (__import__("time").time() - 7 * 86400)
        )
        with load.open(mpc.COMET_URL, reload=stale) as f:
            comets = mpc.load_comets_dataframe(f)

        comets = (
            comets.sort_values("reference")
            .groupby("designation", as_index=False)
            .last()
            .set_index("designation", drop=False)
        )

        pat = _re.compile(_re.escape(name), _re.IGNORECASE)
        rows = comets[comets["designation"].str.contains(pat)]
        if rows.empty:
            return None

        from skyfield.constants import GM_SUN  # type: ignore

        eph = load("de440s.bsp")
        sun, earth = eph["sun"], eph["earth"]
        ts = load.timescale()
        t = ts.now()
        comet_obj = sun + mpc.comet_orbit(rows.iloc[0], ts, GM_SUN)
        ra_obj, dec_obj, _ = earth.at(t).observe(comet_obj).radec()
        return {
            "ra": _fmt_ra(ra_obj),
            "dec": _fmt_dec(dec_obj),
            "name": str(rows.iloc[0]["designation"]),
        }
    except Exception as exc:
        logger.warning("Comet search failed for %r: %s", name, exc)
    return None


def _search_asteroid(name: str) -> dict | None:
    """Look up a minor planet / asteroid using the MPC orbit database."""
    try:
        import re as _re
        from skyfield.data import mpc  # type: ignore
        from skyfield.constants import GM_SUN  # type: ignore

        load = _sky_loader()
        local_mpn = _DATA_DIR / "mpn-01.txt"
        source = (
            str(local_mpn)
            if local_mpn.exists()
            else "http://dss.stellarium.org/MPC/mpn-01.txt"
        )
        with load.open(source) as f:
            minor_planets = mpc.load_mpcorb_dataframe(f)

        minor_planets = minor_planets[minor_planets.semimajor_axis_au.notnull()]
        pat = _re.compile(r"\b{}\b".format(_re.escape(name)), _re.IGNORECASE)
        rows = minor_planets[minor_planets["designation"].str.contains(pat)]
        if rows.empty:
            return None

        eph = load("de440s.bsp")
        sun, earth = eph["sun"], eph["earth"]
        ts = load.timescale()
        t = ts.now()
        obj = sun + mpc.mpcorb_orbit(rows.iloc[0], ts, GM_SUN)
        ra_obj, dec_obj, _ = earth.at(t).observe(obj).radec()
        return {
            "ra": _fmt_ra(ra_obj),
            "dec": _fmt_dec(dec_obj),
            "name": str(rows.iloc[0]["designation"]),
        }
    except Exception as exc:
        logger.warning("Asteroid search failed for %r: %s", name, exc)
    return None


def _search_variable_star(name: str) -> dict | None:
    """Look up a variable star via the AAVSO VSX API."""
    try:
        resp = httpx.get(
            "https://www.aavso.org/vsx/index.php",
            params={"view": "api.object", "format": "json", "ident": name},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        obj = data.get("VSXObject", {})
        if not obj:
            return None
        ra_deg = float(obj["RA2000"])
        dec_deg = float(obj["Declination2000"])

        def _ra_to_hms(deg: float) -> str:
            h = deg / 15.0 % 24
            hh = int(h)
            mm = int((h - hh) * 60)
            ss = (h - hh - mm / 60) * 3600
            return f"{hh}h{mm:02d}m{abs(ss):.2f}s"

        def _dec_to_dms(deg: float) -> str:
            sign = "+" if deg >= 0 else "-"
            d = abs(deg)
            dd = int(d)
            mm = int((d - dd) * 60)
            ss = (d - dd - mm / 60) * 3600
            return f"{sign}{dd}d{mm:02d}m{ss:.2f}s"

        return {
            "ra": _ra_to_hms(ra_deg),
            "dec": _dec_to_dms(dec_deg),
            "name": str(obj.get("Name", name)),
        }
    except Exception as exc:
        logger.warning("Variable star search failed for %r: %s", name, exc)
    return None


# ── routes ────────────────────────────────────────────────────────────────────


@router.post("/devices/{dev_num}/goto")
def goto_target(dev_num: int, body: GotoRequest):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")

    params = {
        "ra": body.ra,
        "dec": body.dec,
        "target_name": body.target_name,
        "is_j2000": body.is_j2000,
    }
    result = do_action("scope_goto", dev_num, params)
    if result is None:
        raise HTTPException(status_code=502, detail="Goto command failed")
    return result


@router.delete("/devices/{dev_num}/goto")
def cancel_goto(dev_num: int):
    if not check_api_state(dev_num):
        raise HTTPException(status_code=503, detail="Device not connected")
    result = do_action("stop_goto", dev_num, {})
    return result or {"status": "ok"}


@router.get("/devices/{dev_num}/search")
def search_object(dev_num: int, q: str, catalog: str = "auto"):
    """
    Search for an astronomical object and return RA/Dec coordinates.

    catalog values:
      auto     - local DB then Simbad fallback (default)
      local    - local alp.dat DB only
      simbad   - Simbad SESAME (online)
      planet   - solar system planet/moon via ephemeris
      asteroid - minor planet / asteroid via MPC
      comet    - comet via MPC
      variable - variable star via AAVSO VSX
    """
    dispatch = {
        "local": _search_local,
        "simbad": _search_simbad,
        "planet": _search_planet,
        "asteroid": _search_asteroid,
        "comet": _search_comet,
        "variable": _search_variable_star,
    }
    if catalog in dispatch:
        result = dispatch[catalog](q)
    else:  # auto
        result = _search_local(q) or _search_simbad(q)
    return {"query": q, "result": result}
