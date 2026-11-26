"""The Listen button in a real browser engine (WebKit, as on the iPhone), with a made-up capture. No sound is made
that anyone hears: the browser is headless."""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from tests.app.test_listen import listening  # noqa: F401  (the fixture)

playwright_sync = pytest.importorskip("playwright.sync_api")

ADD = """() => {
  if (!document.getElementById('listen')) {   // the shell has the span once the tracks are merged
    const s = document.createElement('span'); s.id = 'listen';
    (document.querySelector('#hbot') || document.body).appendChild(s);
  }
  const t = document.createElement('script'); t.type = 'module'; t.src = '/app/listen/listen.js';
  document.head.appendChild(t);
}"""


@pytest.fixture()
def page(listening):  # noqa: F811
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        pg = browser.new_page(viewport={"width": 375, "height": 800})
        pg.goto(listening.rig.url + "/app/")
        pg.wait_for_selector("#hbot")
        yield pg
        browser.close()


def test_a_tap_starts_the_sound_and_a_second_tap_stops_it(listening, page):  # noqa: F811
    page.evaluate(ADD)
    page.wait_for_selector("#listen button[data-state=off]")
    size = page.evaluate("(() => { const r = document.querySelector('#listen button').getBoundingClientRect();"
                         " return [r.width, r.height, document.documentElement.scrollWidth - innerWidth]; })()")  # fmt: skip
    assert size[0] >= 44 and size[1] >= 44 and size[2] <= 0, size
    assert listening.source.streams == []  # nothing plays, and nothing is captured, before the tap
    page.click("#listen button")
    page.wait_for_selector("#listen button[data-state=on]")
    page.wait_for_function("zpktListen.stats.peak > 0.1 && zpktListen.stats.bytes > 48000")  # sound arrives
    stats = page.evaluate("({...zpktListen.stats})")
    assert stats["mode"] == "pcm" and stats["ms"] < 250, stats  # the worklet path, and never far behind
    assert stats["rate"] == 48000, stats  # played at the capture's own rate
    assert page.evaluate("localStorage.getItem('zpkt.listen')") == "on"
    assert page.evaluate("document.querySelector('#listen .lsn-lv i').style.transform") != "scaleY(0)"
    page.click("#listen button")
    page.wait_for_selector("#listen button[data-state=off]")
    assert page.evaluate("localStorage.getItem('zpkt.listen')") == "off"
    assert wait_for(lambda: listening.status()["listeners"] == 0)


def test_a_44100_stream_from_the_live_device_plays_at_44100(listening, page):  # noqa: F811
    listening.source.rate = 44100  # as the "zpkt listen" device gives on a 44.1 kHz set
    page.reload()  # the page asks the status as it loads, and so knows the rate before the tap
    page.wait_for_selector("#listen button[data-state=off]")
    page.click("#listen button")
    page.wait_for_selector("#listen button[data-state=on]")
    page.wait_for_function("zpktListen.stats.peak > 0.1 && zpktListen.stats.bytes > 44100")
    stats = page.evaluate("({...zpktListen.stats})")
    assert stats["mode"] == "pcm" and stats["rate"] == 44100 and stats["ms"] < 250, stats
    assert listening.source.streams[0].rate == 44100


def test_the_streams_header_decides_the_rate_when_the_first_guess_was_wrong(listening, page):  # noqa: F811
    page.wait_for_selector("#listen button[data-state=off]")  # the status said 48000 as the page loaded
    listening.source.rate = 44100  # and then the capture turned out to be the device's
    page.click("#listen button")
    page.wait_for_function("zpktListen.stats.peak > 0.1 && zpktListen.stats.rate === 44100")
    stats = page.evaluate("({...zpktListen.stats})")
    assert stats["mode"] == "pcm" and page.evaluate("zpktListen.state") == "on", stats


REFUSE = """(() => {  // a browser that opens its output at its own rate only, whatever is asked
  const Real = window.AudioContext || window.webkitAudioContext;
  window.AudioContext = window.webkitAudioContext = function (options) {
    if (options && options.sampleRate) throw new DOMException('rate not supported', 'NotSupportedError');
    return new Real(options);
  };
})()"""


def test_a_browser_that_refuses_the_rate_gets_the_mp3_stream(listening, page):  # noqa: F811
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed")
    listening.source.rate = 44100
    page.add_init_script(REFUSE)
    page.reload()
    page.wait_for_selector("#listen button[data-state=off]")
    page.click("#listen button")
    page.wait_for_selector("#listen button[data-state=on]", timeout=20000)
    assert page.evaluate("zpktListen.stats.mode") == "mp3"


def test_when_listening_was_on_the_first_tap_anywhere_resumes_it(listening, page):  # noqa: F811
    page.evaluate("localStorage.setItem('zpkt.listen', 'on')")  # as left by the page before this one
    page.reload()  # the shell loads listen.js itself
    page.wait_for_selector("#listen button[data-resume]")
    assert page.evaluate("zpktListen.state") == "off"  # no sound without a tap
    page.mouse.click(5, 300)  # not on the button
    page.wait_for_selector("#listen button[data-state=on]")


def test_unavailable_shows_the_reason_in_plain_words_on_a_tap(listening, page):  # noqa: F811
    listening.source.reason = "Live is not running on the Mac, so there is nothing to hear."
    listening.adapter.hub._checked = None  # the first page load asked already, and the answer is kept a while
    page.reload()  # the shell loads listen.js itself
    page.wait_for_selector("#listen button[data-state=unavailable]")
    page.click("#listen button")
    assert page.inner_text(".lsn-why") == listening.source.reason
    assert listening.source.streams == []


def test_without_the_adapter_the_script_draws_nothing_and_breaks_nothing(rig):
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        pg = browser.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(rig.url + "/app/")
        pg.wait_for_selector("#hbot")
        from zpkt.app.listen.routes import SCRIPT

        pg.evaluate(
            "() => { const s = document.createElement('span'); s.id = 'listen'; document.body.appendChild(s); }"
        )
        pg.add_script_tag(content=SCRIPT.read_text(), type="module")
        pg.wait_for_function("window.zpktListen && document.querySelector('#listen').children.length === 0")
        browser.close()
    assert errors == []
