import os
import numpy as np
from astropy.io import fits


def _next_seq(shared_dir, name):
    p = os.path.join(shared_dir, name)
    try:
        with open(p) as f:
            return int(f.read().strip()) + 1
    except (FileNotFoundError, ValueError):
        return 1


def _write_seq(shared_dir, name, seq):
    tmp = os.path.join(shared_dir, name + ".tmp")
    with open(tmp, "w") as f:
        f.write(str(seq))
    os.replace(tmp, os.path.join(shared_dir, name))


def write_solve_fits(shared_dir, image, *, header=None):
    os.makedirs(shared_dir, exist_ok=True)
    if image.dtype != np.uint16:
        image = np.clip(image, 0, 0xFFFF).astype(np.uint16)
    hdu = fits.PrimaryHDU(
        data=image
    )  # astropy encodes uint16 as BITPIX=16 + BZERO=32768
    if header:
        for k, v in header.items():
            hdu.header[k] = v
    tmp = os.path.join(shared_dir, "solve.fits.tmp")
    hdu.writeto(tmp, overwrite=True)
    os.replace(tmp, os.path.join(shared_dir, "solve.fits"))
    seq = _next_seq(shared_dir, "solve.seq")
    _write_seq(shared_dir, "solve.seq", seq)
    return seq


def write_raw_frame(shared_dir, image):
    """Write image's native-endian uint16 bytes (no FITS wrapper) to
    live.raw, for the port-4800 live-stream write() interposer in
    stub_hwid.c. Unlike write_solve_fits, this does NOT go through astropy,
    so it stays native-endian (little-endian on the sim host and on the
    real ARM firmware) rather than the big-endian on-disk FITS convention --
    matching the wire format the real camera buffer uses.
    """
    os.makedirs(shared_dir, exist_ok=True)
    if image.dtype != np.uint16:
        image = np.clip(image, 0, 0xFFFF).astype(np.uint16)
    tmp = os.path.join(shared_dir, "live.raw.tmp")
    with open(tmp, "wb") as f:
        f.write(np.ascontiguousarray(image).tobytes())
    os.replace(tmp, os.path.join(shared_dir, "live.raw"))
    seq = _next_seq(shared_dir, "live.seq")
    _write_seq(shared_dir, "live.seq", seq)
    return seq
