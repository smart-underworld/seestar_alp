import time
import argparse
from .geometry import load_frame_format
from .pointing import read_pointing
from .fits_io import write_solve_fits, write_raw_frame
from .render import render_field
from . import catalog as _cat


def render_once(shared_dir, fmt, cat):
    p = read_pointing(shared_dir)
    if p is None:
        return None
    img = render_field(cat, p.ra_hours * 15.0, p.dec_deg, fmt)
    write_raw_frame(shared_dir, img)
    return write_solve_fits(
        shared_dir,
        img,
        header={"BAYERPAT": "GRBG", "RA": p.ra_hours * 15.0, "DEC": p.dec_deg},
    )


def main(shared_dir, model, catalog_path, poll=0.25, format_json="frame_format.json"):
    fmt = load_frame_format(format_json, model)
    cat = _cat.load(catalog_path)
    last = None
    print(f"[renderd] model={model} fmt={fmt} watching {shared_dir}")
    while True:
        p = read_pointing(shared_dir)
        if p and p.seq != last:
            print(
                f"[renderd] pointing.seq={p.seq} -> frame.seq={render_once(shared_dir, fmt, cat)}"
            )
            last = p.seq
        time.sleep(poll)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shared", default="sim/shared")
    ap.add_argument("--model", default="S50")
    ap.add_argument("--catalog", default="sim/data/stars.npy")
    a = ap.parse_args()
    main(a.shared, a.model, a.catalog)
