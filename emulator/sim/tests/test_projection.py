import numpy as np
from sim.geometry import load_frame_format
from sim.projection import project


def test_center_star_at_frame_center():
    fmt = load_frame_format("frame_format.json", "S50")  # portrait 1080x1920
    cat = np.array([[100.0, 20.0, 6.0]], dtype=np.float32)
    xs, ys, _ = project(cat, 100.0, 20.0, fmt)
    assert (
        len(xs) == 1
        and abs(xs[0] - fmt.width / 2) < 1
        and abs(ys[0] - fmt.height / 2) < 1
    )


def test_offset_shifts_by_platescale():
    fmt = load_frame_format("frame_format.json", "S50")
    dra = (100 * fmt.plate_scale_arcsec) / 3600.0
    cat = np.array([[100.0 + dra, 0.0, 6.0]], dtype=np.float32)
    xs, _, _ = project(cat, 100.0, 0.0, fmt)
    assert abs(abs(xs[0] - fmt.width / 2) - 100) < 3
