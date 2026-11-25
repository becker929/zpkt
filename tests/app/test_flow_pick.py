"""The Pick button in WebKit: what an agent proposed is in the Options sheet, and Pick puts it on Now, tagged `you`.
The sheet stays touchable and does not scroll sideways from a phone to a wide desktop. Live is a FakeLive."""

from __future__ import annotations

import json

import pytest

from .test_one_option_store import KEY, propose, volume

playwright_sync = pytest.importorskip("playwright.sync_api")

WIDTHS = [360, 390, 768, 1200, 1600]

SHEET = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const touch = [...document.querySelectorAll('#sheet button')].filter(vis).map(e => {
    const r = e.getBoundingClientRect();
    return {n: e.id || e.className, w: Math.round(r.width), h: Math.round(r.height)}; });
  const box = document.querySelector('#sheet').getBoundingClientRect();
  const out = [...document.querySelectorAll('#sheet > *')].filter(vis)
    .filter(e => e.getBoundingClientRect().right > box.right + 1 || e.scrollWidth > e.clientWidth + 1 && !e.classList.contains('ol'))
    .map(e => e.className || e.tagName);
  return {over: document.documentElement.scrollWidth - innerWidth, touch, out,
          text: document.querySelector('#sheet').innerText,
          emoji: /\\p{Extended_Pictographic}/u.test(document.querySelector('#sheet').innerText),
          icon: !!document.querySelector('#onow svg use')};
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


def open_sheet(browser, rig, width: int):
    pg = browser.new_context(viewport={"width": width, "height": 844}).new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(rig.url + "/app/")
    pg.wait_for_selector(".ctl .w")
    pg.click("#sopts" if width >= 1200 else "#topts")
    pg.wait_for_selector("#onow")
    return pg, errors


def test_pick_puts_what_the_agent_proposed_on_now_as_you(asked, browser):
    rig = asked.rig
    oid = propose(asked)
    before = volume(rig)
    pg, errors = open_sheet(browser, rig, 390)
    text = pg.locator("#sheet").inner_text()
    assert "Kick down" in text and "It masks the bass." in text and "Proposed by an agent" in text
    assert pg.locator(".ol .key.on .tag").text_content() == "proposed"
    assert "off" not in (pg.get_attribute("#onow", "class") or "")
    pg.click("#onow")
    pg.wait_for_selector("#vgrid .vc.now")
    assert volume(rig) == pytest.approx(0.3) and volume(rig) != before
    last = rig.desk.history.entries[-1]
    assert last["who"] == "you" and KEY in json.dumps(last)
    assert rig.desk.options.is_picked(oid)
    pg.wait_for_function("document.querySelector('.ol .key.on .tag').textContent === 'picked'")
    assert errors == []


def test_a_proposal_made_while_the_sheet_is_open_appears_in_it(asked, browser):
    pg, errors = open_sheet(browser, asked.rig, 390)
    assert "No Options yet" in pg.locator("#sheet").inner_text()
    propose(asked)
    pg.wait_for_selector('.ol .key:has-text("Kick down")')
    assert errors == []


@pytest.mark.parametrize("width", WIDTHS)
def test_the_sheet_with_a_proposal_is_touchable_and_fits(asked, browser, width):
    propose(asked)
    propose(asked, {"title": "A much longer title for a proposal that an agent wrote in full", "why": "Because. " * 40})
    pg, errors = open_sheet(browser, asked.rig, width)
    got = pg.evaluate(SHEET)
    assert got["over"] <= 0, got["over"]
    assert got["out"] == [], got["out"]  # nothing in the sheet runs past its edge; the long reason wraps
    small = [t for t in got["touch"] if t["w"] < 44 or t["h"] < 44]
    assert got["touch"] and not small, small
    assert got["icon"] and not got["emoji"]
    assert "Pick" in got["text"]
    assert errors == []
