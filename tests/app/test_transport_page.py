"""The transport on the Hear bar in WebKit, on a phone and on a desktop: Play or Pause, Stop, and the loop's three
keys; the lit key and the strip say what loops. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import pytest

from tests.app.test_zero_scroll import SCROLLERS

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


@pytest.mark.parametrize(("width", "height"), [(375, 667), (1200, 800)])
def test_play_pause_stop_and_the_three_loops(browser, rig, width, height):
    pg = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector("#kplay")
    song = rig.live.song
    keys = pg.locator("#loops button")
    assert keys.all_inner_texts() == ["All", "Start", "Peak"]
    assert [k.get_attribute("aria-pressed") for k in keys.all()] == ["false"] * 3  # nothing loops
    assert pg.locator("#strip .part").count() == 2 and pg.locator("#strip .lp").count() == 0  # the two spans, marked
    assert pg.locator("#kplay").get_attribute("aria-label") == "Play"
    pg.click("#kplay")
    pg.wait_for_function("document.querySelector('#kplay').getAttribute('aria-label') === 'Pause'")
    assert song.is_playing
    pg.click('#loops [data-loop="drop"]')  # the peak: lit at once, Live loops bars 17 to 40
    assert pg.locator('#loops [data-loop="drop"]').get_attribute("aria-pressed") == "true"
    pg.wait_for_function("document.querySelector('#looppill')?.innerText.trim() === '17–40'")
    assert song.loop and (song.loop_start, song.loop_length) == (64.0, 96.0) and song.is_playing
    lp, strip = pg.locator("#strip .lp").bounding_box(), pg.locator("#strip").bounding_box()
    assert lp["x"] == pytest.approx(strip["x"] + strip["width"] * 0.4, abs=2)  # drawn on the strip, from bar 17
    pg.click('#loops [data-loop="build"]')
    pg.wait_for_function("document.querySelector('#looppill')?.innerText.trim() === '1–16'")
    assert [k.get_attribute("aria-pressed") for k in keys.all()] == ["false", "true", "false"]
    pg.click("#kplay")  # pause: the place is kept
    pg.wait_for_function("document.querySelector('#kplay').getAttribute('aria-label') === 'Play'")
    assert not song.is_playing
    pg.click('#loops [data-loop="whole"]')
    pg.wait_for_function("document.querySelector('#looppill')?.innerText.trim() === '1–40'")
    pg.click('#loops [data-loop="whole"]')  # the lit key again: no loop
    pg.wait_for_function("!document.querySelector('#looppill')")
    assert not song.loop and [k.get_attribute("aria-pressed") for k in keys.all()] == ["false"] * 3
    rig.command("transport", {"action": "seek", "beat": 40.0})
    pg.wait_for_function("document.querySelector('#barno').textContent.startsWith('bar 11')")
    pg.click("#kstop")
    pg.wait_for_function("document.querySelector('#barno').textContent.startsWith('bar 1 ')")
    assert song.current_song_time == 0.0
    small = pg.evaluate(
        "[...document.querySelectorAll('#tgrp button')].map(b => b.getBoundingClientRect()).filter(r => r.width < 43.5 || r.height < 43.5).length"
    )
    assert small == 0 and pg.evaluate(SCROLLERS, "#app") == []
    assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
    for tab in ("ask", "desk"):  # the transport is on every tab
        pg.click(f'#tabs [data-t="{tab}"]')
        assert pg.locator("#kplay").is_visible() and pg.locator("#loops").is_visible()
    assert errors == []


def test_a_span_the_set_does_not_define_is_a_key_that_cannot_be_pressed(browser, rig):
    pg = browser.new_page(viewport={"width": 375, "height": 667})
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector("#loops")
    pg.evaluate("() => { const s = window.zpkt.S.state; s.loops = {whole: s.loops.whole}; window.zpkt.redraw(); }")
    assert [b.is_disabled() for b in pg.locator("#loops button").all()] == [False, True, True]
