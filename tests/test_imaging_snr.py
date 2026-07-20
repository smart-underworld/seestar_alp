import warnings

import numpy as np

from imaging.snr import calculate_snr_auto


def test_calculate_snr_auto_flat_frame_does_not_warn_and_has_no_nan():
    # A fully flat/blank frame (e.g. a placeholder buffer before real camera
    # data arrives) has max == min per channel, making the normalization a
    # 0/0 indeterminate form. It must not leak a RuntimeWarning or return NaN.
    flat = np.zeros((240, 240, 3), dtype=np.float32)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = calculate_snr_auto(flat)

    assert not np.isnan(result)
