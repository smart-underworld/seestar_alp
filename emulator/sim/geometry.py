import json
from dataclasses import dataclass, replace

SENSOR = {
    "S50": (1920, 1080),
    "S50V2": (1920, 1080),
    "S30": (1920, 1080),
    "S50P": (3856, 2180),
    "S30P": (3856, 2180),
}
# Plate scale (arcsec/px) and focal length per model, from real solve traces.
# S50: fov 1.265x0.711 deg at 1920x1080 -> 2.37"/px. S50P full-res -> 1.18"/px.
_SCALE = {"S50": 2.37, "S50V2": 2.37, "S30": 2.37, "S50P": 1.18, "S30P": 1.18}
_FOCAL = {"S50": 252.0, "S50V2": 252.0, "S30": 252.0, "S50P": 252.0, "S30P": 252.0}


@dataclass(frozen=True)
class FrameFormat:
    width: int
    height: int
    stride_bytes: int
    plate_scale_arcsec: float
    focal_len_mm: float
    dtype: str = "<u2"
    offset_bytes: int = 0


def frame_format(model: str) -> FrameFormat:
    w, h = SENSOR[model]
    return FrameFormat(
        width=w,
        height=h,
        stride_bytes=w * 2,
        plate_scale_arcsec=_SCALE[model],
        focal_len_mm=_FOCAL[model],
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
