"""The studio machine (/studio/checklist/rummage/machine.js) and the region's player (player.js), on the machine's
bench (machine-dev.html), in WebKit at an iPhone's size. The renders are made here, at test time: a WAV per
combination, each a tone of its own whose level rises steadily through the file, so what is heard tells which render
plays and where in it (fixtures only, never in git). Turning the selector switches the audible render at the same
playhead, loudness-matched by each render's gain_db; turning the knob and pulling the lever commits that option, a
tap on the lever only nudges it, holding it commits too; without renders the selector still works and nothing makes
a sound; and the region's state goes to the harness and comes back."""

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
from heard import MUTE, dominant_hz, heard
from lab_server import app

pytestmark = pytest.mark.ui

RATE, SECONDS = 44100, 6.0
COMBOS = [f"{b}-{d}-{s}" for b in (1, 2, 3) for d in (1, 2, 3) for s in (1, 2, 3)]
FREQ = {c: 300.0 + 37 * i for i, c in enumerate(COMBOS)}
GAIN_DB = {"2-1-1": -6.0206}                     # this render plays at half its level: the loudness match
NO_SOUNDS = "try { localStorage.setItem('map:sound-on', 'off'); } catch {}"     # the interface's knocks are not under test


def level(t: float) -> float:
    """Each fixture's amplitude `t` seconds in: rising, so a restart would be heard as a drop."""
    return 0.1 + 0.5 * t / SECONDS


def render(freq: float) -> bytes:
    t = np.arange(int(RATE * SECONDS)) / RATE
    x = (level(t) * np.sin(2 * math.pi * freq * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(x.tobytes())
    return buf.getvalue()


@pytest.fixture
async def bench(tmp_path):
    audio = tmp_path / "regions" / "rummage" / "audio"
    audio.mkdir(parents=True)
    combos = {}
    for combo in COMBOS:
        data = render(FREQ[combo])
        name = f"sh001-{combo}-{hashlib.sha1(data).hexdigest()[:8]}.wav"
        (audio / name).write_bytes(data)
        combos[combo] = {"file": name, "lufs": -14.0, "gain_db": GAIN_DB.get(combo, 0.0)}
    parts = {part: [{"id": i, "name": f"{part} {i}", "about": f"the {part}'s option {i}"} for i in (1, 2, 3)]
             for part in ("bed", "drums", "bass")}
    manifest = {"track": "sh001", "bpm": 120, "bars": 32, "seconds": SECONDS, "sample_rate": RATE, "parts": parts,
                "combos": combos}
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield {"url": str(server.make_url("/studio/checklist/rummage/machine-dev.html")), "manifest": manifest,
           "root": tmp_path}
    await server.close()


async def _open(browser, bench, query="?audio=fixture-audio.json&base=/studio/regions/rummage/audio/&art=0"):
    context = await browser.new_context(**IPHONE_15)
    await context.add_init_script(MUTE)
    await context.add_init_script(NO_SOUNDS)
    body = json.dumps(bench["manifest"])
    await context.route("**/fixture-audio.json", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(bench["url"] + query)
    await page.wait_for_function("() => window.__dev?.ready")
    return page, errors


def amplitude(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) * math.sqrt(2))


async def test_the_selector_switches_the_audible_render_at_the_same_playhead(webkit, bench):
    page, errors = await _open(webkit, bench)
    await page.tap("#open-bed")
    await page.wait_for_function("() => __dev.player.playing === '1-1-1' && __dev.player.position() > 1.4", timeout=10_000)
    await page.evaluate("() => { window.__switches = []; __dev.player.onChange((e) => { if (e.why === 'switch') __switches.push(e.at); }); }")
    before = await page.evaluate("() => ({ p: __dev.player.position(), t: __dev.player.context.currentTime })")
    await page.tap(".mc-tab[data-id='2']")
    await page.wait_for_function("() => __dev.player.playing === '2-1-1'")
    await page.wait_for_timeout(700)
    after = await page.evaluate("() => ({ p: __dev.player.position(), t: __dev.player.context.currentTime })")
    # The playhead went on as far as the clock did: the switch did not restart anything.
    assert after["p"] - before["p"] == pytest.approx(after["t"] - before["t"], abs=0.02), (before, after)
    assert after["p"] > before["p"] + 0.5
    assert await page.get_attribute(".mc-tab[data-id='2']", "aria-checked") == "true"
    assert await page.get_attribute(".mc-tab[data-id='2']", "data-lamp") == "on"            # what you hear, lit
    assert await page.text_content(".mc-name") == "bed 2"

    # What reached the speaker: render 1-1-1 up to the switch, then 2-1-1 from the same place in the file, at half
    # its level (its gain_db), with no restart (the level would drop to the file's start).
    at = (await page.evaluate("window.__switches"))[0]
    ear = max(await heard(page), key=lambda e: len(e.samples))
    p_at = before["p"] + (at - before["t"])                         # where the switch fell in the file
    pre, post = ear.between(at - 0.25, at - 0.05), ear.between(at + 0.12, at + 0.32)
    assert dominant_hz(pre, ear.rate) == pytest.approx(FREQ["1-1-1"], abs=4)
    assert dominant_hz(post, ear.rate) == pytest.approx(FREQ["2-1-1"], abs=4)
    assert amplitude(pre) == pytest.approx(level(p_at - 0.15), rel=0.1)
    assert amplitude(post) == pytest.approx(level(p_at + 0.22) * 10 ** (GAIN_DB["2-1-1"] / 20), rel=0.1)
    # and nothing else plays: one render audible at a time
    assert await page.locator("audio").count() == 0
    assert not errors, errors


async def test_turning_the_knob_and_pulling_the_lever_commits_that_option(webkit, bench):
    page, errors = await _open(webkit, bench, "?audio=fixture-audio.json&base=/studio/regions/rummage/audio/&art=0&committed=2-0-0")
    await page.tap("#open-drums")
    await page.wait_for_function("() => __dev.player.playing === '2-1-1'", timeout=10_000)   # the bed as committed
    await page.wait_for_selector(".mc[data-ready='true']")                                    # risen into place
    # turn the knob clockwise, by dragging round its centre, from I to III
    box = await page.locator(".mc-knob").bounding_box()
    cx, cy, r = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, box["width"] * 0.42

    def at(deg):
        return cx + r * math.sin(math.radians(deg)), cy - r * math.cos(math.radians(deg))

    await page.mouse.move(*at(-55))
    await page.mouse.down()
    for deg in range(-50, 65, 5):
        await page.mouse.move(*at(deg))
        await page.wait_for_timeout(12)
    await page.mouse.up()
    assert await page.evaluate("__dev.machine.selected") == 3
    await page.wait_for_function("() => __dev.player.playing === '2-3-1'")
    # a tap on the lever only nudges it
    await page.tap(".mc-handle")
    await page.wait_for_timeout(400)
    assert await page.evaluate("__dev.commits") == []
    # pulled down, it commits: the slam, the distilling, the stamp, the drop, then onCommit and the machine closes
    box = await page.locator(".mc-handle").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await page.mouse.move(x, y)
    await page.mouse.down()
    for i in range(1, 18):
        await page.mouse.move(x, y + i * 13)
        await page.wait_for_timeout(12)
    await page.mouse.up()
    await page.wait_for_function("() => __dev.commits.length === 1", timeout=8000)
    assert await page.evaluate("__dev.commits") == [{"part": "drums", "id": 3}]
    await page.wait_for_function("() => __dev.closed.length === 1", timeout=4000)
    assert await page.evaluate("__dev.closed") == [{"part": "drums", "committed": 3}]
    assert await page.locator(".mc").count() == 0
    assert await page.evaluate("__dev.player.playing") is None                                 # the preview stopped
    assert await page.text_content("#open-drums em") == "COMMITTED III"
    assert not errors, errors


async def test_without_renders_the_selector_works_and_holding_the_lever_commits(webkit, bench):
    page, errors = await _open(webkit, bench, "?audio=none&art=0")
    await page.tap("#open-bass")
    await page.wait_for_selector(".mc[data-audio='none'][data-ready='true']")
    assert "not here yet" in await page.text_content(".mc-note")
    assert await page.locator(".mc-ph").count() == 1                                          # cut paper, no art
    assert await page.is_disabled(".mc-play")
    await page.tap(".mc-tab[data-id='3']")
    assert await page.get_attribute(".mc-tab[data-id='3']", "aria-checked") == "true"
    assert await page.text_content(".mc-name") == "Stand-in bass three"
    await page.tap(".mc-knob")                                                                # a tap steps on: III to I
    assert await page.evaluate("__dev.machine.selected") == 1
    # the artist's thumbs are on the machine, and a press says which view and which option it was about
    await page.tap(".fb-thumb.up")
    await page.wait_for_function("async () => (await (await fetch('/studio/api/artist/feedback')).json()).items.length === 1")
    press = (await page.evaluate("async () => (await (await fetch('/studio/api/artist/feedback')).json()).items[0]"))
    assert press["view"] == "rummage-machine" and press["context"]["part"] == "bass" and press["context"]["option"] == 1
    await page.tap(".fb-pop .fb-skip")
    box = await page.locator(".mc-handle").bounding_box()
    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    await page.mouse.down()
    await page.wait_for_timeout(900)                                                          # held, it pulls itself
    await page.mouse.up()
    await page.wait_for_function("() => __dev.commits.length === 1", timeout=8000)
    assert await page.evaluate("__dev.commits") == [{"part": "bass", "id": 1}]
    assert await page.evaluate("window.__ears.length") == 0                                   # nothing made a sound
    assert not errors, errors


async def test_the_region_state_goes_to_the_harness_and_comes_back(webkit, bench):
    page, errors = await _open(webkit, bench, "?audio=none&art=0")
    got = await page.evaluate("""async () => {
      const url = '/studio/api/regions/rummage/state';
      const post = (body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const empty = await (await fetch(url)).json();
      const state = { ...empty, committed: { bed: 2, drums: 3, bass: null }, carrying: 'drums-3',
                      plinths: { bed: 'bed-2', drums: null, bass: null }, completions: [{ at: Date.now() / 1000, combo: '2-3-1' }] };
      const put = await post(state);
      const kept = await put.json();
      const back = await (await fetch(url)).json();
      const bad = await post({ ...state, plinths: { bed: 'drums-1' } });
      return { empty, status: put.status, kept, back, bad: bad.status, after: await (await fetch(url)).json() };
    }""")
    assert got["empty"]["committed"] == {"bed": None, "drums": None, "bass": None} and got["empty"]["carrying"] is None
    assert got["status"] == 200 and got["kept"] == got["back"] == got["after"]
    assert got["back"]["committed"] == {"bed": 2, "drums": 3, "bass": None} and got["back"]["carrying"] == "drums-3"
    assert got["back"]["plinths"]["bed"] == "bed-2" and got["back"]["completions"][0]["combo"] == "2-3-1"
    assert got["bad"] == 400
    assert json.loads((bench["root"] / "regions" / "rummage.json").read_text())["carrying"] == "drums-3"
    assert [e for e in errors if "status of 400" not in e] == [], errors          # the refusal is logged; nothing else
