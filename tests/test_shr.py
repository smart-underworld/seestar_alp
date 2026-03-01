from collections import deque
import json
import logging

import falcon
import pytest

from device import shr


class DummyReq:
    def __init__(
        self,
        method="GET",
        params=None,
        media=None,
        path="/api/v1/telescope/1/name",
        remote_addr="127.0.0.1",
    ):
        self.method = method
        self.params = params or {}
        self._media = media or {}
        self.path = path
        self.remote_addr = remote_addr
        self.query_string = "&".join([f"{k}={v}" for k, v in self.params.items()])
        self.content_length = len(json.dumps(self._media)) if self._media else 0

    @property
    def media(self):
        return self._media

    def get_media(self):
        return self._media


@pytest.fixture(autouse=True)
def setup_logger():
    shr.set_shr_logger(logging.getLogger("test-shr"))


def test_to_bool_valid_values():
    assert shr.to_bool("true") is True
    assert shr.to_bool("false") is False


def test_to_bool_invalid_value_raises():
    with pytest.raises(falcon.HTTPBadRequest):
        shr.to_bool("nope")


def test_get_request_field_get_case_insensitive():
    req = DummyReq(method="GET", params={"clientid": "5"})
    assert shr.get_request_field("ClientID", req, caseless=True) == "5"


def test_get_request_field_put_required_and_default_behavior():
    req = DummyReq(method="PUT", media={"ClientID": "12"})
    assert shr.get_request_field("ClientID", req) == "12"
    assert shr.get_request_field("Missing", req, default="fallback") == "fallback"
    with pytest.raises(falcon.HTTPBadRequest):
        shr.get_request_field("Missing", req)


def test_preprocess_request_rejects_invalid_devnum():
    req = DummyReq(
        method="GET",
        params={"ClientID": "1", "ClientTransactionID": "2"},
        path="/api/v1/telescope/999/name",
    )
    pre = shr.PreProcessRequest(maxdev=10)
    with pytest.raises(falcon.HTTPBadRequest):
        pre(req, None, None, {"devnum": 999})


def test_preprocess_request_accepts_valid_request():
    req = DummyReq(
        method="GET",
        params={"ClientID": "1", "ClientTransactionID": "2"},
    )
    pre = shr.PreProcessRequest(maxdev=10)
    pre(req, None, None, {"devnum": 1})


def test_method_response_serializes_deque_values():
    req = DummyReq(method="PUT", media={"ClientTransactionID": "7"})
    rsp = shr.MethodResponse(req, value={"items": deque([1, 2, 3])})
    payload = json.loads(rsp.json)
    assert payload["ClientTransactionID"] == 7
    assert payload["Value"]["items"] == [1, 2, 3]
    assert payload["ErrorNumber"] == 0


def test_transaction_id_monotonic():
    first = shr.getNextTransId()
    second = shr.getNextTransId()
    assert second > first
