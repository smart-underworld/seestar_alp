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
        self.calls = []

    def start_watch_thread(self):
        return None

    def end_watch_thread(self):
        return None

    def stop_slew(self):
        self.calls.append(("stop_slew", None))
        return {"ok": True}

    def move_scope(self, axis, rate):
        self.calls.append(("move_scope", axis, rate))
        return {"ok": True}

    def goto_target(self, payload):
        self.calls.append(("goto_target", payload))
        return {"ok": True}

    def sync_target(self, payload):
        self.calls.append(("sync_target", payload))
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


def test_numeric_and_bool_put_endpoints_success_paths():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    telescope.seestar_dev[1] = FakeDevice()

    ok_cases = [
        (telescope.declinationrate, {"DeclinationRate": "0.1"}),
        (telescope.guideratedeclination, {"GuideRateDeclination": "0.2"}),
        (telescope.guideraterightascension, {"GuideRateRightAscension": "0.3"}),
        (telescope.rightascensionrate, {"RightAscensionRate": "0.4"}),
        (telescope.sideofpier, {"SideOfPier": "0"}),
        (telescope.slewsettletime, {"SlewSettleTime": "1.0"}),
        (telescope.trackingrate, {"TrackingRate": "1.0"}),
        (telescope.utcdate, {"UTCDate": "2024-01-01T00:00:00Z"}),
        (telescope.tracking, {"Tracking": "true"}),
        (telescope.doesrefraction, {"DoesRefraction": "false"}),
    ]
    for responder, media in ok_cases:
        req = DummyReq(method="PUT", extra_media=media)
        resp = DummyResp()
        responder().on_put(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] == 0, responder.__name__


def test_numeric_put_endpoints_invalid_input_return_error():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    telescope.seestar_dev[1] = FakeDevice()

    bad_cases = [
        (telescope.declinationrate, {"DeclinationRate": "nope"}),
        (telescope.guideratedeclination, {"GuideRateDeclination": "nope"}),
        (telescope.guideraterightascension, {"GuideRateRightAscension": "nope"}),
        (telescope.rightascensionrate, {"RightAscensionRate": "nope"}),
        (telescope.sideofpier, {"SideOfPier": "nope"}),
        (telescope.slewsettletime, {"SlewSettleTime": "nope"}),
        (telescope.trackingrate, {"TrackingRate": "nope"}),
    ]
    for responder, media in bad_cases:
        req = DummyReq(method="PUT", extra_media=media)
        resp = DummyResp()
        responder().on_put(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] != 0, responder.__name__


def test_command_put_endpoints_success_paths():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    device = FakeDevice()
    telescope.seestar_dev[1] = device

    ok_cases = [
        (telescope.abortslew, {}),
        (telescope.findhome, {}),
        (telescope.moveaxis, {"Axis": "1", "Rate": "2.5"}),
        (telescope.park, {}),
        (telescope.pulseguide, {"Direction": "1", "Duration": "2"}),
        (telescope.setpark, {}),
        (telescope.slewtoaltaz, {"Azimuth": "10", "Altitude": "20"}),
        (telescope.slewtoaltazasync, {"Azimuth": "10", "Altitude": "20"}),
        (telescope.slewtocoordinates, {"RightAscension": "1.5", "Declination": "2.5"}),
        (
            telescope.slewtocoordinatesasync,
            {"RightAscension": "1.5", "Declination": "2.5"},
        ),
        (telescope.slewtotarget, {}),
        (telescope.slewtotargetasync, {}),
        (telescope.synctoaltaz, {"Azimuth": "10", "Altitude": "20"}),
        (telescope.synctocoordinates, {"RightAscension": "1.5", "Declination": "2.5"}),
        (telescope.synctotarget, {}),
        (telescope.unpark, {}),
    ]
    for responder, media in ok_cases:
        req = DummyReq(method="PUT", extra_media=media)
        resp = DummyResp()
        responder().on_put(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] == 0, responder.__name__


def test_command_put_endpoints_invalid_number_inputs():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    telescope.seestar_dev[1] = FakeDevice()

    bad_cases = [
        (telescope.moveaxis, {"Axis": "x", "Rate": "1"}),
        (telescope.moveaxis, {"Axis": "1", "Rate": "x"}),
        (telescope.pulseguide, {"Direction": "x", "Duration": "1"}),
        (telescope.pulseguide, {"Direction": "1", "Duration": "x"}),
        (telescope.slewtoaltaz, {"Azimuth": "x", "Altitude": "1"}),
        (telescope.slewtoaltaz, {"Azimuth": "1", "Altitude": "x"}),
        (telescope.slewtocoordinates, {"RightAscension": "x", "Declination": "1"}),
        (telescope.slewtocoordinates, {"RightAscension": "1", "Declination": "x"}),
        (telescope.synctocoordinates, {"RightAscension": "x", "Declination": "1"}),
        (telescope.synctocoordinates, {"RightAscension": "1", "Declination": "x"}),
    ]
    for responder, media in bad_cases:
        req = DummyReq(method="PUT", extra_media=media)
        resp = DummyResp()
        responder().on_put(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] != 0, responder.__name__


def test_not_connected_on_get_responders_return_error():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    disconnected = FakeDevice()
    disconnected.is_connected = False
    telescope.seestar_dev[1] = disconnected

    responders = [
        telescope.alignmentmode,
        telescope.altitude,
        telescope.aperturearea,
        telescope.aperturediameter,
        telescope.athome,
        telescope.atpark,
        telescope.azimuth,
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
        telescope.declination,
        telescope.declinationrate,
        telescope.doesrefraction,
        telescope.equatorialsystem,
        telescope.focallength,
        telescope.guideratedeclination,
        telescope.guideraterightascension,
        telescope.ispulseguiding,
        telescope.rightascension,
        telescope.rightascensionrate,
        telescope.sideofpier,
        telescope.siderealtime,
        telescope.siteelevation,
        telescope.sitelatitude,
        telescope.sitelongitude,
        telescope.slewing,
        telescope.slewsettletime,
        telescope.targetdeclination,
        telescope.targetrightascension,
        telescope.tracking,
        telescope.trackingrate,
        telescope.trackingrates,
        telescope.utcdate,
        telescope.axisrates,
        telescope.canmoveaxis,
        telescope.destinationsideofpier,
    ]
    for responder in responders:
        req = DummyReq(method="GET")
        resp = DummyResp()
        responder().on_get(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] != 0, responder.__name__


def test_not_connected_on_put_responders_return_error():
    set_shr_logger(logging.getLogger("test-telescope-props"))
    device_exceptions.logger = DummyLogger()
    telescope.seestar_dev.clear()
    disconnected = FakeDevice()
    disconnected.is_connected = False
    telescope.seestar_dev[1] = disconnected

    put_responders = [
        telescope.declinationrate,
        telescope.doesrefraction,
        telescope.guideratedeclination,
        telescope.guideraterightascension,
        telescope.rightascensionrate,
        telescope.sideofpier,
        telescope.siteelevation,
        telescope.sitelatitude,
        telescope.sitelongitude,
        telescope.slewsettletime,
        telescope.targetdeclination,
        telescope.targetrightascension,
        telescope.tracking,
        telescope.trackingrate,
        telescope.utcdate,
        telescope.abortslew,
        telescope.findhome,
        telescope.moveaxis,
        telescope.park,
        telescope.pulseguide,
        telescope.setpark,
        telescope.slewtoaltaz,
        telescope.slewtoaltazasync,
        telescope.slewtocoordinates,
        telescope.slewtocoordinatesasync,
        telescope.slewtotarget,
        telescope.slewtotargetasync,
        telescope.synctoaltaz,
        telescope.synctocoordinates,
        telescope.synctotarget,
        telescope.unpark,
    ]
    for responder in put_responders:
        req = DummyReq(method="PUT")
        resp = DummyResp()
        responder().on_put(req, resp, devnum=1)
        payload = json.loads(resp.text)
        assert payload["ErrorNumber"] != 0, responder.__name__
