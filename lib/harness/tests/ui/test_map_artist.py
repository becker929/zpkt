"""The artist agent's first slice on the map (/studio/checklist/map/, docs/artist-agent.md): each commit performs a
work from the artist's repertoire (a wax seal, a room lit in the colour of the decision, stars at night) and hangs a
plate in the gallery with the work, the map and the render of the task; the thumbs on both edges of every view store
a press at once, with what was on screen and what had just played, and then ask a quick question."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

TAP = """(sel) => {
  const el = typeof sel === 'string' ? document.querySelector(sel) : sel; const r = el.getBoundingClientRect();
  const o = {pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + Math.min(20, r.width / 2), clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o));
}"""
API = "(path) => fetch('/studio/api/artist/' + path).then((r) => r.json())"


@pytest.fixture
async def site(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield lambda q="": str(server.make_url(f"/studio/checklist/map/{q}"))
    await server.close()


async def _open(browser, url):
    context = await browser.new_context(**IPHONE_15, color_scheme="dark")
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_selector(".step")
    await page.evaluate("""() => { window.__seen = new Set();
      new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) if (n.className) __seen.add(String(n.className));
        for (const m of ms) if (m.type === 'attributes' && m.target.className) __seen.add(String(m.target.className)); })
        .observe(document.getElementById('fx'), {childList: true, subtree: true, attributes: true, attributeFilter: ['class']}); }""")
    return page, errors


async def _through(page):
    await page.wait_for_function("() => document.getElementById('cont').classList.contains('show')", timeout=15000)
    await page.evaluate(TAP, "#go-on")
    await page.wait_for_function("() => !document.getElementById('splash').classList.contains('show')", timeout=5000)


async def test_a_commit_performs_a_work_and_hangs_a_plate(webkit, site):
    page, errors = await _open(webkit, site("?work=wax"))
    await page.evaluate(TAP, ".item[data-key='kick.drive'] .box")
    await page.wait_for_function("() => [...__seen].some((c) => c.includes('sealed'))", timeout=5000)   # the wax seal
    await _through(page)
    await page.wait_for_selector("#toast.show")
    assert "Plate 1 hung in the gallery" in await page.text_content("#toast")
    plates = (await page.evaluate(API, "plates?track=hw002"))["items"]
    assert len(plates) == 1
    p = plates[0]
    assert p["work"]["id"] == "wax" and p["work"]["params"]["seal"] == "wax"
    assert p["step"] == "kick" and p["item"] == "drive" and "kick.drive" in p["done"]
    assert p["unlocked"] == ["kick.drive"]
    assert p["render"]["path"].startswith("skrng/") and "b8-1-kick-distortion" in p["render"]["path"]    # the batch 8.1 render
    assert not errors, errors


async def test_lamplight_lights_the_room_in_the_colour_of_the_decision(webkit, site):
    page, errors = await _open(webkit, site("?work=lamplight&item=kick.drive"))
    await page.wait_for_selector("#widget.show .cm-btn")
    await page.wait_for_timeout(400)
    hue = await page.evaluate("parseFloat(getComputedStyle(document.querySelector('#widget .wg')).getPropertyValue('--hue'))")
    await page.evaluate(TAP, "#widget .cm-btn")
    await page.wait_for_function("() => document.querySelector('#stage .wl-lamp[data-key=\"kick.drive\"]')", timeout=12000)
    lamps = await page.evaluate("JSON.parse(localStorage.getItem('checklist:hw002'))['map!lamps']")
    assert abs(lamps["kick.drive"] - hue) < 0.01
    await _through(page)
    assert not errors, errors


async def test_a_thumb_is_stored_at_once_then_asks_a_quick_question(webkit, site):
    page, errors = await _open(webkit, site("?item=kick.eq"))
    await page.wait_for_selector("#widget.show")
    assert await page.locator(".fb-thumb.up").count() == 1 and await page.locator(".fb-thumb.down").count() == 1
    up, down = await page.locator(".fb-thumb.up").bounding_box(), await page.locator(".fb-thumb.down").bounding_box()
    assert up["x"] == 0 and down["x"] + down["width"] == 393                     # on opposite edges, over the widget
    await page.evaluate(TAP, ".fb-thumb.down")
    await page.wait_for_function("() => document.querySelector('.fb-pop.show .fb-chip')", timeout=8000)
    items = (await page.evaluate(API, "feedback?limit=5"))["items"]
    assert len(items) == 1 and items[0]["vote"] == "down" and items[0]["view"] == "widget"
    assert items[0]["context"]["item"] == "kick.eq"
    assert items[0]["question"]["question"]                                      # the question was stored with it
    await page.evaluate(TAP, ".fb-pop .fb-chip")
    await page.wait_for_function("() => [...document.querySelectorAll('.fb-msg.agent')].some((m) => m.textContent.includes('Noted'))")
    items = (await page.evaluate(API, "feedback?limit=5"))["items"]
    assert items[0]["answers"] and items[0]["answers"][0]["choice"]
    assert not errors, errors


async def test_the_pick_follows_the_repertoire(webkit, site):
    page, errors = await _open(webkit, site())
    got = await page.evaluate("""async () => {
      const w = await import('./works.js');
      const rep = await w.repertoire();
      const noon = new Date(2026, 9, 14, 12), midnight = new Date(2026, 9, 14, 23, 30);
      const count = {}, recent = [];
      let repeats = 0;
      for (let i = 0; i < 400; i++) {
        const k = w.choose(rep, { recent, seed: 'kick.drive|' + i, now: noon });
        count[k.id] = (count[k.id] || 0) + 1;
        if (recent.at(-1) === k.id) repeats++;
        recent.push(k.id);
      }
      const night = w.choose(rep, { recent: [], seed: 'x', now: midnight });
      const bad = w.params({ shake: 99, seal: 'glitter', particles: { power: -3 } });
      return { count, repeats, nightOk: rep.works.some((x) => x.when?.night), bad, version: rep.version };
    }""")
    c = got["count"]
    assert got["version"] == 1
    assert "night" not in c                                                      # night works only at night
    assert c.get("wax", 0) < 400 * 0.12                                          # rare stays rare
    assert max(c, key=c.get) in ("ledger", "lamplight")                          # what's weighted most plays most
    assert len(c) >= 4                                                           # and the rest still come round
    assert got["repeats"] < 400 * 0.3
    assert got["bad"]["shake"] == 1.6 and got["bad"]["seal"] == "check" and got["bad"]["particles"]["power"] == 0.3
    assert not errors, errors
