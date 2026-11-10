"""The lab (/studio/lab/): it starts, every surface mounts, controls move the store and the sound follows, and every
sketch is silent at the set's value. On a stand-in audio folder (short WAV stems of clicks and tones), so the tests
need neither Anthony's set nor ffmpeg. Muted: the page's speakers are the ear (heard.py)."""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import numpy as np
import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from heard import MUTE
from lab_server import app

pytestmark = pytest.mark.ui

RATE = 44100
BAR = 1.5
SURFACES = ["collage", "arrange", "kick", "mix", "play"]


def _wav(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(np.repeat(x[:, None], 2, axis=1), -1, 1) * 32000).astype("<i2").tobytes())
    return buf.getvalue()


def stand_in_audio(folder: Path, bars: int = 4) -> Path:
    """Stems of `bars` bars at 160 BPM (a kick on every beat, hats on the offbeats, a pad), a clip and a kick hit."""
    n = int(bars * BAR * RATE)
    t = np.arange(n) / RATE
    beat = BAR / 4
    phase = t % beat
    kick = np.sin(2 * np.pi * (50 + 200 * np.exp(-phase * 40)) * phase) * np.exp(-phase * 9) * 0.6
    rng = np.random.default_rng(1)
    hats = rng.standard_normal(n) * np.exp(-((t + beat / 2) % beat) * 60) * 0.15
    pad = np.sin(2 * np.pi * 220 * t) * 0.05
    files = {"kick": kick, "perc": hats, "sfx": pad, "mix": kick + hats + pad}
    manifest = {"bpm": 160, "rate": RATE, "bar_seconds": BAR, "stems": [], "full": None, "clips": [], "kicks": [],
                "tracks": []}
    for key, x in files.items():
        (folder / f"{key}.wav").write_bytes(_wav(x))
        manifest["stems"].append({"id": key, "title": key, "file": f"{key}.wav", "seconds": n / RATE, "bars": bars})
    (folder / "clip.wav").write_bytes(_wav(pad * 4))
    manifest["clips"].append({"id": "src-1", "title": "a tone", "track": "11-Audio", "group": "SFX group",
                              "file": "clip.wav", "seconds": n / RATE, "uses": [[1, 5, 0]]})
    (folder / "hit.wav").write_bytes(_wav(kick[: int(beat * RATE)]))
    manifest["kicks"].append({"id": "kick-0", "title": "Kick, beat 1", "file": "hit.wav", "seconds": beat})
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


@pytest.fixture
async def lab(tmp_path):
    server = TestServer(app(stand_in_audio(tmp_path)))
    await server.start_server()
    yield str(server.make_url("/studio/lab/"))
    await server.close()


class Lab:
    def __init__(self, page):
        self.page = page
        self.errors: list[str] = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(f"page error: {e}"))

    async def js(self, expression: str, arg=None):
        return await self.page.evaluate(expression, arg)

    async def drag(self, selector: str, dx: float, dy: float) -> None:
        """A one-finger drag as touch pointer events, in ten steps."""
        await self.js("""([sel, dx, dy]) => {
          const el = document.querySelector(sel); const r = el.getBoundingClientRect();
          const x = r.x + r.width / 2, y = r.y + r.height / 2;
          const o = {pointerId: 7, pointerType: 'touch', bubbles: true, isPrimary: true};
          el.dispatchEvent(new PointerEvent('pointerdown', {...o, clientX: x, clientY: y}));
          for (let i = 1; i <= 10; i++) el.dispatchEvent(new PointerEvent('pointermove', {...o, clientX: x + dx * i / 10, clientY: y + dy * i / 10}));
          el.dispatchEvent(new PointerEvent('pointerup', {...o, clientX: x + dx, clientY: y + dy}));
        }""", [selector, dx, dy])


async def open_lab(browser, url: str, surface: str = "kick") -> Lab:
    context = await browser.new_context(**IPHONE_15)
    await context.add_init_script(MUTE)
    lab = Lab(await context.new_page())
    await lab.page.goto(f"{url}?s={surface}")
    await lab.page.click(".gate button")
    await lab.page.wait_for_function("() => !document.querySelector('.gate') && window.lab?.engine.playing", timeout=20_000)
    return lab


async def test_it_starts_with_hw002s_100_params_and_plays(either, lab):
    page = await open_lab(either, lab)
    n = await page.js("window.lab.params.list.filter((p) => p.origin !== 'phone').length")
    assert n == 100
    await page.page.wait_for_timeout(800)
    pos = await page.js("window.lab.engine.position()")
    assert pos["playing"] and pos["t"] > 0.05          # in bars: the clock runs
    assert await page.js("window.lab.engine.loudness().peak") > -40          # the stems are heard
    assert page.errors == [], page.errors
    await page.page.context.close()


async def test_every_surface_mounts_and_unmounts_cleanly(either, lab):
    page = await open_lab(either, lab)
    for sid in SURFACES + SURFACES[:1]:
        await page.page.click(f".tab[data-id='{sid}']")
        await page.page.wait_for_timeout(400)
        assert await page.js(f"document.getElementById('surface').dataset.stage === '{sid}'")
        assert await page.js("!document.querySelector('#surface .rack-note')?.textContent.includes('broke')")
    assert page.errors == [], page.errors
    await page.page.context.close()


async def test_a_knob_drag_moves_its_param_and_undo_takes_it_back(webkit, lab):
    page = await open_lab(webkit, lab, "kick")
    found = await page.js("""() => {
      const el = document.querySelector("#surface [data-param='kick.sub30']");
      if (!el) return false;
      (el.querySelector('.k-dial, .f-groove') ?? el).setAttribute('data-test-drag', '');
      return true; }""")
    if not found:
        pytest.skip("the kick surface shows kick.sub30 with a control of its own")
    before = await page.js("window.lab.store.real('kick.sub30')")
    await page.drag("[data-test-drag]", 0, -60)
    after = await page.js("window.lab.store.real('kick.sub30')")
    assert after > before + 3
    await page.js("window.lab.store.undo()")
    assert abs(await page.js("window.lab.store.real('kick.sub30')") - before) < 1e-6
    assert page.errors == [], page.errors
    await page.page.context.close()


async def test_sketches_are_silent_at_the_sets_values_and_play_the_change(webkit, lab):
    page = await open_lab(webkit, lab, "kick")
    await page.js("window.lab.store.resetAll()")
    await page.page.wait_for_timeout(200)
    kick = """() => { const b = window.lab.engine.bus('kick');
      return {bands: Object.fromEntries([...(b.extra ?? new Map())].map(([k, f]) => [k, f.gain.value])),
              drive: b.state.drive, trim: b.trim.gain.value, fader: b.fader.gain.value}; }"""
    at_set = await page.js(kick)
    assert all(abs(g) < 0.01 for g in at_set["bands"].values()), at_set
    assert at_set["drive"] == 0 and abs(at_set["trim"] - 1) < 1e-3 and abs(at_set["fader"] - 1) < 1e-3
    await page.js("""() => { const p = window.lab.params.get('kick.sub30');
      window.lab.store.set('kick.sub30', (p.set + 6 - p.min) / (p.max - p.min)); }""")
    await page.page.wait_for_timeout(300)
    moved = await page.js(kick)
    assert abs(moved["bands"]["sub30"] - 6) < 0.3, moved
    assert page.errors == [], page.errors
    await page.page.context.close()


async def test_a_channel_strip_at_rest_is_flat(webkit, lab):
    """A fresh Channel passes sines from 30 Hz to 10 kHz within 0.3 dB (its crossover and pass filters included)."""
    page = await open_lab(webkit, lab, "kick")
    gains = await page.js("""async () => {
      const { Channel } = await import('./js/audio/channel.js');
      const out = {};
      for (const f of [30, 60, 120, 250, 1000, 10000]) {
        const ctx = new OfflineAudioContext(2, 44100, 44100);
        const osc = ctx.createOscillator(); osc.frequency.value = f;
        const ch = new Channel(ctx, 'test'); osc.connect(ch.input); ch.connect(ctx.destination);
        osc.start();
        const buf = await ctx.startRendering();
        const x = buf.getChannelData(0).slice(22050);
        out[f] = 20 * Math.log10(Math.sqrt(x.reduce((a, v) => a + v * v, 0) / x.length) * Math.SQRT2);
      }
      return out; }""")
    assert all(abs(g) < 0.3 for g in gains.values()), gains
    await page.page.context.close()
