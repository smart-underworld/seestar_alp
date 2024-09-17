#
# Start frontend and pass in ALP for it to manage
#
import falcon
from flask import Flask, Response
import threading
import time
import sys
import os
import waitress

from front.app import FrontMain

if not getattr(sys, "frozen", False):  # if we are not running from a bundled app
    sys.path.append(os.path.join(os.path.dirname(__file__), "device"))

from device.app import DeviceMain     # type: ignore
from config import Config      # type: ignore
import log                     # type: ignore
import telescope               # type: ignore

import os

class AppRunner:
    def __init__(self, log, name, app_main):
        self.name = name
        self.logger = log
        self.thread = None
        self.app_main = app_main()

    def start(self):
        self.logger.info(f"Starting {self.name}")
        self.thread = threading.Thread(target=self.runner, args=(1,), daemon=True)
        self.thread.name = f"{self.name}MainThread"
        self.thread.start()

    # def on_get_start(self, req, resp):
    #     self.start()
    #     resp.status = falcon.HTTP_200
    #     resp.content_type = 'application/text'
    #     resp.text = 'Started, yo!'
    #
    # def on_get_stop(self, req, resp):
    #     self.logger.info(f"Stopping {self.name}")
    #     self.app_main.stop()
    #     self.thread.join()
    #     resp.status = falcon.HTTP_200
    #     resp.content_type = 'application/text'
    #     resp.text = 'Stopped'

    def get_imager(self, device_num: int):
        return self.app_main.get_imager(device_num)

    def runner(self, name):
        self.logger.info(f"Seestar{self.name} %s: starting", name)
        self.app_main.start()
        self.logger.info(f"Seestar{self.name} %s: finishing", name)

    def join(self):
        self.thread.join()


if __name__ == "__main__":
    if Config.rtsp_udp:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp"
    # We want to initialize ALP logger
    logger = log.init_logging()

    logger.info("Starting ALP web server")
    main = AppRunner(logger, "ALP", DeviceMain)
    main.start()
    time.sleep(1)

    logger.info("Starting Front web server")
    front = AppRunner(logger, "Front", FrontMain)
    front.start()

    time.sleep(1)

    if Config.experimental:
        logger.info("Setting up imaging web server")
        app = Flask(__name__)


        @app.route("/<dev_num>/vid/status")
        def vid_status(dev_num):
            return Response(telescope.get_seestar_imager(int(dev_num)).get_video_status(),
                            mimetype='text/event-stream')


        @app.route('/<dev_num>/vid')
        def vid(dev_num):
            return Response(telescope.get_seestar_imager(int(dev_num)).get_frame(),
                            mimetype='multipart/x-mixed-replace; boundary=frame')

        print("Startup Complete")
        waitress.serve(app, host=Config.ip_address, port=Config.imgport)
    else:
        print("Startup Complete")
        front.join()
