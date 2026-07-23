"""Shared Playwright CDP-based liveness check for a live-view video stream.

Used by both ui_classic.py and ui_v2.py so the CDP byte-counting logic
exists in exactly one place.
"""

from playwright.sync_api import Page, expect


def assert_stream_liveness(
    page: Page, locator: str, window_s: float = 5.0, min_bytes: int = 2048
) -> None:
    """Assert the element at `locator` is visible and its network stream
    keeps delivering bytes over `window_s` seconds (liveness, not pixel
    content — the sandbox's camera stream is a static synthetic pattern,
    so pixel-change would be a false negative there)."""
    img = page.locator(locator).first
    expect(img).to_be_visible(timeout=10000)

    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")

    # Scope byte-counting to the stream's own request, not all page traffic:
    # both frontends have other things going the whole time this window is
    # open (v2 polls device status and holds an SSE event stream; classic
    # HTMX-polls live/event status), and either can clear a low min_bytes on
    # its own -- silently passing even if the actual video stream were dead.
    stream_request_ids: set[str] = set()
    received = {"total": 0}

    def _on_request(event):
        if "/vid" in event.get("request", {}).get("url", ""):
            stream_request_ids.add(event["requestId"])

    def _on_data(event):
        if event.get("requestId") in stream_request_ids:
            received["total"] += event.get("dataLength", 0)

    cdp.on("Network.requestWillBeSent", _on_request)
    cdp.on("Network.dataReceived", _on_data)

    # The element may already be mid-stream from before these listeners were
    # attached (its src was set during an earlier page.goto()), so its
    # original requestWillBeSent would have been missed. Force a fresh,
    # cache-busted request within our observation window instead of racing
    # an already-in-flight connection.
    img.evaluate(
        "(el) => {"
        "  const u = new URL(el.getAttribute('src'), location.href);"
        "  u.searchParams.set('_liveness_check', Date.now());"
        "  el.src = u.toString();"
        "}"
    )

    page.wait_for_timeout(int(window_s * 1000))
    cdp.detach()

    assert received["total"] >= min_bytes, (
        f"only {received['total']} bytes received on the live view stream's "
        f"own request in {window_s}s — stream appears stalled"
    )
