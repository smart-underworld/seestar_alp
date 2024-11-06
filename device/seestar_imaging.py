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
import socket
import threading
import zipfile
from io import BytesIO
from struct import unpack, calcsize
from time import sleep, time
from astropy.io import fits
from skimage import exposure, img_as_float32
from PIL import ImageEnhance
from flask import Flask, Response
import numpy as np
import cv2
from blinker import signal

import sys

from device import log
from device.rtspclient import RtspClient
from imaging.snr import calculate_snr_auto
from imaging.stretch import stretch, StretchParameters
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
        self.raw_img = None
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
                    stacked_frame = event['stacked_frame']
                    # xxx change to just stacked frame _or_ initial request?
                    if self.is_connected and stacked_frame != self.last_stacking_frame and stacked_frame > 0 and self.is_live_viewing:
                        self.logger.debug(f'Received Stack event.  Fetching stacked image') # xxx trace
                        # If we get a stack event, we're going to assume we're stacking!
                        self.request_stacked_image()
                    self.last_stacking_frame = stacked_frame
                case _:
                    pass
        except:
            pass
        # print(f'Event handler: {event}')

    def reconnect(self):
        with self.lock:
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
        with self.lock:
            self.is_connected = False
            self.sent_subscription = False
            if self.s:
                try:
                    self.s.close()
                    self.s = None
                except:
                    pass

    def send_message(self, data):
        self.logger.debug(f"sending message: {data}")  # temp made info
        with self.lock:
            try:
                self.s.sendall(data.encode())  # TODO: would utf-8 or unicode_escaped help here
                return True
            except socket.timeout:
                return False
            except socket.error as e:
                # Don't bother trying to recover if watch events is False
                self.logger.error(f"Send Socket error: {e}")
                # if self.is_watch_events:
                self.disconnect()
                if self.reconnect():
                    return self.send_message(data)
                return False

    def request_stacked_image(self):
        with self.lock:
            self.send_message('{"id": 23, "method": "get_stacked_img"}' + "\r\n")

    def send_star_subscription(self):
        # todo : have more complicated mechanism.  counter?
        with self.lock:
            if not self.sent_subscription:
                if self.exposure_mode == "preview":
                    self.logger.info(f"sending star subscription {self.exposure_mode}")
                    self.send_message('{"id": 21, "method": "begin_streaming"}' + "\r\n")
            self.sent_subscription = True

    def heartbeat_message_thread_fn(self):
        while True:
            threading.current_thread().last_run = datetime.datetime.now()

            with self.lock:
                if not self.is_connected and not self.reconnect():
                    sleep(5)
                    continue

                # have a decorator that wraps method and tracks when last run.
                self.send_message('{  "id" : 2,  "method" : "test_connection"}' + "\r\n")
                # xxx : check exposure mode.
                #    if preview, and if subscription wasn't sent, send it (clear in connect)
                #    if stack, and stack count changed, fetch latest
                if self.is_gazing:
                    self.send_star_subscription()

            now = int(time())
            with self.lock:
                # Check to see if it is time to shut down imaging system.  If we are
                #   saving frames, we do _not_ want to shut down imaging.
                # xxx double check that we're in preview mode too...
                if self.last_live_view_time is not None and not Config.save_frames:
                    # xxx perhaps also check stats?
                    elapsed = now - self.last_live_view_time
                    # print(f"Elapsed time since last frame send: {elapsed}")
                    if elapsed > 10:
                        self.last_live_view_time = None
                        self.is_live_viewing = False
                        # If it's been more than 30 seconds since the last frame was sent, shut down things if they're running
                        self.logger.warn(f"{elapsed} seconds since last live view send.  Shutting down imager")
                        self.stop()

            sleep(3)

    def receive_message_thread_fn(self):
        self.logger.info("starting receive message: main loop")
        while True:
            threading.current_thread().last_run = datetime.datetime.now()

            if self.is_connected and self.exposure_mode is not None:
                # todo : make this something that can timeout, but don't make timeout too short...
                header = self.read_bytes(80)
                size, id, width, height = self.parse_header(header)
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
                        self.raw_img_size = [width, height]
                        if Config.save_frames:
                            try:
                                # Write the frame IFF stacking is enabled
                                image = self.get_star_preview()
                                #now = int(time())
                                now = str(datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
                                # todo :
                                # - target
                                # - unified vs per-device
                                # - name the frames based on which filter is in place
                                wheel = self.device.event_state['WheelMove']
                                image_type = "unknown"
                                image_dir = "unknown"
                                # xxx : have a config or schedule-specific setting to combine images in "unified" directory
                                target_dir = self.device_name

                                if wheel:
                                    match wheel['position']:
                                        case 0:
                                            image_type = "dark"
                                            image_dir = "dark"
                                        case 1:
                                            image_type = "lights"
                                            image_dir = "lights"
                                        case 2:
                                            image_type = "lights_lp"
                                            image_dir = "lights"

                                directory = f'{Config.save_frames_dir}/frames/{target_dir}/{image_dir}'
                                if not os.path.exists(directory):
                                    try:
                                        os.makedirs(directory)
                                    except Exception as e:
                                        self.logger.error(f"Device {self.device_name}: create directory failed: {e}")
                                filename = f'{directory}/{image_type}.{self.device_name}.{now}'
                                # filename = f'{Config.save_frames_dir}/frames/{self.device_name}/lights/lights.{self.device_name}.{now}'
                                self.logger.info(f"saving image to {filename}")
                                #print("Image:", image.shape)
                                # cv2.imwrite(f'{filename}.tif', image)

                                w = self.raw_img_size[0] or 1080
                                h = self.raw_img_size[1] or 1920
                                img = np.frombuffer(self.raw_img, np.uint16).reshape(h, w)
                                img = cv2.cvtColor(img, cv2.COLOR_BAYER_GRBG2RGB)
                                img = np.moveaxis(img, -1, 0)
                                # 1920, 1080, 3 -> 3, 1920, 1080
                                # want? 3, 1080, 1920
                                #print("after Image:", image.shape)
                                # > >> >> image.shape in row column order(3, 1920, 1080)
                                # >> > image.max(), image.min()(62498, 0)
                                # >> > image.shape, image.max(), image.min()
                                # ( (3, 1920, 1080), 62498, 0) 11: 0
                                #8
                                # PM
                                # >> > image = image.swapaxes(0, 1)
                                # >> > image = image.swapaxes(1, 2)
                                # >> > data.shape, data.max(), data.min()
                                # ( (1920, 1080, 3), 62498, 0)
                                #
                                hdu = fits.PrimaryHDU(img)
                                # img = np.frombuffer(self.raw_img, np.uint16).reshape(h, w)
                                # img = cv2.cvtColor(img, cv2.COLOR_BAYER_GRBG2BGR)
                                hdu.writeto(f'{filename}.fits', overwrite=True)
                            except Exception as e:
                                pass


                    elif id == 23:  # self.exposure_mode == "stack":
                        # for stacking, we have to extract zipfile
                        try:
                            zip_file = BytesIO(data)
                            with zipfile.ZipFile(zip_file) as zip:
                                contents = {name: zip.read(name) for name in zip.namelist()}
                                self.raw_img = contents['raw_data']
                                self.raw_img_size = [width, height]

                            # xxx Temp hack: just disconnect for now...
                            # xxx Ideally we listen for an event that stack count has increased, or we track the stack
                            #     count ourselves...
                            #if self.is_gazing and self.exposure_mode == "stack":
                            #    self.disconnect()
                            #    self.reconnect()
                        except Exception as e:
                            self.logger.error(f"Exception handling zip stack: {e}")
                    else:
                        continue

                    self.received_frame += 1
                    if self.raw_img is not None:
                        self.logger.debug(f"read image size={len(self.raw_img)}")
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
            if size > 100:
                self.logger.debug(f"header: {size=} {width=} {height=} {_s1=} {_s2=} {_s3=} {code=} {id=}") # xxx trace

            return size, id, width, height
        return 0, None, None, None

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
                            if empty_images > 200:
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
        w = self.raw_img_size[0] or 1080
        h = self.raw_img_size[1] or 1920
        if len(self.raw_img) == w * h * 6:
            # print("raw buffer size:", len(self.raw_img))
            img = np.frombuffer(self.raw_img, dtype=np.uint16).reshape(h, w, 3)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return img

        img = np.frombuffer(self.raw_img, np.uint16).reshape(h, w)
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

    def is_star_mode(self):
        return self.exposure_mode == "preview" or self.exposure_mode == "stack"

    def set_exposure_mode(self, exposure_mode):
        self.logger.info(f"changing subscription from {self.exposure_mode} to {exposure_mode}")
        # if self.exposure_mode != exposure_mode:
        self.stop()
        sleep(0.5)
        with self.lock:
            self.exposure_mode = exposure_mode
            self.start(exposure_mode)

    def start(self, new_exposure_mode=None):
        with self.lock:
            # print(f"start imaging {new_exposure_mode=} {self.exposure_mode=} {self.is_gazing=} {self.sent_subscription=}")
            self.exposure_mode = new_exposure_mode
            self.is_streaming = self.exposure_mode == "stream"
            self.is_gazing = self.is_star_mode()
            self.disconnect()
            self.reconnect()
            self.is_streaming = self.exposure_mode == "stream"
            self.is_gazing = self.is_star_mode()
            self.received_frame = 0
            self.sent_frame = 0
            self.last_frame = 0

        # xxx:
        #   try to connect if necessary?  or disconnect first, then connect if necessary
        if self.heartbeat_msg_thread is None:
            # print("CREATING THREAD get_heartbeat_thread!!!!!")
            self.heartbeat_msg_thread = threading.Thread(target=self.heartbeat_message_thread_fn, daemon=True)
            self.heartbeat_msg_thread.name = f"ImagingHeartbeatMessageThread.{self.device_name}"
            self.heartbeat_msg_thread.start()

        if self.exposure_mode == "stream":
            if self.get_stream_thread is None:
                # print("CREATING THREAD get_stream_thread!!!!!")
                self.get_stream_thread = threading.Thread(target=self.streaming_thread_fn, daemon=True)
                self.get_stream_thread.name = f"ImagingReceiveStreamThread.{self.device_name}"
                self.get_stream_thread.start()
        else:
            if self.get_image_thread is None:
                # print("CREATING THREAD get_image_thread!!!!!")
                self.get_image_thread = threading.Thread(target=self.receive_message_thread_fn, daemon=True)
                self.get_image_thread.name = f"ImagingReceiveImageThread.{self.device_name}"
                self.get_image_thread.start()

    def stop(self):
        with self.lock:
            self.disconnect()
            # self.is_connected = False
            self.is_streaming = False
            self.is_gazing = False
            self.is_live_viewing = False
            # self.sent_subscription = False
            # xxx might want to reset some things?
            self.raw_img = None
            self.raw_img_size = [None, None]
            self.last_stat_time = None
            self.last_live_view_time = None
            self.exposure_mode = None

    def blank_frame(self, message="Loading...", gif_path="/home/pi/seestar_alp/device/loading.gif"):
        #load the gif image
        try:
            with open(gif_path, 'rb') as gif_file:
                gif_data = gif_file.read()

                return (b'Content-Type: image/gif\r\n\r\n' + gif_data +self.BOUNDARY)
        except Exception as e:
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
            return (b'Content-Type: image/png\r\n\r\n' + stringData + self.BOUNDARY)

    # def blank_frame(self, message="Loading..."):

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

    def compare_set_exposure_mode(self):
        exposure_mode = None
        view_state = self.device.view_state
        # state = view_state.get("state")
        stage = view_state.get('stage')
        # mode = view_state.get('mode')
        # print(f"Compare And Set Exposure Mode {stage=} {self.exposure_mode=}")
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
            # If stage is stack, leave exposure mode alone UNLESS exposure mode isn't set.
            # if self.exposure_mode is None and  the number of stacked exposures is > 2:
            exposure_mode = 'stack'
            if self.exposure_mode != exposure_mode:
                self.start(exposure_mode)

        # xxx what other exposure modes?
        return exposure_mode

    def get_image(self, exposure_mode):
        image = None
        snr_value = None
        match exposure_mode:
            case "stream":
                # print starting RTSP stream...
                if self.raw_img is not None:
                    try:
                        image = self.raw_img
                    except Exception as e:
                        self.logger.info("exception")
                        image = None
                delay = 0.015

            case _:
                if self.raw_img is not None:
                    try:
                        image = self.get_star_preview()
                        snr_value = calculate_snr_auto(image)
                        image = self.image_stretch_graxpert(image)
                        # image = np.uint8(np.clip(image, 0, 255))
                        # image = cv2.fastNlMeansDenoisingColored(image,None,10,10,7,21)
                        # cv2.imwrite('stacked.png', image)
                    except Exception as e:
                        # if buffer is misformed, just catch error
                        self.logger.info(f"misformed buffer exception... {e}")
                        self.raw_img = None
                        self.raw_img_size = [None, None]
                        image = None
                delay = 0.5

        return image, delay, snr_value

    def build_frame_bytes(self, image):
        font = cv2.FONT_HERSHEY_COMPLEX

        dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]
        # print("Emiting frame", dt)

        w = self.raw_img_size[0] or 1080
        h = self.raw_img_size[1] or 1920
        image = cv2.putText(np.copy(image), dt,  # f'{dt} {self.received_frame}',
                            (int(w / 2 - 240), h - 70),
                            font, 1,
                            (210, 210, 210),
                            4, cv2.LINE_8)
        imgencode = cv2.imencode('.png', image)[1]
        stringData = imgencode.tobytes()
        frame = (b'Content-Type: image/png\r\n\r\n' + stringData + self.BOUNDARY)

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
        if self.raw_img is not None and self.exposure_mode is not None:
            image, _, _ = self.get_image(self.exposure_mode)
            frame = self.build_frame_bytes(image)
            yield frame
            yield frame
        else:
            yield self.blank_frame()
            yield self.blank_frame()

        # view_state = self.device.view_state
        # self.logger.info(f"mode: {self.mode} {type(self.mode)} view_state: {view_state}")

        exiting = False
        while not self.is_idle():
            exposure_mode = self.compare_set_exposure_mode()
            image, delay, snr = self.get_image(exposure_mode)

            if image is not None:
                try:
                    if self.last_frame != self.received_frame:
                        frame = self.build_frame_bytes(image)
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

                        self.last_frame = self.received_frame
                        self.snr = snr

                        yield frame
                        if not self.is_gazing:
                            yield frame
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

                    with self.lock:
                        self.raw_img = None
                        self.raw_img_size = [None, None]
            sleep(delay)

        self.stop()

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
