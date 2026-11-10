"""The repair board (/studio/checklist/concepts/repair.html), one of three concepts for the checklist: every item a tile
on one screen, restored (ink) or decayed (grime, the same for an item every time). Scrubbing a tile clean restores
it; opening an item again cracks the cleared items after it in its step, and scrubbing a crack heals it in gold,
which stays. It shares its checks with the checklist page."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui


@pytest.fixture
async def server(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield server
    await server.close()


async def _open(browser, server):
    context = await browser.new_context(**IPHONE_15)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(str(server.make_url("/studio/checklist/concepts/repair.html")))
    await page.wait_for_selector("body[data-ready]")
    return page, errors


# Strokes across the surface, one per row (fractions of its height), as a finger would.
SCRUB = """async (rows) => {
  const el = document.getElementById('surface'); const r = el.getBoundingClientRect();
  const ev = (t, x, y) => el.dispatchEvent(new PointerEvent(t, {pointerId: 5, pointerType: 'touch', bubbles: true,
    isPrimary: true, clientX: r.left + x * r.width, clientY: r.top + y * r.height}));
  for (const y of rows) {
    ev('pointerdown', 0.02, y);
    for (let x = 0.02; x <= 0.98; x += 0.04) ev('pointermove', x, y);
    ev('pointerup', 0.98, y);
    await new Promise((ok) => setTimeout(ok, 5));
  }
}"""
EVERYWHERE = [i / 12 for i in range(13)]


async def _tile(page, key):
    return await page.get_attribute(f".tile[data-key='{key}']", "data-state")


async def _sheet(page, key):
    await page.tap(f".tile[data-key='{key}']")
    await page.wait_for_selector("#sheet.open")
    await page.wait_for_timeout(350)


async def _close(page):
    await page.click("#sheet-close")
    await page.wait_for_selector("#sheet:not(.open)", state="attached")


async def test_scrubbing_a_tile_clean_restores_it_and_half_a_scrub_does_not(webkit, server):
    page, errors = await _open(webkit, server)
    assert await page.locator(".tile").count() == 49
    assert await _tile(page, "kick.decapStyle") == "decayed"
    await _sheet(page, "kick.decapStyle")
    await page.evaluate(SCRUB, [0.3, 0.5])                              # two strokes: partly clean, not restored
    clean = int(await page.get_attribute("#surface", "data-clean"))
    assert 10 < clean < 85
    assert await _tile(page, "kick.decapStyle") == "decayed"
    await page.evaluate(SCRUB, EVERYWHERE)
    await page.wait_for_function("document.querySelector(\".tile[data-key='kick.decapStyle']\").dataset.state === 'restored'")
    assert "Restored" in await page.text_content("#meter-n")
    await _close(page)
    await page.goto(str(server.make_url("/studio/checklist/")))           # the same check, on the checklist page
    await page.wait_for_selector(".card")
    assert await page.get_attribute("#step-kick .item[data-id='decapStyle']", "data-state") == "done"
    assert errors == [], errors
    await page.context.close()


async def test_the_grime_is_the_same_every_time(webkit, server):
    page, errors = await _open(webkit, server)
    shot = "(k) => document.querySelector(`.tile[data-key='${k}'] canvas`).toDataURL()"
    a, b = await page.evaluate(shot, "mix.sfx"), await page.evaluate(shot, "mix.space")
    assert a != b                                                          # each item has its own
    await page.reload()
    await page.wait_for_selector("body[data-ready]")
    assert await page.evaluate(shot, "mix.sfx") == a                       # and keeps it
    await _sheet(page, "mix.sfx")
    big = await page.evaluate("document.getElementById('grime').toDataURL()")
    await _close(page)
    await _sheet(page, "mix.sfx")
    assert await page.evaluate("document.getElementById('grime').toDataURL()") == big
    assert errors == [], errors
    await page.context.close()


async def test_opening_an_item_again_cracks_what_was_built_on_it_and_a_scrubbed_crack_heals_in_gold(webkit, server):
    page, errors = await _open(webkit, server)
    await _sheet(page, "drums.hats")                                      # hats is restored: it can be opened again
    box = await page.locator("#reopen").bounding_box()
    await page.mouse.move(box["x"] + 20, box["y"] + 20)
    await page.mouse.down()
    await page.wait_for_timeout(200)                                       # a short press does nothing
    await page.mouse.up()
    assert await _tile(page, "drums.hats") == "restored"
    await _close(page)

    await _sheet(page, "drums.rack")
    box = await page.locator("#reopen").bounding_box()
    await page.mouse.move(box["x"] + 20, box["y"] + 20)
    await page.mouse.down()
    await page.wait_for_timeout(800)
    await page.mouse.up()
    await page.wait_for_function("document.querySelector(\".tile[data-key='drums.rack']\").dataset.state === 'decayed'")
    states = await page.eval_on_selector_all(".block[data-step='drums'] .tile", "ts => ts.map((t) => t.dataset.state)")
    assert states == ["decayed", "cracked", "cracked", "cracked", "cracked", "cracked"]
    assert await _tile(page, "collage.bed") == "restored"                 # other steps are untouched
    assert await _tile(page, "arrange.cut") == "restored"
    assert "5 cracked" in await page.text_content("#tally")
    await _close(page)

    await _sheet(page, "drums.hats")
    assert await page.get_attribute("#sheet", "data-state") == "cracked"
    await page.evaluate(SCRUB, EVERYWHERE)
    await page.wait_for_function("document.querySelector(\".tile[data-key='drums.hats']\").dataset.state === 'restored'")
    assert await page.get_attribute(".tile[data-key='drums.hats']", "data-gold") == "1"
    assert "gold once" in await page.text_content("#sheet-place")
    await _close(page)
    await page.reload()
    await page.wait_for_selector("body[data-ready]")
    assert await page.get_attribute(".tile[data-key='drums.hats']", "data-gold") == "1"      # the seam stays
    assert await _tile(page, "drums.hats") == "restored"
    assert await _tile(page, "drums.perc") == "cracked"
    assert "4 cracked" in await page.text_content("#tally")
    assert errors == [], errors
    await page.context.close()
