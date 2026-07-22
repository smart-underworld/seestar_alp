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
    received = {"total": 0}

    def _on_data(event):
        received["total"] += event.get("dataLength", 0)

    cdp.on("Network.dataReceived", _on_data)
    page.wait_for_timeout(int(window_s * 1000))
    cdp.detach()

    assert received["total"] >= min_bytes, (
        f"only {received['total']} bytes received on the live view stream in "
        f"{window_s}s — stream appears stalled"
    )
