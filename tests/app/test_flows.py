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
    box = pg.locator(f'.ctl[data-slot="{slot}"] .w').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x, y + dy, steps=6)
    pg.mouse.up()


def test_flow_1_mix_drag_a_control_and_live_moves_then_pin_and_touch(rig, page):
    slot, key, _ = first_control(rig, "f")
    assert page.locator("#chgpill").inner_text() == "0 changed"
    before = rig.desk.history.cur[key][1]
    drag(page, slot, -60)  # up
    page.wait_for_function("document.querySelector('#chgpill').textContent.startsWith('1')")
    assert rig.desk.history.cur[key][1] != before  # Live moved
    assert page.locator(f'.ctl[data-slot="{slot}"]').get_attribute("class").count("chg") == 1  # the lime dot
    page.click('[data-hear="pin"]')
    page.wait_for_selector("#hearpill")
    assert page.locator("#hearpill").inner_text() == "hearing Pin"
    assert page.locator("#banner").is_visible()
    drag(page, slot, 40)  # touch any control: back on Now, with the move counted from Now
    page.wait_for_function("!document.querySelector('#hearpill')")
    assert not page.locator("#banner").is_visible()
    assert rig.desk.history.entries[-1]["who"] == "you"


def test_flow_5_compare_with_hardware_hold_the_pin_and_let_go(rig, page):
    _, key, _ = first_control(rig, "f")
    rig.desk.bus.submit(Command("mix.set", "you", {"norms": [[key, 0.2]]}))
    page.wait_for_function("document.querySelector('#chgpill').textContent.startsWith('1')")
    rig.desk.bus.submit(Command("monitor.hear", "minilab", {"hearing": "pin"}))  # bend up
    page.wait_for_selector("#hearpill")
    assert page.locator("#hearpill").inner_text() == "hearing Pin"
    rig.desk.bus.submit(Command("monitor.hear", "minilab", {"hearing": "now"}))  # let go
    page.wait_for_function("!document.querySelector('#hearpill')")
    assert page.locator("#chgpill").inner_text() == "1 changed"


def test_flow_6_undo_the_history_names_who_and_an_agent_group_undoes_as_one(rig, page):
    keys = [v["key"] for k, v in rig.state()["values"].items() if v.get("key") and k.startswith("0:f")][:3]
    for k in keys:
        rig.desk.bus.submit(
            Command("mix.set", "agent", {"norms": [[k, 0.15]]}, approval="user", group="make the kick sit back")
        )
    page.wait_for_function("document.querySelector('#chgpill').textContent.startsWith('3')")
    page.click("#khist")
    page.wait_for_selector(".he .who.agent")
    rows = page.locator(".he").all_inner_texts()
    assert any("agent" in r and "make the kick sit back" in r for r in rows)
    assert any("sys" in r and "version" in r for r in rows)  # the automatic version before the agent's changes
    page.click("#hundo")
    page.wait_for_function("document.querySelector('#chgpill').textContent.startsWith('0')")  # all three at once
    assert page.locator("#chgpill").inner_text() == "0 changed"
