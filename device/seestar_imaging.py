#
# seestar_imaging - performances image-related tasks with a Seestar
#
# New config settings:
# .   experimental
# .   max_stream_fps. (can set this number lower if you have network constraints)
#
# This is just the beginning
#
import datetime
import os
import threading
import uuid
from time import monotonic, sleep, time
from typing import NamedTuple, Optional

from flask import Flask, Response
import numpy as np
import cv2
from blinker import signal

import sys

from device import log
from device.analysis.snr_analysis import SNRAnalysis
from device.protocols.imager import SeestarImagerProtocol, ExposureModes
from device.config import Config


# view modes:
#   star: 3PPA, ContinuousExposure, Stack

# https://stackoverflow.com/questions/8554282/creating-a-png-file-in-python
# https://docs.astropy.org/en/stable/visualization/normalization.html#stretching

# Port 4700
#   Star:
# {  "id" : 112,  "method" : "iscope_start_view",  "params" : {    "mode" : "star"  }}
#   Moon:
# {  "id" : 254,  "method" : "iscope_start_view",  "params" : {    "mode" : "moon"  }}
# {  "id" : 255,  "method" : "start_scan_planet"}

# Port 4800
#   {  "id" : 21,  "method" : "begin_streaming"}
# Star:
#   {  "id" : 23,  "method" : "get_stacked_img"}

#: How long one snapshot request keeps stacked images flowing without the web
#: live page (whose status loop sets is_live_viewing). Snapshot readers poll far
#: more often than this, so fetching stops a couple of minutes after the last one.
SNAPSHOT_INTEREST_SEC = 120

#: Minimum gap between snapshot-triggered stacked-image fetches (see
#: SeestarImaging.get_snapshot), so polling readers can't flood the scope.
SNAPSHOT_FETCH_MIN_INTERVAL_SEC = 30

#: Longest side of a snapshot, in pixels. The stack is downscaled BEFORE the
#: stretch: stretching the full 2160x3840 stack takes ~500 MB at its peak,
#: while snapshot readers (dashboards, the ha-seestar bridge) display ~1280 px.
SNAPSHOT_MAX_PX = 1280


def _fit_within(image: np.ndarray, max_px: int) -> np.ndarray:
    """``image`` scaled down (area-averaged) so its longest side is ``max_px``."""
    height, width = image.shape[:2]
    scale = max_px / max(height, width)
    if scale >= 1:
        return image
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


class _HeldStack(NamedTuple):
    """The latest stacked-image reply, bound to its stack when it arrived."""

    image: np.ndarray
    #: Stack count (stacked + dropped) current when the reply arrived, or None
    #: when no Stack event had been seen yet.
    stack_frame: Optional[int]
    #: Sequence number of the reply (one per stacked-image reply).
    seq: int


class Snapshot(NamedTuple):
    """One encoded stacked image, shared by every reader until the next reply."""

    #: Sequence number of the stacked-image reply it encodes (stable per image).
    frame: int
    #: Stack count current when that reply arrived (see _HeldStack).
    stack_frame: Optional[int]
    jpeg: bytes
    #: HTTP entity tag (unquoted), unique across driver restarts: a bare
    #: sequence number would repeat, letting a client get a 304 for a
    #: different image.
    etag: str


def table(rows):
    """Simple HTML table on a single row"""
    return "".join(
        [
            '<div class="row">'
            + "".join([f'<div class="col">{col}</div>' for col in row])
            + "</div>"
            for row in rows
        ]
    )


class SeestarImaging:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, logger, host, port, device_name, device_num, device=None):
        logger.info(
            f"Initialize new instance of Seestar imager: {host}:{port}, name:{device_name}"
        )

        self.host = host
        self.port = port
        self.device_name = device_name
        self.device_num = device_num
        self.logger = logger
        # self.raw_img = None
        self.raw_img_size = [None, None]
        self.s = None
        self.is_connected = False
        self.is_streaming = False
        self.is_gazing = False
        self.is_live_viewing = False
        self.sent_subscription = False
        self.mode = None
        self.exposure_mode = None  # "stream"  # None | preview | stack | stream
        self.received_frame = 0
        self.sent_frame = 0
        self.last_frame = 0
        self.get_image_thread = None
        self.get_stream_thread = None
        self.heartbeat_msg_thread = None
        self.device = device
        self.lock = threading.RLock()
        self.eventbus = signal(f"{device_name}.eventbus")
        self.eventbus.connect(self.event_handler)
        self.BOUNDARY = b"\r\n--frame\r\n"

        # Snapshot readers (GET /<dev>/snapshot.jpg). Only stacked-image REPLIES
        # are served, each bound at receipt to the stack count current then, so
        # a preview/stream frame or a previous stack's image is never passed
        # off as the current stack. Encoded once per reply; no reader holds a
        # generator open the way /vid does.
        self._snapshot_lock = threading.Lock()
        self._encode_lock = threading.Lock()
        self._snapshot_epoch = uuid.uuid4().hex[:8]
        self._stack_image: Optional[_HeldStack] = None
        self._stack_seq = 0
        self._snapshot: Optional[Snapshot] = None
        self._snapshot_interest_until = 0.0
        self._last_snapshot_fetch = None

        # self.trace = MessageTrace(self.device_num, self.port, False)
        self.comm = SeestarImagerProtocol(
            logger=logger,
            device_name=device_name,
            device_num=device_num,
            host=host,
            port=port,
        )
        self.comm.on_stack_image = self._on_stack_image
        self.comm.start()

        # Star imaging metrics
        self.snr = None

        # Metrics
        self.last_stat_time = None
        self.last_stat_frames = None
        self.last_live_view_time = None
        self.last_stacking_frame = None

    def __repr__(self):
        return f"{type(self).__name__}(host={self.host}, port={self.port})"

    def event_handler(self, event):
        try:
            match event["Event"]:
                case "Stack":
                    stacked_frame = event["stacked_frame"] + event["dropped_frame"]
                    connected = self.comm.is_connected()
                    with self._snapshot_lock:
                        previous = self.last_stacking_frame
                        if previous is not None and stacked_frame < previous:
                            # The count went down: a new stack began. Never
                            # serve the previous stack's image as this one.
                            self._stack_image = None
                            self._snapshot = None
                        self.last_stacking_frame = stacked_frame
                        # xxx change to just stacked frame _or_ initial request?
                        fetch = (
                            connected
                            and stacked_frame != previous
                            and stacked_frame > 0
                            and (self.is_live_viewing or self._snapshot_wanted())
                        )
                        if fetch:
                            # A snapshot reader polling before this reply
                            # arrives must not fetch it again.
                            self._last_snapshot_fetch = monotonic()
                    if fetch:
                        self.logger.debug(
                            "Received Stack event.  Fetching stacked image"
                        )  # xxx trace
                        # If we get a stack event, we're going to assume we're stacking!
                        self.request_stacked_image()
                case _:
                    pass
        except:
            pass
        # print(f'Event handler: {event}')

    def request_stacked_image(self):
        with self.lock:
            self.comm.send_message('{"id": 23, "method": "get_stacked_img"}' + "\r\n")

    def _snapshot_wanted(self) -> bool:
        return monotonic() < self._snapshot_interest_until

    def _on_stack_image(self, image: np.ndarray) -> None:
        """A stacked-image reply arrived (imager receive thread): while a
        snapshot reader is interested, bind it to the stack count current now,
        so readers never see it under another stack."""
        with self._snapshot_lock:
            if not self._snapshot_wanted():
                return  # nobody reads snapshots: hold no extra image
            self._stack_seq += 1
            self._stack_image = _HeldStack(
                image=image, stack_frame=self.last_stacking_frame, seq=self._stack_seq
            )

    def get_snapshot(self) -> Optional[Snapshot]:
        """The latest stacked-image reply as one JPEG, encoded once per reply.

        Each call keeps stacked-image fetching on for SNAPSHOT_INTEREST_SEC, so a
        polling reader sees the stack grow even if the web live page was never
        opened. While no reply for the current stack count is held, one fetch is
        requested, at most every SNAPSHOT_FETCH_MIN_INTERVAL_SEC. Returns None
        until a stacked-image reply for the current stack has arrived.

        Neither the fetch (a socket write) nor the stretch + encode runs under
        the snapshot lock, which the imager receive thread takes for every
        stacked-image reply; concurrent readers share one encode.
        """
        now = monotonic()
        with self._snapshot_lock:
            self._snapshot_interest_until = now + SNAPSHOT_INTEREST_SEC
            held = self._stack_image
            cached = self._snapshot
            current_stack = self.last_stacking_frame
            fetch = bool(
                current_stack
                and (held is None or held.stack_frame != current_stack)
                and (
                    self._last_snapshot_fetch is None
                    or now - self._last_snapshot_fetch
                    >= SNAPSHOT_FETCH_MIN_INTERVAL_SEC
                )
            )
            if fetch:
                self._last_snapshot_fetch = now
        if fetch and self.comm.is_connected():
            self.request_stacked_image()

        if held is None:
            return None
        if cached is not None and cached.frame == held.seq:
            return cached
        with self._encode_lock:
            with self._snapshot_lock:
                cached = self._snapshot
            if cached is not None and cached.frame == held.seq:
                return cached  # another reader encoded it meanwhile
            image = _fit_within(held.image, SNAPSHOT_MAX_PX)
            for processor in self.comm.StarProcessors:
                image = processor.process(image)
            ok, encoded = cv2.imencode(".jpeg", image)
            if not ok:
                return None
            snap = Snapshot(
                frame=held.seq,
                stack_frame=held.stack_frame,
                jpeg=encoded.tobytes(),
                etag=f"{self._snapshot_epoch}-{held.seq}",
            )
            with self._snapshot_lock:
                current = self._stack_image
                if current is held:
                    self._snapshot = snap
            # A new stack (or a newer reply) arrived while encoding.
            return snap if current is held else None

    def blank_frame(self, message="Loading", timestamp=False):
        # load the gif image
        gif_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), Config.loading_gif
        )

        if message == "Loading":
            try:
                with open(gif_path, "rb") as gif_file:
                    gif_data = gif_file.read()

                    return b"Content-Type: image/gif\r\n\r\n" + gif_data + self.BOUNDARY
            except Exception:
                pass

        blank_image = np.ones((1920, 1080, 3), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        image = cv2.putText(
            blank_image,
            message,
            (200, 900),
            # (300, 1850),
            font,
            5,
            (128, 128, 128),
            4,
            cv2.LINE_8,
        )
        # image = cv2.imread('img/blank.jpg')
        if timestamp:
            dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]

            w = 1080
            h = 1920
            image = cv2.putText(
                np.copy(image),
                dt,  # f'{dt} {self.received_frame}',
                (int(w / 2 - 240), h - 70),
                font,
                1,
                (210, 210, 210),
                4,
                cv2.LINE_8,
            )
        imgencode = cv2.imencode(".jpeg", image)[1]
        stringData = imgencode.tobytes()
        return b"Content-Type: image/jpeg\r\n\r\n" + stringData + self.BOUNDARY

    # render the template?
    # print("get_live_status:",  self.device.ra, self.device.dec)
    # status = f"RA: {self.device.ra} Dec: {self.device.dec}".encode('utf-8')
    # deprecated!
    def get_live_status(self):
        while True:
            self.update_live_status()
            # print(self.device.event_state)
            status = table(
                [["RA", "%.3f" % self.device.ra], ["Dec", "%.3f" % self.device.dec]]
            ).encode("utf-8")
            # status = "Testing..."
            frame = b"data: " + status + b"\n\n"
            yield frame
            sleep(5)

    def update_live_status(self):
        with self.lock:
            self.is_live_viewing = True
            self.last_live_view_time = int(time())

    def get_video_status(self):
        while True:
            status = f"Frame: {self.last_frame}".encode("utf-8")
            frame = b"data: " + status + b"\n\n"
            yield frame
            sleep(5)

    def is_working(self):
        view_state = self.device.view_state
        return view_state.get("state") == "working"

    def is_idle(self):
        return not self.is_working()

    def compare_set_exposure_mode(self) -> Optional[ExposureModes]:
        exposure_mode = None
        view_state = self.device.view_state
        # print("comparing exposure mode", view_state)
        # state = view_state.get("state")
        stage = view_state.get("stage")
        # mode = view_state.get('mode')
        # print(f"Compare And Set Exposure Mode {stage=} {self.exposure_mode=}")
        if self.is_idle():
            return None

        if stage == "RTSP":
            # if self.is_working():
            exposure_mode = "stream"
            # if self.exposure_mode != exposure_mode:
            #    self.start(exposure_mode)
        elif stage == "ContinuousExposure":
            exposure_mode = "preview"
            # if self.exposure_mode != exposure_mode:
            #    self.start(exposure_mode)
        elif stage == "Stack":
            # If stage is stack, leave exposure mode alone UNLESS exposure mode isn't set.
            # if self.exposure_mode is None and  the number of stacked exposures is > 2:
            exposure_mode = "stack"
            # if self.exposure_mode != exposure_mode:
            #    self.start(exposure_mode)

        # xxx what other exposure modes?
        return exposure_mode

    def build_frame_bytes(self, image: np.ndarray, width: int, height: int):
        font = cv2.FONT_HERSHEY_COMPLEX

        dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]
        # print("Emiting frame", dt)

        w = width or self.raw_img_size[0] or 1080
        h = height or self.raw_img_size[1] or 1920
        image = cv2.putText(
            np.copy(image),
            dt,  # f'{dt} {self.received_frame}',
            (int(w / 2 - 240), h - 70),
            font,
            1,
            (210, 210, 210),
            4,
            cv2.LINE_8,
        )
        imgencode = cv2.imencode(".jpeg", image)[1]
        stringData = imgencode.tobytes()
        frame = b"Content-Type: image/jpeg\r\n\r\n" + stringData + self.BOUNDARY

        return frame

    def get_frame(self):
        # xxx : We want to be able to manually switch between preview and stack modes.
        #       If stage is RTSP, we force switch to stream exposure mode.
        # .      If stage is Stack, and exposure mode preview, leave it alone.
        # .      If stage is ContinuousExposure, switch to preview.
        # todo : don't send these if we already have an image and we have an exposure mode
        #
        # We send each frame twice because of a very long term bug in Chromium.  Yes, seriously.
        #   We will only send it when not in RTSP-backed modes.  (The idea being that with
        #   higher FPS being one frame behind isn't noticeable.)
        #
        # Some of the related issues:
        # - https://issues.chromium.org/issues/40791855 "multipart/x-mixed-replace images have 1 frame delay" from 2021
        # - https://issues.chromium.org/issues/41199053 "mjpeg image always shows the second to last image" from 2015
        # - https://issues.chromium.org/issues/40277613 "multipart/x-mixed-replace no longer working reliably" from 2012!
        yield b"\r\n--frame\r\n"
        image, width, height = self.comm.get_image()
        if image is not None:
            # image, _, _ = self.get_image(self.exposure_mode)
            frame = self.build_frame_bytes(image, width, height)
            yield frame
            yield frame
        else:
            yield self.blank_frame("Loading", True)
            yield self.blank_frame("Loading", True)

        # view_state = self.device.view_state
        # self.logger.info(f"mode: {self.mode} {type(self.mode)} view_state: {view_state}")

        exiting = False
        first_image = False
        while not self.is_idle():
            self.comm.set_exposure_mode(self.compare_set_exposure_mode())
            image, width, height = self.comm.get_image()

            if self.comm.is_streaming():
                delay = 0.001
                snr = -1
            else:
                raw_image, _, _ = self.comm.get_unprocessed_image()
                delay = 0.1
                snr = SNRAnalysis().analyze(raw_image)

            if image is not None:
                # print("get_frame image!")
                try:
                    received_frame = self.comm.received_frame()
                    if self.last_frame != received_frame:
                        frame = self.build_frame_bytes(image, width, height)
                        # print("sending frame bytes=", len(stringData))

                        # Update stats!
                        self.sent_frame += 1

                        now = int(time())
                        if self.last_stat_time != now:
                            if (
                                self.last_stat_time is not None
                                and self.last_stat_frames is not None
                                and self.last_stat_frames is not None
                            ):
                                elapsed = now - self.last_stat_time
                                frames = self.sent_frame - self.last_stat_frames
                                self.logger.debug(
                                    f"Sent frames: {frames} in {elapsed} seconds.  FPS: {frames / elapsed}.  Received frame total: {self.received_frame}"
                                )

                            self.last_stat_time = now
                            self.last_stat_frames = self.sent_frame

                        self.last_frame = received_frame
                        self.snr = snr

                        first_image = True
                        # ts = time()
                        yield frame
                        # te = time()
                        # print(f'imaging yield1 took {te - ts:2.4f} seconds')
                        if not self.comm.is_streaming():
                            # ts = time()
                            yield frame
                            # te = time()
                            # print(f'imaging yield2 took {te - ts:2.4f} seconds')
                        # if not self.is_gazing:
                        #    yield frame
                    else:
                        pass
                        # self.logger.info("skipping send")
                except GeneratorExit:
                    # with self.lock:
                    #     self.raw_img = None
                    #     self.raw_img_size = [None, None]
                    exiting = True
                    break
                except Exception as e:
                    # print(traceback.format_exc())
                    self.logger.info(f"exception encoding frame. skipping {e=}")

                    # with self.lock:
                    #    self.raw_img = None
                    #    self.raw_img_size = [None, None]
            else:
                # print("Did not get frame!")
                if not first_image:
                    yield self.blank_frame("Loading", True)
                    yield self.blank_frame("Loading", True)
            sleep(delay)

        self.comm.set_exposure_mode(self.compare_set_exposure_mode())

        if not exiting:
            yield self.blank_frame("Idle")


if __name__ == "__main__":
    app = Flask(__name__)

    host, port, device_num, listen_port = (
        sys.argv[1],
        int(sys.argv[2]),
        int(sys.argv[3]),
        int(sys.argv[4]),
    )
    logger = log.init_logging()
    imager = SeestarImaging(logger, host, port, "SeestarB", device_num)

    @app.route("/vid/<mode>")
    def vid(mode):
        return Response(
            imager.get_frame(), mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    app.run(host="localhost", port=listen_port, debug=True)  # , threaded=True)
