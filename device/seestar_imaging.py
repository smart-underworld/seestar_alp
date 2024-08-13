#
# seestar_imaging - performances image-related tasks with a Seestar
#
# This is just the beginning
#


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

    def __repr__(self):
        return f"{type(self).__name__}(host={self.host}, port={self.port})"

    def reconnect(self):
        pass

    def disconnect(self):
        pass

    def send_message(self, data):
        pass

    def receive_message(self):
        pass
