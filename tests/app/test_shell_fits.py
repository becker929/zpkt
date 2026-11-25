"""The /app/ shell has no horizontal scroll and nothing clipped in the Hear bar at phone and desktop widths (WebKit)."""

from __future__ import annotations

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.mark.parametrize("width", [360, 390, 1280])
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
        small = pg.evaluate(
            "[...document.querySelectorAll('#hbot button')].map(b => b.getBoundingClientRect().height).filter(h => h < 40).length"
        )
        browser.close()
    assert over == [0, []], over
    assert small == 0  # touch targets of 40 px or more
