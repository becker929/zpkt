"""The Song tab of the /app/ shell in WebKit: lanes of bars, Mix 1 and transitions as labelled sketch sheets, the build.

They need the playwright extra and its WebKit and skip when either is missing. The shell and the arranger's pages are
the real ones, served by the real server; Live is a FakeLive.
"""

from __future__ import annotations

import pytest

from tests.app.test_song import MIX_SET, open_set, quick_live, song_rig  # noqa: F401  (fixtures)

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def song_page(song_rig):  # noqa: F811
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        context = browser.new_context(viewport={"width": 390, "height": 844})
        pg = context.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(song_rig.rig.url + "/app/")
        pg.wait_for_selector(".ctl .w")
        pg.errors = errors  # type: ignore[attr-defined]
        yield pg
        browser.close()
    assert errors == []


def test_the_song_tab_shows_the_arrangement_as_lanes_of_bars(song_page):
    song_page.click('#tabs button[data-t="song"]')
    song_page.wait_for_selector("#lanes .lane")
    assert song_page.locator("#songname").inner_text() == "8d2a2 Fast build, slow peak"
    assert song_page.locator("#lanes .lane .ln").all_inner_texts() == ["Kick", "P1 open", "Splash", "Chord"]
    assert song_page.locator("#desk").is_hidden() and song_page.locator("#song").is_visible()
    kick_block = song_page.locator("#lanes .lane").first.locator(".tr i").first
    assert kick_block.evaluate("e => e.style.left") == "40%"  # bar 16 of 40


def test_mix_1_opens_as_a_sheet_labelled_a_sketch_and_the_page_is_the_arrangers_own(song_page):
    song_page.click('#tabs button[data-t="song"]')
    song_page.wait_for_selector("#lanes .lane")
    song_page.click('button[data-sheet="mix"]')
    song_page.wait_for_selector("#psheet.on iframe")
    assert song_page.locator("#psheet h3").inner_text() == "Sketch mix"
    assert song_page.locator("#sketchpill").inner_text() == "sketch"
    frame = song_page.frame_locator("#psheet iframe")
    frame.locator(".sketch").wait_for()
    assert "Not a render of the set" in frame.locator(".sketch").inner_text()
    assert song_page.locator("#psheet iframe").get_attribute("src") == "/app/song/mix/"
    song_page.click("#pclose")
    assert song_page.locator("#psheet iframe").count() == 0  # closing the sheet takes the page, and its sound, away


def test_transitions_open_as_a_sheet_too(song_page):
    song_page.click('#tabs button[data-t="song"]')
    song_page.wait_for_selector("#lanes .lane")
    song_page.click('button[data-sheet="transitions"]')
    song_page.wait_for_selector("#psheet.on iframe")
    assert song_page.locator("#psheet h3").inner_text() == "Transitions"
    assert song_page.locator("#psheet iframe").get_attribute("src") == "/app/song/transitions/"


def test_build_asks_twice_then_builds_through_the_bus(song_rig, song_page, quick_live):  # noqa: F811
    open_set(song_rig.rig, MIX_SET)
    song_page.click('#tabs button[data-t="song"]')
    song_page.wait_for_selector("#lanes .lane")
    song_page.click("#songbuild")
    assert "Tap again" in song_page.locator("#songbuild").inner_text()
    assert song_rig.rig.desk.bus.log == [] or all(e["kind"] != "song.build" for e in song_rig.rig.desk.bus.log)
    song_page.click("#songbuild")
    song_page.wait_for_function("document.querySelector('#toast').textContent.startsWith('Built')")
    assert [e["status"] for e in song_rig.rig.desk.bus.log if e["kind"] == "song.build"] == [200]


@pytest.mark.parametrize("width", [360, 390, 1280])
def test_the_song_tab_does_not_overflow(song_rig, width):  # noqa: F811
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        pg = browser.new_page(viewport={"width": width, "height": 800})
        pg.goto(song_rig.rig.url + "/app/")
        pg.wait_for_selector(".ctl .w")
        pg.click('#tabs button[data-t="song"]')
        pg.wait_for_selector("#lanes .lane")
        over = pg.evaluate(
            """() => {
              const out = [];
              document.querySelectorAll('#song *, #tabs button').forEach(e => {
                const r = e.getBoundingClientRect();
                if (r.width && (r.right > innerWidth + 0.5 || r.left < -0.5)) out.push((e.id || e.className || e.tagName) + ' ' + Math.round(r.right));
              });
              return [document.documentElement.scrollWidth - innerWidth, out];
            }"""
        )
        small = pg.evaluate(
            "[...document.querySelectorAll('#song button, #tabs button')].map(b => b.getBoundingClientRect().height).filter(h => h < 40).length"
        )
        browser.close()
    assert over == [0, []], over
    assert small == 0
