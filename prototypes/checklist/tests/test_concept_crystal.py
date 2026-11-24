"""The crystal concept (/studio/checklist/concepts/crystal.html): the track's checklist as one crystal, a pure
function of the cleared items (the same set draws byte-identical SVG however it was reached), a shard grown for each
item cleared, and Release now (mocked) freezing the crystal as a pressing that later checks never change."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui


@pytest.fixture
async def server(tmp_path):
    s = TestServer(app(tmp_path))
    await s.start_server()
    yield s
    await s.close()


async def _open(browser, url):
    context = await browser.new_context(**IPHONE_15)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_selector("#live .crystal")
    return page, errors


DRAW = """async ([orders, change]) => {
  const { drawCrystal } = await import('./crystal-draw.js');
  const data = await (await fetch('../data/hw002.json')).json();
  const keys = data.steps.flatMap((s) => s.items.map((it) => `${s.id}.${it.id}`));
  const pick = keys.filter((_, i) => i % 3 !== 1);                      // a fixed set: two items in three
  const sets = orders.map((o) => {
    const order = o === 'reverse' ? [...pick].reverse() : o === 'shuffled' ? pick.map((k, i) => [(i * 7919) % 101, k]).sort().map(([, k]) => k) : pick;
    const s = new Set(); for (const k of order) s.add(k); return s;     // the same set, built in a different order
  });
  const out = sets.map((s) => drawCrystal(data, s));
  out.push(drawCrystal(data, [...pick]));                               // an array works the same
  if (change) { const s = new Set(pick); s.delete(pick[5]); out.push(drawCrystal(data, s)); }
  return out;
}"""


async def test_the_same_set_draws_the_same_crystal_whatever_the_order(webkit, server):
    page, errors = await _open(webkit, str(server.make_url("/studio/checklist/concepts/crystal.html")))
    a, b, c, arr, changed = await page.evaluate(DRAW, [["forward", "reverse", "shuffled"], True])
    assert a == b == c == arr                                             # byte-identical
    assert changed != a                                                   # one item less draws something else
    assert a.count('class="shard solid') == changed.count('class="shard solid') + 1
    assert errors == [], errors
    await page.context.close()


async def test_clearing_an_item_grows_one_shard_and_shows_on_the_checklist(webkit, server):
    page, errors = await _open(webkit, str(server.make_url("/studio/checklist/concepts/crystal.html")))
    before = await page.locator("#live .shard.solid").count()
    assert before == 22
    await page.click(".step[data-step='kick']")                          # the fold: the kick's items
    assert await page.locator("#list li").count() == 10
    await page.click("#list .check[data-key='kick.roar']")
    assert await page.get_attribute("#list .check[data-key='kick.roar']", "aria-checked") == "true"
    assert await page.locator("#live .shard.solid").count() == before + 1
    assert await page.locator("#live .shard.new").count() == 1             # only that shard grows in
    assert await page.locator("#live .shard.new[data-key='kick.roar']").count() == 1
    assert await page.text_content("#total-n") == "23"
    await page.click("#list .check[data-key='kick.roar']")               # and back: the shard is a trace again
    assert await page.locator("#live .shard.solid").count() == before
    await page.click("#list .check[data-key='kick.roar']")
    await page.goto(str(server.make_url("/studio/checklist/")))           # one checklist: the other view agrees
    await page.wait_for_selector(".card")
    assert await page.get_attribute("#step-kick .item[data-id='roar']", "data-state") == "done"
    assert errors == [], errors
    await page.context.close()


async def test_release_now_freezes_a_pressing_that_later_checks_never_change(webkit, server):
    page, errors = await _open(webkit, str(server.make_url("/studio/checklist/concepts/crystal.html")))
    assert await page.locator(".pressing").count() == 0
    await page.click("#release")                                          # always available: nothing is locked
    assert await page.locator(".pressing").count() == 1
    assert await page.text_content(".pressing .of") == "22/49"
    frozen = await page.inner_html(".pressing .art")
    live = await page.inner_html("#live")
    assert frozen == live                                                 # the crystal as it was
    await page.click(".step[data-step='mix']")
    await page.click("#list .check[data-key='mix.groups']")
    await page.click("#list .check[data-key='mix.space']")
    assert await page.inner_html(".pressing .art") == frozen              # later checks: the pressing stays
    assert await page.inner_html("#live") != frozen                       # the live crystal moves on
    await page.reload()
    await page.wait_for_selector("#live .crystal")
    assert await page.locator(".pressing").count() == 1                   # kept
    assert await page.inner_html(".pressing .art") == frozen
    assert await page.text_content(".pressing .of") == "22/49"
    await page.click("#release")
    assert await page.locator(".pressing").count() == 2
    assert await page.text_content(".pressing:first-child .of") == "24/49"   # the newest first
    assert errors == [], errors
    await page.context.close()
