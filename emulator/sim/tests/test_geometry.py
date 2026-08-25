import json
from sim.geometry import SENSOR, frame_format, frame_nbytes, load_frame_format


def test_s50_is_1920x1080():
    assert SENSOR["S50"] == (1920, 1080)
    assert SENSOR["S50P"] == (3856, 2180)


def test_frame_format_defaults():
    fmt = frame_format("S50")
    assert (fmt.width, fmt.height) == (1920, 1080)
    assert fmt.dtype == "<u2"
    assert fmt.stride_bytes == 1920 * 2
    assert frame_nbytes(fmt) == 1920 * 2 * 1080  # 4,147,200


def test_frame_format_plate_scale_matches_real_solve():
    # Real solve fov 1.265deg x 0.711deg at 1920x1080 -> ~2.37 arcsec/px
    fmt = frame_format("S50")
    assert abs(fmt.plate_scale_arcsec - 2.37) < 0.1


def test_per_model_keyed_overlay_recomputes_stride(tmp_path):
    """Test Fix 1: overlay width without stride_bytes must recompute stride."""
    cfg_file = tmp_path / "frame_format.json"
    cfg_file.write_text(json.dumps({"S50": {"width": 3856, "height": 2180}}))
    fmt = load_frame_format(str(cfg_file), "S50")
    assert fmt.width == 3856
    assert fmt.height == 2180
    assert fmt.stride_bytes == 3856 * 2, (
        "stride_bytes must be recomputed from overlaid width"
    )


def test_explicit_stride_bytes_wins(tmp_path):
    """Test Fix 1: explicit stride_bytes in overlay takes precedence."""
    cfg_file = tmp_path / "frame_format.json"
    cfg_file.write_text(json.dumps({"S50": {"width": 3856, "stride_bytes": 8000}}))
    fmt = load_frame_format(str(cfg_file), "S50")
    assert fmt.width == 3856
    assert fmt.stride_bytes == 8000, "explicit stride_bytes must not be overridden"


def test_flat_overlay_recomputes_stride(tmp_path):
    """Test Fix 1: flat (non-keyed) overlay with width must recompute stride."""
    cfg_file = tmp_path / "frame_format.json"
    cfg_file.write_text(json.dumps({"width": 3856}))
    fmt = load_frame_format(str(cfg_file), "S50")
    assert fmt.width == 3856
    assert fmt.stride_bytes == 3856 * 2, (
        "stride_bytes must be recomputed from flat overlay width"
    )


def test_missing_file_returns_defaults(tmp_path):
    """Test that missing config file returns default frame format."""
    nonexistent = tmp_path / "nonexistent.json"
    fmt = load_frame_format(str(nonexistent), "S50")
    assert fmt.width == 1920
    assert fmt.height == 1080
    assert fmt.stride_bytes == 1920 * 2


def test_malformed_json_returns_defaults(tmp_path):
    """Test Fix 2: malformed JSON falls back to defaults instead of crashing."""
    cfg_file = tmp_path / "bad.json"
    cfg_file.write_text("not json{")
    fmt = load_frame_format(str(cfg_file), "S50")
    assert fmt.width == 1920
    assert fmt.height == 1080
    assert fmt.stride_bytes == 1920 * 2
