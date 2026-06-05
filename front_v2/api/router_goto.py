import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException

from front_v2.device_client import check_api_state, do_action
from front_v2.schemas.models import GotoRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

_REPO_ROOT = Path(__file__).parent.parent.parent
_ALP_DAT = _REPO_ROOT / "data" / "alp.dat"


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
        # Column names changed across astroquery versions
        main_id = str(row.get("MAIN_ID", row.get("main_id", query)))
        ra = str(row.get("RA", row.get("ra", "")))
        dec = str(row.get("DEC", row.get("dec", "")))
        if not ra:
            return None
        return {"ra": ra, "dec": dec, "name": main_id}
    except Exception as exc:
        logger.warning("Simbad search failed for %r: %s", query, exc)
    return None


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
def search_object(dev_num: int, q: str):
    result = _search_local(q) or _search_simbad(q)
    return {"query": q, "result": result}
