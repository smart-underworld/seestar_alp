#
# Start frontend and pass in ALP for it to manage
#
from pathlib import Path

import pkg_resources
import sys
import os

def launch_app():
    from front.app import main as front_app
    from device.app import DeviceMain
    import device.log

    # We want to initialize ALP logger
    logger = device.log.init_logging()

    front_app(DeviceMain)

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)

    p = Path(__file__).with_name("requirements.txt")
    try:
       pkg_resources.require(open(p, mode='r'))
    except Exception as e:
       print(f"ERROR: pip requirement not satisfied. Please run 'pip install -r requirements.txt'\n{e}")
       sys.exit(255)

    launch_app()
