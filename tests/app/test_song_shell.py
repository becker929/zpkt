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
    assert song_page.locator("#songsel, #songname, #song button[data-sheet], #songbuild").count() == 0  # lanes only
    assert song_page.locator("#lanes .lane .ln").all_inner_texts() == ["Kick", "P1 open", "Splash", "Chord"]
    assert song_page.locator("#desk").is_hidden() and song_page.locator("#song").is_visible()
    kick_block = song_page.locator("#lanes .lane").first.locator(".tr i").first
    assert kick_block.evaluate("e => e.style.left") == "40%"  # bar 16 of 40


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
        pg.click('#tabs button[data-t="song"]')  # the same tab bar at every width
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
            "[...document.querySelectorAll('#song button, #tabs button')].map(b => b.getBoundingClientRect().height).filter(h => h > 0 && h < 40).length"
        )
        browser.close()
    assert over == [0, []], over
    assert small == 0
