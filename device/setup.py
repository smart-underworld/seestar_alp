# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# setup.py - Device setup endpoints.
#
# Part of the AlpycaDevice Alpaca skeleton/template device driver
#
# Author:   Robert B. Denny <rdenny@dc3.com> (rbd)
#
# Python Compatibility: Requires Python 3.7 or later
# GitHub: https://github.com/ASCOMInitiative/AlpycaDevice
#
# -----------------------------------------------------------------------------
# MIT License
#
# Copyright (c) 2022 Bob Denny
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# -----------------------------------------------------------------------------
# Edit History:
# 27-Dec-2022   rbd V0.1 Initial edit. Simply say no GUI.
# 30-Dec-2022   rbd V0.1 Device number captured and sent to responder
#
from falcon import Request, Response
from device.shr import PropertyResponse, DeviceMetadata, log_request


class svrsetup:
    def on_get(self, req: Request, resp: Response):
        log_request(req)
        resp.content_type = "text/html"
        resp.text = "<!DOCTYPE html><html><body><h2>Server setup is in config.toml</h2></body></html>"


class devsetup:
    def on_get(self, req: Request, resp: Response, devnum: str):
        resp.content_type = "text/html"
        log_request(req)
        resp.text = "<!DOCTYPE html><html><body><h2>Device setup is in config.toml</h2></body></html>"
