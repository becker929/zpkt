"""Browser tests of the studio page (marked `ui`). They need Playwright's browsers:

    uv run --extra dev playwright install chromium webkit

Without them every test here skips; `pytest -m "not ui"` leaves them out altogether.

Nothing is ever heard: Chromium runs with --mute-audio, and every page gets a shim that routes its Web Audio
destination through a silent gain (the graph still runs, so playback is checked by instrumentation).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import studio_media as media
from fake_studio import FakeStudio

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright
except ImportError:            # the dev extra is not installed
    async_playwright = None

SCREENS = Path(__file__).parent / "screens"
IPHONE_15 = {"viewport": {"width": 393, "height": 659}, "screen": {"width": 393, "height": 852},
             "device_scale_factor": 3, "is_mobile": True, "has_touch": True}
PHONE = {"viewport": {"width": 393, "height": 760}, "device_scale_factor": 2}

# Web Audio, silenced: everything the page connects to the destination goes through a gain of zero.
MUTE = """
(() => {
  const Real = window.AudioContext;
  if (!Real) return;
  window.AudioContext = class extends Real {
    #silent = null;
    get destination() {
      if (!this.#silent) {
        this.#silent = this.createGain();
        this.#silent.gain.value = 0;
        this.#silent.connect(super.destination);
      }
      return this.#silent;
    }
  };
})();
"""

# Keeps every stream getUserMedia hands the page (to check its tracks are stopped). When this Chromium cannot
# start its fake capture device (it hangs on some macOS versions), the same WAV is played into a MediaStream.
CAPTURE = """
(() => {
  const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  window.__captured = [];
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    let stream;
    if (window.__syntheticMic) {
      const ctx = new AudioContext();
      const data = await (await fetch(window.__syntheticMic)).arrayBuffer();
      const source = ctx.createBufferSource();
      source.buffer = await ctx.decodeAudioData(data);
      source.loop = true;
      const sink = ctx.createMediaStreamDestination();
      source.connect(sink);
      source.start();
      stream = sink.stream;
    } else {
      stream = await real(constraints);
    }
    window.__captured.push(stream);
    return stream;
  };
})();
"""


@pytest.fixture(scope="session")
def mic_wav(tmp_path_factory) -> Path:
    return media.mic_wav(tmp_path_factory.mktemp("mic") / "mic.wav")


@pytest.fixture
async def playwright():
    if async_playwright is None:
        pytest.skip("Playwright is not installed (uv sync --extra dev)")
    async with async_playwright() as p:
        yield p


def chromium_args(mic_wav: Path) -> list[str]:
    return ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={mic_wav}", "--autoplay-policy=no-user-gesture-required",
            "--mute-audio"]


_capture_starts: bool | None = None


async def capture_starts(playwright, args: list[str]) -> bool:
    """Whether Chromium's fake capture device starts on this machine (once per session). On some macOS versions it
    never does, and a capture left hanging breaks that browser's audio for good, so the check gets a browser of
    its own."""
    global _capture_starts
    if _capture_starts is None:
        async def blank(_request: web.Request) -> web.Response:
            return web.Response(text="<!doctype html><title>probe</title>", content_type="text/html")

        app = web.Application()
        app.router.add_get("/", blank)
        server = TestServer(app)
        await server.start_server()
        browser = await playwright.chromium.launch(args=args)
        try:
            page = await (await browser.new_context(permissions=["microphone"])).new_page()
            await page.goto(str(server.make_url("/")))
            _capture_starts = await page.evaluate("""() => Promise.race([
                navigator.mediaDevices.getUserMedia({audio: true}).then((s) => { s.getTracks().forEach((t) => t.stop()); return true; }),
                new Promise((resolve) => setTimeout(() => resolve(false), 4000))])""")
        finally:
            await browser.close()
            await server.close()
    return _capture_starts


@pytest.fixture
async def chromium(playwright, mic_wav):
    args = chromium_args(mic_wav)
    try:
        await capture_starts(playwright, args)
        browser = await playwright.chromium.launch(args=args)
    except PlaywrightError as exc:
        pytest.skip(f"no Chromium for Playwright ({str(exc).splitlines()[0]})")
    yield browser
    await browser.close()


@pytest.fixture
async def webkit(playwright):
    try:
        browser = await playwright.webkit.launch()
    except PlaywrightError as exc:
        pytest.skip(f"no WebKit for Playwright ({str(exc).splitlines()[0]})")
    yield browser
    await browser.close()


@pytest.fixture
async def fake():
    studio = FakeStudio()
    server = TestServer(studio.app())
    await server.start_server()
    studio.base = str(server.make_url("/")).rstrip("/")
    yield studio
    await server.close()


class Page:
    """The studio page in a browser, with its console watched: any error fails the test."""

    def __init__(self, page, fake: FakeStudio):
        self.page, self.fake = page, fake
        self.errors: list[str] = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(f"page error: {e}"))

    async def open(self, query: str = "settle=30") -> None:
        await self.page.goto(f"{self.fake.base}/studio/?{query}")
        await self.fake.expect(lambda m: m["type"] == "hello")
        await self.wait("() => document.querySelector('#messages [data-seq]') || !document.getElementById('empty').hidden")

    async def js(self, expression: str, arg=None):
        return await self.page.evaluate(expression, arg)

    async def messages_in_dom(self) -> int:
        return await self.js("document.querySelectorAll('#messages [data-seq]').length")

    async def wait(self, expression: str, timeout: float = 10_000) -> None:
        await self.page.wait_for_function(expression, timeout=timeout)


async def open_page(browser, fake: FakeStudio, *, synthetic_mic: bool | None = None, color_scheme: str = "dark",
                    device: dict | None = None, query: str = "settle=30") -> Page:
    """A new context and page on the fake server, muted, with getUserMedia watched."""
    if synthetic_mic is None:
        synthetic_mic = browser.browser_type.name == "chromium" and not _capture_starts
    context = await browser.new_context(permissions=["microphone"], color_scheme=color_scheme, **(device or PHONE))
    await context.add_init_script(MUTE)
    await context.add_init_script(CAPTURE)
    if synthetic_mic:
        ref = fake.put(media.mic_wav_bytes(), "wav", "audio/wav")
        await context.add_init_script(f"window.__syntheticMic = {ref['url']!r};")
    page = Page(await context.new_page(), fake)
    await page.open(query)
    return page


@pytest.fixture
async def phone(chromium, fake):
    """The page in Chromium at a phone's size, signed in to the fake server; no console errors allowed."""
    page = await open_page(chromium, fake)
    yield page
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()
