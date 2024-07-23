#
# Runs device and frontend in separate threads
#

import logging
import threading

from front.app import main as front_app
from device.app import DeviceMain

import device.log
#from device.log import init_logging

def seestar_alp(name):
    logging.info("SeestarAlp %s: starting", name)
    main = DeviceMain()
    main.start()
    logging.info("SeestarAlp %s: finishing", name)

def frontend(name):
    logging.info("Frontend %s: starting", name)
    front_app()
    logging.info("Frontend %s: done", name)

if __name__ == "__main__":
    # We want to initialize ALP logger
    logger = device.log.init_logging()
    #logger = logging.getLogger()
    #logger.setLevel(logging.DEBUG)

    #formatter = logging.Formatter('%(asctime)s.%(msecs)03d %(levelname)s ROOT %(message)s', '%Y-%m-%dT%H:%M:%S')
    #formatter.converter = time.gmtime  # UTC time

    #ch = logging.StreamHandler()
    #ch.setFormatter(formatter)

    #logger.addHandler(ch)

    front_app(DeviceMain)

    #fe = threading.Thread(target=frontend,    args=(1,))
    #be = threading.Thread(target=seestar_alp, args=(2,))

    #fe.start()
    #be.start()

    #logging.info("Main    : before running thread")
    #fe.start()
    #logging.info("Main    : wait for the thread to finish")
    # x.join()
    logging.info("Main : startup complete")

