"""The Rummage (/studio/checklist/rummage/), played through in WebKit at an iPhone's size: a wanderer steered by a
floating stick, a tap or the keys round a collage junk market; solid things and the ground's edge stop him; places
name themselves as he comes near. At a machine he operates it (machine.js) and commits, and the artifact lands on
his back; at the Gramophone he places it on its plinth; with all three on, the Gramophone plays the short (a fixture
render per combination, made here), a plate is hung in the museum, and everything survives a reload. The region's
state goes through the harness, or this browser when the harness hasn't the API. And it draws in a few
milliseconds a frame while walking."""

from __future__ import annotations

import hashlib
import io
import json
import math
import wave

import numpy as np
import pytest
from aiohttp.test_utils import TestServer
from conftest import IPHONE_15
from heard import MUTE
from lab_server import app

pytestmark = pytest.mark.ui

POINTER = """([type, x, y]) => document.getElementById('game').dispatchEvent(new PointerEvent(type,
  {pointerId: 9, pointerType: 'touch', isPrimary: true, bubbles: true, clientX: x, clientY: y}))"""
HERO = "() => { const h = __rummage.hero; return { x: h.x, y: h.y, face: h.face, flip: h.flip, carry: h.carry }; }"
STATE = "() => JSON.parse(JSON.stringify(__rummage.flow.state))"
TAP = """(sel) => { const el = document.querySelector(sel), r = el.getBoundingClientRect();
  const o = {pointerId: 4, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o)); }"""
NO_SOUNDS = "try { localStorage.setItem('map:sound-on', 'off'); } catch {}"     # the interface's knocks are not under test

RATE, SECONDS = 22050, 4.0
COMBOS = [f"{b}-{d}-{s}" for b in (1, 2, 3) for d in (1, 2, 3) for s in (1, 2, 3)]


def _wav(freq: float) -> bytes:
    t = np.arange(int(RATE * SECONDS)) / RATE
    x = (0.3 * np.sin(2 * math.pi * freq * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(x.tobytes())
    return buf.getvalue()


@pytest.fixture
async def site(tmp_path):
    """The stand-in harness, with a fixture render for every combination (fixtures only, never in git)."""
    audio = tmp_path / "regions" / "rummage" / "audio"
    audio.mkdir(parents=True)
    combos = {}
    for i, combo in enumerate(COMBOS):
        data = _wav(300.0 + 23 * i)
        name = f"sh001-{combo}-{hashlib.sha1(data).hexdigest()[:8]}.wav"
        (audio / name).write_bytes(data)
        combos[combo] = {"file": name, "lufs": -14.0, "gain_db": 0.0}
    parts = {part: [{"id": i, "name": f"{part.title()} {i}", "about": f"the {part}'s option {i}"} for i in (1, 2, 3)]
             for part in ("bed", "drums", "bass")}
    manifest = {"track": "sh001", "bpm": 120, "bars": 32, "seconds": SECONDS, "sample_rate": RATE, "parts": parts, "combos": combos}
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield {"url": lambda q="": str(server.make_url(f"/studio/checklist/rummage/{q}")), "manifest": manifest}
    await server.close()


def _real(errors: list[str]) -> list[str]:
    # a missing file is not a failure here: audio.json (when the test has no music) and the like
    return [e for e in errors if not e.startswith("Failed to load resource")]


async def _open(browser, site, q="", *, music=True, fresh=True, api=True, art=True):
    context = await browser.new_context(**IPHONE_15)
    await context.add_init_script(MUTE)
    await context.add_init_script(NO_SOUNDS)
    if music:
        body = json.dumps(site["manifest"])
        await context.route("**/rummage/audio.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    if not api:
        await context.route("**/api/regions/rummage/state", lambda r: r.fulfill(status=404, body="no region API"))
    if not art:
        await context.route("**/rummage/art/**", lambda r: r.fulfill(status=404, body="no art"))
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(site["url"](q))
    if fresh:
        await page.evaluate("localStorage.clear()")
        await page.evaluate(NO_SOUNDS)
        await page.goto(site["url"](q))
    await _ready(page)
    return page, errors


async def _ready(page):
    await page.wait_for_function("() => window.__rummage && __rummage.frames() > 3", timeout=20000)
    await page.evaluate("__rummage.modules")


async def _stick(page, dx, dy, ms):
    await page.evaluate(POINTER, ["pointerdown", 200, 400])
    for i in range(1, 5):
        await page.evaluate(POINTER, ["pointermove", 200 + dx * i / 4, 400 + dy * i / 4])
    await page.wait_for_timeout(ms)
    await page.evaluate(POINTER, ["pointerup", 200 + dx, 400 + dy])


async def _go(page, where):
    """Stands the wanderer just in front of a place ('gram', 'bed', 'drums', 'bass', 'portal') and waits for its action."""
    await page.evaluate("""(id) => { const R = __rummage.R, t = id === 'gram' ? R.gram : id === 'portal' ? R.portal : R.machines[id];
      __rummage.teleport(t.x, t.y + 56); }""", where)
    await page.wait_for_function("(id) => __rummage.near() === id && document.getElementById('act').classList.contains('on')", arg=where)


async def test_he_arrives_by_the_tear_walks_and_places_name_themselves(webkit, site):
    page, errors = await _open(webkit, site)
    start = await page.evaluate(HERO)
    tear = await page.evaluate("[__rummage.R.portal.x, __rummage.R.portal.y]")
    assert abs(start["x"] - tear[0]) < 30 and start["y"] < tear[1]                 # just north of the tear
    await page.wait_for_function("() => [...document.querySelectorAll('.lm.on b')].some((b) => b.textContent === 'The tear')")
    await _stick(page, 0, -44, 900)
    up = await page.evaluate(HERO)
    assert up["y"] < start["y"] - 60 and abs(up["x"] - start["x"]) < 10 and up["face"] == "back"
    await _stick(page, -44, 0, 600)
    left = await page.evaluate(HERO)
    assert left["x"] < up["x"] - 40 and left["face"] == "side" and left["flip"] is True
    # a tap on a machine walks him up to it, and its action comes up
    await page.evaluate("([x, y]) => __rummage.teleport(x, y)", await page.evaluate("[__rummage.R.machines.drums.x - 60, __rummage.R.machines.drums.y + 260]"))
    await page.wait_for_timeout(300)
    box = await page.evaluate("""() => { const m = __rummage.R.machines.drums, [x, y] = __rummage.scene.toScreen(m.x, m.y - 120); return [x, y]; }""")
    await page.evaluate(POINTER, ["pointerdown", *box])
    await page.evaluate(POINTER, ["pointerup", *box])
    await page.wait_for_function("() => __rummage.near() === 'drums'", timeout=6000)
    await page.wait_for_function("() => document.getElementById('act').textContent.includes('The Clatter')")
    assert "Operate" in await page.text_content("#act")
    # the tear leads back to The Wasteland (Enter acts, as a tap on the button does)
    await _go(page, "portal")
    assert "The Wasteland" in await page.text_content("#act")
    async with page.expect_navigation():
        await page.keyboard.press("Enter")
    assert page.url.endswith("/studio/checklist/wasteland/")
    assert not _real(errors), errors


async def test_solid_things_and_the_edge_stop_him(webkit, site):
    page, errors = await _open(webkit, site)
    m = await page.evaluate("(() => { const m = __rummage.R.machines.bed; return [m.x, m.y]; })()")
    await page.evaluate("([x, y]) => __rummage.teleport(x, y)", [m[0], m[1] + 60])
    await page.keyboard.down("ArrowUp")
    await page.wait_for_timeout(1000)
    await page.keyboard.up("ArrowUp")
    h = await page.evaluate(HERO)
    assert h["y"] > m[1] - 20                                                       # the machine stopped him at its face
    assert not await page.evaluate("([x, y]) => __rummage.R.blocked(x, y)", [h["x"], h["y"]])
    # a prop is solid too: he slides round it, never into it
    p = await page.evaluate("(() => { const t = __rummage.R.things.find((q) => q.kind === 'prop' && q.x > 300 && q.x < 1300 && q.y > 300 && q.y < 2000); return [t.x, t.y]; })()")
    await page.evaluate("([x, y]) => __rummage.teleport(x, y + 70)", p)
    await page.keyboard.down("ArrowUp")
    await page.wait_for_timeout(500)
    await page.keyboard.up("ArrowUp")
    h = await page.evaluate(HERO)
    assert not await page.evaluate("([x, y]) => __rummage.R.blocked(x, y)", [h["x"], h["y"]])
    # the ground's edge is a wall
    await page.evaluate("() => __rummage.teleport(160, 1200)")
    await page.keyboard.down("ArrowLeft")
    await page.wait_for_timeout(1200)
    await page.keyboard.up("ArrowLeft")
    h = await page.evaluate(HERO)
    assert h["x"] >= await page.evaluate("__rummage.R.LIM.x0") - 0.01
    assert not _real(errors), errors


async def test_the_short_is_made_by_playing_and_survives_a_reload(webkit, site):
    """Operate, commit, carry and place, three times, with the real machine; then the Gramophone plays the short."""
    page, errors = await _open(webkit, site)
    picks = {"bed": 2, "drums": 1, "bass": 3}
    for part, pick in picks.items():
        await _go(page, part)
        assert "Operate" in await page.text_content("#act")
        await page.tap("#act")
        await page.wait_for_function("() => __rummage.machineOpen() && document.querySelector('.mc')")
        assert await page.evaluate("__rummage.player !== null")                    # the renders are here: real sound
        await page.evaluate("(id) => __rummage.commit(id)", pick)                  # the selector, then the lever
        await page.wait_for_function("(k) => __rummage.hero.carry === k && !__rummage.machineOpen()", arg=f"{part}-{pick}", timeout=10_000)
        state = await page.evaluate(STATE)
        assert state["committed"][part] == pick and state["carrying"] == f"{part}-{pick}"
        assert await page.locator("#carry.on").count() == 1
        await _go(page, "gram")
        assert "Place" in await page.text_content("#act")
        await page.tap("#act")
        await page.wait_for_function("(p) => __rummage.flow.state.plinths[p] && !__rummage.flow.state.carrying", arg=part)
        await page.wait_for_function("(p) => document.querySelector(`#pips li[data-part=${p}]`).classList.contains('full')", arg=part)
        assert await page.locator("#carry.on").count() == 0
    # all three are on: the Gramophone plays the short as made
    await page.wait_for_function("() => document.getElementById('act').textContent.includes('Play the short')")
    await page.tap("#act")
    await page.wait_for_selector("#gram.show .gm-play")
    assert await page.evaluate("__rummage.gramOpen()")
    await page.tap(".gm-play")
    await page.wait_for_function("() => __rummage.player.playing === '2-1-3'", timeout=10_000)
    await page.wait_for_selector(".gm-reveal.show img")                          # the sleeve, the reward
    assert "sleeves/2-1-3" in await page.get_attribute(".gm-reveal img", "src")
    assert "sleeves/2-1-3" in await page.get_attribute(".gm-sleeve.show img", "src")
    await page.evaluate(TAP, ".gm-reveal")                                       # a tap puts it away, into the sheet
    await page.wait_for_function("() => !document.querySelector('.gm-reveal')")
    assert await page.locator("#confetti i").count() > 20
    state = await page.evaluate(STATE)
    assert [c["combo"] for c in state["completions"]] == ["2-1-3"]
    await page.wait_for_function("() => __rummage.flow.state.completions[0].plate")
    plates = (await page.evaluate("() => fetch('/studio/api/artist/plates?track=sh001').then((r) => r.json())"))["items"]
    assert len(plates) == 1
    plate = plates[0]
    assert plate["step"] == "release" and plate["item"] == "short" and plate["work"]["id"] == "gramophone"
    assert plate["render"]["path"] == site["manifest"]["combos"]["2-1-3"]["file"]
    assert plate["sleeve"] == "sleeves/2-1-3.webp" and plate["done"] == ["bed-2", "drums-1", "bass-3"]
    # playing it again is not a second plate
    await page.tap(".gm-play")
    await page.wait_for_function("() => !__rummage.player.playing")
    await page.tap(".gm-play")
    await page.wait_for_function("() => __rummage.player.playing === '2-1-3'")
    assert len((await page.evaluate(STATE))["completions"]) == 1
    await page.tap(".gm-x")
    await page.wait_for_function("() => !__rummage.gramOpen() && !__rummage.player.playing")

    # the harness kept it all: the region is the same after a reload, and he stands where he stood
    kept = await page.evaluate("() => fetch('/studio/api/regions/rummage/state').then((r) => r.json())")
    assert kept["plinths"] == {"bed": "bed-2", "drums": "drums-1", "bass": "bass-3"} and kept["carrying"] is None
    assert kept["completions"][0]["combo"] == "2-1-3" and kept["completions"][0]["plate"]
    await page.wait_for_timeout(2200)                                              # where he stood is kept every 2 s
    there = await page.evaluate(HERO)
    await page.reload()
    await _ready(page)
    back = await page.evaluate(STATE)
    assert back["plinths"] == kept["plinths"] and back["committed"] == picks
    h = await page.evaluate(HERO)
    assert abs(h["x"] - there["x"]) <= 1 and abs(h["y"] - there["y"]) <= 1
    assert await page.locator("#pips li.full").count() == 3
    assert "finished" in (await page.text_content("#goal")).lower()
    assert not _real(errors), errors


async def test_one_at_a_time_and_the_stand_in_machine(webkit, site):
    """With ?stub the page's own stand-in machine is used; committing at a second machine swaps what he carries."""
    page, errors = await _open(webkit, site, "?stub")
    await _go(page, "drums")
    await page.tap("#act")
    await page.wait_for_selector(".sm.show .sm-opt")
    await page.evaluate(TAP, ".sm-opt[data-id='3']")
    assert await page.get_attribute(".sm-opt[data-id='3']", "aria-checked") == "true"
    await page.evaluate(TAP, ".sm-commit")
    await page.wait_for_function("() => __rummage.hero.carry === 'drums-3'")
    await _go(page, "bass")
    assert "swaps" in await page.text_content("#act")                             # it says so before you commit
    await page.tap("#act")
    await page.wait_for_selector(".sm.show .sm-opt")
    await page.evaluate(TAP, ".sm-commit")
    await page.wait_for_function("() => __rummage.hero.carry === 'bass-1'")
    assert "one at a time" in await page.text_content("#toast")
    state = await page.evaluate(STATE)
    assert state["carrying"] == "bass-1" and state["committed"] == {"bed": None, "drums": 3, "bass": 1}
    assert not _real(errors), errors


async def test_without_the_api_the_art_or_the_music_it_still_plays(webkit, site):
    """Software and art land in either order: with no art pack the things are cut-paper placeholders of the same
    sizes, with no renders there is no player, and with no region API this browser keeps the state."""
    page, errors = await _open(webkit, site, "?stub", music=False, api=False, art=False)
    assert await page.evaluate("__rummage.flow.mode") == "local"
    assert await page.evaluate("__rummage.player") is None                        # no renders: no player
    assert await page.evaluate("Object.keys(__rummage.art.manifest).length") == 0
    assert await page.evaluate("__rummage.R.things.length") > 60
    await _go(page, "bed")
    await page.tap("#act")
    await page.wait_for_selector(".sm.show .sm-opt")
    await page.evaluate(TAP, ".sm-commit")
    await page.wait_for_function("() => __rummage.hero.carry === 'bed-1'")
    await page.reload()
    await _ready(page)
    assert (await page.evaluate(STATE))["carrying"] == "bed-1"
    assert (await page.evaluate(HERO))["carry"] == "bed-1"
    assert not _real(errors), errors


async def test_the_thumbs_know_where_he_is(webkit, site):
    page, errors = await _open(webkit, site)
    assert await page.locator(".fb-thumb.up").count() == 1 and await page.locator(".fb-thumb.down").count() == 1
    await _go(page, "bed")
    await page.evaluate(TAP, ".fb-thumb.up")
    await page.wait_for_function("() => document.querySelector('.fb-pop.show .fb-chip')", timeout=8000)
    items = (await page.evaluate("() => fetch('/studio/api/artist/feedback?limit=5').then((r) => r.json())"))["items"]
    assert len(items) == 1 and items[0]["view"] == "rummage" and items[0]["context"]["near"] == "bed"
    assert not _real(errors), errors


async def test_it_draws_in_a_few_milliseconds_a_frame_while_walking(webkit, site):
    page, errors = await _open(webkit, site)
    await page.evaluate("() => { __rummage.perf.intervals.length = 0; __rummage.perf.work.length = 0; }")
    await page.evaluate(POINTER, ["pointerdown", 200, 400])
    await page.evaluate(POINTER, ["pointermove", 200, 360])
    await page.evaluate(POINTER, ["pointermove", 200, 354])
    await page.wait_for_timeout(1600)
    await page.evaluate(POINTER, ["pointermove", 240, 380])
    await page.wait_for_timeout(1600)
    await page.evaluate(POINTER, ["pointerup", 240, 380])
    perf = await page.evaluate("""() => { const p = __rummage.perf, m = (a) => a.reduce((x, y) => x + y, 0) / a.length;
      const w = p.work.slice().sort((a, b) => a - b);
      return { n: p.intervals.length, interval: m(p.intervals.slice(1)), work: m(p.work), p95: w[Math.floor(w.length * 0.95)] }; }""")
    print("frames while walking:", perf)
    assert perf["n"] > 100
    assert perf["interval"] < 18, perf                                              # about 60 fps, headless
    assert perf["work"] < 8 and perf["p95"] < 16, perf                              # the page's own work a frame
    assert not _real(errors), errors
