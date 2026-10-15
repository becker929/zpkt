"""The museum holds the finished shorts (/studio/checklist/map/gallery.html): every track has a wing, the one with the
newest plate first. SH001's wing is made for shorts: the title art for a banner, then the record sleeves of the shorts
as made side by side, newest first, each with its three choices' names, its date and its render to play (decoded and
played as rendered, one at a time). #sh001 goes to the wing and lights the newest plate; ?from= points the back link
at where you came in. HW002's wing is as it was. The plates go through the harness's own artist API (stored, then
listed for every track with one GET) and the renders through the region's audio route, from WAV fixtures made here
(never in git)."""

from __future__ import annotations

import io
import math
import wave

import numpy as np
import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from conftest import IPHONE_15
from heard import MUTE, dominant_hz, heard
from lab_server import app

pytestmark = pytest.mark.ui

RATE = 44100
TONES = {"2-1-3": 440.0, "1-1-1": 660.0}
NAMES = {"bed": ["Music box & hiss", "Parlour upright", "Branches & tin bowl"],
         "drums": ["Tin-can break", "Clockwork four", "Cutlery shuffle"],
         "bass": ["Round sub", "Bellows drone", "Pipe hum"]}
TAP = """(sel) => { const el = document.querySelector(sel), r = el.getBoundingClientRect();
  const o = {pointerId: 4, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o)); }"""
PLAYING = "() => [...document.querySelectorAll('.gl-player.playing')].map((p) => p.closest('[data-combo]')?.dataset.combo ?? p.dataset.path)"


def _wav(freq: float, seconds: float = 3.0) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    x = (0.3 * np.sin(2 * math.pi * freq * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(x.tobytes())
    return buf.getvalue()


def _short(combo: str) -> dict:
    ids = [int(x) for x in combo.split("-")]
    file = f"sh001-{combo}-0000{ids[0]}{ids[1]}{ids[2]}0.wav"
    names = {part: NAMES[part][ids[i] - 1] for i, part in enumerate(("bed", "drums", "bass"))}
    return {"track": "sh001", "step": "release", "item": "short", "title": "SH001",
            "work": {"id": "gramophone", "version": 1, "title": "The Gramophone", "params": {}},
            "done": [f"bed-{ids[0]}", f"drums-{ids[1]}", f"bass-{ids[2]}"], "unlocked": [],
            "render": {"path": file, "label": "SH001 · " + " · ".join(names.values()), "url": f"/studio/regions/rummage/audio/{file}"},
            "combo": combo, "choices": {p: {"id": ids[i], "name": names[p]} for i, p in enumerate(names)},
            "sleeve": f"sleeves/{combo}.webp", "client_ts": 1760500000000}


HW002 = {"track": "hw002", "step": "kick", "item": "drive", "title": "Distortion: COLDFIRE and the Decapitator",
         "step_name": "Kick", "work": {"id": "ledger", "version": 1, "title": "The ledger", "params": {}},
         "sound": "anvil", "done": ["kick.drive"], "unlocked": ["kick.drive"], "render": None, "client_ts": 1760400000000}


@pytest.fixture
async def museum(tmp_path):
    audio = tmp_path / "regions" / "rummage" / "audio"
    audio.mkdir(parents=True)
    for combo, freq in TONES.items():
        (audio / _short(combo)["render"]["path"]).write_bytes(_wav(freq))
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield server
    await server.close()


async def _hang(server, *plates):
    async with ClientSession() as http:
        for p in plates:
            async with http.post(str(server.make_url("/studio/api/artist/plates")), json=p) as r:
                assert r.status == 201


async def _open(browser, server, query=""):
    context = await browser.new_context(**IPHONE_15)
    await context.add_init_script(MUTE)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(str(server.make_url("/studio/checklist/map/gallery.html")) + query)
    await page.wait_for_selector(".gl-wing")
    return page, errors


async def test_a_finished_short_hangs_as_its_sleeve_with_its_names_and_plays(webkit, museum):
    await _hang(museum, HW002, _short("1-1-1"), _short("2-1-3"))                  # 2-1-3 is the newest
    page, errors = await _open(webkit, museum, "?from=rummage#sh001")
    await page.wait_for_selector(".gl-short")
    # the wings: the one with the newest plate first; HW002's as it was
    assert await page.eval_on_selector_all(".gl-wing", "els => els.map((e) => e.dataset.track)") == ["sh001", "hw002"]
    assert await page.locator(".gl-wing[data-track='hw002'] > .gl-room:not(.gl-unseen)").count() == 7
    assert await page.locator(".gl-wing[data-track='hw002'] .gl-plate[data-n='1']").count() == 1
    assert "3 plates" in await page.text_content("#counts")
    # SH001's wing: the title art for a banner, the sleeves side by side, newest first
    wing = page.locator(".gl-wing[data-track='sh001']")
    assert "SH001 · The Rummage" in await wing.locator("h2").text_content()
    assert await page.evaluate("() => document.querySelector('.gl-banner img').naturalWidth") == 900
    assert await page.eval_on_selector_all(".gl-short", "els => els.map((e) => e.dataset.combo)") == ["2-1-3", "1-1-1"]
    tops = await page.eval_on_selector_all(".gl-short", "els => els.map((e) => Math.round(e.getBoundingClientRect().top))")
    assert tops[0] == tops[1]                                                     # side by side
    newest = ".gl-short[data-combo='2-1-3']"
    assert (await page.get_attribute(f"{newest} .gl-sleeve img", "src")).endswith("../rummage/art/sleeves/2-1-3.webp")
    await page.wait_for_function(f"() => document.querySelector(\"{newest} .gl-sleeve img\").naturalWidth > 0")
    assert await page.eval_on_selector_all(f"{newest} .gl-choices span", "els => els.map((e) => e.textContent)") == [
        "Parlour upright", "Tin-can break", "Pipe hum"]
    assert await page.locator(f"{newest} .gl-when").count() == 1
    assert await page.locator(f"{newest}.lit").count() == 1                      # #sh001: the new plate is lit
    box = await page.locator(newest).bounding_box()
    assert 0 <= box["y"] < 659 and box["x"] >= 0                                  # and in view
    # the back link goes back where you came from
    assert await page.get_attribute(".gl-back", "href") == "../rummage/"
    assert await page.get_attribute(".gl-back", "aria-label") == "Back to The Rummage"
    assert await page.evaluate("document.documentElement.scrollWidth") <= 393     # the shelf scrolls, the page doesn't

    # play: the render as rendered, one at a time
    await page.evaluate(TAP, f"{newest} .gl-pbtn")
    await page.wait_for_function(f"() => document.querySelector(\"{newest}\").classList.contains('playing')", timeout=10_000)
    await page.wait_for_timeout(600)
    ear = max(await heard(page), key=lambda e: len(e.samples))
    last = ear.samples[-int(ear.rate * 0.3):]
    assert np.sqrt(np.mean(last ** 2)) > 0.1                                      # the fixture's level: as rendered
    assert dominant_hz(last, ear.rate) == pytest.approx(TONES["2-1-3"], abs=4)
    await page.evaluate(TAP, ".gl-short[data-combo='1-1-1'] .gl-sleeve")          # the other sleeve: it takes over
    await page.wait_for_function("() => document.querySelector(\".gl-short[data-combo='1-1-1']\").classList.contains('playing')")
    assert await page.evaluate(PLAYING) == ["1-1-1"]
    await page.wait_for_timeout(500)
    ear = max(await heard(page), key=lambda e: len(e.samples))
    assert dominant_hz(ear.samples[-int(ear.rate * 0.25):], ear.rate) == pytest.approx(TONES["1-1-1"], abs=4)
    await page.evaluate(TAP, ".gl-short[data-combo='1-1-1'] .gl-pbtn")            # and stops
    await page.wait_for_function("() => !document.querySelector('.gl-player.playing')")
    assert await page.locator("audio").count() == 0
    assert not errors, errors


async def test_before_any_short_the_wing_waits_after_hw002(webkit, museum):
    await _hang(museum, HW002)
    page, errors = await _open(webkit, museum, "?from=wasteland")
    await page.wait_for_selector(".gl-plate")
    assert await page.eval_on_selector_all(".gl-wing", "els => els.map((e) => e.dataset.track)") == ["hw002", "sh001"]
    assert "No shorts hung yet" in await page.text_content(".gl-wing[data-track='sh001']")
    assert await page.get_attribute(".gl-wing[data-track='sh001'] .gl-go", "href") == "../rummage/"
    assert await page.get_attribute(".gl-back", "href") == "../wasteland/?from=museum"
    assert await page.text_content(".gl-foot a") == "Back out to The Wasteland"
    assert not errors, errors
