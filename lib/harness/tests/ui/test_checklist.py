"""The checklist page (/studio/checklist/): HW002's seven steps, the lowest incomplete one current, each step a path
(your move, what the agent has cleared ahead of you, where it is clearing, the fog past it), holding an item clears it
(and a cleared step hands over to the next), a tap opens the item's sub-list (below it, or on a page of its own), and
the tweaks panel changes how the page is built."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui


@pytest.fixture
async def checklist(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield str(server.make_url("/studio/checklist/"))
    await server.close()


async def _open(browser, url):
    context = await browser.new_context(**IPHONE_15)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_selector(".card")
    return page, errors


HOLD = """async ([step, id, ms]) => {
  const row = document.querySelector(`#step-${step} .item[data-id='${id}'] .row`);
  const r = row.getBoundingClientRect();
  const o = {pointerId: 3, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + 40, clientY: r.y + r.height / 2};
  row.dispatchEvent(new PointerEvent('pointerdown', o));
  await new Promise((ok) => setTimeout(ok, ms));
  row.dispatchEvent(new PointerEvent('pointerup', o));
}"""


async def test_it_shows_the_spine_with_the_kick_current(either, checklist):
    page, errors = await _open(either, checklist)
    assert await page.locator(".card").count() == 7
    assert await page.text_content("#hud-name") == "Kick"
    states = await page.eval_on_selector_all(".card", "cs => cs.map((c) => c.dataset.state)")
    assert states == ["clear", "clear", "clear", "current", "open", "open", "open"]
    assert await page.locator("#step-kick.open").count() == 1
    roles = await page.eval_on_selector_all("#step-kick .item", "els => els.map((e) => e.dataset.role)")
    assert roles[:6] == ["done", "you", "ready", "ready", "clearing", "ahead"]      # the agent clears the way ahead of you
    assert errors == [], errors
    await page.context.close()


async def test_holding_clears_a_tap_peeks_and_the_step_hands_over(webkit, checklist):
    page, errors = await _open(webkit, checklist)
    await page.evaluate(HOLD, ["kick", "roar", 100])                      # a tap: the sub-list opens, nothing clears
    assert await page.locator("#step-kick .item[data-id='roar'].peek .sub").count() >= 2
    href = await page.get_attribute("#step-kick .item[data-id='roar'] .studio-link", "href")
    assert href == "/studio/?focus=hw002.kick.roar"
    assert await page.get_attribute("#step-kick .item[data-id='roar']", "data-state") == "open"
    await page.evaluate(HOLD, ["kick", "roar", 700])                      # a hold clears it
    assert await page.get_attribute("#step-kick .item[data-id='roar']", "data-state") == "done"
    await page.evaluate(HOLD, ["kick", "drive", 700])                     # your move made: the next ready item is yours
    assert await page.get_attribute("#step-kick .item[data-id='decapStyle']", "data-role") == "you"
    ids = await page.eval_on_selector_all("#step-kick .item", "els => els.map((e) => e.dataset.id)")
    for i in ids:
        if await page.get_attribute(f"#step-kick .item[data-id='{i}']", "data-state") != "done":
            await page.evaluate(HOLD, ["kick", i, 700])
    await page.wait_for_function("() => document.getElementById('hud-name').textContent === 'Mix'", timeout=4000)
    assert await page.get_attribute("#step-kick", "data-state") == "clear"
    await page.reload()
    await page.wait_for_selector(".card")
    assert await page.text_content("#hud-name") == "Mix"                  # kept in this browser
    await page.click("#reset")
    assert await page.text_content("#hud-name") == "Kick"
    assert errors == [], errors
    await page.context.close()


async def test_the_tweaks_panel_changes_how_the_page_is_built(webkit, checklist):
    page, errors = await _open(webkit, checklist)
    assert await page.is_hidden("#hud")                                       # the default objective is the strip
    assert await page.is_visible("#strip")
    await page.click("#tweaks-tab")
    await page.wait_for_timeout(400)
    await page.click(".tw[data-id='objective'] button[data-v='full']")
    assert await page.is_visible("#hud") and await page.is_hidden("#strip")
    await page.click(".tw[data-id='details'] button[data-v='drill']")
    await page.click("#tweaks-tab")
    await page.wait_for_timeout(400)
    await page.evaluate(HOLD, ["kick", "comp", 100])                      # a tap now opens the item's own page
    await page.wait_for_selector("#drill.open .sub")
    assert "compressor" in await page.text_content("#drill h2")
    await page.click("#drill-back")
    await page.wait_for_function("() => !document.getElementById('drill').classList.contains('open')")
    await page.reload()
    await page.wait_for_selector(".card")
    assert await page.evaluate("document.documentElement.dataset.objective") == "full"      # kept
    assert errors == [], errors
    await page.context.close()
