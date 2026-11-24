"""Browser tests of the checklist's pages (marked `ui`). They need Playwright's browsers:

    uv run --extra dev playwright install chromium webkit

Without them every test here skips; `pytest -m "not ui"` leaves them out altogether. They bind loopback ports and
launch a browser, so run them outside the agent sandbox. Each test serves the page from server.py with its data in
the test's folder, and pages that play audio are muted by heard.py's shim, which also records what they played.
"""

from __future__ import annotations

import pytest

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright
except ImportError:            # the dev extra is not installed
    async_playwright = None

IPHONE_15 = {"viewport": {"width": 393, "height": 659}, "screen": {"width": 393, "height": 852},
             "device_scale_factor": 3, "is_mobile": True, "has_touch": True}


@pytest.fixture
async def playwright():
    if async_playwright is None:
        pytest.skip("Playwright is not installed (uv sync --extra dev)")
    async with async_playwright() as p:
        yield p


@pytest.fixture
async def webkit(playwright):
    try:
        browser = await playwright.webkit.launch()
    except PlaywrightError as exc:
        pytest.skip(f"no WebKit for Playwright ({str(exc).splitlines()[0]})")
    yield browser
    await browser.close()


@pytest.fixture(params=["chromium", "webkit"])
async def either(request, playwright):
    """Chromium, then WebKit: for what must work in both (the iPhone is WebKit, the desktop mostly Chromium)."""
    try:
        if request.param == "chromium":
            browser = await playwright.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
        else:
            browser = await playwright.webkit.launch()
    except PlaywrightError as exc:
        pytest.skip(f"no {request.param} for Playwright ({str(exc).splitlines()[0]})")
    yield browser
    await browser.close()
