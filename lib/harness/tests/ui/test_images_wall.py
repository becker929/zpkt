"""The image wall (/studio/images/, docs/images.md): a masonry of every image with its context, settings and full
prompt; images load as they come near the screen and are let go when they are far from it; batches filter it."""

from __future__ import annotations

import io

import pytest
from aiohttp.test_utils import TestServer
from PIL import Image

from conftest import IPHONE_15
from harness import images as I
from lab_server import app

pytestmark = pytest.mark.ui


@pytest.fixture
async def wall(tmp_path):
    store = I.Store(tmp_path / "images")
    for k in range(70):
        p = tmp_path / f"{k}.png"
        buf = io.BytesIO()
        Image.new("RGB", (300, 300 + (k % 4) * 120), (k * 3 % 255, 40, 90)).save(buf, "PNG")
        p.write_bytes(buf.getvalue())
        I.import_image(store, p, prompt=f"prompt number {k}, in full", model="gemini-3-pro-image",
                       context="why these were made", batch="wall-a" if k % 2 else "wall-b", title=f"image {k}",
                       settings={"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "3:4"}},
                       created=f"2026-10-14T10:{k:02d}:00+00:00")
    server = TestServer(app(tmp_path))
    await server.start_server()
    yield lambda q="": str(server.make_url(f"/studio/images/{q}"))
    await server.close()


async def test_it_loads_near_the_screen_and_lets_go_far_from_it(webkit, wall):
    context = await webkit.new_context(**IPHONE_15, color_scheme="dark")
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(wall())
    await page.wait_for_function("() => window.__wall && __wall.cards() >= 40")
    assert await page.locator(".iw-col").count() == 2                            # two columns on a phone
    first = page.locator(".iw-card").first
    assert "image 69" in await first.text_content()                              # newest first
    assert "prompt number 69, in full" in await first.locator(".iw-prompt").text_content()
    assert "gemini-3-pro-image" in await first.locator(".iw-set").text_content()
    await page.wait_for_function("() => __wall.loaded() > 0")
    near = await page.evaluate("__wall.loaded()")
    assert near < 30                                                             # not the whole page at once
    top_img = ".iw-card[data-id] img"
    first_id = await first.get_attribute("data-id")
    # scroll far down: more pages arrive, and the first images are let go
    for k in range(1, 16):
        await page.evaluate(f"scrollTo(0, {k * 2500})")
        await page.wait_for_timeout(150)
    await page.wait_for_function("() => __wall.cards() === 70", timeout=8000)
    src = await page.evaluate(f"document.querySelector('.iw-card[data-id=\"{first_id}\"] img').getAttribute('src')")
    assert src is None
    assert await page.evaluate("__wall.loaded()") < 40
    # back up: it comes back
    await page.evaluate("scrollTo(0, 0)")
    await page.wait_for_function(f"() => document.querySelector('.iw-card[data-id=\"{first_id}\"] img').getAttribute('src')")
    assert await page.locator(top_img).count() == 70
    assert not errors, errors


async def test_a_batch_chip_filters_and_an_image_opens_whole(webkit, wall):
    context = await webkit.new_context(**IPHONE_15, color_scheme="dark")
    page = await context.new_page()
    await page.goto(wall("?batch=wall-a"))
    await page.wait_for_function("() => window.__wall && __wall.cards() > 0")
    assert "35 images in wall-a" in await page.text_content("#count")
    assert await page.text_content("#context") == "why these were made"
    await page.locator(".iw-card .iw-img").first.dispatch_event("click")
    await page.wait_for_selector("#view.show img")
    body = await page.text_content("#view-body")
    assert "prompt number 69, in full" in body and "aspectRatio" in body
