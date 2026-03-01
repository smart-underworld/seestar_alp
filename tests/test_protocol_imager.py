import io
import zipfile

import numpy as np

from device.protocols.imager import SeestarImagerProtocol


class DummyLogger:
    def __init__(self):
        self.records = []

    def info(self, msg):
        self.records.append(("info", msg))

    def debug(self, msg):
        self.records.append(("debug", msg))

    def error(self, msg):
        self.records.append(("error", msg))


class AddOneProcessor:
    def process(self, image):
        return image + 1


def make_protocol(monkeypatch):
    proto = SeestarImagerProtocol(DummyLogger(), "scope", 1, "127.0.0.1", 1234)
    monkeypatch.setattr(proto, "send_message", lambda _msg: True)
    return proto


def test_imaging_listener_on_connect_only_previews_when_requested(monkeypatch):
    proto = make_protocol(monkeypatch)

    called = {"preview": 0}
    monkeypatch.setattr(
        proto,
        "start_preview",
        lambda: called.__setitem__("preview", called["preview"] + 1),
    )

    proto.exposure_mode = "stream"
    proto.imaging_listener.on_connect()
    assert called["preview"] == 0

    proto.exposure_mode = "preview"
    proto.imaging_listener.on_connect()
    assert called["preview"] == 1


def test_set_exposure_mode_switches_preview_state(monkeypatch):
    proto = make_protocol(monkeypatch)

    called = {"start": 0, "stop": 0}
    monkeypatch.setattr(
        proto, "start_preview", lambda: called.__setitem__("start", called["start"] + 1)
    )
    monkeypatch.setattr(
        proto, "stop_preview", lambda: called.__setitem__("stop", called["stop"] + 1)
    )

    proto.set_exposure_mode("preview")
    proto.set_exposure_mode("preview")
    proto.set_exposure_mode("stream")

    assert called == {"start": 1, "stop": 1}


def test_get_image_applies_processors_only_when_not_streaming(monkeypatch):
    proto = make_protocol(monkeypatch)
    proto.latest_image = np.array([[1]], dtype=np.uint8)
    proto.raw_img_size = [320, 240]
    proto.StarProcessors = [AddOneProcessor()]

    proto._is_started = True
    proto.exposure_mode = "stream"
    image, width, height = proto.get_image()
    assert int(image[0, 0]) == 1
    assert (width, height) == (320, 240)

    proto.exposure_mode = "preview"
    image2, _, _ = proto.get_image()
    assert int(image2[0, 0]) == 2


def test_run_receive_message_routes_preview_and_stack(monkeypatch):
    proto = make_protocol(monkeypatch)

    monkeypatch.setattr(proto, "is_connected", lambda: True)

    packets = [b"h" * 80, b"p" * 1200]
    monkeypatch.setattr(proto, "recv_exact", lambda _n: packets.pop(0))
    monkeypatch.setattr(proto, "parse_header", lambda _h: (1200, 21, 100, 200))

    preview_calls = []
    monkeypatch.setattr(
        proto,
        "handle_preview_frame",
        lambda w, h, d: preview_calls.append((w, h, len(d))),
    )

    proto._run_receive_message()

    assert preview_calls == [(100, 200, 1200)]
    assert proto.received_frame() == 1

    packets2 = [b"h" * 80, b"s" * 1200]
    monkeypatch.setattr(proto, "recv_exact", lambda _n: packets2.pop(0))
    monkeypatch.setattr(proto, "parse_header", lambda _h: (1200, 23, 111, 222))

    stack_calls = []
    monkeypatch.setattr(
        proto, "handle_stack", lambda w, h, d: stack_calls.append((w, h, len(d)))
    )

    proto._run_receive_message()

    assert stack_calls == [(111, 222, 1200)]
    assert proto.received_frame() == 2


def test_run_receive_message_ignores_small_or_unknown_payloads(monkeypatch):
    proto = make_protocol(monkeypatch)
    monkeypatch.setattr(proto, "is_connected", lambda: True)

    monkeypatch.setattr(proto, "recv_exact", lambda _n: b"x" * 80)
    monkeypatch.setattr(proto, "parse_header", lambda _h: (100, 21, 10, 10))
    proto._run_receive_message()
    assert proto.received_frame() == 0

    packets = [b"h" * 80, b"u" * 1200]
    monkeypatch.setattr(proto, "recv_exact", lambda _n: packets.pop(0))
    monkeypatch.setattr(proto, "parse_header", lambda _h: (1200, 99, 10, 10))
    proto._run_receive_message()
    assert proto.received_frame() == 0


def test_run_receive_message_when_disconnected_sleeps(monkeypatch):
    proto = make_protocol(monkeypatch)
    monkeypatch.setattr(proto, "is_connected", lambda: False)

    slept = {"count": 0}
    monkeypatch.setattr(
        "device.protocols.imager.sleep",
        lambda _s: slept.__setitem__("count", slept["count"] + 1),
    )

    proto._run_receive_message()

    assert slept["count"] == 1


def test_handle_preview_frame_sets_latest(monkeypatch):
    proto = make_protocol(monkeypatch)

    monkeypatch.setattr(proto, "convert_star_image", lambda raw, w, h: (raw, w, h))

    raw = b"abc"
    proto.handle_preview_frame(10, 20, raw)

    assert proto.raw_img == raw
    assert proto.raw_img_size == [10, 20]
    assert proto.latest_image == (raw, 10, 20)


def test_handle_stack_happy_path_and_failure(monkeypatch):
    proto = make_protocol(monkeypatch)

    # Happy path
    raw_bytes = b"\x01\x02\x03\x04"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("raw_data", raw_bytes)

    monkeypatch.setattr(proto, "convert_star_image", lambda raw, _w, _h: raw)
    proto.handle_stack(30, 40, buf.getvalue())
    assert proto.raw_img == raw_bytes
    assert proto.raw_img_size == [30, 40]

    # convert returns None => resets raw state
    monkeypatch.setattr(proto, "convert_star_image", lambda _raw, _w, _h: None)
    proto.handle_stack(31, 41, buf.getvalue())
    assert proto.raw_img is None
    assert proto.raw_img_size == [None, None]

    # Bad zip => exception path
    proto.handle_stack(32, 42, b"not-a-zip")
    assert proto.raw_img is None
    assert proto.raw_img_size == [None, None]


def test_convert_star_image_rgb_and_bayer_and_invalid(monkeypatch):
    proto = make_protocol(monkeypatch)

    monkeypatch.setattr("device.protocols.imager.cv2.cvtColor", lambda img, _code: img)

    rgb_raw = np.arange(2 * 2 * 3, dtype=np.uint16).tobytes()
    rgb = proto.convert_star_image(rgb_raw, 2, 2)
    assert rgb.shape == (2, 2, 3)

    bayer_raw = np.arange(2 * 2, dtype=np.uint16).tobytes()
    bayer = proto.convert_star_image(bayer_raw, 2, 2)
    assert bayer.shape == (2, 2)

    invalid = proto.convert_star_image(b"123", 2, 2)
    assert invalid is None
