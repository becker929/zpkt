"""The flow mock-up (/studio/checklist/flow/): an item opens its production widget full bleed; committing folds it
back, checks the box with the check's juice (a ghost check, a white silhouette from under the box, a shake) and
brings the juice object over the screen in a splash, which settles into the header. A box can be checked straight
away too, and unchecked quietly."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui


@pytest.fixture
async def flow(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield str(server.make_url("/studio/checklist/flow/"))
    await server.close()


async def _open(browser, url):
    context = await browser.new_context(**IPHONE_15)
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_selector(".step")
    # record the juice as it happens: the ghost, the silhouette, the shake, the splash
    await page.evaluate("""() => {
      window.__seen = new Set();
      new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) if (n.className) __seen.add(String(n.className)); })
        .observe(document.getElementById('fx'), {childList: true});
      const orig = Element.prototype.animate;
      Element.prototype.animate = function (...a) { if (this.id === 'app') __seen.add('shake'); return orig.apply(this, a); };
      new MutationObserver(() => { if (document.getElementById('splash').classList.contains('show')) __seen.add('splash'); })
        .observe(document.getElementById('splash'), {attributes: true});
    }""")
    return page, errors


TAP = """(sel) => {
  const el = document.querySelector(sel); const r = el.getBoundingClientRect();
  const o = {pointerId: 5, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
  el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o));
}"""


async def _finish_splash(page):
    await page.wait_for_function("() => document.getElementById('cont').classList.contains('show')", timeout=6000)
    await page.evaluate(TAP, "#splash")
    await page.wait_for_function("() => !document.getElementById('splash').classList.contains('show')", timeout=4000)


async def test_a_widget_commits_into_the_check_and_the_splash(webkit, flow):
    page, errors = await _open(webkit, flow)
    assert await page.locator(".step.open").count() == 1                         # folded: the kick is open
    assert await page.get_attribute(".step.open", "data-step") == "kick"
    await page.evaluate(TAP, ".item[data-key='kick.drive'] .open-item")
    await page.wait_for_selector("#widget.show")
    box = await page.locator("#widget").bounding_box()
    assert box["width"] == 393 and box["height"] >= 650                           # full bleed
    await page.wait_for_timeout(400)
    commit = page.locator("#widget .cm-btn").first
    await commit.wait_for()
    await page.evaluate("(el) => { const r = el.getBoundingClientRect(); const o = {pointerId: 6, pointerType: 'touch', bubbles: true, isPrimary: true, clientX: r.x + 20, clientY: r.y + r.height / 2}; el.dispatchEvent(new PointerEvent('pointerdown', o)); el.dispatchEvent(new PointerEvent('pointerup', o)); }",
                        await commit.element_handle())
    await page.wait_for_function("() => document.querySelector(\".item[data-key='kick.drive']\").classList.contains('done')", timeout=4000)
    assert await page.is_hidden("#widget")
    await _finish_splash(page)
    seen = await page.evaluate("[...__seen]")
    assert "ghost" in seen and "silhouette" in seen and "flash-ring" in seen and "shake" in seen and "splash" in seen, seen
    assert await page.text_content("#total-n") == "23"
    assert await page.locator("#mini > *").count() >= 1                           # it settled into the header
    await page.goto(flow.replace("/flow/", "/"))                                  # the checklist agrees
    await page.wait_for_selector(".card")
    assert await page.get_attribute("#step-kick .item[data-id='drive']", "data-state") == "done"
    assert errors == [], errors
    await page.context.close()


async def test_a_box_checks_straight_away_with_each_juice_object(webkit, flow):
    page, errors = await _open(webkit, flow)
    for kind, item in [("crystal", "decapStyle"), ("repair", "transient"), ("map", "comp")]:
        await page.evaluate(TAP, f"#kind button[data-v='{kind}']")
        await page.evaluate(TAP, f".item[data-key='kick.{item}'] .box")
        await _finish_splash(page)
        assert "done" in await page.get_attribute(f".item[data-key='kick.{item}']", "class")
    assert await page.text_content("#total-n") == "25"
    await page.evaluate(TAP, ".item[data-key='kick.comp'] .box")                   # unchecking is quiet: no splash
    await page.wait_for_timeout(300)
    assert await page.is_hidden("#splash")
    assert await page.text_content("#total-n") == "24"
    await page.reload()
    await page.wait_for_selector(".step")
    assert await page.get_attribute("#kind button[aria-checked='true']", "data-v") == "map"     # kept
    assert errors == [], errors
    await page.context.close()
