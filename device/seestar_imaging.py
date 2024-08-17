#
# seestar_imaging - performances image-related tasks with a Seestar
#
# This is just the beginning
#
import socket
import threading
import zipfile
from io import BytesIO
from struct import unpack, calcsize
from time import sleep
import sys
import os
import rtsp
from astropy.visualization.stretch import SinhStretch, LinearStretch
from astropy.visualization import ImageNormalize

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

import log


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
        self.mode = "preview"  # preview | stack | stream
        self.frame = 0

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
            print("connected")
            return True
        except socket.error as e:
            # Let's just delay a fraction of a second to avoid reconnecting too quickly
            self.is_connected = False
            sleep(0.1)
            return False

    def disconnect(self):
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
        if self.mode != "stream":
            self.get_image_thread = threading.Thread(target=self.receive_message_thread_fn, daemon=True)
            self.get_image_thread.name = f"ReceiveImageThread.{self.device_name}"
            self.get_image_thread.start()

            if self.mode == "stack":
                self.send_message('{"id": 23, "method": "get_stacked_img"}' + "\r\n")
            else:
                self.send_message('{  "id" : 21,  "method" : "begin_streaming"}' + "\r\n")
        else:
            self.get_stream_thread = threading.Thread(target=self.streaming_thread_fn, daemon=True)
            self.get_stream_thread.name = f"ReceiveStreamThread.{self.device_name}"
            self.get_stream_thread.start()

    def receive_message_thread_fn(self):
        # read and discard the initial header
        if self.mode == "preview":
            print("starting receive message: starting read initial header")
            header = self.read_bytes(80)
            size = self.parse_header(header)
            self.read_bytes(size)
        print("starting receive message: main loop")
        while self.is_connected:
            # todo : make this something that can timeout, but don't make timeout too short...
            header = self.read_bytes(80)
            size = self.parse_header(header)
            data = None
            if size is not None:
                data = self.read_bytes(size)

            if data is not None:
                if self.mode == "preview":
                    self.raw_img = data
                else:
                    # for stacking, we have to extract

                    zip_file = BytesIO(data)
                    with zipfile.ZipFile(zip_file) as zip:
                        contents = {name: zip.read(name) for name in zip.namelist()}
                        self.raw_img = contents['raw_data']

                print("read image", len(self.raw_img))

    def parse_header(self, header):
        if header is not None and len(header) > 20:
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
        with rtsp.Client(rtsp_server_uri='rtsp://192.168.42.251:4554/stream', verbose=True) as client:
            self.raw_img = client.read()
            self.frame += 1

            print("getting image", self.frame)
            while True:
                if self.frame % 30 == 0:
                    print("getting image", self.frame)
                image = client.read(raw=True)
                if image is not None:
                    self.raw_img = image
                    self.frame += 1
                sleep(0.025)

    def read_bytes(self, num):
        try:
            data = self.s.recv(num, socket.MSG_WAITALL)  # comet data is >50kb
        except socket.timeout:
            return None
        except socket.error as e:
            # todo : if general socket error, close socket, and kick off reconnect?
            # todo : no route to host...
            # self.logger.error(f"Device {self.device_name}: read Socket error: {e}")
            self.disconnect()
            if self.reconnect():
                return self.get_socket_msg()
            return None

        # data = data.decode("utf-8")
        if len(data) == 0:
            return None

        # self.logger.debug(f'{self.device_name} received : {len(data)}')
        print(f'{self.device_name} received : {len(data)}')
        return data

    def get_star_preview(self):
        size = np.uint16
        if self.mode == "stack":
            size = np.uint32
        img = np.frombuffer(self.raw_img, size).reshape(1920, 1080)
        img_in_range_0to1 = img.astype(np.float32) / (
                2 ** 16 - 1)  # Convert to type float32 in range [0, 1] (before applying gamma correction).
        gamma_img = lin2rgb(img_in_range_0to1)
        gamma_img = np.round(gamma_img * 255).astype(
            np.uint8)  # Convert from range [0, 1] to uint8 in range [0, 255].

        # gamma_img = gamma_img * 1.1

        return gamma_img

    def get_star_stack(self):
        pass

    def get_stream(self):
        pass

    # client.preview()

    def get_frame(self):
        frame = 1
        while True:
            image = None
            match self.mode:
                case "stream":
                    # print starting RTSP stream...
                    if self.raw_img is not None:
                        image = self.raw_img
                        # imgencode = cv2.imencode('.jpg', self.raw_img)[1]
                        # stringData = imgencode.tobytes()
                    delay = 0.05

                case _:
                    if self.is_connected and self.raw_img is not None:
                        frame += 1
                        image = self.raw_img  # self.get_star_preview()
                    delay = 0.5

            if image is not None:
                # print("yielding")
                # stretch = LinearStretch(slope=0.5, intercept=0.5) + SinhStretch() + \
                #          LinearStretch(slope=2, intercept=-1)
                ## ImageNormalize normalizes values to [0,1] before applying the stretch
                # norm = ImageNormalize(stretch=stretch, vmin=-5, vmax=5)

                try:
                    imgencode = cv2.imencode('.jpg', image)[1]
                    stringData = imgencode.tobytes()
                    print("sending frame")
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + stringData + b'\r\n')
                except Exception as e:
                    self.raw_img = None
                    print(f"exception encoding frame. skipping {e=}")

            sleep(delay)

            l = -1
            if self.raw_img is not None:
                l = len(self.raw_img)
            print("frame", frame, self.is_connected, l)


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


# def get_frame():
#     f = open(os.path.join(os.path.dirname(__file__), '../experimental/test_video2.txt'), 'rb')
#
#     Skip header(s)
# f.read(80)
# s = f.read(4)
# print(s)
# f.read(80)
#
# data = f.read(1080 * 1920 * 2)
# inc = 1.1
# frame = 1
# while True:
#     img = np.frombuffer(data, np.uint16).reshape(1920, 1080)
#     img_in_range_0to1 = img.astype(np.float32) / (
#             2 ** 16 - 1)  # Convert to type float32 in range [0, 1] (before applying gamma correction).
#     gamma_img = lin2rgb(img_in_range_0to1)
#     gamma_img = np.round(gamma_img * 255).astype(np.uint8)  # Convert from range [0, 1] to uint8 in range [0, 255].
#
#     gamma_img = gamma_img * 1.5
#     imgencode = cv2.imencode('.jpg', gamma_img)[1]
#     stringData = imgencode.tostring()
#     frame += 1
#     sleep(0.5)
#     print("frame", frame, inc)
#     yield (b'--frame\r\n'
#            b'Content-Type: text/plain\r\n\r\n' + stringData + b'\r\n')

# cleanup?


logger = log.init_logging()
imager = SeestarImaging(logger, "192.168.42.251", 4800, 'SeestarB', 1)
imager.reconnect()  # not in stream mode!
imager.start()


@app.route('/vid')
def vid():
    return Response(imager.get_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    app.run(host='localhost', port=6543, debug=True, threaded=True)
