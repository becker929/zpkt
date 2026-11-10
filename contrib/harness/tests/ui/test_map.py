"""The map round (/studio/checklist/map/): a heavy ledger whose check is stamped at the middle of the screen (the box
lifts out of its row, a ghost check slams down, sparks and dust, white from under the box, an impact mark, a shake),
then the box becomes its room on the map, which reveals the find in The Wasteland that the item leads to; the map
settles into the header, and the box drops back into its row, pressed in and dated. A checked box only knocks when
tapped and reopens when held. What's taken from The Wasteland shows up in the widgets it can be used in."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui


@pytest.fixture
async def ledger(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield str(server.make_url("/studio/checklist/map/"))
    await server.close()


async def _open(browser, url, scheme="light"):
    context = await browser.new_context(**IPHONE_15, color_scheme=scheme)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_selector(".step")
    await page.evaluate("""() => {
      window.__seen = new Set();
      new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) if (n.className) __seen.add(String(n.className)); })
        .observe(document.getElementById('fx'), {childList: true});
      const orig = Element.prototype.animate;
      Element.prototype.animate = function (...a) { if (this.id === 'splash' && a[0].length > 8) __seen.add('shake'); return orig.apply(this, a); };
    }""")
    return page, errors


TAP = """(sel) => {
  const el = typeof sel === 'string' ? document.querySelector(sel) : sel; const r = el.getBoundingClientRect();
  const o = {pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + Math.min(20, r.width / 2), clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o));
}"""
HOLD = """async (sel) => {
  const el = document.querySelector(sel); const r = el.getBoundingClientRect();
  const o = {pointerId: 7, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o));
  await new Promise((ok) => setTimeout(ok, 1000));
  el.dispatchEvent(new PointerEvent('pointerup', o));
}"""


async def _through_the_splash(page, choice="#go-on"):
    await page.wait_for_function("() => document.getElementById('cont').classList.contains('show')", timeout=12000)
    await page.evaluate(TAP, choice)
    await page.wait_for_function("() => !document.getElementById('splash').classList.contains('show')", timeout=5000)


async def test_a_commit_is_stamped_then_reveals_a_find_and_lands_in_the_ledger(webkit, ledger):
    page, errors = await _open(webkit, ledger)
    assert await page.get_attribute(".step.open", "data-step") == "kick"
    box = await page.locator(".item[data-key='kick.drive'] .box i").bounding_box()
    assert box["width"] >= 34 and box["height"] >= 34                            # big, heavy boxes
    await page.evaluate(TAP, ".item[data-key='kick.drive'] .open-item")
    await page.wait_for_selector("#widget.show .wg-crate")
    await page.wait_for_timeout(400)
    await page.evaluate(TAP, "#widget .cm-btn")
    await page.wait_for_function("() => window.__seen.has('bigbox')", timeout=4000)
    assert await page.is_hidden("#widget")
    await _through_the_splash(page)
    seen = await page.evaluate("[...__seen]")
    for part in ("bigbox", "ghost-check", "silhouette-big", "ring-big", "impact", "shake"):
        assert part in seen, (part, seen)
    row = ".item[data-key='kick.drive']"
    await page.wait_for_function(f"() => document.querySelector(\"{row}\").classList.contains('done')")
    assert (await page.text_content(f"{row} .stamp")).startswith("Settled · ")
    assert await page.text_content("#total-n") == "23"
    assert await page.text_content("#fresh") == "1"                              # one new find out there
    assert await page.locator("#mini svg").count() >= 1
    await page.wait_for_function(f"() => getComputedStyle(document.querySelector(\"{row} .box i\")).visibility === 'visible'")
    assert not errors, errors


async def test_a_checked_box_knocks_and_reopens_only_when_held(webkit, ledger):
    page, errors = await _open(webkit, ledger)
    row = ".item[data-key='kick.scoop']"
    await page.evaluate(TAP, f"{row} .box")
    await page.wait_for_selector("#toast.show")
    assert "Hold" in await page.text_content("#toast")
    assert await page.evaluate(f"document.querySelector(\"{row}\").classList.contains('done')")
    await page.evaluate(HOLD, f"{row} .box")
    await page.wait_for_function(f"() => !document.querySelector(\"{row}\").classList.contains('done')")
    assert await page.text_content("#total-n") == "21"
    assert not errors, errors


async def test_a_find_taken_shows_up_in_the_widgets_it_fits(webkit, ledger):
    page, errors = await _open(webkit, ledger, scheme="dark")
    await page.evaluate(TAP, ".item[data-key='kick.drive'] .box")
    await _through_the_splash(page, "#see")
    await page.wait_for_selector("#explore.show")
    await page.wait_for_selector("#card.show")
    await page.wait_for_timeout(300)
    use = await page.evaluate("""async () => {
      const {findFor} = await import('./finds.js');
      return findFor('kick.drive').useIn;
    }""")
    take = page.locator("#card button", has_text="Take")
    await take.first.wait_for()
    await page.evaluate(TAP, await take.first.element_handle())
    await page.wait_for_function("() => document.querySelector('#card').textContent.includes('crate')")
    assert await page.text_content("#fresh") == ""                               # looked at: no longer new
    # use it: open an item the find can be used in, straight from the card
    target = use[0]
    work = page.locator(f"#card [data-key='{target}']")
    if await work.count():
        await page.evaluate(TAP, await work.first.element_handle())
    else:
        await page.goto(ledger + f"?item={target}")
    await page.wait_for_selector("#widget.show .wg-crate")
    assert await page.locator("#widget .cr-row[data-key='kick.drive']").count() == 1
    await page.evaluate(TAP, "#widget .cr-row[data-key='kick.drive']")
    assert "mocked" in await page.text_content("#widget .cr-row[data-key='kick.drive']")
    assert not errors, errors


async def test_the_sound_sheet_picks_the_check_sound(webkit, ledger):
    page, errors = await _open(webkit, ledger)
    await page.evaluate(TAP, "#snd")
    await page.wait_for_selector("#sheet.show .sp-row")
    await page.evaluate(TAP, "#sheet .sp-row[data-id='vault']")
    await page.evaluate(TAP, "#sheet-close")
    assert "Vault" in await page.get_attribute("#snd", "aria-label")
    assert await page.evaluate("localStorage.getItem('map:sound')") == "vault"
    assert await page.locator("audio").count() == 0
    assert not errors, errors
