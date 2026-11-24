"""The Wasteland (/studio/checklist/map/: world.js, finds.js, card.js), on its bench (dev-world.html): every item
has one find out in its step's zone and every step a cache; a commit runs the trail out to the item's find and
settles on exactly the drawing a fresh render of the new done set gives (with the find tagged as just unlocked);
clearing a step opens its cache; the explore view pans without opening anything, opens a find or a signal on a tap,
and zooms; a find's card takes it into the crate, and a signal's card leads to the item that reaches it. Mocked:
nothing on the bench makes a sound."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

# counts every AudioContext the page makes: the Wasteland is mocked and must make none
NO_AUDIO = """
window.__ac = 0;
for (const name of ['AudioContext', 'webkitAudioContext']) {
  const C = window[name];
  if (C) window[name] = class extends C { constructor(...a) { super(...a); window.__ac++; } };
}
"""

TAP = """(el) => {
  const r = el.getBoundingClientRect();
  const o = {pointerId: 7, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o));
}"""


@pytest.fixture
async def bench(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield lambda q: str(server.make_url(f"/studio/checklist/map/dev-world.html?{q}"))
    await server.close()


async def _open(browser, url):
    context = await browser.new_context(**IPHONE_15, color_scheme="dark")
    await context.add_init_script(NO_AUDIO)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_function("() => window.__dev")
    return page, errors


async def _tap(page, selector):
    await page.evaluate(TAP, await page.query_selector(selector))


async def test_every_item_has_a_find_and_every_step_a_cache(webkit, bench):
    page, errors = await _open(webkit, bench("auto=0"))
    missing = await page.evaluate("""() => {
      const d = window.__dev, keys = new Set(d.data.steps.flatMap((s) => s.items.map((it) => `${s.id}.${it.id}`)));
      const out = [];
      for (const k of keys) if (!d.FINDS[k]) out.push(`no find for ${k}`);
      for (const s of d.data.steps) if (!d.CACHES[s.id]) out.push(`no cache for ${s.id}`);
      for (const f of [...Object.values(d.FINDS), ...Object.values(d.CACHES)]) {
        for (const u of f.useIn) if (!keys.has(u)) out.push(`${f.key} is used in ${u}, which is no item`);
        for (const field of ['kind', 'title', 'what', 'size', 'why']) if (!f[field]) out.push(`${f.key} has no ${field}`);
      }
      if (Object.keys(d.FINDS).length !== keys.size) out.push('finds for items that do not exist');
      // one find per item, each placed once, none on top of another
      const L = d.W.world(d.data);
      if (L.finds.length !== keys.size) out.push('the map places the wrong number of finds');
      for (const a of L.finds) for (const b of L.finds) if (a !== b && Math.hypot(a.x - b.x, a.y - b.y) < 16) out.push(`${a.key} on ${b.key}`);
      return out;
    }""")
    assert missing == [], missing
    assert errors == [], errors
    await page.context.close()


async def test_a_commit_runs_out_to_its_find_and_settles_on_the_new_drawing(webkit, bench):
    page, errors = await _open(webkit, bench("auto=0&item=kick.drive"))
    before = await page.evaluate("() => window.__dev.expected('kick.drive', false, 'before')")
    assert 'class="wl-signal" data-key="kick.drive"' in before                  # a signal through the fog
    await page.evaluate("() => { window.__p = window.__dev.run(); }")
    await page.wait_for_timeout(1600)
    assert await page.locator("#stage .wl-trail.live").count() >= 1              # the trail is being drawn
    res = await page.evaluate("() => window.__p")
    assert res["ms"] < 6000, res
    assert res["unlocked"] == ["kick.drive"], res
    settled = await page.inner_html("#stage")
    assert settled == await page.evaluate("() => window.__dev.expected('kick.drive', false, 'after', ['kick.drive'])")
    assert await page.locator("#stage .wl-poi.fresh[data-key='kick.drive']").count() == 1
    assert await page.locator("#stage .wl-tag[data-key='kick.drive']").count() == 1
    assert await page.locator("#stage .wl-signal[data-key='kick.drive']").count() == 0
    # the same set reached in another order draws the same
    same = await page.evaluate("""() => {
      const d = window.__dev, s = d.sets('kick.drive', false).after;
      return d.norm(d.W.render(d.data, new Set([...s].reverse()), { fresh: new Set(['kick.drive']), taken: d.taken }));
    }""")
    assert same == settled
    assert await page.locator("#mini svg .wl-mnew").count() == 1                # something new, in the header
    assert await page.evaluate("window.__ac") == 0
    assert errors == [], errors
    await page.context.close()


async def test_clearing_a_step_opens_its_cache(webkit, bench):
    page, errors = await _open(webkit, bench("auto=0&item=kick.pick&fill=1"))
    before = await page.evaluate("() => window.__dev.expected('kick.pick', true, 'before')")
    assert 'class="wl-cache sealed" data-step="kick"' in before
    assert "IV KICK" not in before
    res = await page.evaluate("() => window.__dev.run()")
    assert res["unlocked"] == ["kick.pick", "cache:kick"], res
    assert await page.locator("#stage .wl-cache:not(.sealed)[data-step='kick']").count() == 1
    assert await page.locator("#stage .wl-tag.cache[data-step='kick']").count() == 1
    assert "IV KICK" in await page.inner_html("#stage")
    assert await page.inner_html("#stage") == await page.evaluate(
        "() => window.__dev.expected('kick.pick', true, 'after', ['kick.pick', 'kick'])")
    assert errors == [], errors
    await page.context.close()


async def test_explore_pans_opens_finds_and_signals_and_zooms(webkit, bench):
    page, errors = await _open(webkit, bench("explore=1"))
    await page.wait_for_selector(".wl-explore .wl-poi")
    view = page.locator(".wl-x-view")
    box = await view.bounding_box()
    assert box["width"] == 393
    assert "22 of 49 found" in await page.text_content(".wl-x-count")
    # zoom in (to the frontier), then drag: the view moves and nothing opens
    await _tap(page, ".wl-x-zoom")
    assert await page.get_attribute(".wl-x-zoom", "aria-pressed") == "true"
    v0 = await page.evaluate("() => document.querySelector('.wl-x-view svg').getAttribute('viewBox')")
    await page.evaluate("""() => {
      const el = document.querySelector('.wl-x-view svg'), r = el.getBoundingClientRect();
      const at = (x, y) => ({pointerId: 9, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: x, clientY: y});
      const x = r.x + r.width / 2, y = r.y + r.height / 2;
      el.dispatchEvent(new PointerEvent('pointerdown', at(x, y)));
      for (let i = 1; i <= 6; i++) el.dispatchEvent(new PointerEvent('pointermove', at(x - i * 12, y - i * 6)));
      el.dispatchEvent(new PointerEvent('pointerup', at(x - 72, y - 36)));
    }""")
    v1 = await page.evaluate("() => document.querySelector('.wl-x-view svg').getAttribute('viewBox')")
    assert v1 != v0
    assert await page.evaluate("window.__dev.log") == []
    # back out to the whole map, then a tap on a found find opens its card
    await _tap(page, ".wl-x-zoom")
    assert await page.get_attribute(".wl-x-zoom", "aria-pressed") == "false"
    await _tap(page, ".wl-x-view .wl-poi[data-key='drums.hats'] .wl-poi-bg")
    assert await page.evaluate("window.__dev.log") == [["find", "drums.hats"]]
    await page.wait_for_selector(".wl-card[data-key='drums.hats']")
    await _tap(page, ".wl-card .wl-c-back")
    await page.wait_for_selector(".wl-card", state="detached")
    # a signal through the fog opens what reaches it
    await _tap(page, ".wl-x-view .wl-signal[data-key='kick.transient'] .wl-sig-dot")
    assert ["signal", "kick.transient"] in await page.evaluate("window.__dev.log")
    await page.wait_for_selector(".wl-card.signal")
    assert "transient shaper" in await page.text_content(".wl-card.signal")
    assert "release without it" in await page.text_content(".wl-card.signal")
    await _tap(page, ".wl-card.signal .wl-c-work")
    assert ["work", "kick.transient"] in await page.evaluate("window.__dev.log")
    await _tap(page, ".wl-card.signal .wl-c-pass")
    await page.wait_for_selector(".wl-card", state="detached")
    # a double tap on open ground zooms in there
    await page.evaluate("""() => {
      const el = document.querySelector('.wl-x-view svg'), r = el.getBoundingClientRect();
      const o = {pointerId: 11, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height * 0.62};
      for (let i = 0; i < 2; i++) { el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o)); }
    }""")
    assert await page.get_attribute(".wl-x-zoom", "aria-pressed") == "true"
    await _tap(page, ".wl-x-back")
    assert ["close"] in await page.evaluate("window.__dev.log")
    assert await page.locator(".wl-explore").count() == 0
    assert await page.evaluate("window.__ac") == 0
    assert errors == [], errors
    await page.context.close()


async def test_a_card_takes_its_find_into_the_crate(webkit, bench):
    page, errors = await _open(webkit, bench("card=kick.drive"))
    await page.wait_for_selector(".wl-card[data-key='kick.drive']")
    text = await page.text_content(".wl-card")
    assert "Kicks already driven like yours" in text and "mocked: no audio" in text and "Use in" in text
    take = ".wl-card .wl-c-take"
    assert await page.get_attribute(take, "aria-pressed") == "false"
    assert "Take into HW002" in await page.text_content(take)
    await _tap(page, take)
    assert await page.get_attribute(take, "aria-pressed") == "true"
    assert "In HW002's crate" in await page.text_content(take)
    assert await page.evaluate("[...window.__dev.taken]") == ["kick.drive"]
    await _tap(page, take)
    assert await page.evaluate("[...window.__dev.taken]") == []
    await _tap(page, take)
    # the player is mocked: its playhead moves, nothing sounds
    await _tap(page, ".wl-card .wl-c-play")
    assert await page.get_attribute(".wl-card .wl-c-play", "aria-pressed") == "true"
    # "use in" leads to that item's widget
    await _tap(page, ".wl-card .wl-c-use[data-key='kick.pick']")
    assert ["work", "kick.pick"] in await page.evaluate("window.__dev.log")
    # a taken find is marked on the map
    await _tap(page, ".wl-card .wl-c-back")
    markup = await page.evaluate("() => window.__dev.W.render(window.__dev.data, new Set(['kick.drive']), { taken: window.__dev.taken })")
    assert 'class="wl-poi taken" data-key="kick.drive"' in markup
    assert await page.evaluate("window.__ac") == 0
    assert errors == [], errors
    await page.context.close()
