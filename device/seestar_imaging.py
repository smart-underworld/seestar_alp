#
# seestar_imaging - performances image-related tasks with a Seestar
#
# New config settings:
# .   experimental
# .   max_stream_fps. (can set this number lower if you have network constraints)
#
# This is just the beginning
#
import socket
import threading
import zipfile
from copy import deepcopy
from io import BytesIO
from struct import unpack, calcsize
from time import sleep, time
import sys
import os
from PIL import Image
from astropy.visualization.stretch import SinhStretch, LinearStretch
from astropy.visualization import ImageNormalize
from auto_stretch.stretch import Stretch
from skimage import exposure

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

import log
from rtspclient import RtspClient


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

    def __init__(self, logger, host, port, device_name, device_num):
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
        self.mode = None
        self.exposure_mode = None  # "stream"  # None | preview | stack | stream
        self.received_frame = 0
        self.sent_frame = 0
        self.last_frame = 0
        self.get_image_thread = None
        self.get_stream_thread = None

        # Metrics
        self.last_stat_time = None
        self.last_stat_frames = None

    def __repr__(self):
        return f"{type(self).__name__}(host={self.host}, port={self.port})"

    def set_mode(self, mode):
        if self.mode != mode:
            print(f"CHANGING mode from {self.mode} to {mode}")
            self.stop()
            self.mode = mode
            match mode:
                case 'sun':
                    self.exposure_mode = 'stream'
                case 'moon':
                    self.exposure_mode = 'stream'
                case 'scenery':
                    self.exposure_mode = 'stream'
                case 'planet':
                    self.exposure_mode = 'stream'
                case 'star':
                    self.exposure_mode = 'stack'  # it could stack or preview (need to check)
                case _:
                    self.exposure_mode = None

            if self.exposure_mode is not None:
                self.start()
        if not self.is_connected and (self.exposure_mode == 'stack' or self.exposure_mode == 'preview'):
            # If we aren't connected, start
            self.start()

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
            print("connected")
            return True
        except socket.error as e:
            # Let's just delay a fraction of a second to avoid reconnecting too quickly
            self.is_connected = False
            sleep(0.1)
            return False

    def disconnect(self):
        print("disconnect")
        self.is_connected = False
        if self.s:
            try:
                self.s.close()
                self.s = ""
            except:
                pass

    def send_message(self, data):
        print("sending message:", data)
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

    def start(self):
        self.reconnect()
        if self.exposure_mode == "stream":
            self.is_streaming = True
        self.received_frame = 0
        self.sent_frame = 0
        self.last_frame = 0
        # xxx:
        #   try to connect if necessary?  or disconnect first, then connect if necessary
        if self.exposure_mode == "stream":
            if self.get_stream_thread is None:
                self.get_stream_thread = threading.Thread(target=self.streaming_thread_fn, daemon=True)
                self.get_stream_thread.name = f"ReceiveStreamThread.{self.device_name}"
                self.get_stream_thread.start()
        else:
            if self.get_image_thread is None:
                self.get_image_thread = threading.Thread(target=self.receive_message_thread_fn, daemon=True)
                self.get_image_thread.name = f"ReceiveImageThread.{self.device_name}"
                self.get_image_thread.start()

            if self.exposure_mode == "stack":
                self.send_message('{"id": 23, "method": "get_stacked_img"}' + "\r\n")
            else:
                self.send_message('{  "id" : 21,  "method" : "begin_streaming"}' + "\r\n")

    def stop(self):
        self.disconnect()
        # xxx might want to reset some things?
        self.raw_img = None
        self.is_streaming = False
        self.is_connected = False

    def receive_message_thread_fn(self):
        # read and discard the initial header
        if self.exposure_mode == "preview":
            print("starting receive message: starting read initial header")
            header = self.read_bytes(80)
            size = self.parse_header(header)
            self.read_bytes(size)
        print("starting receive message: main loop")
        while True:
            if self.is_connected:
                # todo : make this something that can timeout, but don't make timeout too short...
                header = self.read_bytes(80)
                size = self.parse_header(header)
                data = None
                if size is not None:
                    data = self.read_bytes(size)

                if data is not None:
                    if self.exposure_mode == "preview":
                        self.raw_img = data
                    else:
                        # for stacking, we have to extract zipfile
                        zip_file = BytesIO(data)
                        with zipfile.ZipFile(zip_file) as zip:
                            contents = {name: zip.read(name) for name in zip.namelist()}
                            self.raw_img = contents['raw_data']

                        # Temp hack: just disconnect for now...
                        self.disconnect()

                    self.received_frame += 1
                    print("read image", len(self.raw_img))
            else:
                # If we aren't connected, just wait...
                sleep(1)

    def parse_header(self, header):
        if header is not None and len(header) > 20:
            print(type(header))
            print("Header:", ":".join("{:02x}".format(c) for c in header))
            # We ignore all values at end of header...
            header = header[:20]
            fmt = ">HHHIHHHHH"
            print("size:", calcsize(fmt))
            _s1, _s2, _s3, size, _s5, _s6, _s7, width, height = unpack(fmt, header)
            print(f"header: {size=} {width=} {height=} {_s1=} {_s2=} {_s3=}")

            return size
        return 0

    def streaming_thread_fn(self):
        print("starting streaming thread")
        ip = "192.168.42.251"
        # ip="10.0.0.1"
        while True:
            if self.is_streaming:
                try:
                    empty_images = 0
                    with RtspClient(rtsp_server_uri=f'rtsp://{ip}:4554/stream', verbose=True) as client:
                        self.raw_img = client.read(raw=True)
                        self.received_frame += 1

                        while self.is_streaming:
                            image = client.read(raw=True)
                            if image is not None:
                                self.raw_img = image
                                self.received_frame += 1
                                empty_images = 0  # Reset counter...
                            else:
                                empty_images += 1

                            sleep(0.025)

                            if empty_images > 10:
                                print("empty image threshold exceeded.  reconnecting")
                                break
                except Exception as e:
                    print(f"Exception in stream thread... {e=}")

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
        print(f'{self.device_name} received : {len(data)}')
        return data

    def get_star_preview(self):
        if self.exposure_mode == "stack":
            # img = np.frombuffer(self.raw_img, dtype=np.uint16, count=-1)
            img = np.frombuffer(self.raw_img, dtype=np.uint16).reshape(1920, 1080, 3)

            #img_in_range_0to1 = img.astype(np.float32) / (
            #       2 ** 16 - 1)  # Convert to type float32 in range [0, 1] (before applying gamma correction).
            #gamma_img = lin2rgb(img_in_range_0to1)
            #gamma_img = np.round(gamma_img * 255).astype(
            #   np.uint8)  # Convert from range [0, 1] to uint8 in range [0, 255].

            #f = open("stacked.raw", "wb")
            #f.write(self.raw_img)
            #f.close()
            #gamma_img = gamma_img * 1.1
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            # cv2.imwrite('stacked.gamma.tiff', img)

            return img  # Image.fromarray(img, 'RGB')

        img = np.frombuffer(self.raw_img, np.uint16).reshape(1920, 1080)
        # img = (img >> 8) + (img << 8) # Convert big endian to little endian
        img = cv2.cvtColor(img, cv2.COLOR_BAYER_GRBG2BGR)

        # img_in_range_0to1 = img.astype(np.float32) / (
        #        2 ** 16 - 1)  # Convert to type float32 in range [0, 1] (before applying gamma correction).
        # gamma_img = lin2rgb(img_in_range_0to1)
        # gamma_img = np.round(gamma_img * 255).astype(
        #    np.uint8)  # Convert from range [0, 1] to uint8 in range [0, 255].

        ## gamma_img = gamma_img * 1.1

        # New to debayer here!

        return img

    def image_stretch(self, img):
        # stretched_image = Stretch().stretch(img)
        # return stretched_image
        # https://scikit-image.org/docs/stable/auto_examples/color_exposure/plot_equalize.html
        # Contrast stretching
        p2, p98 = np.percentile(img, (2, 99.5))
        # p2, p98 = np.percentile(img, (2, 98))
        img_rescale = exposure.rescale_intensity(img, in_range=(p2, p98))

        # Equalization
        # img_eq = exposure.equalize_hist(img)

        # Adaptive Equalization
        # img_adapteq = exposure.equalize_adapthist(img, clip_limit=0.03)

        return img_rescale

    def get_frame(self, mode=None):
        self.set_mode(mode)
        print("mode:", self.mode, type(self.mode))
        if self.mode is None or self.mode == "None":
            print("returning none")
            return ""

        while True:
            image = None
            match self.exposure_mode:
                case "stream":
                    # print starting RTSP stream...
                    if self.raw_img is not None:
                        try:
                            image = self.raw_img
                        except Exception as e:
                            print("exception")
                            image = None
                    delay = 0.025

                case _:
                    if self.raw_img is not None:
                        try:
                            image = self.get_star_preview()
                            image = self.image_stretch(image)
                            cv2.imwrite('stacked.png', image)
                        except Exception as e:
                            # if buffer is misformed, just catch error
                            print(f"misformed buffer exception... {e}")
                            image = None
                    delay = 0.5

            if image is not None:
                try:
                    if self.last_frame != self.received_frame:
                        imgencode = cv2.imencode('.png', image)[1]
                        stringData = imgencode.tobytes()
                        print("sending frame", len(stringData))

                        # Update stats!
                        self.sent_frame += 1

                        now = int(time())
                        if self.last_stat_time != now:
                            if self.last_stat_frames is not None and self.last_stat_frames is not None:
                                elapsed = now - self.last_stat_time
                                frames = self.sent_frame - self.last_stat_frames
                                print(
                                    f"Sent frames: {frames} in {elapsed} seconds.  FPS: {frames / elapsed}.  Received frame total: {self.received_frame}")

                            self.last_stat_time = now
                            self.last_stat_frames = self.sent_frame

                        self.last_frame = self.received_frame

                        frame = (b'--frame\r\n' b'Content-Type: image/png\r\n\r\n' + stringData + b'\r\n')
                        # If stack mode, we just do one and done.
                        if self.exposure_mode == "stack":
                            yield frame
                            return
                        else:
                            yield frame
                    else:
                        pass
                        # print("skipping send")
                except Exception as e:
                    # self.raw_img = None
                    print(f"exception encoding frame. skipping {e=}")

            sleep(delay)

            # l = -1
            # if image is not None:
            #     l = len(image)
            # print("frame", frame, self.is_connected, l, self.raw_img is not None)


from flask import Flask, render_template, Response
import numpy as np
import cv2
import sys
import numpy
import os

app = Flask(__name__)


def lin2rgb(im):
    """ Convert im from "Linear sRGB" to sRGB - apply Gamma. """
    # sRGB standard applies gamma = 2.4, Break Point = 0.00304 (and computed Slope = 12.92)
    # lin2rgb MATLAB functions uses the exact formula [we may approximate it to power of (1/gamma)].
    g = 2.4
    bp = 0.00304
    inv_g = 1 / g
    sls = 1 / (g / (bp ** (inv_g - 1)) - g * bp + bp)
    fs = g * sls / (bp ** (inv_g - 1))
    co = fs * bp ** (inv_g) - sls * bp

    srgb = im.copy()
    srgb[im <= bp] = sls * im[im <= bp]
    srgb[im > bp] = np.power(fs * im[im > bp], inv_g) - co
    return srgb


logger = log.init_logging()
imager = SeestarImaging(logger, "192.168.42.251", 4800, 'SeestarB', 1)
imager.set_mode(None)  # Perhaps not necessary?


# imager.reconnect()  # not in stream mode!
# imager.start()


@app.route('/vid/<mode>')
def vid(mode):
    return Response(imager.get_frame(mode), mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    app.run(host='localhost', port=6543, debug=True)  # , threaded=True)
