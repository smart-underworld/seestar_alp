import os
import json
import time
from dataclasses import dataclass, asdict


@dataclass
class Pointing:
    ra_hours: float
    dec_deg: float
    axle0: float
    axle1: float
    seq: int = 0
    ts: float = 0.0


def from_radec(ra_hours, dec_deg, seq=0):
    return Pointing(ra_hours, dec_deg, ra_hours * 15.0, dec_deg, seq, time.time())


def write_pointing(shared_dir, p):
    os.makedirs(shared_dir, exist_ok=True)
    cur = read_pointing(shared_dir)
    p.seq = (cur.seq + 1) if cur else 1
    p.ts = time.time()
    tmp = os.path.join(shared_dir, "pointing.json.tmp")
    with open(tmp, "w") as f:
        json.dump(asdict(p), f)
    os.replace(tmp, os.path.join(shared_dir, "pointing.json"))
    return p.seq


def read_pointing(shared_dir):
    try:
        with open(os.path.join(shared_dir, "pointing.json")) as f:
            return Pointing(**json.load(f))
    except (FileNotFoundError, ValueError):
        return None
