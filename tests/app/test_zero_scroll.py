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
    assert pg.evaluate(SCROLLERS, "#app") == []  # the Desk, the Hear bar, History, the list of Pages: none scrolls
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


def many_changes(rig, count: int) -> None:
    """A long history: more rows than any screen holds."""
    keys = [
        v["key"] for v in rig.state()["values"].values() if v.get("key") and v.get("n") is not None and not v.get("q")
    ]
    keys = list(dict.fromkeys(keys))[:2]
    for i in range(count):
        rig.command("mix.set", {"norms": [[keys[i % 2], 0.2 + 0.01 * i]]})


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_history_is_paged_newest_first_and_never_scrolls(browser, rig, width, height):
    many_changes(rig, 30)
    pg = open_big(browser, rig, width, height)
    if width < 1100:
        pg.click("#khist")
    pg.wait_for_selector("#hrows .he.row")
    assert pg.evaluate(SCROLLERS, "#app") == []
    rows = pg.locator("#hrows > *")
    shown, total = rows.count(), int(pg.locator("#hrows").get_attribute("data-total"))
    assert 1 <= shown < total and total >= 30
    box, last = pg.locator("#hrows").bounding_box(), rows.nth(shown - 1).bounding_box()
    assert last["y"] + last["height"] <= box["y"] + box["height"] + 1  # every row shown is whole
    newest = rig.desk.history.entries[-1]["id"]
    assert rows.nth(0).get_attribute("data-row") == str(newest)  # newest first
    newer, older = pg.locator('#hpgs [data-histstep="-1"]'), pg.locator('#hpgs [data-histstep="1"]')
    assert newer.is_disabled() and older.bounding_box()["height"] >= 44
    assert pg.locator("#hpgn").inner_text() == f"1–{shown} / {total}"
    older.click()
    pg.wait_for_function(f"document.querySelector('#hpgn').textContent.startsWith('{shown + 1}–')")
    assert pg.locator("#hrows > *").nth(0).get_attribute("data-row") != str(newest) and not newer.is_disabled()
    assert pg.evaluate(SCROLLERS, "#app") == []
    for part in ("#hpgs", "#cpform", "#tabs"):
        b = pg.locator(part).bounding_box()
        assert b["y"] >= 0 and b["y"] + b["height"] <= height + 0.5, part
    rig.command("history.checkpoint", {"name": "a new one", "new": True})  # a save brings the newest part back
    pg.wait_for_selector('#hrows .he.cp[data-cp="a new one"]')
    assert pg.locator("#hpgn").inner_text().startswith("1–")


# ---- the Song -----------------------------------------------------------------------------------------------------------


def many_tracks(rig, count: int) -> None:
    """A set with more tracks than a phone holds at 14 px each, a clip on each."""
    rig.conn.run(
        f"for i in range({count}):\n    t = song.create_midi_track(-1)\n    t.name = 'extra %02d' % i\n"
        "    t.create_midi_clip(float(4 * (i % 8)), 16.0)\nresult = 1"
    )


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_the_song_never_scrolls_and_its_lanes_fit_or_are_paged(browser, rig, width, height):
    many_tracks(rig, 30)
    pg = browser.new_page(viewport={"width": width, "height": height})
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_selector("#lanes .lane")
    pg.wait_for_timeout(250)
    assert pg.evaluate(SCROLLERS, "#app") == []
    assert pg.evaluate("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]") == [
        width,
        height,
    ]
    main = pg.locator("#main").bounding_box()
    paged = pg.locator("#lanepgs").is_visible()
    parts = [
        "#ruler",
        "#tabs",
        *(["#lanepgs"] if paged else []),
    ]
    for part in parts:
        b = pg.locator(part).bounding_box()
        assert b and b["y"] >= 0 and b["y"] + b["height"] <= height + 0.5 and b["x"] + b["width"] <= width + 0.5, part
        if part != "#tabs":
            assert b["y"] + b["height"] <= main["y"] + main["height"] + 0.5, part  # inside the Song's own box
    shown = pg.locator("#lanes .lane:visible")
    total = pg.locator("#lanes .lane").count()
    assert all(b["height"] >= 13.5 for b in [shown.nth(i).bounding_box() for i in range(shown.count())])  # whole lanes
    if not paged:  # a tall screen holds them all
        assert height >= 800 and shown.count() == total
    else:  # a part of the lanes, the ruler over every part
        assert 1 <= shown.count() < total
        last, box = shown.nth(shown.count() - 1).bounding_box(), pg.locator("#lanepgs").bounding_box()
        assert last["y"] + last["height"] <= box["y"] + 0.5
        first, said = shown.nth(0).inner_text(), pg.locator("#lanepgn").inner_text()
        assert said.startswith("1–") and said.endswith(f"/ {total}")
        pg.click('#lanepgs [data-songstep="1"]')
        assert pg.locator("#lanes .lane:visible").nth(0).inner_text() != first and pg.locator("#ruler").is_visible()
    small = pg.evaluate(
        "[...document.querySelectorAll('#song button, #song select')].map(b => b.getBoundingClientRect()).filter(r => r.width && (r.height < 43.5 || r.width < 43.5)).length"
    )
    assert small == 0 and pg.evaluate(SCROLLERS, "#app") == []


def test_a_short_arrangement_shows_every_lane_with_no_paging(browser, rig):
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    pg.goto(rig.url + "/app/#song")
    pg.wait_for_selector("#lanes .lane")
    assert (
        pg.locator("#lanepgs").is_hidden()
        and pg.locator("#lanes .lane:visible").count() == pg.locator("#lanes .lane").count()
    )
