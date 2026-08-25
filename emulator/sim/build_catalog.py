#!/usr/bin/env python3
"""Build the renderer's real-star catalog (sim/data/stars.npy) directly from a
public astrometry.net star-kdtree index, via libastrometry's own startree API
(ctypes). These are real Tycho-2 star positions from the same index series
solve-field searches against (see emulator/astrometry/download_index.sh),
so a field rendered from them is guaranteed to be solvable.

Runs where libastrometry.so.0 exists — i.e. INSIDE the emulator container
(armhf), not on a macOS host. libastrometry is installed via apt (the
`astrometry.net` package) when the image is built (see ../Dockerfile); the
public index files are downloaded separately by
emulator/astrometry/download_index.sh into emulator/astrometry/index/, so:

    # from emulator/, with the image built (Task 4) and the index downloaded (Task 3):
    docker run --rm --platform linux/arm/v7 \
      -v "$PWD/sim:/sim" \
      -v "$PWD/astrometry/index:/usr/local/astrometry/data:ro" \
      --entrypoint python3 seestar-emulator \
      /sim/build_catalog.py /usr/local/astrometry/data/index-4107.fits /sim/data/stars.npy

That writes sim/data/stars.npy on the host (via the bind mount). stars.npy is
git-ignored (~23MB derived); regenerate it with this command on a fresh checkout.

The index startree only stores positions, so magnitudes are a deterministic
placeholder spread (seeded) — solving depends on positions, not brightness (the
end-to-end solve was validated this way).
"""

import ctypes
import sys
from pathlib import Path

import numpy as np

DEFAULT_LIB = "/usr/lib/arm-linux-gnueabihf/libastrometry.so.0"


def read_index_radec(index_path, lib_path=DEFAULT_LIB):
    lib = ctypes.CDLL(lib_path)
    lib.startree_open.restype = ctypes.c_void_p
    lib.startree_open.argtypes = [ctypes.c_char_p]
    lib.startree_N.restype = ctypes.c_int
    lib.startree_N.argtypes = [ctypes.c_void_p]
    lib.startree_get_radec.restype = ctypes.c_int
    lib.startree_get_radec.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    s = lib.startree_open(index_path.encode())
    if not s:
        raise RuntimeError(f"startree_open failed for {index_path}")
    n = lib.startree_N(s)
    ra = np.empty(n, dtype=np.float64)
    dec = np.empty(n, dtype=np.float64)
    cra, cdec = ctypes.c_double(), ctypes.c_double()
    kept = 0
    for i in range(n):
        if lib.startree_get_radec(s, i, ctypes.byref(cra), ctypes.byref(cdec)) == 0:
            ra[kept], dec[kept] = cra.value, cdec.value
            kept += 1
    return ra[:kept], dec[:kept]


def build(index_path, out_npy, lib_path=DEFAULT_LIB):
    ra, dec = read_index_radec(index_path, lib_path)
    # Deterministic placeholder magnitudes (index has positions only).
    # RandomState (not default_rng) so this runs on the container's numpy 1.16.
    rng = np.random.RandomState(0)
    mag = 8.0 + 4.0 * rng.random_sample(len(ra))
    cat = np.column_stack([ra, dec, mag]).astype(np.float32)
    # sim/data/ is gitignored (derived artifact) and so doesn't exist on a
    # fresh checkout — np.save doesn't create parent directories itself.
    Path(out_npy).parent.mkdir(parents=True, exist_ok=True)
    np.save(out_npy, cat)
    print(f"wrote {out_npy}: {len(cat)} stars")
    return len(cat)


if __name__ == "__main__":
    idx = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "/usr/local/astrometry/data/index-4107-Vt.fits"
    )
    out = sys.argv[2] if len(sys.argv) > 2 else "sim/data/stars.npy"
    lib = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_LIB
    build(idx, out, lib)
