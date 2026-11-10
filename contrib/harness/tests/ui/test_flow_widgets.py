"""The flow's production widgets (/studio/checklist/flow/dev-widgets.html): each takes the whole screen; a switch is
pending until the next bar and then audible (the player engine's cues, with no audio at all in this mock-up); the done
measures follow the choice and the commit's emphasis follows them; commit and close reach the shell."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

# Count any attempt to make sound: the mock-up must make none.
NO_AUDIO = """
window.__audio = 0;
for (const k of ['AudioContext', 'webkitAudioContext', 'OfflineAudioContext']) {
  const C = window[k];
  if (C) window[k] = function (...a) { window.__audio++; return new C(...a); };
}
const make = Document.prototype.createElement;
Document.prototype.createElement = function (t, ...a) { if (String(t).toLowerCase() === 'audio') window.__audio++; return make.call(this, t, ...a); };
const A = window.Audio;
window.Audio = function (...a) { window.__audio++; return new A(...a); };
"""


@pytest.fixture
async def bench(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield str(server.make_url("/studio/checklist/flow/dev-widgets.html"))
    await server.close()


async def _open(browser, url, item):
    context = await browser.new_context(**IPHONE_15)
    await context.add_init_script(NO_AUDIO)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(f"{url}?item={item}")
    await page.wait_for_selector("body[data-ready]", state="attached")
    await page.wait_for_selector(".wg")
    return page, errors


async def _settled(page):
    return float(await page.get_attribute(".wg", "data-settled"))


@pytest.mark.parametrize("item", ["kick.drive", "kick.eq", "mix.groups"])
async def test_each_widget_takes_the_whole_screen(webkit, bench, item):
    page, errors = await _open(webkit, bench, item)
    box = await page.locator(".wg").bounding_box()
    assert box["x"] == 0 and box["y"] == 0
    assert box["width"] == 393 and box["height"] >= 650                     # full bleed on an iPhone 15
    assert await page.evaluate("document.documentElement.scrollWidth") == 393
    assert await page.evaluate("document.querySelector('.wg').scrollWidth") == 393
    assert await page.is_visible(".wg-player .pl-mock")                     # says it is mocked, no audio
    assert await page.locator(".ms-row").count() >= 3                         # the done measures
    assert await page.is_enabled(".cm-btn")                                   # the commit is never locked
    assert await page.evaluate("window.__audio") == 0
    assert errors == [], errors
    await page.context.close()


async def test_a_switch_is_pending_until_the_bar_then_audible(webkit, bench):
    page, errors = await _open(webkit, bench, "kick.drive")
    assert await page.get_attribute(".opt[data-v='1']", "aria-pressed") == "true"      # B is what you hear
    await page.click(".opt[data-v='3']")
    assert await page.get_attribute(".wg", "data-cue") == "pending"
    assert "pending" in (await page.get_attribute(".opt[data-v='3']", "class"))
    assert await page.get_attribute(".opt[data-v='3']", "aria-pressed") == "false"     # not audible yet
    assert await page.is_visible(".pl-wait")
    await page.wait_for_function("document.querySelector('.wg').dataset.cue === 'audible'", timeout=3000)
    assert await page.get_attribute(".opt[data-v='3']", "aria-pressed") == "true"
    assert "audible" in (await page.get_attribute(".opt[data-v='3']", "class"))
    assert await page.locator(".wg-player.flash").count() == 1                         # the flash across the player
    assert await page.locator(".wg-ring").count() == 3                                 # the layered rings
    assert "D" in await page.text_content(".pl-now")
    await page.wait_for_timeout(1200)                                                  # the rings are gone
    assert await page.locator(".wg-ring").count() == 0
    assert await page.evaluate("document.querySelector('.wg').scrollWidth") == 393
    assert await page.evaluate("window.__audio") == 0
    assert errors == [], errors
    await page.context.close()


async def test_the_measures_follow_the_choice_and_the_commit_follows_them(webkit, bench):
    page, errors = await _open(webkit, bench, "kick.drive")
    b = await _settled(page)
    assert await page.get_attribute(".wg-commit", "data-emphasis") == "high"
    await page.click(".opt[data-v='3']")                                     # 50 %: out of the zone on most dims
    d = await _settled(page)
    assert d < b - 0.2
    assert await page.get_attribute(".wg-commit", "data-emphasis") != "high"
    assert await page.is_enabled(".cm-btn")                                   # still allowed: never forced
    assert "anyway" in (await page.text_content(".cm-words")) or "Nearly" in (await page.text_content(".cm-words"))
    await page.click(".opt[data-v='1']")
    assert await _settled(page) == b                                          # deterministic
    await page.click(".cm-btn")
    await page.click(".wg-back")
    assert await page.evaluate("window.calls") == ["commit", "close"]
    assert errors == [], errors
    await page.context.close()


async def test_the_macro_dial_snaps_across_rendered_stops(webkit, bench):
    page, errors = await _open(webkit, bench, "kick.eq")
    assert await page.get_attribute(".dial", "aria-valuenow") == "4"
    await page.click(".dl-stop[data-v='6']")
    assert await page.get_attribute(".wg", "data-cue") == "pending"
    assert "asking" in (await page.get_attribute(".dial", "class"))
    await page.wait_for_function("document.querySelector('.wg').dataset.cue === 'audible'", timeout=3000)
    assert await page.get_attribute(".dial", "aria-valuenow") == "7"
    assert "Render 7" in await page.text_content(".dl-big")
    # a drag moves the ghost across the stops and asks for the one it ends on
    box = await page.locator(".dial").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await page.evaluate(
        """([cx, cy, r]) => {
          const d = document.querySelector('.dial');
          const o = (x, y) => ({pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: x, clientY: y});
          d.dispatchEvent(new PointerEvent('pointerdown', o(cx, cy - r)));
          d.dispatchEvent(new PointerEvent('pointermove', o(cx - r * 0.7, cy - r * 0.7)));
          d.dispatchEvent(new PointerEvent('pointermove', o(cx - r, cy)));
          d.dispatchEvent(new PointerEvent('pointerup', o(cx - r, cy)));
        }""",
        [cx, cy, box["width"] * 0.35],
    )
    assert await page.get_attribute(".wg", "data-cue") == "pending"
    await page.wait_for_function("document.querySelector('.wg').dataset.cue === 'audible'", timeout=3000)
    assert await page.get_attribute(".dial", "aria-valuenow") == "2"         # straight left is stop 2
    assert await page.evaluate("window.__audio") == 0
    assert errors == [], errors
    await page.context.close()
