import numpy as np
from . import catalog as _cat
from .projection import project


def render_field(
    cat, ra0_deg, dec0_deg, fmt, mag_zero=12.0, fwhm_px=2.5, bg=1000, noise=True
):
    radius = 1.2 * (max(fmt.width, fmt.height) * fmt.plate_scale_arcsec / 3600.0)
    near = _cat.near(cat, ra0_deg, dec0_deg, radius)
    xs, ys, mags = project(near, ra0_deg, dec0_deg, fmt)
    img = np.full((fmt.height, fmt.width), float(bg))
    sigma = fwhm_px / 2.3548
    half = int(np.ceil(3 * sigma))
    for x, y, m in zip(xs, ys, mags):
        peak = min((0xFFFF - bg) * (10 ** (-0.4 * (m - mag_zero))), 0xFFFF - bg)
        xi, yi = int(round(x)), int(round(y))
        x0, x1 = max(0, xi - half), min(fmt.width, xi + half + 1)
        y0, y1 = max(0, yi - half), min(fmt.height, yi + half + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        gx = np.arange(x0, x1) - x
        gy = (np.arange(y0, y1) - y)[:, None]
        img[y0:y1, x0:x1] += peak * np.exp(-(gx**2 + gy**2) / (2 * sigma**2))
    if noise:
        rng = np.random.default_rng(7)
        img += rng.normal(0, np.sqrt(np.maximum(img, 1)) * 0.5)
    return np.clip(img, 0, 0xFFFF).astype(np.uint16)
