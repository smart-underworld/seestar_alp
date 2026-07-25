"""Generate `sim/data/stars.npy`, the star catalog used by the plate-solve
renderer's cone filter (see `sim/catalog.py`).

Catalog format: float32 ndarray, shape (N, 3), columns [ra_deg, dec_deg, mag].

--------------------------------------------------------------------------
Source of real stars (production catalog, sim/data/stars.npy)
--------------------------------------------------------------------------
Positions come straight from the on-device astrometry.net star index that
solve-field actually searches against, so any field rendered from this
catalog is guaranteed star-position-matchable by the real solver.

`sim/data/stars.npy` is a large (~23MB) derived artifact and is gitignored.
Regenerate it on a fresh checkout with the committed `sim/build_catalog.py`,
which reads the staged index (`index-4107-Vt.fits`, ~1.9M full-sky stars)
directly via libastrometry's startree API. It must run in the container
(ARM libastrometry); see `build_catalog.py`'s module docstring for the exact
`docker run` command. Magnitudes are a deterministic placeholder spread (the
index stores positions only; solving depends on position, not brightness).

`build()` below is a separate CSV-based path used by the unit tests and for
building a catalog from any external RA/Dec/mag source.

--------------------------------------------------------------------------
build() below is the small CSV-based builder used by the unit test
(`sim/tests/test_catalog.py`) -- it is generic and not tied to the
astrometry-index source above.
--------------------------------------------------------------------------
"""

import csv
import numpy as np


def build(src_csv, out_npy, mag_limit=11.0):
    rows = []
    with open(src_csv) as f:
        for r in csv.DictReader(f):
            m = float(r["mag"])
            if m <= mag_limit:
                rows.append((float(r["ra_deg"]), float(r["dec_deg"]), m))
    arr = np.array(sorted(rows, key=lambda x: x[2]), dtype=np.float32)
    np.save(out_npy, arr)
    return len(arr)


def build_from_radec(ra_npy, dec_npy, out_npy, seed=0):
    """Assemble stars.npy from real RA/Dec arrays (degrees, float64) plus a
    deterministic placeholder magnitude spread (real magnitudes are not
    available from the astrometry-index startree source; see module
    docstring). Keeps every star -- no downsampling.
    """
    ra = np.load(ra_npy)
    dec = np.load(dec_npy)
    assert ra.shape == dec.shape
    rng = np.random.default_rng(seed)
    mag = 8.0 + 4.0 * rng.random(ra.shape[0])
    arr = np.column_stack([ra, dec, mag]).astype(np.float32)
    np.save(out_npy, arr)
    return len(arr)


if __name__ == "__main__":
    import sys

    print(
        build(
            sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 11.0
        )
    )
