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
import socket
import threading
import zipfile
from io import BytesIO
from struct import unpack, calcsize
from time import sleep, time
import sys
import os
from skimage import exposure, img_as_float32, io
from skimage.util import img_as_uint
from PIL import Image, ImageEnhance
from flask import Flask, render_template, Response
import numpy as np
import cv2

import sys

from device import log
from device.rtspclient import RtspClient
from device.stretch import stretch, StretchParameters


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
        self.raw_img = None
        self.s = None
        self.is_connected = False
        self.is_streaming = False
        self.is_gazing = False
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

        # Metrics
        self.last_stat_time = None
        self.last_stat_frames = None

    def __repr__(self):
        return f"{type(self).__name__}(host={self.host}, port={self.port})"

    def reconnect(self):
        if self.is_connected:
            return True

        try:
            self.disconnect()
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # self.s.settimeout(2)
            self.s.connect((self.host, self.port))
            # self.s.settimeout(None)
            self.is_connected = True
            self.logger.info("connected")
            if self.is_gazing:
                self.send_star_subscription()
            return True
        except socket.error as e:
            # Let's just delay a fraction of a second to avoid reconnecting too quickly
            self.is_connected = False
            sleep(0.1)
            return False

    def disconnect(self):
        self.logger.info("disconnect")
        self.is_connected = False
        self.sent_subscription = False
        if self.s:
            try:
                self.s.close()
                self.s = ""
            except:
                pass

    def send_message(self, data):
        self.logger.debug(f"sending message: {data}")  # temp made info
        try:
            self.s.sendall(data.encode())  # TODO: would utf-8 or unicode_escaped help here
            return True
        except socket.timeout:
            return False
        except socket.error as e:
            # Don't bother trying to recover if watch events is False
            self.logger.error(f"Device {self.device_name}: send Socket error: {e}")
            # if self.is_watch_events:
            self.disconnect()
            if self.reconnect():
                return self.send_message(data)
            return False

    def send_star_subscription(self):
        if not self.sent_subscription:
            self.logger.info(f"sending star subscription {self.exposure_mode}")
            if self.exposure_mode == "stack":
                self.send_message('{"id": 23, "method": "get_stacked_img"}' + "\r\n")
            else:
                self.send_message('{"id": 21, "method": "begin_streaming"}' + "\r\n")
        self.sent_subscription = True

    def heartbeat_message_thread_fn(self):
        while True:
            threading.current_thread().last_run = datetime.datetime.now()

            if not self.is_connected and not self.reconnect():
                sleep(5)
                continue

            self.send_message('{  "id" : 2,  "method" : "test_connection"}' + "\r\n")
            if self.is_gazing:
                self.send_star_subscription()

            sleep(3)

    def receive_message_thread_fn(self):
        self.logger.info("starting receive message: main loop")
        while True:
            threading.current_thread().last_run = datetime.datetime.now()

            if self.is_connected and self.exposure_mode is not None:
                # todo : make this something that can timeout, but don't make timeout too short...
                header = self.read_bytes(80)
                size, id = self.parse_header(header)
                data = None
                if size is not None:
                    data = self.read_bytes(size)

                # This isn't a payload message, so skip it.  xxx: probably header item to indicate this...
                if size < 1000:
                    continue

                if data is not None:
                    # id of 23 should be stack, id of 21 should be stream
                    # print(f"header {id=} message {size=}")
                    if id == 21:  # self.exposure_mode == "preview":
                        self.raw_img = data
                    elif id == 23:  # self.exposure_mode == "stream":
                        # for stacking, we have to extract zipfile
                        zip_file = BytesIO(data)
                        with zipfile.ZipFile(zip_file) as zip:
                            contents = {name: zip.read(name) for name in zip.namelist()}
                            self.raw_img = contents['raw_data']

                        # xxx Temp hack: just disconnect for now...
                        # xxx Ideally we listen for an event that stack count has increased, or we track the stack
                        #     count ourselves...
                        if self.is_gazing:
                            self.disconnect()
                            self.reconnect()
                    else:
                        continue

                    self.received_frame += 1
                    self.logger.info(f"read image size={len(self.raw_img)}")
            else:
                # If we aren't connected, just wait...
                sleep(1)

    def parse_header(self, header):
        if header is not None and len(header) > 20:
            # print(type(header))
            self.logger.debug("Header:" + ":".join("{:02x}".format(c) for c in header))
            # We ignore all values at end of header...
            header = header[:20]
            fmt = ">HHHIHHBBHH"
            self.logger.debug(f"size: {calcsize(fmt)}")
            _s1, _s2, _s3, size, _s5, _s6, code, id, width, height = unpack(fmt, header)
            self.logger.debug(f"header: {size=} {width=} {height=} {_s1=} {_s2=} {_s3=} {code=} {id=}")

            return size, id
        return 0, None

    def streaming_thread_fn(self):
        self.logger.info("starting streaming thread")
        while True:
            threading.current_thread().last_run = datetime.datetime.now()

            if self.is_streaming:
                try:
                    empty_images = 0
                    with RtspClient(rtsp_server_uri=f'rtsp://{self.host}:4554/stream', logger=self.logger,
                                    verbose=True) as client:
                        # self.raw_img = np.copy(client.read(raw=True))
                        # self.received_frame += 1

                        while self.is_streaming:
                            image = client.read(raw=True)
                            if image is not None and not np.array_equal(image, self.raw_img):
                                # RTSP is async, so when we read we might get the same frame back.
                                # We could adjust the Rtsp code, but for now just going to brute force compare
                                # frames.
                                self.raw_img = np.copy(image)
                                self.received_frame += 1
                                empty_images = 0  # Reset counter...

                                if self.received_frame % 100 == 0:
                                    self.logger.debug(f"Read {self.received_frame} images {self.is_streaming=}")
                            else:
                                empty_images += 1

                            sleep(0.025)

                            # Let it fail for a few seconds before attempting a reconnect...
                            if empty_images >  200:
                                self.logger.info("empty image threshold exceeded.  reconnecting")
                                break
                except Exception as e:
                    self.logger.error(f"Exception in stream thread... {e=}")

            sleep(1)  # Wait a second before trying to reconnect...

    def read_bytes(self, num):
        if not self.is_connected:
            return None

        data = None
        try:
            data = self.s.recv(num, socket.MSG_WAITALL)  # comet data is >50kb
        except socket.timeout:
            return None
        except socket.error as e:
            # todo : if general socket error, close socket, and kick off reconnect?
            # todo : no route to host...
            # self.logger.error(f"Device {self.device_name}: read Socket error: {e}")
            self.disconnect()
            return None

        if data is None or len(data) == 0:
            return None

        # self.logger.debug(f'{self.device_name} received : {len(data)}')
        self.logger.debug(f'{self.device_name} received : {len(data)}')
        l = len(data)
        if l < 100 and l != 80:
            self.logger.debug(f'Message: {data}')
        return data

    def get_star_preview(self):
        # if self.exposure_mode == "stack" or len(self.raw_img) == 1920 * 1080 * 6:
        if len(self.raw_img) == 1920 * 1080 * 6:
            # print("raw buffer size:", len(self.raw_img))
            img = np.frombuffer(self.raw_img, dtype=np.uint16).reshape(1920, 1080, 3)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return img

        img = np.frombuffer(self.raw_img, np.uint16).reshape(1920, 1080)
        img = cv2.cvtColor(img, cv2.COLOR_BAYER_GRBG2BGR)
        return img


    def update_saturation(self, img_array, img_display, saturation):
        img_saturated = img_display

        if img_array.shape[-1] == 3:
            img_saturated = ImageEnhance.Color(img_display)
            img_saturated = img_saturated.enhance(saturation)

        return img_saturated


    def image_stretch_graxpert(self, img):
        image_array = img_as_float32(img)

        if np.min(image_array) < 0 or np.max(image_array > 1):
            image_array = exposure.rescale_intensity(image_array, out_range=(0, 1))

        image_display = stretch(image_array, StretchParameters("15% Bg, 3 sigma"))
        image_display = image_display * 255

        # if image_display.shape[2] == 1:
        #    image_display = Image.fromarray(image_display[:, :, 0].astype(np.uint8))
        # else:
        #    image_display = Image.fromarray(image_display.astype(np.uint8))

        # image_display = self.update_saturation(image_array, image_display, saturation=1.0)

        return image_display


    def image_stretch(self, img):
        # https://scikit-image.org/docs/stable/auto_examples/color_exposure/plot_equalize.html
        # Contrast stretching
        p2, p98 = np.percentile(img, (2, 99.5))
        # p2, p98 = np.percentile(img, (2, 98))
        img_rescale = exposure.rescale_intensity(img, in_range=(p2, p98))

        # Equalization
        # img_eq = exposure.equalize_hist(img)

        # Adaptive Equalization
        # img_adapteq = exposure.equalize_adapthist(img, clip_limit=0.03)

        # stretched_image = Stretch().stretch(img)
        # return stretched_image

        return img_rescale


    def start(self, new_exposure_mode=None):
        self.reconnect()
        self.exposure_mode = new_exposure_mode
        self.is_streaming = self.exposure_mode == "stream"
        self.is_gazing = self.exposure_mode == "preview" or self.exposure_mode == "stack"
        self.received_frame = 0
        self.sent_frame = 0
        self.last_frame = 0
        # xxx:
        #   try to connect if necessary?  or disconnect first, then connect if necessary
        if self.heartbeat_msg_thread is None:
            self.heartbeat_msg_thread = threading.Thread(target=self.heartbeat_message_thread_fn, daemon=True)
            self.heartbeat_msg_thread.name = f"ImagingHeartbeatMessageThread.{self.device_name}"
            self.heartbeat_msg_thread.start()

        if self.exposure_mode == "stream":
            if self.get_stream_thread is None:
                self.get_stream_thread = threading.Thread(target=self.streaming_thread_fn, daemon=True)
                self.get_stream_thread.name = f"ImagingReceiveStreamThread.{self.device_name}"
                self.get_stream_thread.start()
        else:
            if self.get_image_thread is None:
                self.get_image_thread = threading.Thread(target=self.receive_message_thread_fn, daemon=True)
                self.get_image_thread.name = f"ImagingReceiveImageThread.{self.device_name}"
                self.get_image_thread.start()


    def stop(self):
        self.disconnect()
        # xxx might want to reset some things?
        self.raw_img = None
        self.exposure_mode = None
        self.is_streaming = False
        self.is_gazing = False
        self.is_connected = False
        self.sent_subscription = False


    def blank_frame(self, message="Loading..."):
        blank_image = np.ones((1920, 1080, 3), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        image = cv2.putText(blank_image, message,
                            (200, 900),
                            # (300, 1850),
                            font, 5,
                            (128, 128, 128),
                            4, cv2.LINE_8)
        imgencode = cv2.imencode('.png', image)[1]
        stringData = imgencode.tobytes()
        return (b'--frame\r\n' b'Content-Type: image/png\r\n\r\n' + stringData + b'\r\n')


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


    def get_frame(self, mode=None):
        # todo : don't send these if we already have an image?
        yield self.blank_frame()
        yield self.blank_frame()

        # view_state = self.device.view_state
        # self.logger.info(f"mode: {self.mode} {type(self.mode)} view_state: {view_state}")

        while not self.is_idle():
            image = None
            exposure_mode = None
            view_state = self.device.view_state
            state = view_state.get("state")
            stage = view_state.get('stage')
            mode = view_state.get('mode')
            if stage == 'RTSP':
                # if self.is_working():
                exposure_mode = 'stream'
                if self.exposure_mode != exposure_mode:
                    self.start(exposure_mode)
            elif stage == 'ContinuousExposure':
                exposure_mode = 'preview'
                if self.exposure_mode != exposure_mode:
                    self.start(exposure_mode)
            elif stage == 'Stack':
                exposure_mode = 'stack'
                if self.exposure_mode != exposure_mode:
                    self.start(exposure_mode)

            # xxx what other exposure modes?

            match exposure_mode:
                case "stream":
                    # print starting RTSP stream...
                    if self.raw_img is not None:
                        try:
                            image = self.raw_img
                        except Exception as e:
                            self.logger.info("exception")
                            image = None
                    delay = 0.025

                case _:
                    if self.raw_img is not None:
                        try:
                            image = self.get_star_preview()
                            image = self.image_stretch_graxpert(image)
                            # image = np.uint8(np.clip(image, 0, 255))
                            # image = cv2.fastNlMeansDenoisingColored(image,None,10,10,7,21)
                            # cv2.imwrite('stacked.png', image)
                        except Exception as e:
                            # if buffer is misformed, just catch error
                            self.logger.info(f"misformed buffer exception... {e}")
                            self.raw_img = None
                            image = None
                    delay = 0.5

            if image is not None:
                try:
                    if self.last_frame != self.received_frame:
                        font = cv2.FONT_HERSHEY_COMPLEX

                        dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]

                        image = cv2.putText(image, dt,  # f'{dt} {self.received_frame}',
                                            (300, 1850),
                                            font, 1,
                                            (210, 210, 210),
                                            4, cv2.LINE_8)
                        imgencode = cv2.imencode('.png', image)[1]
                        stringData = imgencode.tobytes()
                        # print("sending frame bytes=", len(stringData))

                        # Update stats!
                        self.sent_frame += 1

                        now = int(time())
                        if self.last_stat_time != now:
                            if self.last_stat_frames is not None and self.last_stat_frames is not None:
                                elapsed = now - self.last_stat_time
                                frames = self.sent_frame - self.last_stat_frames
                                self.logger.debug(
                                    f"Sent frames: {frames} in {elapsed} seconds.  FPS: {frames / elapsed}.  Received frame total: {self.received_frame}")

                            self.last_stat_time = now
                            self.last_stat_frames = self.sent_frame

                        self.last_frame = self.received_frame

                        frame = (b'--frame\r\n' b'Content-Type: image/png\r\n\r\n' + stringData + b'\r\n')
                        # If stack mode, we just do one and done.
                        # if self.exposure_mode == "stack":
                        yield frame
                        # else:
                        #    yield frame
                    else:
                        pass
                        # self.logger.info("skipping send")
                except Exception as e:
                    self.logger.info(f"exception encoding frame. skipping {e=}")
            sleep(delay)

        self.stop()

        yield self.blank_frame("Idle")


if __name__ == '__main__':
    app = Flask(__name__)

    host, port, device_num, listen_port = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    logger = log.init_logging()
    imager = SeestarImaging(logger, host, port, 'SeestarB', device_num)


    @app.route('/vid/<mode>')
    def vid(mode):
        return Response(imager.get_frame(mode), mimetype='multipart/x-mixed-replace; boundary=frame')


    app.run(host='localhost', port=listen_port, debug=True)  # , threaded=True)
