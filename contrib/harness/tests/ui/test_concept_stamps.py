"""Concept A, the stamp rally (/studio/checklist/concepts/stamps.html): a hold brings the stamp down and prints it, a
short tap prints nothing; each item's print is drawn from its hash alone, so it is identical after a reload and in a
fresh browser; the prints are the checklist's own checks; and what the agent has inked ahead of you shows as ghosts."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui


@pytest.fixture
async def server(tmp_path):
    srv = TestServer(app(tmp_path))
    await srv.start_server()
    yield srv
    await srv.close()


async def _open(browser, url, context=None):
    context = context or await browser.new_context(**IPHONE_15)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    return page, errors


PRESS = """async ([id, ms]) => {
  const well = document.querySelector(`#slots .slot[data-id='${id}'] .well`);
  well.scrollIntoView({block: 'center'});
  const r = well.getBoundingClientRect();
  const o = {pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  well.dispatchEvent(new PointerEvent('pointerdown', o));
  await new Promise((ok) => setTimeout(ok, ms));
  well.dispatchEvent(new PointerEvent('pointerup', o));
}"""

PRINT = "(id) => document.querySelector(`#slots .slot[data-id='${id}'] svg.print`)?.outerHTML ?? null"


async def test_a_hold_prints_and_a_tap_does_not(webkit, server):
    url = str(server.make_url("/studio/checklist/concepts/stamps.html#kick"))
    page, errors = await _open(webkit, url)
    await page.wait_for_selector("#sheet.open .slot")
    await page.evaluate(PRESS, ["roar", 120])                              # lifted early: nothing prints
    await page.wait_for_timeout(100)
    assert await page.evaluate(PRINT, "roar") is None
    assert await page.get_attribute("#slots .slot[data-id='roar']", "data-role") != "done"
    await page.evaluate(PRESS, ["roar", 650])                              # held to the notch: it prints
    assert await page.get_attribute("#slots .slot[data-id='roar']", "data-role") == "done"
    first = await page.evaluate(PRINT, "roar")
    assert first and "mask=" in first

    await page.reload()                                                    # the same print after a reload
    await page.wait_for_selector("#sheet.open .slot")
    assert await page.evaluate(PRINT, "roar") == first

    other = await webkit.new_context(**IPHONE_15)                          # and for the same item anywhere else
    fresh, more = await _open(webkit, url, other)
    await fresh.wait_for_selector("#sheet.open .slot")
    assert await fresh.evaluate(PRINT, "roar") is None                     # (nothing stamped in this browser yet)
    await fresh.evaluate(PRESS, ["roar", 650])
    assert await fresh.evaluate(PRINT, "roar") == first
    await other.close()

    await page.evaluate(PRESS, ["roar", 650])                              # holding a print lifts it
    assert await page.evaluate(PRINT, "roar") is None
    assert errors == [] and more == [], errors + more
    await page.context.close()


async def test_a_stamp_is_the_checklists_own_check(webkit, server):
    page, errors = await _open(webkit, str(server.make_url("/studio/checklist/concepts/stamps.html")))
    await page.wait_for_selector(".pcard")
    assert await page.text_content("#total-n") == "22"
    await page.click(".pcard[data-step='master']")                        # any card, in any order: nothing is locked
    await page.wait_for_selector("#sheet.open .slot")
    await page.evaluate(PRESS, ["chain", 650])
    await page.click("#sheet-back")
    await page.wait_for_function("() => !document.getElementById('sheet').classList.contains('open')")
    assert await page.text_content("#total-n") == "23"
    assert await page.text_content(".pcard[data-step='master'] .pc-count") == "2/5"

    await page.goto(str(server.make_url("/studio/checklist/")))
    await page.wait_for_selector(".card")
    assert await page.get_attribute("#step-master .item[data-id='chain']", "data-state") == "done"
    assert errors == [], errors
    await page.context.close()


async def test_the_kick_card_shows_the_agents_ghosts(webkit, server):
    page, errors = await _open(webkit, str(server.make_url("/studio/checklist/concepts/stamps.html")))
    await page.wait_for_selector(".pcard")
    assert await page.locator(".pcard[data-step='kick'] .pc-tag").count() == 1         # suggested, not required
    await page.click(".pcard[data-step='kick']")
    await page.wait_for_selector("#sheet.open .slot")
    roles = await page.eval_on_selector_all("#slots .slot", "els => els.map((e) => e.dataset.role)")
    assert roles[:6] == ["done", "you", "ready", "ready", "clearing", "ahead"]
    for slot_id in ("decapStyle", "transient", "eq"):                      # inked ahead by the agent: a ghost
        assert await page.locator(f"#slots .slot[data-id='{slot_id}'] svg.ghost").count() == 1
    for slot_id in ("drive", "comp", "pick"):                              # yours, or past the agent: no ghost
        assert await page.locator(f"#slots .slot[data-id='{slot_id}'] svg.ghost").count() == 0
    assert "Batch 8.1" in await page.text_content("#slots .slot[data-id='drive'] .why")
    # the ghost is the print that will land: the same placement
    ghost = await page.get_attribute("#slots .slot[data-id='transient'] svg.ghost > g", "transform")
    await page.evaluate(PRESS, ["transient", 650])
    assert await page.get_attribute("#slots .slot[data-id='transient'] svg.print > g", "transform") == ghost
    await page.go_back()
    await page.wait_for_function("() => !document.getElementById('sheet').classList.contains('open')")
    assert errors == [], errors
    await page.context.close()
