import threading

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
        self.StarProcessors = []
        self.on_stack_image = None

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


def _count_stack_requests(monkeypatch, imager):
    called = {"stack": 0}
    monkeypatch.setattr(
        imager,
        "request_stacked_image",
        lambda: called.__setitem__("stack", called["stack"] + 1),
    )
    return called


def test_stack_event_without_live_page_or_snapshot_reader_does_not_fetch(
    monkeypatch,
):
    imager = make_imager(monkeypatch)
    called = _count_stack_requests(monkeypatch, imager)

    imager.event_handler({"Event": "Stack", "stacked_frame": 3, "dropped_frame": 0})

    assert called["stack"] == 0
    assert imager.last_stacking_frame == 3


def _stack_event(imager, stacked, dropped=0):
    imager.event_handler(
        {"Event": "Stack", "stacked_frame": stacked, "dropped_frame": dropped}
    )


def _stack_reply(imager, value):
    """A stacked-image reply arriving on the imaging socket (receive thread)."""
    imager.comm.on_stack_image(np.full((2, 2, 3), value, dtype=np.uint16))


def _reader(monkeypatch):
    """An imager with a snapshot reader polling (replies are held for it)."""
    imager = make_imager(monkeypatch)
    imager.get_snapshot()
    return imager


def test_stack_replies_are_not_held_without_a_snapshot_reader(monkeypatch):
    # The web live page alone (is_live_viewing) must not make every user keep
    # an extra copy of the last stack in memory.
    imager = make_imager(monkeypatch)
    imager.is_live_viewing = True
    _count_stack_requests(monkeypatch, imager)
    _stack_event(imager, 5)
    _stack_reply(imager, 50)

    assert imager._stack_image is None


def test_snapshot_reader_keeps_stack_fetching_on_without_live_page(monkeypatch):
    imager = make_imager(monkeypatch)
    called = _count_stack_requests(monkeypatch, imager)
    imager.get_snapshot()

    _stack_event(imager, 3, 1)
    _stack_reply(imager, 100)

    assert called["stack"] == 1
    assert imager.get_snapshot().stack_frame == 4


def test_snapshot_interest_expires(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(seestar_imaging, "monotonic", lambda: clock["now"])
    imager = make_imager(monkeypatch)
    called = _count_stack_requests(monkeypatch, imager)
    imager.get_snapshot()

    clock["now"] += seestar_imaging.SNAPSHOT_INTEREST_SEC + 1
    _stack_event(imager, 3)

    assert called["stack"] == 0


def test_snapshot_requests_current_stack_once_per_interval(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(seestar_imaging, "monotonic", lambda: clock["now"])
    imager = make_imager(monkeypatch)
    # A stack was already running before anyone asked for an image.
    _stack_event(imager, 7)
    called = _count_stack_requests(monkeypatch, imager)

    imager.get_snapshot()
    imager.get_snapshot()
    assert called["stack"] == 1

    # The reply arrives: nothing more to fetch for this count.
    _stack_reply(imager, 100)
    clock["now"] += seestar_imaging.SNAPSHOT_FETCH_MIN_INTERVAL_SEC + 1
    imager.get_snapshot()
    assert called["stack"] == 1


def test_reader_before_the_stack_reply_does_not_fetch_twice(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(seestar_imaging, "monotonic", lambda: clock["now"])
    imager = make_imager(monkeypatch)
    called = _count_stack_requests(monkeypatch, imager)
    imager.get_snapshot()  # a reader is interested

    _stack_event(imager, 8)  # fetches the new sub-frame's stack
    imager.get_snapshot()  # polls before that reply arrives
    assert called["stack"] == 1

    # The reply never came: the reader retries after the interval.
    clock["now"] += seestar_imaging.SNAPSHOT_FETCH_MIN_INTERVAL_SEC + 1
    imager.get_snapshot()
    assert called["stack"] == 2


def test_snapshot_is_downscaled_to_the_size_cap(monkeypatch):
    monkeypatch.setattr(seestar_imaging, "SNAPSHOT_MAX_PX", 32)
    imager = _reader(monkeypatch)
    _count_stack_requests(monkeypatch, imager)
    _stack_event(imager, 5)
    imager.comm.on_stack_image(np.full((128, 72, 3), 500, dtype=np.uint16))

    jpeg = imager.get_snapshot().jpeg
    decoded = seestar_imaging.cv2.imdecode(
        np.frombuffer(jpeg, dtype=np.uint8), seestar_imaging.cv2.IMREAD_COLOR
    )

    assert decoded.shape[:2] == (32, 18)


def test_snapshot_does_not_fetch_without_a_stack(monkeypatch):
    imager = make_imager(monkeypatch)
    called = _count_stack_requests(monkeypatch, imager)

    imager.get_snapshot()

    assert called["stack"] == 0


def test_snapshot_never_serves_a_non_stack_image(monkeypatch):
    # The imager holds a frame (preview/stream, or anything from before), but
    # no stacked-image reply has arrived: nothing is served, even though a
    # fetch for the current stack was just requested.
    imager = make_imager(monkeypatch)
    called = _count_stack_requests(monkeypatch, imager)
    _stack_event(imager, 5)

    assert imager.comm.get_image()[0] is not None
    assert imager.get_snapshot() is None
    assert called["stack"] == 1


def test_delayed_reply_is_bound_to_the_stack_current_on_arrival(monkeypatch):
    # An older stacked image is held (count 5). A reader asks while the stack
    # is at 6: it gets the held image labelled 5, never relabelled 6, until
    # the reply for 6 actually arrives.
    imager = _reader(monkeypatch)
    _count_stack_requests(monkeypatch, imager)
    _stack_event(imager, 5)
    _stack_reply(imager, 50)
    _stack_event(imager, 6)

    pending = imager.get_snapshot()
    assert pending.stack_frame == 5

    _stack_reply(imager, 60)
    arrived = imager.get_snapshot()
    assert arrived.stack_frame == 6
    assert arrived.frame != pending.frame


def test_preview_frames_between_stack_replies_do_not_change_the_snapshot(
    monkeypatch,
):
    imager = _reader(monkeypatch)
    _count_stack_requests(monkeypatch, imager)
    frame = {"n": 1}
    monkeypatch.setattr(imager.comm, "received_frame", lambda: frame["n"])
    _stack_event(imager, 5)
    _stack_reply(imager, 50)
    first = imager.get_snapshot()

    frame["n"] += 3  # preview frames arrive on the imaging socket
    again = imager.get_snapshot()

    assert again is first  # same stack reply, not re-encoded or relabelled


def test_new_stack_drops_the_previous_stacks_image(monkeypatch):
    # The count going down means a new stack: the old target's image must not
    # be served for it, even under a matching count.
    imager = _reader(monkeypatch)
    _count_stack_requests(monkeypatch, imager)
    _stack_event(imager, 287)
    _stack_reply(imager, 50)
    assert imager.get_snapshot().stack_frame == 287

    _stack_event(imager, 1)

    assert imager.get_snapshot() is None
    _stack_reply(imager, 60)
    assert imager.get_snapshot().stack_frame == 1


def test_snapshot_encodes_once_per_stack_reply(monkeypatch):
    imager = _reader(monkeypatch)
    _count_stack_requests(monkeypatch, imager)
    encodes = {"n": 0}
    real_imencode = seestar_imaging.cv2.imencode

    def counting_imencode(ext, image):
        encodes["n"] += 1
        return real_imencode(ext, image)

    monkeypatch.setattr(seestar_imaging.cv2, "imencode", counting_imencode)
    _stack_event(imager, 5)
    _stack_reply(imager, 50)

    first = imager.get_snapshot()
    again = imager.get_snapshot()
    _stack_reply(imager, 60)
    newer = imager.get_snapshot()

    assert again is first
    assert encodes["n"] == 2
    assert newer.jpeg[:2] == b"\xff\xd8"


def test_snapshot_etag_is_unique_across_driver_restarts(monkeypatch):
    tags = []
    for _ in range(2):
        imager = _reader(monkeypatch)
        _stack_event(imager, 5)
        _stack_reply(imager, 50)
        tags.append(imager.get_snapshot().etag)

    assert tags[0] != tags[1]


def test_new_stack_during_encode_is_not_served_the_old_image(monkeypatch):
    # The event thread delivers a new stack (count went down) while a reader
    # encodes. It must not wait on the reader (bounded join, so a lock held
    # across the encode fails the test instead of hanging it), and the reader
    # must not serve the previous stack's image.
    imager = _reader(monkeypatch)
    _count_stack_requests(monkeypatch, imager)
    _stack_event(imager, 287)
    _stack_reply(imager, 50)
    event_done = []

    class NewStackMidEncode:
        def process(self, image):
            thread = threading.Thread(target=_stack_event, args=(imager, 1))
            thread.start()
            thread.join(timeout=2)
            event_done.append(not thread.is_alive())
            return image

    imager.comm.StarProcessors = [NewStackMidEncode()]

    assert imager.get_snapshot() is None
    assert event_done == [True]


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


def test_repr_and_event_handler_exception_path(monkeypatch):
    imager = make_imager(monkeypatch)
    assert repr(imager) == "SeestarImaging(host=127.0.0.1, port=9999)"

    # Missing keys raises internally but should be swallowed.
    imager.event_handler({"Event": "Stack"})


def test_blank_frame_uses_gif_when_available(monkeypatch):
    imager = make_imager(monkeypatch)

    class DummyFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"GIF89a"

    monkeypatch.setattr(
        seestar_imaging, "open", lambda *_a, **_k: DummyFile(), raising=False
    )
    frame = imager.blank_frame("Loading", timestamp=False)
    assert frame.startswith(b"Content-Type: image/gif")


def test_get_frame_loop_streaming_branch(monkeypatch):
    imager = make_imager(monkeypatch)
    monkeypatch.setattr(seestar_imaging, "sleep", lambda _s: None)
    monkeypatch.setattr(imager, "build_frame_bytes", lambda *_a, **_k: b"FRAME")
    monkeypatch.setattr(
        imager,
        "blank_frame",
        lambda message="", timestamp=False: f"B:{message}:{timestamp}".encode(),
    )
    monkeypatch.setattr(seestar_imaging.SNRAnalysis, "analyze", lambda self, _img: 42)

    state = {"count": 0}

    def fake_idle():
        state["count"] += 1
        return state["count"] > 1

    monkeypatch.setattr(imager, "is_idle", fake_idle)
    monkeypatch.setattr(imager, "compare_set_exposure_mode", lambda: "stream")
    imager.comm._streaming = True
    imager.comm.received_frame = lambda: 2

    frames = list(imager.get_frame())
    assert frames[0] == b"\r\n--frame\r\n"
    assert b"FRAME" in frames
    assert imager.snr == -1


def test_get_frame_loop_non_streaming_and_stats(monkeypatch):
    imager = make_imager(monkeypatch)
    monkeypatch.setattr(seestar_imaging, "sleep", lambda _s: None)
    monkeypatch.setattr(imager, "build_frame_bytes", lambda *_a, **_k: b"F2")
    monkeypatch.setattr(
        imager,
        "blank_frame",
        lambda message="", timestamp=False: f"B:{message}:{timestamp}".encode(),
    )
    monkeypatch.setattr(seestar_imaging.SNRAnalysis, "analyze", lambda self, _img: 77)

    times = iter([10, 11, 11, 12])
    monkeypatch.setattr(seestar_imaging, "time", lambda: next(times))

    state = {"count": 0}

    def fake_idle():
        state["count"] += 1
        return state["count"] > 2

    monkeypatch.setattr(imager, "is_idle", fake_idle)
    monkeypatch.setattr(imager, "compare_set_exposure_mode", lambda: "preview")
    imager.comm._streaming = False
    imager.comm.received_frame = lambda: 3 if state["count"] == 1 else 3

    frames = list(imager.get_frame())
    assert frames.count(b"F2") >= 2
    assert imager.snr == 77


def test_get_frame_handles_encode_exception_and_loading(monkeypatch):
    imager = make_imager(monkeypatch)
    monkeypatch.setattr(seestar_imaging, "sleep", lambda _s: None)
    monkeypatch.setattr(
        imager, "blank_frame", lambda message="", timestamp=False: b"BL"
    )

    # Initial image missing -> loading blanks
    imager.comm.get_image = lambda: (None, None, None)
    monkeypatch.setattr(imager, "is_idle", lambda: True)
    frames = list(imager.get_frame())
    assert frames[1] == b"BL"
    assert frames[2] == b"BL"

    # Loop image present but frame encoding fails -> handled by exception path
    state = {"count": 0}

    def fake_idle():
        state["count"] += 1
        return state["count"] > 1

    calls = {"n": 0}

    def seq_image():
        calls["n"] += 1
        if calls["n"] == 1:
            return (None, None, None)
        return (np.ones((2, 2, 3), dtype=np.uint8), 2, 2)

    imager.comm.get_image = seq_image
    imager.comm.get_unprocessed_image = lambda: (
        np.ones((2, 2, 3), dtype=np.uint8),
        2,
        2,
    )
    imager.comm.received_frame = lambda: 10
    imager.comm._streaming = False
    monkeypatch.setattr(imager, "is_idle", fake_idle)
    monkeypatch.setattr(imager, "compare_set_exposure_mode", lambda: "preview")
    monkeypatch.setattr(
        imager,
        "build_frame_bytes",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("encode")),
    )
    monkeypatch.setattr(seestar_imaging.SNRAnalysis, "analyze", lambda self, _img: 3)
    list(imager.get_frame())
