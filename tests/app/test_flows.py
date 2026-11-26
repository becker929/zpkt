"""Browser flows of the /app/ shell in WebKit, against the app on FakeLive (flows 1, 5 and 6 of DESIGN section 11).

They need the playwright extra and its WebKit (`uv sync --extra e2e`, `playwright install webkit`) and skip when
either is missing. The page is the real page, served by the real server; Live is a FakeLive, the MiniLab and the agent
are commands on the bus.
"""

from __future__ import annotations

import pytest

from tests.app.test_web import first_control
from zpkt.app.bus import Command

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def page(rig):
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:  # the browser is not installed on this machine
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        context = browser.new_context(viewport={"width": 390, "height": 844})
        pg = context.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(rig.url + "/app/")
        pg.wait_for_selector(".ctl .w")
        pg.errors = errors  # type: ignore[attr-defined]
        yield pg
        browser.close()
    assert errors == []


def drag(pg, slot: str, dy: float) -> None:
    if not pg.locator(f'.ctl[data-slot="{slot}"] .w').is_visible():  # a phone shows one face of the map at a time
        pg.click(f'#faces [data-face="{"f" if slot[0] == "f" or slot in ("b5", "b6", "b7", "b8") else "k"}"]')
    box = pg.locator(f'.ctl[data-slot="{slot}"] .w').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x, y + dy, steps=6)
    pg.mouse.up()


def test_flow_1_mix_drag_a_control_and_live_moves(rig, page):
    slot, key, _ = first_control(rig, "f")
    assert page.locator("#chgn").inner_text() == "0 changed"
    before = rig.desk.history.cur[key][1]
    drag(page, slot, -60)  # up
    page.wait_for_function("document.querySelector('#chgn').textContent.startsWith('1')")
    page.wait_for_function("window.zpkt.S.hear.changed === 1")
    assert rig.desk.history.cur[key][1] != before  # Live moved
    assert page.locator(f'.ctl[data-slot="{slot}"]').get_attribute("class").count("chg") == 1  # the lime dot
    assert rig.desk.history.entries[-1]["who"] == "you"


def test_the_list_view_names_each_control_in_a_row_and_a_row_is_moved_sideways(rig, page):
    """A phone away from the MiniLab reads the list (26 November 2026): a row per knob and fader, moved sideways. The
    head stays the surface's title while a control is in hand."""
    slot, key, _ = first_control(rig, "k")
    page.click("#viewsw")
    assert page.locator("#panel").get_attribute("data-view") == "list"
    row = page.locator(f'.ctl[data-slot="{slot}"]')
    box = row.bounding_box()
    assert (
        box["width"] > 250 and row.locator(".num").inner_text() == slot[1:]
    )  # a row as wide as the map, with its knob number
    before = rig.desk.history.cur[key][1]
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    assert page.locator("#pagename").count() == 1 and page.locator("#readout").count() == 0
    page.mouse.move(x + 60, y, steps=6)
    page.mouse.up()
    page.wait_for_function("window.zpkt.S.hear.changed === 1")
    assert rig.desk.history.cur[key][1] > before  # to the right is up
    # The whole row is the handle (Anthony could not get hold of a row on his phone): a drag that starts on the value
    # or on the group's name moves it too, and does not open the field for typing a value.
    for spot in (".v", ".g"):
        part = row.locator(spot)
        if not part.is_visible():
            continue
        was, pb = rig.desk.history.cur[key][1], part.bounding_box()
        px, py = pb["x"] + pb["width"] / 2, pb["y"] + pb["height"] / 2
        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px - 40, py + 3, steps=5)
        page.mouse.up()
        page.wait_for_timeout(300)
        assert rig.desk.history.cur[key][1] < was, spot
        assert page.locator(".vt").count() == 0, spot
    page.click("#viewsw")
    assert page.locator("#panel").get_attribute("data-view") == "map"


def test_compare_is_in_the_play_bar_and_history_chooses_the_pinned_b(rig, page):
    """A, B and C are keys of the play bar (26 November 2026): the mix now, the pinned mix, the reference. A checkpoint
    is chosen as B in History."""
    assert [b.inner_text() for b in page.locator("#abc button").all()] == ["A", "B", "C"]
    assert page.locator('#abc [data-hear="now"]').get_attribute("aria-pressed") == "true"
    page.click('#abc [data-hear="pin"]')
    page.wait_for_function("window.zpkt.S.hear.hearing === 'pin'")
    assert rig.desk.monitor.message()["hearing"] == "pin"
    assert page.locator('#abc [data-hear="pin"]').get_attribute("aria-pressed") == "true"
    page.click('#abc [data-hear="now"]')
    page.wait_for_function("window.zpkt.S.hear.hearing === 'now'")
    # a press shows at once: the key pulses until Live has answered (the walk: "more than 1 s with no visible change")
    page.evaluate("window.__hold = new Promise(r => { window.__go = r; }); window.__fetch = window.fetch; window.fetch = async (...a) => { if (String(a[0]).includes('/api/command')) await window.__hold; return window.__fetch(...a); }")
    page.click('#abc [data-hear="pin"]')
    page.wait_for_selector('#abc [data-hear="pin"].ask[aria-busy="true"]')
    page.evaluate("window.__go(); window.fetch = window.__fetch")
    page.wait_for_selector('#abc [data-hear="pin"]:not(.ask)[aria-pressed="true"]')
    page.click('#abc [data-hear="now"]')
    page.wait_for_function("window.zpkt.S.hear.hearing === 'now'")
    rig.desk.bus.submit(Command("history.checkpoint", "you", {"name": "before the hats", "new": True}))
    page.click("#khist")
    page.click('[data-pinb="before the hats"]')
    page.wait_for_function("window.zpkt.S.hear.pin === 'before the hats'")
    assert rig.desk.monitor.message()["pin"] == "before the hats"
    assert page.locator('[data-pinb="before the hats"]').get_attribute("aria-pressed") == "true"
    status, body = rig.desk.bus.submit(Command("monitor.pin", "you", {"name": "no such checkpoint"}))
    assert status == 404, body
    page.click('[data-pinb="before the hats"]')  # a tap on the lit B lets it go: B is the mix as first seen again
    page.wait_for_function("window.zpkt.S.hear.pin === 'start'")
    assert rig.desk.monitor.message()["pin"] == "start"
    assert page.locator('[data-pinb="before the hats"]').get_attribute("aria-pressed") == "false"


def test_the_monitor_tab_draws_a_curve_for_each_of_a_b_and_c_once_heard(rig, page):
    """The Monitor tab (26 November 2026): the live meter's bands as a curve for whichever of A, B and C is heard while
    the song plays, each kept as it was last heard, with a table of levels."""
    page.click("#tab-monitor")
    page.wait_for_selector("#monplot")
    assert page.evaluate("location.hash") == "#monitor" and page.locator("#desk").is_hidden()
    assert page.locator("#monplot path.cv").count() == 0  # nothing has been heard yet
    feed = """h => { const S = window.zpkt.S, hz = Array.from({length: 31}, (_, i) => 20 * Math.pow(1000, i / 30));
      S.state.playing = true; S.hear = {...S.hear, hearing: h};
      window.zpkt.monFeed({t: "meter", hz, db: hz.map(f => (h === "ref" ? -20 : -30) - Math.log2(f / 20))}); }"""
    page.evaluate(feed, "now")
    page.wait_for_selector("#monplot path.cv.a.on")
    page.evaluate(feed, "ref")
    page.wait_for_selector("#monplot path.cv.c.on")
    assert page.locator("#monplot path.cv").count() == 2 and page.locator("#monplot path.cv.a.on").count() == 0
    cells = [c.inner_text() for c in page.locator("#montab .num").all()]
    assert cells[0].startswith("−") and cells[1] == "–" and cells[2] == "+10.0"  # A's level, B unheard, C against A
    assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
    # a reading's length never moves a column (Anthony saw the columns shift with the digits)
    left = "[...document.querySelectorAll('#montab .hd')].map(e => Math.round(e.getBoundingClientRect().left))"
    before = page.evaluate(left)
    page.evaluate(feed.replace("-20 : -30", "-3 : -104"), "now")
    page.evaluate(feed.replace("-20 : -30", "-3 : -104"), "ref")
    assert page.evaluate(left) == before
    # three ways to see the one heard now: Live follows the newest reading, Smooth a second, Average four and evened out
    assert [b.inner_text() for b in page.locator("#monmode button").all()] == ["Live", "Smooth", "Average"]
    assert page.locator('#monmode [aria-pressed="true"]').inner_text() == "Smooth"
    shape = "document.querySelector('#monplot path.cv.c').getAttribute('d')"
    smooth = page.evaluate(shape)
    page.click('[data-monmode="average"]')
    assert page.evaluate(shape) != smooth and page.evaluate("localStorage.getItem('zpkt.mon')") == "average"
    page.click('[data-monmode="live"]')
    page.evaluate("""() => { const S = window.zpkt.S, hz = Array.from({length: 31}, (_, i) => 20 * Math.pow(1000, i / 30));
      window.zpkt.monFeed({t: "meter", hz, db: hz.map((f, i) => i === 15 ? -5 : -60)}); }""")
    page.wait_for_function(
        "was => { const d = document.querySelector('#monplot path.cv.c.on'); return d && d.getAttribute('d') !== was; }",
        arg=smooth,
    )
    page.wait_for_timeout(400)  # the curve has come to rest on the newest reading: one band far above the rest
    ys = page.evaluate(
        "document.querySelector('#monplot path.cv.c.on').getAttribute('d').split('C').slice(1).map(s => +s.trim().split(' ').pop())"
    )
    assert min(ys) == ys[14] and sorted(ys)[1] - ys[14] > 100
    page.evaluate("window.zpkt.S.state.playing = false")
    page.evaluate(feed.replace("S.state.playing = true;", ""), "pin")  # a stopped song adds nothing to a curve
    assert page.locator("#monplot path.cv.b").count() == 0


def test_flow_6_undo_the_history_names_who_and_an_agent_group_undoes_as_one(rig, page):
    keys = [v["key"] for k, v in rig.state()["values"].items() if v.get("key") and k.startswith("0:f")][:3]
    for k in keys:
        rig.desk.bus.submit(
            Command("mix.set", "agent", {"norms": [[k, 0.15]]}, approval="user", group="make the kick sit back")
        )
    page.wait_for_function("document.querySelector('#chgn').textContent.startsWith('3')")
    page.click("#khist")
    page.wait_for_selector(".he .who.agent")
    rows = page.locator(".he").all_inner_texts()
    older = page.locator('#hpgs [data-histstep="1"]')  # the rows are paged: the checkpoint may be on the next part
    while older.is_visible() and not older.is_disabled():
        older.click()
        rows += page.locator(".he").all_inner_texts()
    assert any("agent" in r and "make the kick sit back" in r for r in rows)
    assert any("sys" in r and "Before “make the kick sit back”" in r for r in rows)  # the automatic checkpoint, by name
    page.click("#kundo")  # Undo is on the Hear bar, under the sheet
    page.wait_for_function("document.querySelector('#chgn').textContent.startsWith('0')")  # all three at once
    assert page.locator("#chgn").inner_text() == "0 changed"
