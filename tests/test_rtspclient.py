"""Tests for device/rtspclient.py"""

import numpy as np
import pytest

from device.rtspclient import RtspClient


class DummyLogger:
    def info(self, msg, *args):
        pass


class FakeCapture:
    """Minimal cv2.VideoCapture stand-in."""

    def __init__(self, frames=None, opened=True):
        self._frames = list(frames or [])
        self._opened = opened
        self._read_calls = 0

    def isOpened(self):
        return self._opened

    def read(self):
        self._read_calls += 1
        if self._frames:
            return True, self._frames.pop(0)
        return False, None

    def release(self):
        self._opened = False


def make_client(monkeypatch, frames=None, opened=True):
    """Create an RtspClient with a fake VideoCapture."""
    fake_cap = FakeCapture(frames=frames, opened=opened)
    monkeypatch.setattr("device.rtspclient.cv2.VideoCapture", lambda _uri: fake_cap)
    client = RtspClient("rtsp://fake/stream", DummyLogger())
    return client, fake_cap


def test_queue_initialised_to_none_before_first_frame(monkeypatch):
    """_queue must exist as None immediately after __init__, before any frame arrives."""
    # Use a capture that never returns a frame so _update loop exits quickly.
    client, _ = make_client(monkeypatch, frames=[])
    # Give the background thread a moment to run and exit.
    client._bgt.join(timeout=1.0)
    # _queue was initialised to None in __init__ and never overwritten (no frames).
    assert client._queue is None


def test_read_returns_none_when_no_frame_yet(monkeypatch):
    """read() must return None (not raise) when _queue is still None."""
    client, _ = make_client(monkeypatch, frames=[])
    client._bgt.join(timeout=1.0)
    assert client.read() is None
    assert client.read(raw=True) is None


def test_read_raw_returns_frame_after_capture(monkeypatch):
    """read(raw=True) returns the numpy array grabbed by the background thread."""
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    client, _ = make_client(monkeypatch, frames=[frame])
    client._bgt.join(timeout=1.0)
    result = client.read(raw=True)
    assert result is not None
    assert result.shape == (4, 4, 3)


def test_read_converts_to_pil_image(monkeypatch):
    """read() (no raw) converts the frame via PIL."""
    from PIL import Image

    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    # Stub cv2.cvtColor so it just returns the frame unchanged.
    monkeypatch.setattr("device.rtspclient.cv2.cvtColor", lambda img, _mode: img)
    client, _ = make_client(monkeypatch, frames=[frame])
    client._bgt.join(timeout=1.0)

    result = client.read()
    assert isinstance(result, Image.Image)


def test_isopened_false_when_not_started(monkeypatch):
    """isOpened() returns False before open() is called (bg_run=False, stream=None)."""
    # Prevent open() from actually spawning a thread by making VideoCapture not opened.
    fake_cap = FakeCapture(opened=False)
    monkeypatch.setattr("device.rtspclient.cv2.VideoCapture", lambda _uri: fake_cap)
    client = RtspClient.__new__(RtspClient)
    client.rtsp_server_uri = "rtsp://fake"
    client._verbose = False
    client.logger = DummyLogger()
    client._bg_run = False
    client._queue = None
    client._stream = None
    assert client.isOpened() is False


def test_isopened_false_after_frames_exhausted(monkeypatch):
    """isOpened() becomes False once the background thread exits (no more frames)."""
    client, _ = make_client(monkeypatch, frames=[])
    client._bgt.join(timeout=1.0)
    assert client.isOpened() is False


def test_close_stops_background_thread(monkeypatch):
    """close() sets _bg_run=False and joins the thread."""
    frame = np.zeros((2, 2, 3), dtype=np.uint8)

    # Provide enough frames to keep the thread alive briefly, then stop it.
    class SlowCapture(FakeCapture):
        def read(self):
            import time

            time.sleep(0.01)
            return super().read()

    fake_cap = SlowCapture(frames=[frame] * 5)
    monkeypatch.setattr("device.rtspclient.cv2.VideoCapture", lambda _uri: fake_cap)
    client = RtspClient("rtsp://fake", DummyLogger())

    assert client._bg_run is True
    client.close()
    assert client._bg_run is False
    assert not client._bgt.is_alive()


def test_context_manager_calls_close(monkeypatch):
    """The with-statement calls close() on exit."""
    closed = []
    client, _ = make_client(monkeypatch, frames=[])
    client._bgt.join(timeout=1.0)
    monkeypatch.setattr(client, "close", lambda: closed.append(True))
    with client:
        pass
    assert closed == [True]
