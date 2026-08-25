import numpy as np
from .geometry import FrameFormat


def make_probe(fmt: FrameFormat, n=30, bg=1000) -> np.ndarray:
    # fmt for the solve FITS is portrait: width=1080, height=1920
    img = np.full((fmt.height, fmt.width), bg, dtype=np.float64)
    rng = np.random.default_rng(1)
    ys = rng.integers(20, fmt.height - 20, n)
    xs = rng.integers(20, fmt.width - 20, n)
    yy, xx = np.mgrid[-3:4, -3:4]
    psf = np.exp(-(xx**2 + yy**2) / 2.0)
    for y, x in zip(ys, xs):
        img[y - 3 : y + 4, x - 3 : x + 4] += 40000 * psf
    return np.clip(img, 0, 0xFFFF).astype(np.uint16)
