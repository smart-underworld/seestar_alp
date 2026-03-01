import json
import logging

from device import exceptions as device_exceptions
from device import telescope
from device.shr import set_shr_logger


class DummyReq:
    method = "GET"
    remote_addr = "127.0.0.1"
    path = "/api/v1/telescope/1/prop"
    query_string = ""

    def __init__(self, method="GET", extra_media=None):
        self.method = method
        self.params = {"ClientID": "1", "ClientTransactionID": "2"}
        self._media = {"ClientID": "1", "ClientTransactionID": "2"}
        if extra_media:
            self._media.update(extra_media)
        self.content_length = len(json.dumps(self._media))

    @property
    def media(self):
        return self._media

    def get_media(self):
        return self._media


class DummyResp:
    def __init__(self):
        self.text = ""


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def warn(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class FakeDevice:
    def __init__(self):
        self.is_connected = True
        self.ra = 1.23
        self.dec = 4.56
        self.site_elevation = 123.0
        self.site_latitude = 40.0
        self.site_longitude = -70.0
        self.is_slewing = False
        self.target_dec = 11.0
        self.target_ra = 22.0
        self.utcdate = 1000.0

    def start_watch_thread(self):
        return None

    def end_watch_thread(self):
        return None

    def stop_slew(self):
        return {"ok": True}


def call_get(resource_cls):
    req = DummyReq(method="GET")
    resp = DummyResp()
    resource_cls().on_get(req, resp, devnum=1)
    return json.loads(resp.text)


def test_many_simple_property_responders_return_value():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    telescope.seestar_dev[1] = FakeDevice()

    responders = [
        telescope.description,
        telescope.driverinfo,
        telescope.interfaceversion,
        telescope.driverversion,
        telescope.name,
        telescope.supportedactions,
        telescope.alignmentmode,
        telescope.canfindhome,
        telescope.canpark,
        telescope.canpulseguide,
        telescope.cansetdeclinationrate,
        telescope.cansetguiderates,
        telescope.cansetpark,
        telescope.cansetpierside,
        telescope.cansetrightascensionrate,
        telescope.cansettracking,
        telescope.canslew,
        telescope.canslewaltaz,
        telescope.canslewaltazasync,
        telescope.canslewasync,
        telescope.cansync,
        telescope.cansyncaltaz,
        telescope.canunpark,
        telescope.doesrefraction,
        telescope.equatorialsystem,
        telescope.focallength,
        telescope.guideratedeclination,
        telescope.guideraterightascension,
        telescope.ispulseguiding,
        telescope.rightascension,
        telescope.sideofpier,
        telescope.siderealtime,
        telescope.siteelevation,
        telescope.sitelatitude,
        telescope.sitelongitude,
        telescope.slewing,
        telescope.slewsettletime,
        telescope.tracking,
        telescope.trackingrate,
        telescope.trackingrates,
        telescope.utcdate,
    ]
    for responder in responders:
        payload = call_get(responder)
        assert payload["ErrorNumber"] == 0, responder.__name__
        assert "Value" in payload, responder.__name__


def test_settable_property_put_endpoints_update_device_state():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    device = FakeDevice()
    telescope.seestar_dev[1] = device

    put_cases = [
        (telescope.siteelevation, {"SiteElevation": "250.5"}, "site_elevation", 250.5),
        (telescope.sitelatitude, {"SiteLatitude": "41.1"}, "site_latitude", 41.1),
        (telescope.sitelongitude, {"SiteLongitude": "-71.2"}, "site_longitude", -71.2),
        (
            telescope.targetdeclination,
            {"TargetDeclination": "12.2"},
            "target_dec",
            12.2,
        ),
        (
            telescope.targetrightascension,
            {"TargetRightAscension": "13.3"},
            "target_ra",
            13.3,
        ),
    ]
    for responder, media, attr, expected in put_cases:
        req = DummyReq(method="PUT", extra_media=media)
        resp = DummyResp()
        responder().on_put(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] == 0
        assert getattr(device, attr) == expected
