"""The Wasteland, walked (/studio/checklist/wasteland/): a wanderer steered round a 1-bit world by a floating stick,
a tap, or the keyboard; solid things and the storm stop him; places name themselves as he comes near; where he
stood is kept; the artist's thumbs are on the edges."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

POINTER = """([type, x, y]) => document.getElementById('game').dispatchEvent(new PointerEvent(type,
  {pointerId: 9, pointerType: 'touch', isPrimary: true, bubbles: true, clientX: x, clientY: y}))"""
HERO = "() => { const h = __wasteland.hero; return { x: h.x, y: h.y, face: h.face, flip: h.flip }; }"
PUT = "([x, y]) => { const h = __wasteland.hero; h.x = x; h.y = y; h.vx = 0; h.vy = 0; }"


@pytest.fixture
async def site(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield lambda q="": str(server.make_url(f"/studio/checklist/wasteland/{q}"))
    await server.close()


async def _open(browser, url, fresh=True):
    context = await browser.new_context(**IPHONE_15, color_scheme="dark")
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    if fresh:
        await page.evaluate("localStorage.clear()")
        await page.goto(url)
    await page.wait_for_function("() => window.__wasteland && __wasteland.frames() > 3", timeout=20000)
    return page, errors


async def _stick(page, dx, dy, ms):
    await page.evaluate(POINTER, ["pointerdown", 200, 600])
    for i in range(1, 5):
        await page.evaluate(POINTER, ["pointermove", 200 + dx * i / 4, 600 + dy * i / 4])
    await page.wait_for_timeout(ms)
    await page.evaluate(POINTER, ["pointerup", 200 + dx, 600 + dy])


async def test_the_stick_walks_him_and_the_camp_names_itself(webkit, site):
    page, errors = await _open(webkit, site())
    start = await page.evaluate(HERO)
    assert await page.evaluate("__wasteland.near()") == "machine"          # he starts at the camp, by the machine
    assert await page.locator(".lm.on").count() == 1
    assert "HW002" in await page.text_content(".lm.on")
    await _stick(page, -44, 0, 700)
    left = await page.evaluate(HERO)
    assert left["x"] < start["x"] - 25 and abs(left["y"] - start["y"]) < 4
    assert left["face"] == "side" and left["flip"] is True
    await _stick(page, 0, 44, 600)
    down = await page.evaluate(HERO)
    assert down["y"] > left["y"] + 20 and down["face"] == "down"
    assert not errors, errors


async def test_solid_things_and_the_storm_stop_him(webkit, site):
    page, errors = await _open(webkit, site())
    m = await page.evaluate("(() => { const p = __wasteland.land.props.find((q) => q.type === 'machine'); return [p.x, p.y]; })()")
    await page.evaluate(PUT, [m[0], m[1] + 8])
    await page.keyboard.down("ArrowUp")
    await page.wait_for_timeout(900)
    await page.keyboard.up("ArrowUp")
    h = await page.evaluate(HERO)
    assert h["y"] > m[1] - 1                                               # the machine stopped him
    assert not await page.evaluate("([x, y]) => __wasteland.blocked(x, y)", [h["x"], h["y"]])
    await page.evaluate(PUT, [70, 704])
    await page.keyboard.down("ArrowLeft")
    await page.wait_for_timeout(1200)
    await page.keyboard.up("ArrowLeft")
    h = await page.evaluate(HERO)
    assert h["x"] > 30                                                     # the storm is a wall
    assert not errors, errors


async def test_a_tap_walks_him_there_and_where_he_stood_is_kept(webkit, site):
    page, errors = await _open(webkit, site())
    start = await page.evaluate(HERO)
    sc = await page.evaluate("__wasteland.scale()")
    v = await page.evaluate("({ x: __wasteland.view.x, y: __wasteland.view.y })")
    # tap 30 art px to the left of him, on open ground
    tx, ty = start["x"] - 30, start["y"] + 6
    cx, cy = (tx - v["x"]) * sc["S"] / sc["dpr"], (ty - v["y"]) * sc["S"] / sc["dpr"]
    await page.evaluate(POINTER, ["pointerdown", cx, cy])
    await page.evaluate(POINTER, ["pointerup", cx, cy])
    await page.wait_for_function(f"() => Math.hypot(__wasteland.hero.x - {tx}, __wasteland.hero.y - {ty}) < 3", timeout=4000)
    await page.wait_for_timeout(2200)                                      # it's kept every two seconds
    there = await page.evaluate(HERO)
    await page.reload()
    await page.wait_for_function("() => window.__wasteland && __wasteland.frames() > 3")
    back = await page.evaluate(HERO)
    assert abs(back["x"] - there["x"]) <= 1 and abs(back["y"] - there["y"]) <= 1
    assert not errors, errors


async def test_the_thumbs_know_where_he_is(webkit, site):
    page, errors = await _open(webkit, site())
    assert await page.locator(".fb-thumb.up").count() == 1 and await page.locator(".fb-thumb.down").count() == 1
    await page.evaluate("""() => { const el = document.querySelector('.fb-thumb.up'), r = el.getBoundingClientRect();
      const o = {pointerId: 3, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + 10, clientY: r.y + 10};
      el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o)); }""")
    await page.wait_for_function("() => document.querySelector('.fb-pop.show .fb-chip')", timeout=8000)
    items = (await page.evaluate("() => fetch('/studio/api/artist/feedback?limit=5').then((r) => r.json())"))["items"]
    assert len(items) == 1 and items[0]["vote"] == "up" and items[0]["view"] == "overworld"
    assert items[0]["context"]["near"] == "machine" and isinstance(items[0]["context"]["x"], int)
    assert not errors, errors
