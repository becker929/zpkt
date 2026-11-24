"""The gallery (/studio/checklist/map/gallery.html): a wing for the track, rooms by step in order, a plate per commit
with the map at that moment; a plate opens full bleed and plays its render as rendered (a context only after the tap,
no <audio>); the repertoire's works not seen yet hang as silhouettes with their titles hidden; the artist's thumbs
are there and a press is stored with the plate in view; and when the store doesn't answer, the page says so.

The artist API and the site-audio route are stubbed with page.route, so these tests need neither the harness's store
nor the network."""

from __future__ import annotations

import io
import json
import math
import struct
import wave
from pathlib import Path

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

MAP = Path(__file__).resolve().parents[2] / "src/harness/studio/static/checklist/map"
REPERTOIRE = {**json.loads((MAP / "works.json").read_text()), "at": 1760000000}

COUNT = """(() => {
  window.__contexts = 0;
  const AC = window.AudioContext;
  if (AC) window.AudioContext = class extends AC { constructor(...a) { super(...a); window.__contexts++; } };
})()"""

TAP = """(sel) => {
  const el = typeof sel === 'string' ? document.querySelector(sel) : sel; const r = el.getBoundingClientRect();
  const o = {pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o));
}"""

DONE_BEFORE = ["collage.game", "collage.splash", "collage.chord", "collage.synths", "collage.recordings",
               "collage.rumbleBounce", "collage.bed", "drums.rack", "drums.rumble", "drums.hats", "drums.perc",
               "drums.splashHits", "drums.across", "arrange.cut", "arrange.opening", "arrange.staircase",
               "arrange.splashes", "arrange.grid", "arrange.approved", "kick.scoop", "mix.baseline", "master.lab"]


def _plate(n, step, item, title, work, done, render=None, unlocked=None, sound="anvil"):
    w = next(x for x in REPERTOIRE["works"] if x["id"] == work)
    return {"id": f"pl_{n}", "n": n, "at": 1760440000 + n * 600, "track": "hw002", "step": step, "item": item,
            "title": title, "step_name": step.title(),
            "work": {"id": work, "version": 1, "title": w["title"], "params": w["params"]},
            "sound": sound, "done": done, "unlocked": unlocked if unlocked is not None else [f"{step}.{item}"],
            "render": render, "client_ts": (1760440000 + n * 600) * 1000}


PLATES = [
    _plate(1, "kick", "drive", "Distortion: COLDFIRE and the Decapitator, 37 to 50 %", "ledger",
           DONE_BEFORE + ["kick.drive"],
           {"label": "Batch 8.1, round: baseline, 37%, 43.5%, 50%",
            "path": "skrng/2026-10-07-hw002-b8-1-kick-distortion-t4.mp3"}),
    _plate(2, "kick", "decapStyle", "The Decapitator's style on the rumble", "lamplight",
           DONE_BEFORE + ["kick.drive", "kick.decapStyle"]),
    _plate(3, "mix", "chordLevel", "The chord loop's level", "ledger",
           DONE_BEFORE + ["kick.drive", "kick.decapStyle", "mix.chordLevel"],
           {"label": "Batch 8.2, chord up 8 dB", "path": "skrng/2026-10-09-hw002-b8-2-chord-level-t2.mp3"}, sound="vault"),
]


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / 44100))) for i in range(22050)))
    return buf.getvalue()


@pytest.fixture
async def gallery(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield str(server.make_url("/studio/checklist/map/gallery.html"))
    await server.close()


async def _open(browser, url, *, scheme="light", store=True):
    context = await browser.new_context(**IPHONE_15, color_scheme=scheme)
    await context.add_init_script(COUNT)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "503" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    posted: list[dict] = []
    audio = _wav()

    async def api(route):
        req = route.request
        url = req.url
        if not store:
            return await route.fulfill(status=503, body="down")
        if req.method == "GET" and "/plates" in url:
            return await route.fulfill(json={"items": PLATES})
        if req.method == "GET" and url.endswith("/repertoire"):
            return await route.fulfill(json=REPERTOIRE)
        if req.method == "POST" and url.endswith("/feedback"):
            posted.append(json.loads(req.post_data))
            return await route.fulfill(status=201, json={"id": f"fb_{len(posted)}", "at": 1760450000})
        if req.method == "POST" and url.endswith("/question"):
            return await route.fulfill(json={"question": "What was off?", "choices": ["The plate", "Something else"], "by": "rules"})
        if req.method == "POST" and url.endswith("/answer"):
            return await route.fulfill(json={"ok": True})
        return await route.fulfill(status=404, body="no")

    await page.route("**/studio/api/artist/**", api)
    await page.route("**/studio/site-audio/**", lambda r: r.fulfill(body=audio, content_type="audio/wav",
                                                                  headers={"Cache-Control": "no-store"}))
    await page.goto(url)
    return page, errors, posted


async def test_the_wing_hangs_its_plates_by_step_and_unseen_works_as_silhouettes(webkit, gallery):
    page, errors, _ = await _open(webkit, gallery)
    await page.wait_for_selector(".gl-plate")
    rooms = await page.eval_on_selector_all(".gl-wing > .gl-room:not(.gl-unseen)", "els => els.map(e => e.dataset.step)")
    assert rooms == ["collage", "drums", "arrange", "kick", "mix", "master", "release"]           # the steps, in order
    by_room = await page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('.gl-room[data-step]')]
      .map((r) => [r.dataset.step, [...r.querySelectorAll('.gl-plate')].map((p) => p.dataset.n)]))""")
    assert by_room["kick"] == ["1", "2"] and by_room["mix"] == ["3"] and by_room["collage"] == []
    assert await page.locator(".gl-room.empty").count() == 5
    # every plate draws the map at its moment (lazily, as it nears the screen)
    for n in (1, 2, 3):
        card = page.locator(f".gl-plate[data-n='{n}']")
        await card.scroll_into_view_if_needed()
        await page.wait_for_function(f"() => document.querySelector(\".gl-plate[data-n='{n}'] .gl-map svg\")")
    assert await page.locator(".gl-plate[data-n='1'] .gl-map .wl-poi[data-key='kick.drive']").count() == 1
    assert await page.text_content(".gl-plate[data-n='2'] .gl-work") == "Lamplight"
    assert await page.locator(".gl-plate[data-n='2'] .gl-norender").count() == 1                 # no render yet
    # the works not seen yet: heavy, night and wax hang as silhouettes, titles hidden
    assert await page.locator(".gl-silhouette").count() == 3
    unseen = await page.text_content(".gl-unseen")
    for title in ("The heavy hand", "Night watch", "Wax seal"):
        assert title not in unseen
    assert "2 works seen of 5" in await page.text_content("#counts")
    assert await page.evaluate("document.documentElement.scrollWidth") <= 393                  # no sideways scroll
    assert not errors, errors


async def test_a_plate_opens_and_plays_its_render_as_rendered(webkit, gallery):
    page, errors, _ = await _open(webkit, gallery, scheme="dark")
    await page.wait_for_selector(".gl-plate")
    assert await page.evaluate("window.__contexts") == 0
    await page.evaluate(TAP, ".gl-plate[data-n='1'] .gl-frame")
    await page.wait_for_selector("#open.show .gl-bigmap svg")
    await page.evaluate("Promise.all(document.getElementById('open').getAnimations().map((a) => a.finished))")
    box = await page.locator("#open").bounding_box()
    assert box["width"] == 393 and box["height"] >= 650                                       # full bleed
    assert await page.text_content("#open .gl-o-work h3") == "The ledger"
    assert "first made" in await page.text_content("#open .gl-o-about")                      # the work's about
    others = await page.locator("#open .gl-o-others .gl-player").count()
    assert others == 3                                                                         # the rest of batch 8.1
    assert "Kicks already driven like yours" in await page.text_content("#open .gl-o-found")
    assert await page.evaluate("window.__contexts") == 0                                       # nothing before a tap
    await page.evaluate(TAP, "#open .gl-player.big .gl-pbtn")
    await page.wait_for_function("() => document.querySelector('#open .gl-player.big').classList.contains('playing')")
    assert await page.evaluate("window.__contexts") == 1
    assert await page.locator("audio").count() == 0
    await page.evaluate(TAP, "#open .gl-player.big .gl-pbtn")                                  # a second tap stops it
    await page.wait_for_function("() => !document.querySelector('#open .gl-player.big').classList.contains('playing')")
    await page.evaluate(TAP, "#open .gl-close")
    await page.wait_for_function("() => !document.getElementById('open').classList.contains('show')")
    assert not errors, errors


async def test_a_thumbs_down_is_stored_with_the_plate_in_view(webkit, gallery):
    page, errors, posted = await _open(webkit, gallery)
    await page.wait_for_selector(".gl-plate")
    assert await page.locator(".fb-thumb.up").count() == 1 and await page.locator(".fb-thumb.down").count() == 1
    await page.evaluate(TAP, ".gl-plate[data-n='3'] .gl-frame")
    await page.wait_for_selector("#open.show")
    await page.evaluate(TAP, ".fb-thumb.down")
    await page.wait_for_function("() => document.querySelector('.fb-pop.show .fb-chip')")
    assert len(posted) == 1
    ev = posted[0]
    assert ev["vote"] == "down" and ev["view"] == "gallery"
    assert ev["context"]["plate"] == "pl_3" and ev["context"]["open"] is True
    assert not errors, errors


async def test_when_the_store_does_not_answer_the_page_says_so(webkit, gallery):
    page, errors, _ = await _open(webkit, gallery, store=False)
    await page.wait_for_selector(".gl-down")
    assert "The gallery's store isn't answering." in await page.text_content(".gl-down")
    assert await page.locator(".gl-retry").count() == 1
    assert not [e for e in errors if "page error" in e], errors
