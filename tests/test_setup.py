import device.setup as setup_mod


class DummyReq:
    remote_addr = "127.0.0.1"
    method = "GET"
    path = "/setup"
    query_string = ""
    content_length = 0


class DummyResp:
    def __init__(self):
        self.content_type = None
        self.text = None


def test_svrsetup_on_get_sets_html_response(monkeypatch):
    called = {"count": 0}
    monkeypatch.setattr(
        setup_mod, "log_request", lambda req: called.__setitem__("count", 1)
    )
    req = DummyReq()
    resp = DummyResp()

    setup_mod.svrsetup().on_get(req, resp)

    assert called["count"] == 1
    assert resp.content_type == "text/html"
    assert "Server setup is in config.toml" in resp.text


def test_devsetup_on_get_sets_html_response(monkeypatch):
    called = {"count": 0}
    monkeypatch.setattr(
        setup_mod, "log_request", lambda req: called.__setitem__("count", 1)
    )
    req = DummyReq()
    resp = DummyResp()

    setup_mod.devsetup().on_get(req, resp, "1")

    assert called["count"] == 1
    assert resp.content_type == "text/html"
    assert "Device setup is in config.toml" in resp.text
