"""Nothing in /app/ scrolls (Anthony, 25 November 2026: "This app must have zero scrolling"): at every size from
360 x 640 up the Hear bar, the page's title, the paging controls and the tab bar are on screen, and the whole map of
the current page is visible at once, every control at 44 px or more. Where a phone cannot hold all 20 slots, the map
shows one face at a time, and the switch is always there. WebKit; skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import pytest

from tests.app.test_page_shell import big_spec, open_page

playwright_sync = pytest.importorskip("playwright.sync_api")

SIZES = [(360, 640), (375, 667), (375, 812), (390, 844), (768, 1024), (1200, 800)]

# Every element under `root` that can scroll (overflow auto or scroll) and has more than its box holds.
SCROLLERS = """root => [...document.querySelectorAll(root + ', ' + root + ' *')].filter(e => {
  const s = getComputedStyle(e);
  return e.getClientRects().length && s.visibility !== 'hidden'
    && ((/auto|scroll/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 1) || (/auto|scroll/.test(s.overflowX) && e.scrollWidth > e.clientWidth + 1));
}).map(e => (e.id || e.className || e.tagName) + ' ' + e.scrollHeight + '>' + e.clientHeight)"""

# Where the Desk's parts are, and what of the map does not fit or is too small to touch.
DESK = """() => {
  const box = s => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null; const r = e.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; };
  const p = document.querySelector('#panel'), pr = p.getBoundingClientRect();
  const shown = [...p.querySelectorAll('.mc')].filter(e => e.getClientRects().length);
  const faces = shown.map(e => e.querySelector('.w').getBoundingClientRect());
  return {inner: [innerWidth, innerHeight], page: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
    title: box('#pagename'), pager: box('#deskdots .dots'), nums: box('#mlpages'), tabs: box('#tabs'), hear: box('#htop'), keys: box('#hbot'), panel: box('#panel'),
    slots: shown.length, faces: window.zpkt.S.faces,
    small: faces.filter(r => r.width < 43.5 || r.height < 43.5).length,
    spill: shown.filter(e => e.scrollHeight > e.clientHeight + 1 || e.getBoundingClientRect().bottom > pr.bottom + 1 || e.getBoundingClientRect().top < pr.top - 1).length,
    buttons: [...document.querySelectorAll('#deskdots button, #mlpages button')].map(b => b.getBoundingClientRect()).filter(r => r.width && (r.width < 43.5 || r.height < 43.5)).length};
}"""


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def on_screen(got: dict, name: str) -> None:
    box, (w, h) = got[name], got["inner"]
    assert box is not None, f"{name} is not drawn"
    assert box["top"] >= -0.5 and box["bottom"] <= h + 0.5 and box["left"] >= -0.5 and box["right"] <= w + 0.5, (
        name,
        box,
    )


def open_big(browser, rig, width, height):
    pg, _ = open_page(browser, rig, width, big_spec())  # the biggest Page: two MiniLab pages, every kind of control
    pg.set_viewport_size({"width": width, "height": height})
    pg.wait_for_timeout(250)  # the map is fitted to its new box
    return pg


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_the_desk_never_scrolls_and_its_paging_controls_stay_on_screen(browser, rig, width, height):
    pg = open_big(browser, rig, width, height)
    assert pg.evaluate(SCROLLERS, "#main") == []
    got = pg.evaluate(DESK)
    assert got["page"] == got["inner"]  # the page itself has nowhere to scroll to
    for part in ("title", "nums", "tabs", "hear", "keys", "panel"):
        on_screen(got, part)
    if width < 1100:
        on_screen(got, "pager")  # wider, the list of Pages is the side column
    assert (got["small"], got["spill"], got["buttons"]) == (0, 0, 0), got  # all of it visible, nothing under 44 px
    if got["faces"] == 1:
        assert got["slots"] == 20  # the whole map at once
    else:  # a phone too short for 20 slots: two faces, switched in place, the switch always there
        assert width < 700 and got["slots"] == 12
        assert pg.locator("#faces [data-face=k]").get_attribute("aria-pressed") == "true"
        pg.click("#faces [data-face=f]")
        pg.wait_for_function("document.querySelector('#panel').dataset.face === 'f'")
        other = pg.evaluate(DESK)
        assert other["slots"] == 8 and (other["small"], other["spill"]) == (0, 0), other
        assert (
            pg.locator('#panel .mc[data-slot="f1"]').is_visible()
            and pg.locator('#panel .mc[data-slot="b8"]').is_visible()
        )
        assert not pg.locator('#panel .mc[data-slot="k1"]').is_visible()
        on_screen(other, "pager")
        assert other["pager"]["top"] == pytest.approx(
            got["pager"]["top"], abs=1
        )  # the switch does not move under the thumb
        assert pg.evaluate(SCROLLERS, "#main") == []


def test_a_soloed_track_takes_a_row_and_the_desk_still_fits(browser, rig):
    rig.conn.run("next(t for t in song.tracks if t.name == 'Kick bus').solo = True\nresult = 1")
    pg = open_big(browser, rig, 360, 640)
    pg.wait_for_selector("#flags .chip.solo")
    pg.wait_for_timeout(250)
    got = pg.evaluate(DESK)
    for part in ("title", "pager", "tabs", "keys", "panel"):
        on_screen(got, part)
    assert (got["small"], got["spill"]) == (0, 0) and pg.evaluate(SCROLLERS, "#main") == []


def test_the_paging_row_steps_through_the_pages(browser, rig):
    pg = open_big(browser, rig, 375, 667)
    pages = pg.evaluate("window.zpkt.S.desk.pages.length")
    count = pg.locator("#pgcount").inner_text()
    assert (
        count.endswith(f"/ {len(set(p.get('page_id') or i for i, p in enumerate(rig.get('/api/desk')[1]['pages'])))}")
        and pages
    )
    nxt, prev = pg.locator(".dots button").nth(1), pg.locator(".dots button").nth(0)
    assert nxt.is_disabled() and "Previous page: " in prev.get_attribute("aria-label")  # the new Page is the last
    name = prev.get_attribute("aria-label").split(": ", 1)[1]
    prev.click()
    pg.wait_for_function(f"document.querySelector('#pagename').textContent === {name!r} && !window.zpkt.S.pend")
    assert not pg.locator(".dots button").nth(1).is_disabled()
    assert pg.evaluate(SCROLLERS, "#main") == []
