"""The layout pass: /app/ fills a desktop in three columns, and controls stay touchable on every width (WebKit).

Both pages are served by the app on FakeLive. The old desk at / only gets wider controls on a phone, by CSS.
"""

from __future__ import annotations

import pytest

from tests.app.conftest import osc_spec
from zpkt.live import meter

playwright_sync = pytest.importorskip("playwright.sync_api")

WIDTHS = [360, 390, 768, 1200, 1600]

# Every visible control of /app/, as {tag, w, h}; plus the page's own overflow and the widest control card.
APP_MEASURE = """() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && !e.closest('.sheet:not(.on)'); };
  const touch = [...document.querySelectorAll('#app button, #app select, #app [role=slider], #tabs a')].filter(vis).map(e => {
    const r = e.getBoundingClientRect();
    return {n: (e.id || e.className || e.tagName) + '', w: Math.round(r.width), h: Math.round(r.height)}; });
  const cards = [...document.querySelectorAll('#app .ctl, #app .pc, #app .pair')].filter(vis)
    .map(e => ({n: e.className + '', w: Math.round(e.getBoundingClientRect().width)}));
  return {over: document.documentElement.scrollWidth - innerWidth, touch, cards};
}"""

# The columns, the spectrum, and every gap between neighbours in a row (flex or grid containers that show a row).
DESKTOP_MEASURE = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
  const ids = ['#side', '#main', '#hear'];
  const cols = ids.map(i => { const e = document.querySelector(i); return e && vis(e) ? e.getBoundingClientRect() : null; });
  const used = cols.filter(Boolean);
  const spc = document.querySelector('#htop .spc:not(.ver)');
  const gaps = [];
  document.querySelectorAll('#cols *').forEach(c => {
    const s = getComputedStyle(c);
    if (!vis(c) || !/flex|grid/.test(s.display) || s.flexDirection === 'column' || c.closest('.sheet:not(.on)')) return;
    const kids = [...c.children].filter(vis).map(k => k.getBoundingClientRect()).sort((a, b) => a.left - b.left);
    kids.forEach((k, i) => { const p = kids[i - 1];
      if (p && Math.abs(p.top - k.top) < Math.min(p.height, k.height) / 2 && k.left - p.right > 120)
        gaps.push((c.id || c.className) + ' ' + Math.round(k.left - p.right)); });
  });
  return {columns: used.length,
          width: used.length ? (Math.max(...used.map(r => r.right)) - Math.min(...used.map(r => r.left))) / innerWidth : 0,
          spectrum: spc ? spc.getBoundingClientRect().height : 0, gaps,
          tabs: [...document.querySelectorAll('#tabs button, #tabs a')].filter(vis).length};
}"""

OLD_MEASURE = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  return {over: document.documentElement.scrollWidth - innerWidth,
          narrow: [...document.querySelectorAll('.knobs .ctl, .faders .ctl, .pads .ctl, .knobs, .faders, .ctl')]
            .filter(vis).map(e => [e.className, Math.round(e.getBoundingClientRect().width)]).filter(x => x[1] < 44)};
}"""


@pytest.fixture()
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not available: {str(exc)[:80]}")
        yield b
        b.close()


def open_app(browser, rig, width: int, path: str = "/app/", wait: str = ".ctl .w"):
    pg = browser.new_page(viewport={"width": width, "height": 800})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + path)
    pg.wait_for_selector(wait)
    pg.wait_for_timeout(300)  # the side lists load after the first draw
    return pg, errors


@pytest.mark.parametrize("width", WIDTHS)
def test_app_controls_are_touchable_and_fit(browser, rig, width):
    pg, errors = open_app(browser, rig, width)
    got = pg.evaluate(APP_MEASURE)
    assert got["over"] == 0, "the page scrolls sideways"
    assert [t for t in got["touch"] if t["w"] < 44 or t["h"] < 44] == []
    assert [c for c in got["cards"] if c["w"] > 220] == []
    assert errors == []


@pytest.mark.parametrize("width", [1200, 1600])
def test_app_desktop_uses_three_columns_and_the_width(browser, rig, width):
    pg, _ = open_app(browser, rig, width)
    assert (
        pg.evaluate(DESKTOP_MEASURE)["spectrum"] <= 60
    )  # no meter sends: a short strip with the one action, not a blank well
    rig.meter.send(osc_spec([0.1] * len(meter.centers())))
    pg.wait_for_selector("#spec:not(.act) i")
    got = pg.evaluate(DESKTOP_MEASURE)
    assert got["columns"] == 3
    assert got["width"] >= 0.85
    assert got["spectrum"] >= 90  # History is docked under it in the same column, so it no longer takes it all
    dock = pg.locator("#histdock").bounding_box()
    assert dock["height"] >= 120 and dock["x"] >= pg.locator("#main").bounding_box()["x"] + 300
    assert got["gaps"] == []
    assert got["tabs"] == 3, "the same three tabs at every width"


@pytest.mark.parametrize("width", [360, 390])
def test_app_phone_is_one_column_with_its_tabs(browser, rig, width):
    pg, _ = open_app(browser, rig, width)
    got = pg.evaluate(DESKTOP_MEASURE)
    assert got["columns"] == 1  # #main only
    assert got["tabs"] == 3


def test_app_tablet_has_two_columns(browser, rig):
    pg, _ = open_app(browser, rig, 768)
    assert pg.evaluate(DESKTOP_MEASURE)["columns"] == 2


@pytest.mark.parametrize("width", WIDTHS)
def test_old_desk_controls_are_44_px_wide_and_nothing_overflows(browser, rig, width):
    pg, errors = open_app(browser, rig, width, "/desk/", ".ctl")
    got = pg.evaluate(OLD_MEASURE)
    assert got["narrow"] == [], got["narrow"]
    assert got["over"] == 0
    assert errors == []
