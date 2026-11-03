"""Serving the web UI under a reverse-proxy sub-path.

The prefix comes from a valid X-Forwarded-Prefix header, else from
[webui_settings] root_path, else nothing; with no prefix the UI must render
exactly as before.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import falcon
import pytest
from falcon import testing

import front.app as front_app
from device.config import Config


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(Config, "root_path", "", raising=False)
    front_app._context_cached.clear()
    front_app._last_context_get_time.clear()
    yield
    front_app._context_cached.clear()
    front_app._last_context_get_time.clear()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        (None, ""),
        ("/", ""),
        ("/ssc", "/ssc"),
        ("/ssc/", "/ssc"),
        (" /api/hassio_ingress/AbC-1_x.y~z ", "/api/hassio_ingress/AbC-1_x.y~z"),
        ("ssc", None),  # must be root-relative
        ("//evil.example", None),  # protocol-relative would leave the site
        ('/a"onmouseover=alert(1)', None),  # never reflected into HTML
        ("/a/../b", "/a/../b"),  # dots are plain path characters here
        ("/a b", None),
    ],
)
def test_normalize_root_path(value, expected):
    assert front_app.normalize_root_path(value) == expected


class _Req:
    def __init__(self, header=None):
        self._header = header

    def get_header(self, name):
        assert name == "X-Forwarded-Prefix"
        return self._header


def test_header_wins_over_config(monkeypatch):
    monkeypatch.setattr(Config, "root_path", "/configured")
    assert front_app.get_root_path(_Req("/from-proxy")) == "/from-proxy"
    assert front_app.get_root_path(_Req(None)) == "/configured"


def test_invalid_header_falls_back_to_config(monkeypatch):
    monkeypatch.setattr(Config, "root_path", "/configured")
    assert front_app.get_root_path(_Req("not-a-path")) == "/configured"
    monkeypatch.setattr(Config, "root_path", "")
    assert front_app.get_root_path(_Req("not-a-path")) == ""


def test_invalid_config_is_ignored(monkeypatch):
    monkeypatch.setattr(Config, "root_path", "no-leading-slash")
    assert front_app.get_root_path(_Req(None)) == ""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("/1/schedule", "/p/1/schedule"),
        ("/", "/p/"),
        ("/p/1/schedule", "/p/1/schedule"),  # already prefixed: idempotent
        ("//cdn.example/x.js", "//cdn.example/x.js"),
        ("https://example.com/x", "https://example.com/x"),
        ("relative/x", "relative/x"),
        ("", ""),
    ],
)
def test_with_root_path(url, expected):
    assert front_app.with_root_path("/p", url) == expected


def test_with_root_path_without_prefix_is_identity():
    assert front_app.with_root_path("", "/1/schedule") == "/1/schedule"


# --- full page rendering through the real context path ------------------------


def _page_app(monkeypatch):
    monkeypatch.setattr(
        front_app,
        "_get_context_real",
        lambda telescope_id, req: {
            "online": True,
            "client_master": True,
            "root": f"/{telescope_id}",
            "imager_root": f"http://scope-host:7556/{telescope_id}",
            "defgain": 80,
            "telescope": {"device_num": telescope_id},
            "telescopes": [],
        },
    )
    monkeypatch.setattr(
        front_app,
        "do_action_device",
        lambda action, dev_num, params, is_schedule=False: {
            "Value": {"state": "stopped"}
        },
    )
    app = falcon.App(middleware=[front_app.RootPathMiddleware()])
    app.add_route("/{telescope_id:int}/framed_mosaic", front_app.FramedMosaicResource())
    return testing.TestClient(app)


def test_standalone_page_urls_are_unchanged(monkeypatch):
    resp = _page_app(monkeypatch).simulate_get("/1/framed_mosaic")

    assert resp.status_code == 200
    assert 'src="/public/htmx.min.js"' in resp.text
    assert 'href="/public/bootstrap.min.css"' in resp.text
    assert 'action="/1/framed_mosaic"' in resp.text
    assert 'href="/schedule"' in resp.text
    assert "data-root-path" not in resp.text


def test_prefixed_page_urls_carry_the_prefix(monkeypatch):
    resp = _page_app(monkeypatch).simulate_get(
        "/1/framed_mosaic", headers={"X-Forwarded-Prefix": "/ingress/abc"}
    )

    assert resp.status_code == 200
    assert 'data-root-path="/ingress/abc"' in resp.text
    assert 'src="/ingress/abc/public/htmx.min.js"' in resp.text
    assert 'src="/ingress/abc/public/main.js"' in resp.text
    assert 'href="/ingress/abc/public/bootstrap.min.css"' in resp.text
    assert 'action="/ingress/abc/1/framed_mosaic"' in resp.text
    assert 'href="/ingress/abc/schedule"' in resp.text
    assert 'src="/public/' not in resp.text
    assert "/ingress/abc/ingress/abc" not in resp.text


def test_configured_root_path_applies_without_header(monkeypatch):
    monkeypatch.setattr(Config, "root_path", "/ssc")
    resp = _page_app(monkeypatch).simulate_get("/1/framed_mosaic")

    assert 'src="/ssc/public/htmx.min.js"' in resp.text
    assert 'action="/ssc/1/framed_mosaic"' in resp.text


def test_cached_context_never_leaks_a_prefix_across_requests(monkeypatch):
    # The page context is cached for ~1s per telescope; a prefixed request
    # followed by a direct one must not hand the direct one prefixed URLs.
    monkeypatch.setattr(
        front_app,
        "_get_context_real",
        lambda telescope_id, req: {
            "root": f"/{telescope_id}",
            "imager_root": f"http://scope-host:7556/{telescope_id}",
        },
    )
    prefixed = front_app.get_context(1, _Req("/p"))
    direct = front_app.get_context(1, _Req(None))

    assert prefixed["root"] == "/p/1"
    assert prefixed["imager_root"] == "/p/1/imaging"
    assert direct["root"] == "/1"
    assert direct["imager_root"] == "http://scope-host:7556/1"
    assert "root_path" not in direct


def test_empty_root_means_the_prefix_itself():
    context = front_app.apply_root_path({"root": "", "imager_root": ""}, "/p", 1)
    assert context["root"] == "/p"
    assert context["imager_root"] == ""


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, "/1/schedule"), ("/p", "/p/1/schedule")],
)
def test_redirects_stay_inside_the_prefix(header, expected):
    class Redirecting:
        def on_get(self, req, resp):
            front_app.redirect("/1/schedule")

    app = falcon.App(middleware=[front_app.RootPathMiddleware()])
    app.add_route("/go", Redirecting())
    headers = {"X-Forwarded-Prefix": header} if header else {}

    resp = testing.TestClient(app).simulate_get("/go", headers=headers)

    assert resp.status_code == 302
    assert resp.headers["Location"] == expected


# --- live-view relay -----------------------------------------------------------


@pytest.fixture
def imaging_server():
    """Stand-in imaging server: an MJPEG-ish body on /1/vid, 404 elsewhere."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            seen.append(self.path)
            if self.path != "/1/vid":
                self.send_error(404)
                return
            body = b"\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\nJPEGDATA"
            self.send_response(200)
            self.send_header(
                "Content-Type", "multipart/x-mixed-replace; boundary=frame"
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], seen
    server.shutdown()


def _relay_client(monkeypatch, port):
    monkeypatch.setattr(front_app, "get_listening_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(Config, "imgport", port)
    app = falcon.App()
    for path in ("vid", "vid/status", "events", "live/status"):
        app.add_route(
            f"/{{telescope_id:int}}/imaging/{path}",
            front_app.ImagingProxyResource(path),
        )
    return testing.TestClient(app)


def test_relay_passes_the_stream_through(monkeypatch, imaging_server):
    port, seen = imaging_server
    resp = _relay_client(monkeypatch, port).simulate_get("/1/imaging/vid")

    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("multipart/x-mixed-replace")
    assert resp.content.endswith(b"JPEGDATA")
    assert seen == ["/1/vid"]


def test_relay_passes_upstream_errors_through(monkeypatch, imaging_server):
    port, _seen = imaging_server
    resp = _relay_client(monkeypatch, port).simulate_get("/2/imaging/events")
    assert resp.status_code == 404


@pytest.mark.parametrize("chunked", [False, True])
def test_relay_forwards_data_while_the_upstream_stream_stays_open(monkeypatch, chunked):
    # Live streams never end: MJPEG/SSE bodies have no Content-Length. The
    # relay must hand each piece downstream as it arrives, not wait for EOF.
    release = threading.Event()
    event = b"event: status\ndata: hello\n\n"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1" if chunked else "HTTP/1.0"

        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(
                b"%x\r\n%s\r\n" % (len(event), event) if chunked else event
            )
            self.wfile.flush()
            release.wait(timeout=10)  # hold the stream open
            if chunked:
                self.wfile.write(b"0\r\n\r\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(front_app, "get_listening_ip", lambda: "127.0.0.1")
        monkeypatch.setattr(Config, "imgport", server.server_address[1])
        resp = falcon.Response()
        front_app.ImagingProxyResource("events").on_get(None, resp, 1)

        first = {}
        reader = threading.Thread(
            target=lambda: first.update(chunk=next(iter(resp.stream)))
        )
        reader.start()
        reader.join(timeout=3)
        assert not reader.is_alive(), "relay waited for the upstream stream to end"
        assert event in first["chunk"]
        # Closing the relay (what a browser leaving the page triggers) must
        # release the upstream connection.
        resp.stream.close()
    finally:
        release.set()
        server.shutdown()


def test_relay_reports_an_unreachable_imaging_server(monkeypatch):
    import socket

    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    resp = _relay_client(monkeypatch, port).simulate_get("/1/imaging/vid")
    assert resp.status_code == 502
