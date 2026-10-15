"""The check's sounds (/studio/checklist/map/sounds.js), on their bench (dev-sounds.html): six sounds rendered in
Ableton Live (hands/scripts/ui_sounds/), each as a hit, a heavier one for a finished step and a soft knock. A tap
picks one and keeps it, and its other two can be heard from its row. Every file is served, decodes in WebKit, starts
at once (no encoder delay), stays under full scale, and is heavier or softer as it should be. The files are in R2
(sounds.json names them) and come through the harness, which copies each once. Played as rendered:
the page makes no context before a touch, plays no <audio>, and builds no oscillators or filters."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

# count the contexts the page makes, and any node that would make or change sound in the browser
SPY = """(() => {
  window.__contexts = 0; window.__made = [];
  const AC = window.AudioContext;
  if (AC) window.AudioContext = class extends AC { constructor(...a) { super(...a); window.__contexts++; } };
  const B = window.BaseAudioContext?.prototype;
  for (const m of ['createOscillator', 'createBiquadFilter', 'createGain', 'createWaveShaper', 'createDynamicsCompressor', 'createConvolver', 'createDelay'])
    if (B?.[m]) { const f = B[m]; B[m] = function (...a) { window.__made.push(m); return f.apply(this, a); }; }
})()"""

TAP = """(sel) => {
  const el = document.querySelector(sel); const r = el.getBoundingClientRect();
  const o = {pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o));
}"""

# Decode every file and measure it.
MEASURE = """async () => {
  const m = await import('./sounds.js');
  const out = [];
  for (const s of m.SOUNDS) for (const kind of m.KINDS) {
    const r = await fetch(await m.fileOf(s.id, kind));
    const c = new OfflineAudioContext(2, 1, 44100);
    const buf = await c.decodeAudioData(await r.arrayBuffer());
    let peak = 0, sum = 0, n = 0;
    for (let ch = 0; ch < buf.numberOfChannels; ch++) {
      const d = buf.getChannelData(ch);
      for (let i = 0; i < d.length; i++) { peak = Math.max(peak, Math.abs(d[i])); if (i < 0.3 * buf.sampleRate) { sum += d[i] * d[i]; n++; } }
    }
    const d = buf.getChannelData(0);
    let on = 0; while (on < d.length && Math.abs(d[on]) < peak * 0.05) on++;
    out.push({ id: s.id, kind, type: r.headers.get('content-type'), dur: buf.duration, peak, onset: on / buf.sampleRate,
               rms: 10 * Math.log10(sum / n), channels: buf.numberOfChannels });
  }
  return out;
}"""


@pytest.fixture
async def bench(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield str(server.make_url("/studio/checklist/map/dev-sounds.html"))
    await server.close()


async def _open(browser, url):
    context = await browser.new_context(**IPHONE_15)
    await context.add_init_script(SPY)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_function("() => window.__dev")
    return page, errors


async def test_a_sound_is_picked_by_a_tap_kept_and_its_others_heard(webkit, bench):
    page, errors = await _open(webkit, bench)
    assert await page.locator(".sp-row").count() == 6
    assert await page.get_attribute(".sp-row[aria-checked='true']", "data-id") == "anvil"     # the default
    assert await page.evaluate("window.__contexts") == 0                                       # nothing before a touch
    await page.evaluate(TAP, ".sp-row[data-id='vault']")
    assert await page.get_attribute(".sp-row[aria-checked='true']", "data-id") == "vault"
    await page.evaluate(TAP, ".sp-item:nth-child(3) .sp-alt[data-kind='strong']")
    await page.evaluate(TAP, ".sp-item:nth-child(3) .sp-alt[data-kind='land']")
    await page.wait_for_timeout(500)
    assert await page.evaluate("window.__contexts") == 1
    await page.reload()
    await page.wait_for_function("() => window.__dev")
    assert await page.get_attribute(".sp-row[aria-checked='true']", "data-id") == "vault"
    await page.evaluate(TAP, ".sp-on")
    assert await page.get_attribute(".sp-on", "aria-checked") == "false"
    assert await page.evaluate("localStorage.getItem('map:sound-on')") == "off"
    assert await page.locator("audio").count() == 0
    assert await page.evaluate("window.__made") == []                                          # played as rendered
    assert not errors, errors


async def test_every_rendered_file_decodes_starts_at_once_and_has_its_weight(webkit, bench):
    page, errors = await _open(webkit, bench)
    first = await page.evaluate("async () => (await fetch(await (await import('./sounds.js')).fileOf('anvil', 'hit'))).status")
    if first == 502:
        pytest.skip("the check sounds' store (R2, through the site) did not answer")
    got = await page.evaluate(MEASURE)
    assert len(got) == 18
    by = {(g["id"], g["kind"]): g for g in got}
    for g in got:
        assert g["type"] == "audio/mp4", g
        assert g["channels"] == 2, g                                     # the delay ping-pongs
        assert g["onset"] < 0.002, g                                     # no encoder delay before the hit
        assert 0.1 < g["peak"] < 1.0, g                                  # headroom: AAC never clips
        assert g["dur"] < (4.2 if g["id"] == "thunder" else 3.0), g
    for sid in {g["id"] for g in got}:
        hit, strong, land = by[(sid, "hit")], by[(sid, "strong")], by[(sid, "land")]
        assert land["rms"] < hit["rms"] - 6, (sid, land["rms"], hit["rms"])     # the knock is soft
        assert land["dur"] < 0.5, land
        assert strong["dur"] >= hit["dur"] - 0.05, (sid, strong["dur"], hit["dur"])
    assert not errors, errors
