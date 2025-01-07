#!/usr/bin/env python3
"""
Generate a support bundle not through the UI
"""
import sys
import argparse
import os
import logging
from pathlib import Path

current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.append(parent)

from front.app import do_support_bundle, logger
from device.config import Config

class Request:
    media = {
        "desc": "",
        "getSeeStarLogs": "off"
    }
    def __init__(self, desc, logs):
        self.media["desc"] = desc
        self.media["getSeeStarLogs"] = logs

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate support bundle')
    parser.add_argument('--description', default="")
    parser.add_argument('--get_seestar_logs', action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--telescope_id', default=1)
    parser.add_argument('--outfile', default="supportbundle.zip")

    args = parser.parse_args()

    logger.setLevel(logging.INFO)

    req = Request(args.description, args.get_seestar_logs)
    zip_buffer = do_support_bundle(req, args.telescope_id)

    cwd = Path(os.getcwd())
    fpath = cwd.joinpath(cwd, args.outfile)
    with open(fpath, "wb") as f:
        f.write(zip_buffer.getbuffer())

    print(f"Support bundle written to: {fpath}")
