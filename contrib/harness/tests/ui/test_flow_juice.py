"""The flow's juice objects (/studio/checklist/flow/juice/*.js), on their bench (dev-juice.html): each plays one
commit and settles within 3 s on exactly the drawing a fresh render of the new done set gives (the same set always
draws the same thing, however it was reached), draws its header glyph, and opens a region or ends a step where the
commit completes one."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer

from conftest import IPHONE_15
from lab_server import app

pytestmark = pytest.mark.ui

KINDS = ["crystal", "repair", "map"]


@pytest.fixture
async def bench(tmp_path):
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield lambda q: str(server.make_url(f"/studio/checklist/flow/dev-juice.html?auto=0&{q}"))
    await server.close()


async def _open(browser, url):
    context = await browser.new_context(**IPHONE_15, color_scheme="dark")
    page = await context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
    await page.goto(url)
    await page.wait_for_function("() => window.__dev")
    return page, errors


@pytest.mark.parametrize("kind", KINDS)
async def test_a_commit_plays_and_settles_on_the_new_drawing(webkit, bench, kind):
    page, errors = await _open(webkit, bench(f"kind={kind}&item=kick.drive"))
    ms = await page.evaluate("() => window.__dev.run()")
    assert ms < 3000, ms
    settled = await page.inner_html("#stage")
    assert settled == await page.evaluate(f"() => window.__dev.expected('{kind}', 'kick.drive', false)")
    assert settled != await page.evaluate(f"() => window.__dev.expected('{kind}', 'kick.drive', false, 'before')")
    # the same set reached in another order draws the same, and a fresh page draws the same
    same = await page.evaluate(f"""() => {{
      const d = window.__dev, s = d.sets('kick.drive', false).after;
      return d.norm(d.KINDS['{kind}'].render(d.data, new Set([...s].reverse()), {{ step: 'kick' }}));
    }}""")
    assert same == settled
    page2, _ = await _open(webkit, bench(f"kind={kind}&item=kick.drive"))
    assert await page2.evaluate(f"() => window.__dev.expected('{kind}', 'kick.drive', false)") == settled
    # the header glyph
    assert await page.locator("#mini svg").count() == 1
    assert await page.locator("#mini svg *").count() > 10
    assert errors == [], errors
    await page.context.close()
    await page2.context.close()


async def test_it_is_moving_while_it_plays(webkit, bench):
    page, errors = await _open(webkit, bench("kind=crystal&item=kick.eq"))
    await page.evaluate("() => { window.__p = window.__dev.run(); }")
    await page.wait_for_timeout(500)
    mid = await page.eval_on_selector(".shard.solid[data-key='kick.eq']", "g => g.getAttribute('transform')")
    assert "scale(" in mid                                                 # the new shard is still growing
    await page.evaluate("() => window.__p")
    end = await page.eval_on_selector(".shard.solid[data-key='kick.eq']", "g => g.getAttribute('transform')")
    assert "scale(" not in end
    assert errors == [], errors
    await page.context.close()


async def test_clearing_a_step_opens_its_region_and_gate(webkit, bench):
    page, errors = await _open(webkit, bench("kind=map&item=kick.pick&fill=1"))
    before = await page.evaluate("() => window.__dev.expected('map', 'kick.pick', true, 'before')")
    assert "IV KICK" not in before
    await page.evaluate("() => window.__dev.run()")
    assert await page.locator(".mp-gate[data-step='kick']").count() == 1   # the way out into The Wasteland
    assert "IV KICK" in await page.inner_html("#stage")
    await page.evaluate("() => window.__dev.setKind('repair')")
    await page.evaluate("() => window.__dev.run()")
    assert await page.locator(".rp-tile.open").count() == 0               # every kick tile restored
    assert errors == [], errors
    await page.context.close()


async def test_reduced_motion_shows_the_new_state(webkit, bench):
    for kind in KINDS:
        page, errors = await _open(webkit, bench(f"kind={kind}&item=mix.groups&reduced=1"))
        ms = await page.evaluate("() => window.__dev.run()")
        assert ms < 600, (kind, ms)
        assert await page.inner_html("#stage") == await page.evaluate(f"() => window.__dev.expected('{kind}', 'mix.groups', false)")
        assert errors == [], errors
        await page.context.close()
