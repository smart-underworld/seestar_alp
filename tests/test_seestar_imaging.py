import numpy as np

from device import seestar_imaging


class DummyLogger:
    def __init__(self):
        self.records = []

    def info(self, msg):
        self.records.append(("info", msg))

    def debug(self, msg):
        self.records.append(("debug", msg))

    def error(self, msg):
        self.records.append(("error", msg))


class DummyDevice:
    def __init__(self):
        self.view_state = {"state": "working", "stage": "RTSP"}
        self.ra = 10.123
        self.dec = 20.456


class FakeComm:
    def __init__(self, **_kwargs):
        self._connected = True
        self.exposure_mode = None
        self.set_modes = []
        self.sent = []
        self._streaming = False

    def start(self):
        return None

    def is_connected(self):
        return self._connected

    def send_message(self, msg):
        self.sent.append(msg)
        return True

    def set_exposure_mode(self, mode):
        self.exposure_mode = mode
        self.set_modes.append(mode)

    def get_image(self):
        return np.ones((2, 2, 3), dtype=np.uint8), 2, 2

    def get_unprocessed_image(self):
        return np.ones((2, 2, 3), dtype=np.uint8), 2, 2

    def is_streaming(self):
        return self._streaming

    def received_frame(self):
        return 1


def make_imager(monkeypatch):
    monkeypatch.setattr(seestar_imaging, "SeestarImagerProtocol", FakeComm)
    return seestar_imaging.SeestarImaging(
        logger=DummyLogger(),
        host="127.0.0.1",
        port=9999,
        device_name="scope",
        device_num=1,
        device=DummyDevice(),
    )


def test_table_renders_rows():
    html = seestar_imaging.table([["A", "1"], ["B", "2"]])
    assert 'class="row"' in html
    assert "A" in html and "B" in html


def test_compare_set_exposure_mode_paths(monkeypatch):
    imager = make_imager(monkeypatch)

    imager.device.view_state = {"state": "idle", "stage": "RTSP"}
    assert imager.compare_set_exposure_mode() is None

    imager.device.view_state = {"state": "working", "stage": "RTSP"}
    assert imager.compare_set_exposure_mode() == "stream"

    imager.device.view_state = {"state": "working", "stage": "ContinuousExposure"}
    assert imager.compare_set_exposure_mode() == "preview"

    imager.device.view_state = {"state": "working", "stage": "Stack"}
    assert imager.compare_set_exposure_mode() == "stack"


def test_event_handler_stack_requests_stacked_image(monkeypatch):
    imager = make_imager(monkeypatch)
    imager.is_live_viewing = True
    imager.last_stacking_frame = None

    called = {"stack": 0}
    monkeypatch.setattr(
        imager,
        "request_stacked_image",
        lambda: called.__setitem__("stack", called["stack"] + 1),
    )

    imager.event_handler({"Event": "Stack", "stacked_frame": 1, "dropped_frame": 1})
    assert called["stack"] == 1
    assert imager.last_stacking_frame == 2

    imager.event_handler({"Event": "Unknown", "stacked_frame": 5, "dropped_frame": 0})
    assert called["stack"] == 1


def test_request_stacked_image_emits_protocol_message(monkeypatch):
    imager = make_imager(monkeypatch)

    imager.request_stacked_image()

    assert imager.comm.sent == ['{"id": 23, "method": "get_stacked_img"}\r\n']


def test_blank_frame_and_build_frame_bytes(monkeypatch):
    imager = make_imager(monkeypatch)

    # Force fallback image path for blank frame
    monkeypatch.setattr(
        seestar_imaging,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
        raising=False,
    )
    monkeypatch.setattr(
        seestar_imaging.cv2, "putText", lambda image, *_args, **_kwargs: image
    )

    class Encoded:
        def tobytes(self):
            return b"jpeg"

    monkeypatch.setattr(
        seestar_imaging.cv2, "imencode", lambda *_args, **_kwargs: (True, Encoded())
    )

    frame = imager.blank_frame("Loading", timestamp=True)
    assert frame.startswith(b"Content-Type: image/jpeg")

    img = np.ones((2, 2, 3), dtype=np.uint8)
    frame2 = imager.build_frame_bytes(img, 2, 2)
    assert frame2.startswith(b"Content-Type: image/jpeg")


def test_get_frame_yields_initial_and_idle_frames(monkeypatch):
    imager = make_imager(monkeypatch)

    monkeypatch.setattr(imager, "build_frame_bytes", lambda *_args, **_kwargs: b"FRAME")
    monkeypatch.setattr(
        imager,
        "blank_frame",
        lambda message="", timestamp=False: f"BLANK:{message}:{timestamp}".encode(),
    )

    imager.device.view_state = {"state": "idle", "stage": "RTSP"}

    frames = list(imager.get_frame())

    assert frames[0] == b"\r\n--frame\r\n"
    assert frames[1] == b"FRAME"
    assert frames[2] == b"FRAME"
    assert frames[-1] == b"BLANK:Idle:False"


def test_get_live_and_video_status_generators(monkeypatch):
    imager = make_imager(monkeypatch)

    monkeypatch.setattr(seestar_imaging, "sleep", lambda _s: None)

    live = imager.get_live_status()
    live_frame = next(live)
    assert live_frame.startswith(b"data: ")

    video = imager.get_video_status()
    video_frame = next(video)
    assert video_frame.startswith(b"data: Frame:")
