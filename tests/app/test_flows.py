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
    rig.desk.bus.submit(Command("history.checkpoint", "you", {"name": "before the hats", "new": True}))
    page.click("#khist")
    page.click('[data-pinb="before the hats"]')
    page.wait_for_function("window.zpkt.S.hear.pin === 'before the hats'")
    assert rig.desk.monitor.message()["pin"] == "before the hats"
    assert page.locator('[data-pinb="before the hats"]').get_attribute("aria-pressed") == "true"
    status, body = rig.desk.bus.submit(Command("monitor.pin", "you", {"name": "no such checkpoint"}))
    assert status == 404, body


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
