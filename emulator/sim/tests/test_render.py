import numpy as np
from sim.geometry import load_frame_format, frame_nbytes
from sim.render import render_field
from sim.pointing import from_radec, write_pointing
from sim import renderd


def test_bright_star_blob_at_center():
    fmt = load_frame_format("frame_format.json", "S50")
    cat = np.array([[100.0, 20.0, 4.0]], dtype=np.float32)
    img = render_field(cat, 100.0, 20.0, fmt, bg=1000, noise=False)
    assert img.dtype == np.uint16
    assert img[fmt.height // 2, fmt.width // 2] > 0x4000
    assert img[0, 0] <= 1100


def test_empty_field_is_background():
    fmt = load_frame_format("frame_format.json", "S50")
    cat = np.array([[200.0, -40.0, 4.0]], dtype=np.float32)
    img = render_field(cat, 100.0, 20.0, fmt, bg=1000, noise=False)
    assert int(img.max()) <= 1100


def test_render_once_writes_fits(tmp_path):
    import numpy as np
    from sim.geometry import load_frame_format

    fmt = load_frame_format("frame_format.json", "S50")
    cat = np.array([[100.0, 20.0, 4.0]], dtype=np.float32)
    write_pointing(str(tmp_path), from_radec(100.0 / 15.0, 20.0))
    seq = renderd.render_once(str(tmp_path), fmt, cat)
    assert seq is not None and (tmp_path / "solve.fits").exists()


def test_render_once_writes_live_raw(tmp_path):
    fmt = load_frame_format("frame_format.json", "S50")
    cat = np.array([[100.0, 20.0, 4.0]], dtype=np.float32)
    write_pointing(str(tmp_path), from_radec(100.0 / 15.0, 20.0))
    renderd.render_once(str(tmp_path), fmt, cat)
    raw_path = tmp_path / "live.raw"
    assert raw_path.exists()
    assert raw_path.stat().st_size == frame_nbytes(fmt)
