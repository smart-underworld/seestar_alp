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
from time import sleep, time
from typing import List, Optional

from flask import Flask, Response
import numpy as np
import cv2
from blinker import signal

import sys

from device import log
from device.analysis.snr_analysis import SNRAnalysis
from device.protocols.imager import SeestarImagerProtocol, ExposureModes
from device.config import Config
from lib.trace import MessageTrace


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


def table(rows):
    """Simple HTML table on a single row"""
    return "".join(
        ['<div class="row">' + "".join([f'<div class="col">{col}</div>' for col in row]) + "</div>" for row in rows])


class SeestarImaging:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, logger, host, port, device_name, device_num, device=None):
        logger.info(f"Initialize new instance of Seestar imager: {host}:{port}, name:{device_name}")

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
        self.BOUNDARY = b'\r\n--frame\r\n'
        # self.trace = MessageTrace(self.device_num, self.port, False)
        self.comm = SeestarImagerProtocol(logger=logger, device_name=device_name, device_num=device_num, host=host, port=port)
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
            match event['Event']:
                case 'Stack':
                    stacked_frame = event['stacked_frame'] + event['dropped_frame']
                    # xxx change to just stacked frame _or_ initial request?
                    if self.comm.is_connected() and stacked_frame != self.last_stacking_frame and stacked_frame > 0 and self.is_live_viewing:
                        self.logger.debug(f'Received Stack event.  Fetching stacked image') # xxx trace
                        # If we get a stack event, we're going to assume we're stacking!
                        self.request_stacked_image()
                    self.last_stacking_frame = stacked_frame
                case _:
                    pass
        except:
            pass
        # print(f'Event handler: {event}')

    def request_stacked_image(self):
        with self.lock:
            self.comm.send_message('{"id": 23, "method": "get_stacked_img"}' + "\r\n")

    def blank_frame(self, message="Loading", timestamp=False):
        #load the gif image
        gif_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), Config.loading_gif)

        if message == "Loading":
            try:
                with open(gif_path, 'rb') as gif_file:
                    gif_data = gif_file.read()

                    return (b'Content-Type: image/gif\r\n\r\n' + gif_data +self.BOUNDARY)
            except Exception as e:
                pass

        blank_image = np.ones((1920, 1080, 3), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        image = cv2.putText(blank_image, message,
                            (200, 900),
                            # (300, 1850),
                            font, 5,
                            (128, 128, 128),
                            4, cv2.LINE_8)
        # image = cv2.imread('img/blank.jpg')
        if timestamp:
            dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]

            w = 1080
            h = 1920
            image = cv2.putText(np.copy(image), dt,  # f'{dt} {self.received_frame}',
                                (int(w / 2 - 240), h - 70),
                                font, 1,
                                (210, 210, 210),
                                4, cv2.LINE_8)
        imgencode = cv2.imencode('.jpeg', image)[1]
        stringData = imgencode.tobytes()
        return (b'Content-Type: image/jpeg\r\n\r\n' + stringData + self.BOUNDARY)

    # render the template?
    # print("get_live_status:",  self.device.ra, self.device.dec)
    # status = f"RA: {self.device.ra} Dec: {self.device.dec}".encode('utf-8')
    # deprecated!
    def get_live_status(self):
        while True:
            self.update_live_status()
            # print(self.device.event_state)
            status = table([["RA", "%.3f" % self.device.ra], ["Dec", "%.3f" % self.device.dec]]).encode('utf-8')
            # status = "Testing..."
            frame = (b'data: ' + status + b'\n\n')
            yield frame
            sleep(5)


    def update_live_status(self):
        with self.lock:
            self.is_live_viewing = True
            self.last_live_view_time = int(time())


    def get_video_status(self):
        while True:
            status = f"Frame: {self.last_frame}".encode('utf-8')
            frame = (b'data: ' + status + b'\n\n')
            yield frame
            sleep(5)

    def is_working(self):
        view_state = self.device.view_state
        return view_state.get('state') == 'working'

    def is_idle(self):
        return not self.is_working()

    def compare_set_exposure_mode(self) -> Optional[ExposureModes]:
        exposure_mode = None
        view_state = self.device.view_state
        # print("comparing exposure mode", view_state)
        # state = view_state.get("state")
        stage = view_state.get('stage')
        # mode = view_state.get('mode')
        # print(f"Compare And Set Exposure Mode {stage=} {self.exposure_mode=}")
        if self.is_idle():
            return None

        if stage == 'RTSP':
            # if self.is_working():
            exposure_mode = 'stream'
            #if self.exposure_mode != exposure_mode:
            #    self.start(exposure_mode)
        elif stage == 'ContinuousExposure':
            exposure_mode = 'preview'
            #if self.exposure_mode != exposure_mode:
            #    self.start(exposure_mode)
        elif stage == 'Stack':
            # If stage is stack, leave exposure mode alone UNLESS exposure mode isn't set.
            # if self.exposure_mode is None and  the number of stacked exposures is > 2:
            exposure_mode = 'stack'
            #if self.exposure_mode != exposure_mode:
            #    self.start(exposure_mode)

        # xxx what other exposure modes?
        return exposure_mode

    def build_frame_bytes(self, image: np.ndarray, width: int, height: int):
        font = cv2.FONT_HERSHEY_COMPLEX

        dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]
        # print("Emiting frame", dt)

        w = width or self.raw_img_size[0] or 1080
        h = height or self.raw_img_size[1] or 1920
        image = cv2.putText(np.copy(image), dt,  # f'{dt} {self.received_frame}',
                            (int(w / 2 - 240), h - 70),
                            font, 1,
                            (210, 210, 210),
                            4, cv2.LINE_8)
        imgencode = cv2.imencode('.jpeg', image)[1]
        stringData = imgencode.tobytes()
        frame = (b'Content-Type: image/jpeg\r\n\r\n' + stringData + self.BOUNDARY)

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
        yield b'\r\n--frame\r\n'
        image, width, height = self.comm.get_image()
        if image is not None:
            #image, _, _ = self.get_image(self.exposure_mode)
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
                            if self.last_stat_time is not None and self.last_stat_frames is not None and self.last_stat_frames is not None:
                                elapsed = now - self.last_stat_time
                                frames = self.sent_frame - self.last_stat_frames
                                self.logger.debug(
                                    f"Sent frames: {frames} in {elapsed} seconds.  FPS: {frames / elapsed}.  Received frame total: {self.received_frame}")

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
                        #if not self.is_gazing:
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

                    #with self.lock:
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


if __name__ == '__main__':
    app = Flask(__name__)

    host, port, device_num, listen_port = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    logger = log.init_logging()
    imager = SeestarImaging(logger, host, port, 'SeestarB', device_num)


    @app.route('/vid/<mode>')
    def vid(mode):
        return Response(imager.get_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')


    app.run(host='localhost', port=listen_port, debug=True)  # , threaded=True)
