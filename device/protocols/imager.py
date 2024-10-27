import threading
import zipfile
from datetime import datetime
from enum import Enum
from io import BytesIO
from struct import unpack, calcsize
from time import sleep
from typing import Optional, Tuple

import numpy as np

from device.config import Config
from device.protocols.binary import SeestarBinaryProtocol
from device.protocols.socket_base import SocketListener
from device.rtspclient import RtspClient

ExposureModes = Enum('ExposureModes', ['stream', 'preview', 'stacking'])

# todo : run processors here, since this is independent of UI
# todo : make saving code some kind of listener?

class SeestarImagerProtocol(SeestarBinaryProtocol):
    def __init__(self, logger, device_name, device_num, host, port):
        super().__init__(logger, device_name, device_num, host, port)
        # We need a receiving thread at all times for heartbeats
        self.receiving_thread = None
        self.streaming_thread = None
        self.exposure_mode: Optional[ExposureModes] = None
        self._received_frame = 0
        self.raw_img = None
        self.raw_img_size: Tuple[Optional[int], Optional[int]] = [None, None]
        self.latest_image = None

    # enable mode - stream, preview, stacking

    def is_streaming(self) -> bool:
        with self.lock:
            return self._is_started and self.exposure_mode == "stream"

    def start(self):
        super().start()
        if self.receiving_thread is None or not self.receiving_thread.is_alive():
            self.logger.info("Starting ImagingReceiverImagingThread")
            self.receiving_thread = threading.Thread(target=self.receiving_thread_fn, daemon=True)
            self.receiving_thread.name = f"ImagingReceiveThread2.{self.device_name}"
            self.receiving_thread.start()
        if self.streaming_thread is None or not self.streaming_thread.is_alive():
            self.logger.info("Starting ImagingReceiverStreamingThread")
            self.streaming_thread = threading.Thread(target=self.streaming_thread_fn, daemon=True)
            self.streaming_thread.name = f"ImagingReceiveStreamingThread2.{self.device_name}"
            self.streaming_thread.start()

    def stop(self):
        super().stop()
        if self.receiving_thread is not None and self.receiving_thread.is_alive():
            self.logger.info("Stopping ImagingReceiveImagingThread")
            self.receiving_thread.join()
            self.receiving_thread = None
        if self.streaming_thread is not None and self.streaming_thread.is_alive():
            self.logger.info("Stopping ImagingReceiveStreamingThread")
            self.streaming_thread.join()
            self.streaming_thread = None

    def set_exposure_mode(self, exposure_mode: ExposureModes):
        with self.lock:
            #print(f"Changing exposure mode to {exposure_mode} from {self.exposure_mode}")
            self.exposure_mode = exposure_mode

    def get_image(self) -> Tuple[Optional[np.ndarray], Optional[int], Optional[int]]:
        with self.lock:
            return self.latest_image, self.raw_img_size[0], self.raw_img_size[1]

    def received_frame(self) -> int:
        with self.lock:
            return self._received_frame

    def receiving_thread_fn(self):
        self.logger.info("starting image receiving thread")

        while self.is_started():
            #print("RECEIVING non-stream image loop")
            threading.current_thread().last_run = datetime.now()

            self._run_receive_message()

        self.logger.info("STOPPING image receiving thread")

    def streaming_thread_fn(self):
        self.logger.info("starting image stream receiving thread")

        while self.is_started():
            # print("RECEIVING stream loop")
            threading.current_thread().last_run = datetime.now()

            # todo : check exposure mode too!
            if self.is_streaming():
                # print("Streaming loop")
                self._run_streaming_loop()

            sleep(1)  # Wait a second before trying to reconnect...

        self.logger.info("STOPPING image stream receiving thread")

    def _run_receive_message(self):
        if self.is_connected():
            header = self.recv_exact(80)
            size, _id, width, height = self._parse_header(header)
            data = None
            if size is not None:
                data = self.recv_exact(size)

            # This isn't a payload message, so skip it.  xxx: probably header item to indicate this...
            if size < 1000:
                return

            if data is not None:
                if _id == 21: # Preview frame
                    self.handle_preview_frame(width, height, data)
                elif _id == 23:
                    self.handle_stack(width, height, data)
                else:
                    return

                self._received_frame += 1
                if self.raw_img is not None:
                    self.logger.debug(f"read image size={len(self.raw_img)}")
                # todo : run on message listeners here!
        else:
            # If we aren't connected, just wait...
            sleep(1)

    def _run_streaming_loop(self):
        try:
            empty_images = 0
            with RtspClient(rtsp_server_uri=f'rtsp://{self.host}:4554/stream', logger=self.logger,
                            verbose=True) as client:
                # self.raw_img = np.copy(client.read(raw=True))
                # self.received_frame += 1

                while self.is_streaming():
                    image = client.read(raw=True)
                    with self.lock:
                        if image is not None and not np.array_equal(image, self.raw_img):
                            # print("received frame")
                            # RTSP is async, so when we read we might get the same frame back.
                            # We could adjust the Rtsp code, but for now just going to brute force compare
                            # frames.
                            self.raw_img = np.copy(image)
                            self.latest_image = self.raw_img
                            self._received_frame += 1
                            empty_images = 0  # Reset counter...

                            if self._received_frame % 100 == 0:
                                self.logger.debug(f"Read {self._received_frame} images {self.is_streaming=}")
                        else:
                            empty_images += 1

                    sleep(0.025)

                    # Let it fail for a few seconds before attempting a reconnect...
                    if empty_images > 200:
                        self.logger.info("empty image threshold exceeded.  reconnecting")
                        break
        except Exception as e:
            self.logger.error(f"Exception in stream thread... {e=}")



    def _parse_header(self, header) -> Tuple[int, Optional[int], Optional[int], Optional[int]]:
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

    def handle_preview_frame(self, width, height, data):
        self.raw_img = data
        self.raw_img_size = [width, height]
        if Config.save_frames:
            # save the raw frames
            pass

    def handle_stack(self, width, height, data):
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
            # if self.is_gazing and self.exposure_mode == "stack":
            #    self.disconnect()
            #    self.reconnect()
        except Exception as e:
            self.logger.error(f"Exception handling zip stack: {e}")
            self.raw_img = None
            self.raw_img_size = [None, None]
