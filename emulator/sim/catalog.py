"""Star catalog loader and cone-search filter.

Catalog format: float32 ndarray, shape (N, 3), columns [ra_deg, dec_deg, mag].
"""

import numpy as np


def load(path="sim/data/stars.npy"):
    return np.load(path)


def near(cat, ra_deg, dec_deg, radius_deg):
    """Return rows of `cat` within `radius_deg` of (ra_deg, dec_deg) using the
    great-circle (haversine-style) angular separation via the spherical law
    of cosines.
    """
    ra = np.radians(cat[:, 0])
    dec = np.radians(cat[:, 1])
    ra0 = np.radians(ra_deg)
    dec0 = np.radians(dec_deg)
    cosd = np.sin(dec) * np.sin(dec0) + np.cos(dec) * np.cos(dec0) * np.cos(ra - ra0)
    return cat[np.degrees(np.arccos(np.clip(cosd, -1, 1))) <= radius_deg]
