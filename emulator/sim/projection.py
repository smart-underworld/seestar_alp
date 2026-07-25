import numpy as np


def project(cat_near, ra0_deg, dec0_deg, fmt, roll_deg=0.0):
    ra = np.radians(cat_near[:, 0])
    dec = np.radians(cat_near[:, 1])
    ra0 = np.radians(ra0_deg)
    dec0 = np.radians(dec0_deg)
    cosc = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = (np.cos(dec) * np.sin(ra - ra0)) / cosc
    eta = (
        np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)
    ) / cosc
    scale = np.radians(fmt.plate_scale_arcsec / 3600.0)
    dx = xi / scale
    dy = eta / scale
    r = np.radians(roll_deg)
    xr = dx * np.cos(r) - dy * np.sin(r)
    yr = dx * np.sin(r) + dy * np.cos(r)
    xs = fmt.width / 2 + xr
    ys = fmt.height / 2 - yr
    inside = (cosc > 0) & (xs >= 0) & (xs < fmt.width) & (ys >= 0) & (ys < fmt.height)
    return xs[inside], ys[inside], cat_near[:, 2][inside]
