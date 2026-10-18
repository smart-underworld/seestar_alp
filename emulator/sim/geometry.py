import json
from dataclasses import dataclass, replace

SENSOR = {
    "S50": (1920, 1080),
    "S50V2": (1920, 1080),
    "S30": (1920, 1080),
    "S50P": (3856, 2180),
    "S30P": (3856, 2180),
}
# Plate scale (arcsec/px) and focal length per model.
# S50: fov 1.265x0.711 deg at 1920x1080 -> 2.37"/px, from real solve traces.
# S50P: derived, not measured.  The 9.75 aarch64 firmware reports focal_len=260
# mm for the S50 Pro and its IMX585 has 2.9 um pixels, so 2.9e-3/260 rad =
# 2.30"/px at the full 3856x2180 readout -- which is also what the firmware
# itself expects when it builds solve-field's scale bounds (-L 2.22 -H 2.71).
# (An earlier 1.18"/px assumed the same field of view at twice the pixel count;
# the solver can't match a frame at that scale against those bounds.)
# S30P is left at the old guess: its optics are unknown here.
_SCALE = {"S50": 2.37, "S50V2": 2.37, "S30": 2.37, "S50P": 2.30, "S30P": 1.18}
_FOCAL = {"S50": 252.0, "S50V2": 252.0, "S30": 252.0, "S50P": 260.0, "S30P": 252.0}


# Upper bound on stars drawn per frame (0 = unlimited).  The solver only uses the
# ~100 brightest objects anyway, but on a dense field (e.g. Cygnus, which the
# polar-align routine slews to) the extra faint ones multiply the quads it tries.
# Measured under x86-hosted QEMU on that field: uncapped ~250 stars never solved
# in 112 s; 80 stars solved in 38 s (30 stars is too few to match at all).  Only
# the models that have to run the aarch64 image are capped; the 32-bit S50 lanes
# are unchanged.
_MAX_STARS = {"S50P": 80, "S30P": 80}


@dataclass(frozen=True)
class FrameFormat:
    width: int
    height: int
    stride_bytes: int
    plate_scale_arcsec: float
    focal_len_mm: float
    dtype: str = "<u2"
    offset_bytes: int = 0
    max_stars: int = 0


def frame_format(model: str) -> FrameFormat:
    w, h = SENSOR[model]
    return FrameFormat(
        width=w,
        height=h,
        stride_bytes=w * 2,
        plate_scale_arcsec=_SCALE[model],
        focal_len_mm=_FOCAL[model],
        max_stars=_MAX_STARS.get(model, 0),
    )


def frame_nbytes(fmt: FrameFormat) -> int:
    return fmt.stride_bytes * fmt.height + fmt.offset_bytes


def load_frame_format(path, model: str) -> FrameFormat:
    fmt = frame_format(model)
    if path:
        try:
            with open(path) as f:
                data = json.load(f)
        except (FileNotFoundError, ValueError):
            return fmt
        over = data.get(model, data)  # per-model-keyed, else flat
        fmt = replace(
            fmt,
            **{k: v for k, v in over.items() if k in FrameFormat.__dataclass_fields__},
        )
        # Fix 1: if overlay changed width but not stride_bytes, recompute stride
        if "width" in over and "stride_bytes" not in over:
            fmt = replace(fmt, stride_bytes=fmt.width * 2)
    return fmt
