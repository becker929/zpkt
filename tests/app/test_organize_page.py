"""The Surfaces organizer on the Desk in WebKit: every surface a row with its small MiniLab map, reorder by the
earlier and later keys and by dragging the map, rename, archive and restore, archive all, delete from the archive
with a confirm that shows the surface; paged, never scrolled. Skipped when playwright or its WebKit is missing."""

from __future__ import annotations

import pytest

from tests.app.conftest import wait_for
from tests.app.test_zero_scroll import SCROLLERS
from zpkt.app.bus import Command

playwright_sync = pytest.importorskip("playwright.sync_api")

SPEC = {
    "title": "Kick: level",
    "groups": [{"name": "g", "controls": [{"target": "Kick bus/volume"}, {"target": "Kick bus/mute"}]}],
}


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def units(rig, archived=False):
    return [u for u in rig.command("page.list")[1]["units"] if u["archived"] == archived]


def open_org(browser, rig, width, height):
    pg = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector("#panel .mc")
    pg.locator('[data-org="open"]:visible').first.click()
    pg.wait_for_selector("#sheet.on #orows .orgrow")
    pg.errors = errors  # type: ignore[attr-defined]
    return pg


@pytest.mark.parametrize(("width", "height"), [(375, 667), (1200, 800)])
def test_rows_show_the_map_and_reorder_rename_archive_restore_delete(browser, rig, width, height):
    made = rig.desk.bus.submit(Command("page.make", "agent", {"spec": SPEC}))[1]
    pg = open_org(browser, rig, width, height)
    before = [u["id"] for u in units(rig)]
    rows = pg.locator("#orows > .orgrow")
    first = rows.nth(0)
    assert first.get_attribute("data-uid") == before[0]
    lit = units(rig)[0]["slots"][0]
    assert (
        first.locator(".othumb svg .on").count() == len(lit) and first.locator(".othumb svg *").count() == 20
    )  # its map
    assert pg.evaluate(SCROLLERS, "#app") == []
    small = pg.evaluate(
        "[...document.querySelectorAll('#sheet button')].map(b => b.getBoundingClientRect()).filter(r => r.width && (r.width < 43.5 || r.height < 43.5)).length"
    )
    assert small == 0
    # later, by its key
    first.locator('[data-orgmove="1"]').click()
    wait_for(lambda: [u["id"] for u in units(rig)][:2] == [before[1], before[0]])
    pg.wait_for_function(f"document.querySelector('#orows > .orgrow').dataset.uid === {before[1]!r}")
    # and back, by dragging its map up over the row before it
    handle = pg.locator(f'#orows > .orgrow[data-uid="{before[0]}"] .ohandle').bounding_box()
    target = pg.locator("#orows > .orgrow").nth(0).bounding_box()
    pg.mouse.move(handle["x"] + 10, handle["y"] + 10)
    pg.mouse.down()
    pg.mouse.move(handle["x"] + 10, target["y"] + 4, steps=5)
    assert pg.locator("#orows .mark-before").count() == 1  # where it would land is marked
    pg.mouse.up()
    wait_for(lambda: [u["id"] for u in units(rig)] == before)
    pg.wait_for_function(f"document.querySelector('#orows > .orgrow').dataset.uid === {before[0]!r}")
    # a tap on a name shows what can be done with it: rename
    row = pg.locator(f'#orows > .orgrow[data-uid="{before[0]}"]')
    row.locator(".onm").click()
    pg.click(f'[data-orgren="{before[0]}"]')
    pg.fill("#orgname", "Front of house")
    pg.keyboard.press("Enter")
    pg.wait_for_function("document.querySelector('#orows > .orgrow .onm').textContent === 'Front of house'")
    assert units(rig)[0]["name"] == "Front of house"
    # archive: it leaves the desk and is kept
    row.locator(".onm").click()
    pg.click(f'[data-orgarch="{before[0]}"]')
    wait_for(lambda: [u["id"] for u in units(rig, archived=True)] == [before[0]])
    assert "Front of house" not in [p["name"] for p in rig.get("/api/desk")[1]["pages"]]
    pg.click('[data-orgtab="archived"]')
    arch = pg.locator("#orows > .orgrow")
    assert arch.count() == 1 and arch.locator(".onm").inner_text() == "Front of house"
    arch.locator(".onm").click()
    assert pg.locator("[data-orgdel]").count() == 0  # one of the desk's own: restored, never deleted
    pg.click(f'[data-orgrest="{before[0]}"]')
    wait_for(lambda: units(rig, archived=True) == [])
    # a made surface: archived, then deleted from the archive after a confirm that shows it
    uid = f"page:{made['id']}"
    assert rig.command("page.organize", {"action": "archive", "id": uid})[0] == 200
    pg.wait_for_selector('[data-orgtab="archived"]:not([disabled])')
    pg.click('[data-orgtab="archived"]')
    pg.locator(f'#orows > .orgrow[data-uid="{uid}"] .onm').click()
    pg.click(f'[data-orgdel="{uid}"]')
    confirm = pg.locator("#orows > .orgrow.gone")
    assert confirm.locator(".othumb").count() == 1 and "Kick: level" in confirm.inner_text()
    assert uid in [u["id"] for u in units(rig, archived=True)]  # nothing yet
    pg.click(f'[data-orgdelgo="{uid}"]')
    wait_for(lambda: uid not in [u["id"] for u in rig.command("page.list")[1]["units"]])
    assert pg.evaluate(SCROLLERS, "#app") == [] and pg.errors == []  # type: ignore[attr-defined]


def test_archive_all_empties_the_desk_and_restore_all_brings_it_back(browser, rig):
    pg = open_org(browser, rig, 375, 667)
    n = len(units(rig))
    assert pg.locator("#opgs").is_visible() and pg.locator("#orows > .orgrow").count() < n  # paged to its height
    pg.click('[data-orgall="archive_all"]')
    wait_for(lambda: units(rig) == [])
    pg.wait_for_selector("#asknew")  # the empty desk, behind the sheet
    pg.click('[data-orgtab="archived"]')
    pg.click('[data-orgall="restore_all"]')
    wait_for(lambda: len(units(rig)) == n and units(rig, archived=True) == [])
    pg.click("#oclose")
    pg.wait_for_selector("#panel .mc.live")
    assert pg.errors == []  # type: ignore[attr-defined]
