import warnings

import numpy as np

from imaging.stretch import stretch, StretchParameters


def test_stretch_flat_frame_does_not_warn_and_has_no_nan():
    # A fully blank/flat frame (e.g. a placeholder buffer before real camera
    # data arrives) has zero MAD, which drives the computed midtone to 0.
    # MTF(0, 0) is a 0/0 indeterminate form; it must not leak a RuntimeWarning
    # or produce NaNs in the output.
    flat = np.zeros((10, 10, 3), dtype=np.float32)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = stretch(flat, StretchParameters("15% Bg, 3 sigma"))

    assert not np.isnan(result).any()
