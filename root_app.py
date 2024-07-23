#
# Start frontend and pass in ALP for it to manage
#
from front.app import main as front_app
from device.app import DeviceMain

import device.log

if __name__ == "__main__":
    # We want to initialize ALP logger
    logger = device.log.init_logging()

    front_app(DeviceMain)
