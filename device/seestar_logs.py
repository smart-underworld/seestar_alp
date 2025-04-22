#
# seestar_logs - Collects logs from seestar
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
from flask import Flask, render_template, Response

import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

import log


class SeestarLogging:
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
        self.raw_img = None
        self.s = None
        self.is_connected = False
        self.device = device
        self.get_logging_thread = None
        self.raw_log = None

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
            self.s.sendall(
                data.encode()
            )  # TODO: would utf-8 or unicode_escaped help here
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

    def send_get_server_log(self):
        self.logger.info(f"sending get_server_log")
        self.send_message('{"id": 44, "method": "get_server_log"}' + "\r\n")

    def receive_message_thread_fn(self):
        self.logger.info("starting receive message: main loop")
        while True:
            threading.current_thread().last_run = datetime.datetime.now()

            if self.is_connected:
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
                    if id == 44:
                        self.raw_log = data
                    else:
                        continue

                    self.logger.info(f"read log size={len(self.raw_log)}")
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
            self.logger.debug(
                f"header: {size=} {width=} {height=} {_s1=} {_s2=} {_s3=} {code=} {id=}"
            )

            return size, id
        return 0, None

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
            self.logger.error(f"Device {self.device_name}: read Socket error: {e}")
            self.disconnect()
            return None

        if data is None or len(data) == 0:
            return None

        # self.logger.debug(f'{self.device_name} received : {len(data)}')
        self.logger.debug(f"{self.device_name} received : {len(data)}")
        dl = len(data)
        if dl < 100 and dl != 80:
            self.logger.debug(f"Message: {data}")
        return data

    def start(self):
        self.reconnect()
        self.get_logging_thread = threading.Thread(
            target=self.receive_message_thread_fn, daemon=True
        )
        self.get_logging_thread.name = f"LoggingReceiveImageThread.{self.device_name}"
        self.get_logging_thread.start()

    def stop(self):
        # self.get_logging_thread.join()
        self.disconnect()

    def get_logs_sync(self):
        self.start()
        self.send_get_server_log()
        while self.raw_log is None:
            self.logger.info("waiting...")
            sleep(2)

        self.stop()
        return self.raw_log


if __name__ == "__main__":
    app = Flask(__name__)

    host, port, device_num, listen_port = (
        sys.argv[1],
        int(sys.argv[2]),
        int(sys.argv[3]),
        int(sys.argv[4]),
    )
    logger = log.init_logging()
    dev_log = SeestarLogging(logger, host, port, "SeestarB", device_num)

    dev_log.start()

    @app.route("/getlogs")
    def getlogs():
        f = open("test.zip", "wb+")
        f.write(dev_log.raw_log)
        f.close()

        return Response(
            dev_log.get_logs_sync(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    app.run(host="localhost", port=listen_port, debug=True)  # , threaded=True)
