"""The /app/ shell has no horizontal scroll and nothing clipped in the Hear bar at phone and desktop widths (WebKit)."""

from __future__ import annotations

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.mark.parametrize("width", [360, 375, 390, 430, 768, 1280])
def test_nothing_overflows_at_this_width(rig, width):
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        pg = browser.new_page(viewport={"width": width, "height": 800})
        pg.goto(rig.url + "/app/")
        pg.wait_for_selector(".ctl .w")
        over = pg.evaluate(
            """() => {
              const out = [];
              document.querySelectorAll('#hbot button, #htop *, .ctl').forEach(e => {
                const r = e.getBoundingClientRect();
                if (r.width && (r.right > innerWidth + 0.5 || r.left < -0.5)) out.push((e.id || e.className || e.tagName) + ' ' + Math.round(r.right));
              });
              return [document.documentElement.scrollWidth - innerWidth, out];
            }"""
        )
        panel = pg.evaluate(
            r"""() => {
              const box = s => document.querySelector(`#panel .mc[data-slot="${s}"]`).getBoundingClientRect();
              const faces = [...document.querySelectorAll('#panel .mc .w')].map(w => w.getBoundingClientRect());
              return {slots: document.querySelectorAll('#panel .mc').length,
                      small: faces.filter(r => r.width && (r.width < 44 || r.height < 44)).length,
                      faces: window.zpkt.S.faces,
                      out: faces.filter(r => r.right > innerWidth + 0.5 || r.left < -0.5).length,
                      folded: getComputedStyle(document.querySelector('#panel')).gridTemplateColumns.trim().split(/\s+/).length === 1,
                      order: ['k1', 'k5', 'b1', 'f1', 'b5'].map(s => Math.round(box(s).top))};
            }"""
        )
        small = pg.evaluate(
            "min => [...document.querySelectorAll('#hbot button')].map(b => b.getBoundingClientRect()).filter(r => r.height && (r.height < min || r.width < min)).length",
            36 if width < 700 else 40,  # on a phone the Hear bar's keys are smaller: 38 px high, 36 px or more wide
        )
        browser.close()
    assert over == [0, []], over
    assert small == 0  # touch targets of 40 px or more (36 on a phone)
    # the panel: all 20 slots of the MiniLab, each at least 44 px, none off the side
    assert (panel["slots"], panel["small"], panel["out"]) == (20, 0, 0), panel
    # The panel folds in half when its own box is 440 px or less: every phone, and a 768 px tablet (the Hear bar takes
    # 320 px beside it). Wider, it is the MiniLab as it sits.
    assert panel["folded"] == (width < 1000)
    if panel["folded"] and panel["faces"] == 1:  # knobs 1-4, knobs 5-8, pads 1-4, faders, pads 5-8, top to bottom
        assert panel["order"] == sorted(panel["order"]) and len(set(panel["order"])) == 5, panel
