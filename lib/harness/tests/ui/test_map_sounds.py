"""The check's contact sounds (/studio/checklist/map/sounds.js), on their bench (dev-sounds.html): a choice of at
least eight, picked by a tap and kept; each one, rendered offline, is short, quiet, starts without a click and is
mostly low (Anthony asked for a bassy snap or clunk, not a ping). Interface sounds only: the page makes no context
before a touch and plays no <audio>."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

# count the contexts the page makes (the offline ones the test makes are another class)
COUNT = """(() => {
  window.__contexts = 0;
  const AC = window.AudioContext;
  if (AC) window.AudioContext = class extends AC { constructor(...a) { super(...a); window.__contexts++; } };
})()"""

TAP = """(sel) => {
  const el = document.querySelector(sel); const r = el.getBoundingClientRect();
  const o = {pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o));
}"""

# Render every sound (and its strong form) offline and measure it.
MEASURE = """async () => {
  const m = await import('./sounds.js');
  const SR = 48000, out = [];
  for (const s of m.SOUNDS) for (const strong of [false, true]) {
    const c = new OfflineAudioContext(1, Math.round(SR * 0.8), SR);
    m.build(c, c.destination, s.id, 0, { strong });
    const d = (await c.startRendering()).getChannelData(0);
    let peak = 0, nan = false, head = 0, tail = 0, low = 0, all = 0, lp = 0;
    const a = 1 - Math.exp(-2 * Math.PI * 300 / SR);          // one-pole lowpass at 300 Hz
    const after = Math.round(SR * (strong ? 0.6 : 0.4));
    for (let i = 0; i < d.length; i++) {
      const x = d[i];
      if (!Number.isFinite(x)) nan = true;
      peak = Math.max(peak, Math.abs(x));
      if (i < SR / 1000) head = Math.max(head, Math.abs(x));
      if (i >= after) tail = Math.max(tail, Math.abs(x));
      lp += a * (x - lp);
      low += lp * lp; all += x * x;
    }
    out.push({ id: s.id, strong, peak, nan, first: Math.abs(d[0]), head, tail, low: low / all });
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
    await context.add_init_script(COUNT)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_function("() => window.__dev")
    return page, errors


async def test_a_sound_is_picked_by_a_tap_and_kept(webkit, bench):
    page, errors = await _open(webkit, bench)
    rows = page.locator(".sp-row")
    assert await rows.count() >= 8
    assert await page.get_attribute(".sp-row[aria-checked='true']", "data-id") == "clunk"     # the default
    assert await page.evaluate("window.__contexts") == 0                                       # nothing before a touch
    await page.evaluate(TAP, ".sp-row[data-id='vault']")
    assert await page.get_attribute(".sp-row[aria-checked='true']", "data-id") == "vault"
    assert await page.locator(".sp-row[aria-checked='true']").count() == 1
    assert await page.evaluate("localStorage.getItem('map:sound')") == "vault"
    assert await page.evaluate("window.__contexts") == 1                                       # made inside the touch
    await page.reload()
    await page.wait_for_function("() => window.__dev")
    assert await page.get_attribute(".sp-row[aria-checked='true']", "data-id") == "vault"
    await page.evaluate(TAP, ".sp-on")                                                         # sound off is kept too
    assert await page.get_attribute(".sp-on", "aria-checked") == "false"
    assert await page.evaluate("localStorage.getItem('map:sound-on')") == "off"
    assert await page.locator("audio").count() == 0
    assert not errors, errors


async def test_every_sound_is_short_quiet_clean_and_low(webkit, bench):
    page, errors = await _open(webkit, bench)
    results = await page.evaluate(MEASURE)
    assert len(results) >= 16
    for r in results:
        name = f"{r['id']}{' strong' if r['strong'] else ''}"
        assert not r["nan"], name
        assert 0.02 <= r["peak"] <= 0.9, (name, r["peak"])
        assert r["first"] < 0.001 and r["head"] < 0.2, (name, r["first"], r["head"])            # no click at the start
        assert r["tail"] < 0.002, (name, r["tail"])                                             # over in time
        assert r["low"] >= 0.5, (name, r["low"])                                                # mostly under 300 Hz
    assert await page.evaluate("window.__contexts") == 0
    assert not errors, errors
