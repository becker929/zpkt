"""Browser tests of the studio page (marked `ui`). They need Playwright's browsers:

    uv run --extra dev playwright install chromium webkit

Without them every test here skips; `pytest -m "not ui"` leaves them out altogether.

    uv run --extra dev pytest                                  # everything, from lib/harness (~1.5 min)
    uv run --extra dev pytest tests/ui/test_heard.py           # what the page played, as recorded
    STUDIO_STACK=1 uv run --extra dev pytest tests/ui/test_stack.py   # real Kokoro and Parakeet (test_stack.py)

They bind loopback ports and launch browsers, so run them outside the agent sandbox.

Audio goes both ways, and nothing reaches the speakers:
- In: the page's mic is a WAV. Chromium plays it through its fake capture device (--use-file-for-fake-audio-capture)
  or, where that device hangs, the getUserMedia shim (`CAPTURE`) plays `window.__syntheticMic` into a MediaStream.
  `CAPTURE` also keeps every stream it hands out (`window.__captured`) and when each was open
  (`window.__micSpans`, performance-clock ms, until its first track is stopped).
- Out: `MUTE` (heard.py) gives every AudioContext a destination that is really a tap into an AudioWorklet "ear":
  each render quantum the page sends to its speakers is recorded (mono, with the audio-clock time of its first
  sample), and the ear passes silence on to the real destination. A context gets its ear the first time the page
  asks for its destination, so the one the page makes after being in the background is recorded too.
  `await heard(page)` returns one `Ear` per context: the samples, their times, and the map from the audio clock to
  the page's clock (from getOutputTimestamp, so it includes the output's latency). Chromium also runs with
  --mute-audio. It works in Chromium and WebKit; the tests that use it are test_heard.py, one in test_webkit.py and
  the voice loop in test_stack.py.

The ready cue (cue.js: two soft notes when the mic starts hearing) is off unless a test asks for it (`open_page(...,
ready_cue=True)`): it is the one sound the page makes while the mic is open, and the ear's tests check that
nothing else does. test_mic.py hears it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import studio_media as media
from fake_studio import FakeStudio
from heard import MUTE

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright
except ImportError:            # the dev extra is not installed
    async_playwright = None

SCREENS = Path(__file__).parent / "screens"
IPHONE_15 = {"viewport": {"width": 393, "height": 659}, "screen": {"width": 393, "height": 852},
             "device_scale_factor": 3, "is_mobile": True, "has_touch": True}
PHONE = {"viewport": {"width": 393, "height": 760}, "device_scale_factor": 2}

# Keeps every stream getUserMedia hands the page (to check its tracks are stopped) and when the mic was open. When
# this Chromium cannot start its fake capture device (it hangs on some macOS versions), the same WAV is played into
# a MediaStream. It patches MediaDevices.prototype, not navigator.mediaDevices: WebKit may drop a property set on a
# DOM object's wrapper when the wrapper is collected and made again (and the page's calls then miss the shim).
CAPTURE = """
(() => {
  const native = MediaDevices.prototype.getUserMedia;
  const real = (constraints) => native.call(navigator.mediaDevices, constraints);
  window.__captured = [];
  window.__micSpans = [];
  MediaDevices.prototype.getUserMedia = async (constraints) => {
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
    // When the mic was open, for the ear's tests: from getUserMedia (or re-enabling a kept track) until a track
    // stops or is disabled.
    let span = { open: performance.now(), close: null };
    window.__micSpans.push(span);
    const enabled = Object.getOwnPropertyDescriptor(MediaStreamTrack.prototype, 'enabled');
    for (const track of stream.getTracks()) {
      const stop = track.stop.bind(track);
      track.stop = () => { span.close ??= performance.now(); stop(); };
      Object.defineProperty(track, 'enabled', {
        get() { return enabled.get.call(this); },
        set(on) {
          if (!on) span.close ??= performance.now();
          else if (span.close !== null) window.__micSpans.push(span = { open: performance.now(), close: null });
          enabled.set.call(this, on);
        },
      });
    }
    return stream;
  };
})();
"""


def ready_sound(on: bool) -> str:
    """An init script that sets the page's Ready sound preference, unless the page has saved one of its own."""
    return f"""(() => {{
  try {{
    const saved = JSON.parse(localStorage.getItem('studio.prefs') || '{{}}');
    if (!('readySound' in saved)) localStorage.setItem('studio.prefs', JSON.stringify({{ ...saved, readySound: {str(on).lower()} }}));
  }} catch {{
    // A page with no storage (about:blank) has no preferences either.
  }}
}})();"""


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


@pytest.fixture(params=["chromium", "webkit"])
async def either(request, playwright, mic_wav):
    """Chromium, then WebKit: for what must work in both (the iPhone is WebKit, the desktop mostly Chromium)."""
    try:
        if request.param == "chromium":
            args = chromium_args(mic_wav)
            await capture_starts(playwright, args)
            browser = await playwright.chromium.launch(args=args)
        else:
            browser = await playwright.webkit.launch()
    except PlaywrightError as exc:
        pytest.skip(f"no {request.param} for Playwright ({str(exc).splitlines()[0]})")
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
                    device: dict | None = None, query: str = "settle=30", ready_cue: bool = False) -> Page:
    """A new context and page on the fake server, muted, with getUserMedia watched (and the ready cue off)."""
    if synthetic_mic is None:
        synthetic_mic = browser.browser_type.name == "chromium" and not _capture_starts
    context = await browser.new_context(permissions=["microphone"], color_scheme=color_scheme, **(device or PHONE))
    await context.add_init_script(MUTE)
    await context.add_init_script(CAPTURE)
    await context.add_init_script(ready_sound(ready_cue))
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
