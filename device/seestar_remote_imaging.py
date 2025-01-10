import requests

from device.abstract_imager import AbstractImager


class SeestarRemoteImaging(AbstractImager):
    def __init__(self, logger, host, port, name, device_num, location, remote_offset):
        self.logger = logger
        self.host = host
        self.port = port
        self.name = name
        self.device_num = device_num
        self.location = location
        self.remote_offset = remote_offset
        self.remote_id = device_num - remote_offset

        self.base_url = f"http://{self.host}:{self.port}/{self.remote_id}"

    def get_frame(self):
        with requests.get(f'{self.base_url}/vid', stream=True) as r:
            for chunk in r.iter_content(chunk_size=None):
                self.logger.info("SeestarRemoteImaging.get_frame")
                yield chunk

    def get_live_status(self):
        r = requests.get(f'{self.base_url}/live/status', stream=True)
        for line in r.iter_lines():
            yield line + b'\n'
